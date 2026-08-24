"""Deterministic job matching, with optional LLM semantic boost.

Basic filtering/scoring never depends entirely on an LLM - it is computed
from skills overlap, location, salary and work-mode fit. An LLMProvider may
optionally add a semantic adjustment and natural-language reasoning, but if
the LLM is unavailable the deterministic score is still fully usable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.jobs.models import Job
from app.jobs.skills_taxonomy import find_related_candidate_skill, normalize as _normalize_skill


@dataclass
class MatchResult:
    match_score: float
    matching_skills: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    matching_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


_ROLE_STOPWORDS = {"a", "an", "the", "of", "and", "or", "for", "in", "at", "to"}


def _role_words(role: str) -> set[str]:
    return {w for w in role.lower().split() if w not in _ROLE_STOPWORDS and len(w) > 2}


def title_matches_preferred_roles(title: str, preferred_roles: list[str]) -> bool:
    """Return True if the job title is a plausible match for at least one
    preferred role, based on significant-word overlap (e.g. "Backend
    Engineer" matches "Senior Backend Engineer II") rather than exact
    string equality."""
    title_words = _role_words(title)
    for role in preferred_roles:
        role_words = _role_words(role)
        if not role_words:
            continue
        if role.lower() in title.lower() or title.lower() in role.lower():
            return True
        # Majority of the role's significant words appear in the title.
        overlap = role_words & title_words
        if overlap and len(overlap) >= max(1, len(role_words) // 2):
            return True
    return False


def score_job(
    job: Job,
    profile: dict[str, Any],
    preferences: dict[str, Any],
    semantic_skill_checker: Optional[Callable[[str, set[str]], Optional[str]]] = None,
) -> MatchResult:
    """Score a job deterministically.

    Skill matching is intentionally strict-but-fair:
    - Exact skill match -> full credit.
    - A related/adjacent skill from the taxonomy (e.g. candidate has
      scikit-learn, job wants pytorch) -> partial credit (60%), and the job
      skill is still surfaced as "related" rather than a full match so the
      user knows it's not an exact hit.
    - No exact or taxonomy match -> optionally ask ``semantic_skill_checker``
      (typically LLM-backed) whether it's genuinely related; if it says yes,
      the same partial credit is given, but this can only add credit for
      skills that are otherwise a real gap - it can never grant full credit
      for something the candidate doesn't actually have, and if unavailable
      or it says no, the skill is counted as fully missing.
    """
    candidate_skills = {_normalize_skill(s) for s in profile.get("skills", [])}
    job_skills = {_normalize_skill(s) for s in job.skills}

    # If the job posting didn't list explicit skills, fall back to scanning
    # the description text for candidate skills mentioned there.
    if not job_skills and job.description:
        desc_lower = job.description.lower()
        job_skills = {s for s in candidate_skills if s in desc_lower}

    exact_matches = sorted(candidate_skills & job_skills)
    remaining = job_skills - candidate_skills

    related_matches: list[str] = []
    missing: list[str] = []
    for job_skill in sorted(remaining):
        related_candidate_skill = find_related_candidate_skill(job_skill, candidate_skills)
        if related_candidate_skill:
            related_matches.append(job_skill)
            continue
        if semantic_skill_checker:
            llm_related = semantic_skill_checker(job_skill, candidate_skills)
            if llm_related:
                related_matches.append(job_skill)
                continue
        missing.append(job_skill)

    skills_component = 0.0
    if job_skills:
        exact_credit = len(exact_matches)
        related_credit = len(related_matches) * 0.6
        skills_component = ((exact_credit + related_credit) / len(job_skills)) * 50
    else:
        # No skills data at all to compare - stay neutral rather than
        # penalizing or rewarding.
        skills_component = 25.0

    reasons: list[str] = []
    concerns: list[str] = []
    matching = exact_matches

    # Role/title relevance - critical for filtering out jobs that are
    # technically posted by the right company but are an entirely different
    # function (e.g. Sales/Support postings showing up alongside Engineering
    # roles on a shared company job board).
    title_component = 0.0
    preferred_roles = preferences.get("preferred_roles") or []
    if preferred_roles:
        if title_matches_preferred_roles(job.title, preferred_roles):
            title_component = 20.0
            reasons.append(f"Title matches a preferred role: {job.title}")
        else:
            title_component = 0.0
            concerns.append(
                f"Job title '{job.title}' does not match any preferred role "
                f"({', '.join(preferred_roles)})"
            )
    else:
        # No role preference configured - stay neutral.
        title_component = 10.0

    # Location / visa relevance. Candidate is India-based: a job is
    # relevant if it's located in India, OR it's remote (location-agnostic),
    # OR the posting explicitly mentions visa/relocation sponsorship. Jobs
    # that are onsite/hybrid in a country with no sponsorship signal and no
    # India presence are penalized rather than excluded outright, since a
    # posting may simply omit sponsorship info.
    location_component = 0.0
    location_text = (job.location or "").lower()
    description_text = (job.description or "").lower()
    is_india = "india" in location_text
    is_remote_mode = job.work_mode.value == "remote"
    mentions_remote_text = "remote" in location_text
    visa_keywords = ("visa sponsorship", "sponsor visa", "will sponsor", "relocation assistance", "relocation support", "visa support")
    mentions_visa = any(k in description_text for k in visa_keywords)

    if is_india or is_remote_mode or mentions_remote_text:
        location_component = 15.0
        reasons.append(f"Location/work mode compatible with India-based remote work: {job.location or job.work_mode.value}")
    elif mentions_visa:
        location_component = 12.0
        reasons.append("Posting mentions visa/relocation support")
    else:
        location_component = 0.0
        concerns.append(
            f"Location '{job.location or 'unknown'}' is not in India, not remote, and the posting "
            "does not mention visa/relocation sponsorship"
        )

    # Seniority / fresher relevance. Candidate is a fresher, so senior-level
    # postings are penalized and entry-level/intern/graduate postings are
    # rewarded. Unlabeled postings stay neutral rather than being penalized,
    # since many entry-friendly roles don't explicitly say "junior".
    #
    # Matching is restricted to the job TITLE (not the full description) and
    # uses word-boundary regex, since keyword substrings inside a long
    # description are unreliable (e.g. "intern" inside "internet", or a
    # description merely mentioning "graduate" as an education requirement
    # rather than describing the seniority of the role itself).
    seniority_component = 0.0
    title_lower = job.title.lower()
    senior_keywords = (r"senior", r"sr\.?", r"staff", r"principal", r"lead", r"director", r"vp", r"head of", r"manager")
    entry_keywords = (r"junior", r"jr\.?", r"entry[\s-]?level", r"associate", r"intern(ship)?", r"graduate", r"new grad", r"trainee", r"fresher")

    def _title_has_any(keywords: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{kw}\b", title_lower) for kw in keywords)

    is_senior = _title_has_any(senior_keywords)
    is_entry = _title_has_any(entry_keywords)

    if is_senior:
        seniority_component = 0.0
        concerns.append(f"Job title suggests a senior-level role ('{job.title}'), not suitable for a fresher")
    elif is_entry:
        seniority_component = 15.0
        reasons.append("Posting is explicitly entry-level/internship/graduate friendly")
    else:
        # Unlabeled - stay neutral rather than penalizing.
        seniority_component = 8.0

    work_mode_component = 0.0
    preferred_work_mode = preferences.get("work_mode", "any")
    if preferred_work_mode in ("any", None) or job.work_mode.value == preferred_work_mode:
        work_mode_component = 5.0
        if job.work_mode.value != "unknown":
            reasons.append(f"Work mode matches: {job.work_mode.value}")
    else:
        concerns.append(f"Work mode mismatch: job is {job.work_mode.value}, preferred {preferred_work_mode}")

    salary_component = 0.0
    minimum_salary = preferences.get("minimum_salary")
    if minimum_salary and job.salary_max:
        if job.salary_max >= minimum_salary:
            salary_component = 5.0
            reasons.append("Salary range meets minimum expectation")
        else:
            concerns.append("Salary range may be below minimum expectation")
    elif not minimum_salary:
        salary_component = 5.0

    excluded_companies = {c.lower() for c in preferences.get("excluded_companies", [])}
    if job.company.lower() in excluded_companies:
        concerns.append(f"{job.company} is in the excluded companies list")

    if matching:
        reasons.append("Strong matches: " + ", ".join(matching))
    if related_matches:
        reasons.append("Related/transferable skills: " + ", ".join(related_matches))
    if missing:
        concerns.append("Missing skills: " + ", ".join(missing))

    total = (
        skills_component
        + title_component
        + location_component
        + seniority_component
        + work_mode_component
        + salary_component
    )
    total = max(0.0, min(100.0, total))

    return MatchResult(
        match_score=round(total, 1),
        matching_skills=matching,
        related_skills=related_matches,
        missing_skills=missing,
        matching_reasons=reasons,
        concerns=concerns,
    )


def make_llm_semantic_skill_checker(llm_provider: Any) -> Callable[[str, set[str]], Optional[str]]:
    """Build a semantic_skill_checker callback backed by an LLMProvider.

    Only ever used as a fallback for job skills that have no exact or
    taxonomy match against the candidate's real skills - it can grant
    partial credit for a genuinely adjacent tool, but it is explicitly
    instructed to be strict and to answer "no" when in doubt, since this
    directly affects whether a job clears the notification threshold.
    """
    from app.llm.base import LLMError
    from app.llm.prompts import semantic_skill_check_prompt

    def checker(job_skill: str, candidate_skills: set[str]) -> Optional[str]:
        if not candidate_skills:
            return None
        system, user = semantic_skill_check_prompt(job_skill, candidate_skills)
        try:
            # 5 tokens is enough for a plain "yes"/"no" from a non-reasoning
            # model, but reasoning-capable providers (e.g. Nvidia Nemotron,
            # Groq's gpt-oss/qwen models) still spend a handful of tokens on
            # a minimal reasoning pass before the answer even with
            # reasoning effort minimized - confirmed via live testing that
            # 5 tokens reliably truncates them before they ever answer. 50
            # is a small, cheap budget that reliably accommodates that
            # minimal reasoning across all currently supported providers.
            response = llm_provider.complete(user, system=system, max_tokens=50)
        except LLMError:
            return None
        if response and response.strip().lower().startswith("yes"):
            return job_skill
        return None

    return checker


def apply_llm_boost(base_result: MatchResult, llm_analysis: Optional[dict[str, Any]]) -> MatchResult:
    """Optionally blend in an LLM's semantic judgement.

    Deterministic score always dominates (70/30 weighting) so the system
    remains usable and predictable even if the LLM output is noisy, absent
    or the provider fails.
    """
    if not llm_analysis or "semantic_score" not in llm_analysis:
        return base_result

    semantic_score = float(llm_analysis["semantic_score"])
    blended = round(base_result.match_score * 0.7 + semantic_score * 0.3, 1)
    reasons = base_result.matching_reasons + llm_analysis.get("reasons", [])
    concerns = base_result.concerns + llm_analysis.get("concerns", [])
    return MatchResult(
        match_score=blended,
        matching_skills=base_result.matching_skills,
        related_skills=base_result.related_skills,
        missing_skills=base_result.missing_skills,
        matching_reasons=reasons,
        concerns=concerns,
    )
