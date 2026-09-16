"""Deterministic job matching, with optional LLM semantic boost.

Basic filtering/scoring never depends entirely on an LLM - it is computed
from skills overlap, location, salary and work-mode fit. An LLMProvider may
optionally add a semantic adjustment and natural-language reasoning, but if
the LLM is unavailable the deterministic score is still fully usable.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.jobs.models import Job
from app.jobs.skills_taxonomy import (
    SKILL_CLUSTERS,
    find_related_candidate_skill,
    normalize as _normalize_skill,
)


@dataclass
class MatchResult:
    match_score: float
    matching_skills: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    matching_reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FresherFit:
    """Deterministic fresher suitability used by scoring and notification gating."""

    eligible: bool
    entry_signal: bool
    required_years: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class LocationFit:
    """Whether a posting is realistically open to an India-based candidate."""

    eligible: bool
    reason: str


_ROLE_STOPWORDS = {"a", "an", "the", "of", "and", "or", "for", "in", "at", "to"}
_ENGINEERING_WORDS = {"engineer", "engineering", "developer", "development"}

# These are role-family aliases, not a global list of roles to search. They
# only expand a role the candidate explicitly selected. This prevents a
# Backend/Applied-AI candidate from matching QA, support, product, or data
# analyst jobs merely because those happen to be common fresher titles.
_ROLE_FAMILIES: dict[str, tuple[re.Pattern[str], ...]] = {
    "entry_software": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\b(?:sde|swe)[-\s]?[01]\b",
            r"\bgraduate\s+software\s+engineer\b",
            r"\bentry[\s-]?level\s+software\s+engineer\b",
            r"\bjunior\s+software\s+engineer\b",
        )
    ),
    "software": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bsoftware\s+(?:development\s+)?engineer\b",
            r"\bsoftware\s+developer\b",
            r"\b(?:sde|swe)(?:[-\s]?[01])?\b",
            r"\bgraduate\s+software\s+engineer\b",
        )
    ),
    "backend": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bback[\s-]?end\s+(?:software\s+)?(?:engineer|developer)\b",
            r"\bpython\s+(?:back[\s-]?end\s+)?(?:engineer|developer)\b",
            r"\bapi\s+(?:platform\s+)?engineer\b",
        )
    ),
    "applied_ai": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bapplied\s+ai\b",
            r"\b(?:generative\s+)?ai\s+(?:software\s+)?(?:engineer|developer)\b",
            r"\b(?:llm|rag)\s+(?:engineer|developer)\b",
            r"\bmachine\s+learning\s+(?:engineer|developer)\b",
            r"\bml\s+(?:engineer|developer)\b",
        )
    ),
    "full_stack": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bfull[\s-]?stack\s+(?:engineer|developer)\b",
            r"\bmern\s+(?:stack\s+)?(?:engineer|developer)\b",
        )
    ),
    "site_reliability": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bsite\s+reliability\s+engineer\b",
            r"\bsre(?:[-\s]?[01])?\b",
        )
    ),
    "quality": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\bqa\s+(?:automation\s+)?(?:engineer|developer|analyst)\b",
            r"\bquality\s+assurance\s+(?:engineer|developer|analyst)\b",
            r"\bsoftware\s+test(?:ing)?\s+engineer\b",
            r"\btest\s+automation\s+engineer\b",
            r"\bsdet(?:[-\s]?[01])?\b",
        )
    ),
    "application": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\b(?:mobile\s+)?app(?:lication)?\s+(?:engineer|developer)\b",
            r"\bios\s+(?:engineer|developer)\b",
            r"\bandroid\s+(?:engineer|developer)\b",
            r"\b(?:flutter|react\s+native)\s+(?:engineer|developer)\b",
        )
    ),
}


def _role_words(role: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9+#.]+", role.lower())
        if w not in _ROLE_STOPWORDS and len(w) > 2
    }


def _role_family(role: str) -> Optional[str]:
    normalized = " ".join(re.findall(r"[a-z0-9]+", role.lower()))
    words = set(normalized.split())
    if normalized in {
        "sde 0", "sde 1", "swe 0", "swe 1", "graduate software engineer",
        "entry level software engineer", "junior software engineer",
    }:
        return "entry_software"
    if normalized in {
        "sde", "swe", "software engineer",
        "software developer", "software development engineer",
    }:
        return "software"
    if "backend" in words or ("back" in words and "end" in words) or normalized.startswith("python backend"):
        return "backend"
    if normalized in {
        "applied ai", "ai engineer", "llm engineer", "ml engineer",
        "machine learning engineer",
    }:
        return "applied_ai"
    if "full stack" in normalized or "fullstack" in words or "mern" in words:
        return "full_stack"
    if normalized in {"site reliability engineer", "sre", "sre 0", "sre 1"}:
        return "site_reliability"
    if normalized in {
        "qa engineer", "qa automation engineer", "quality assurance engineer",
        "software test engineer", "test automation engineer", "sdet", "sdet 1",
    }:
        return "quality"
    if normalized in {
        "application developer", "app developer", "mobile application developer",
        "mobile app developer", "ios developer", "android developer",
        "flutter developer", "react native developer",
    }:
        return "application"
    return None


def title_matches_preferred_roles(title: str, preferred_roles: list[str]) -> bool:
    """Return True only for an explicitly selected role family.

    Known aliases (SDE/SWE, engineer/developer) are supported, but generic
    overlap on words such as "engineer" is intentionally insufficient.
    """
    title_words = _role_words(title)
    normalized_title = " ".join(re.findall(r"[a-z0-9+#.]+", title.lower()))
    for role in preferred_roles:
        family = _role_family(role)
        if family and any(pattern.search(title) for pattern in _ROLE_FAMILIES[family]):
            return True

        role_words = _role_words(role)
        if not role_words:
            continue

        normalized_role = " ".join(re.findall(r"[a-z0-9+#.]+", role.lower()))
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized_role)}(?![a-z0-9])", normalized_title):
            return True

        # Generic roles require every meaningful word. Engineer/developer
        # are interchangeable only when all specialization words match.
        specialization = role_words - _ENGINEERING_WORDS
        title_specialization = title_words - _ENGINEERING_WORDS
        engineering_matches = bool(role_words & _ENGINEERING_WORDS) and bool(title_words & _ENGINEERING_WORDS)
        if specialization and specialization <= title_specialization and (
            engineering_matches or not (role_words & _ENGINEERING_WORDS)
        ):
            return True
    return False


def role_priority_for_title(title: str) -> int:
    """Return the candidate's requested role tier (1 is highest priority)."""
    normalized = " ".join(re.findall(r"[a-z0-9]+", title.lower()))
    if (
        re.search(r"\b(?:applied ai|ai backend|llm|rag)\b", normalized)
        or re.search(r"\b(?:sde|swe)\s*[01]\b", normalized)
    ):
        return 1
    if re.search(r"\bback(?:\s|-)?end\b", title, re.IGNORECASE):
        return 2
    if re.search(r"\b(?:graduate|entry\s*level|junior)\b", normalized) and re.search(
        r"\bsoftware\s+(?:development\s+)?engineer\b", normalized
    ):
        return 3
    if re.search(r"\bfull[\s-]?stack\b", title, re.IGNORECASE):
        return 4
    if any(
        pattern.search(title)
        for family in ("site_reliability", "quality", "application")
        for pattern in _ROLE_FAMILIES[family]
    ):
        return 5
    return 6


_AMBIGUOUS_SHORT_SKILLS = {
    "ai": "AI",
    "c": "C",
    "cv": "CV",
    "eda": "EDA",
    "go": "Go",
    "js": "JS",
    "llm": "LLM",
    "ml": "ML",
    "r": "R",
    "rag": "RAG",
    "sse": "SSE",
    "ts": "TS",
}


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()


def _mentions_skill(text: str, skill: str) -> bool:
    """Match a skill as a token/phrase, never as an arbitrary substring."""
    skill = skill.strip()
    if not skill:
        return False
    normalized = _normalize_skill(skill)
    if normalized in _AMBIGUOUS_SHORT_SKILLS:
        display = _AMBIGUOUS_SHORT_SKILLS[normalized]
        return bool(re.search(rf"(?<![A-Za-z0-9+#.]){re.escape(display)}(?![A-Za-z0-9+#.])", text))
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9+#.]){re.escape(skill)}(?![A-Za-z0-9+#.])",
            text,
            re.IGNORECASE,
        )
    )


def _extract_description_skills(description: str, candidate_skills: set[str]) -> set[str]:
    """Extract a conservative comparison set from unstructured ATS text."""
    text = _plain_text(description)
    vocabulary = set(candidate_skills)
    for cluster in SKILL_CLUSTERS:
        vocabulary.update(cluster)
    return {skill for skill in vocabulary if _mentions_skill(text, skill)}


_SENIOR_TITLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b",
        r"\blead\b", r"\bdirector\b", r"\bmanager\b", r"\barchitect\b",
        r"\bhead\s+of\b", r"\bvp\b",
        r"\b(?:engineer|developer|sde|swe)\s+(?:ii|iii|iv|2|3|4)\b",
    )
)
_ENTRY_TITLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bjunior\b", r"\bjr\.?\b", r"\bentry[\s-]?level\b",
        r"\bgraduate\b", r"\bnew\s+grad\b", r"\btrainee\b",
        r"\bfresher\b", r"\bintern(?:ship)?\b", r"\b(?:sde|swe)[-\s]?[01]\b",
    )
)
_ENTRY_DESCRIPTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:fresh|recent|new)\s+graduate(?:s)?\b",
        r"\bgraduate\s+(?:programme|program|role|position)\b",
        r"\b0\s*(?:-|–|to)\s*[12]\s+years?\b",
        r"\bno\s+(?:professional\s+)?experience\s+(?:is\s+)?required\b",
        r"\b202[4-7]\s+(?:batch|graduate|graduation)\b",
    )
)
_EXPERIENCE_PATTERN = re.compile(
    r"(?<!\d)(?P<minimum>\d{1,2})(?:\s*(?:-|–|—|to)\s*(?P<maximum>\d{1,2}))?\s*\+?\s*"
    r"(?:years?|yrs?)(?:\s+of)?(?:\s+(?:relevant|professional|industry|work|hands-on|commercial|software|engineering|development|technical))*\s+experience\b",
    re.IGNORECASE,
)


def assess_fresher_fit(job: Job, profile: dict[str, Any], preferences: dict[str, Any]) -> FresherFit:
    """Assess title seniority and explicit experience requirements."""
    title = job.title or ""
    description = _plain_text(" ".join(filter(None, (job.description, job.requirements))))
    if any(pattern.search(title) for pattern in _SENIOR_TITLE_PATTERNS):
        return FresherFit(False, False, reason=f"senior-level title is not fresher friendly: {title}")

    entry_signal = any(pattern.search(title) for pattern in _ENTRY_TITLE_PATTERNS) or any(
        pattern.search(description) for pattern in _ENTRY_DESCRIPTION_PATTERNS
    )
    requirements = [float(match.group("minimum")) for match in _EXPERIENCE_PATTERN.finditer(description)]
    required_years = max(requirements) if requirements else None

    configured_max = preferences.get("experience_max")
    allowed_years = float(configured_max) if configured_max is not None else 1.0
    if required_years is not None and required_years > allowed_years:
        return FresherFit(
            False,
            entry_signal,
            required_years,
            f"Posting requires at least {required_years:g} years of experience (fresher limit: {allowed_years:g})",
        )
    if entry_signal:
        return FresherFit(True, True, required_years, "Posting has an explicit entry-level/fresher/new-grad signal")
    if required_years is not None:
        return FresherFit(True, False, required_years, f"Experience requirement is within fresher range ({required_years:g} year minimum)")
    return FresherFit(True, False, None, "No senior title or disqualifying experience requirement found")


_GLOBAL_REMOTE_MARKERS = ("worldwide", "anywhere", "global", "all locations")
_INDIA_LOCATION_MARKERS = (
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi",
    "gurgaon", "gurugram", "noida", "chennai", "kolkata", "indore", "goa",
    "ahmedabad", "kochi", "ncr",
)
_FOREIGN_REGION_MARKERS = (
    "united states", "usa", "u.s.", "canada", "europe", "emea", "uk", "united kingdom",
    "australia", "new zealand", "latin america", "latam", "north america",
)


def assess_location_fit(job: Job) -> LocationFit:
    """Treat remote as a work mode, not automatic worldwide eligibility."""
    location = (job.location or "").strip().lower()
    description = _plain_text(job.description or "").lower()
    visa_keywords = (
        "visa sponsorship", "sponsor visa", "will sponsor", "relocation assistance",
        "relocation support", "visa support",
    )
    if any(marker in location for marker in _INDIA_LOCATION_MARKERS):
        return LocationFit(True, f"Location/work mode compatible with India-based search: {job.location}")
    if any(keyword in description for keyword in visa_keywords):
        return LocationFit(True, "Posting mentions visa/relocation support")
    if job.work_mode.value == "remote" or "remote" in location:
        if not location or location == "remote" or any(marker in location for marker in _GLOBAL_REMOTE_MARKERS):
            return LocationFit(True, f"Role is globally remote: {job.location or 'Remote'}")
        if any(marker in location for marker in _FOREIGN_REGION_MARKERS):
            return LocationFit(False, f"Remote role is geographically restricted: {job.location}")
        if "remote" in location:
            return LocationFit(True, f"Role is remote with no recognized exclusion: {job.location}")
    return LocationFit(False, f"Location is not in India/global-remote and has no sponsorship signal: {job.location or 'unknown'}")


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

    # If the job posting didn't list explicit skills, conservatively extract
    # both candidate and taxonomy skills from the description. Looking only
    # for candidate skills makes every detected skill look like a perfect fit.
    if not job_skills and job.description:
        job_skills = _extract_description_skills(job.description, candidate_skills)

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
        skills_component = ((exact_credit + related_credit) / len(job_skills)) * 40
    else:
        # No skills data at all to compare - stay neutral rather than
        # penalizing or rewarding.
        skills_component = 20.0

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
            priority = role_priority_for_title(job.title)
            title_component = {1: 25.0, 2: 23.0, 3: 22.0, 4: 20.0}.get(priority, 18.0)
            reasons.append(f"Priority {priority} role match: {job.title}")
        else:
            title_component = 0.0
            concerns.append(
                f"Job title '{job.title}' does not match any preferred role "
                f"({', '.join(preferred_roles)})"
            )
    else:
        # No role preference configured - stay neutral.
        title_component = 12.5

    # Location / visa relevance. "Remote" describes work mode, not worldwide
    # eligibility: US-only and Europe-only remote roles are not India fits.
    location_component = 0.0
    location_fit = assess_location_fit(job)
    if location_fit.eligible:
        location_component = 15.0
        reasons.append(location_fit.reason)
    else:
        concerns.append(location_fit.reason)

    # Seniority / fresher relevance. Candidate is a fresher, so senior-level
    # postings are penalized and entry-level/intern/graduate postings are
    # rewarded. Unlabeled postings stay neutral rather than being penalized,
    # since many entry-friendly roles don't explicitly say "junior".
    #
    # Title seniority is combined with explicit experience requirements and
    # carefully scoped new-grad signals from the description.
    seniority_component = 0.0
    fresher_fit = assess_fresher_fit(job, profile, preferences)
    if not fresher_fit.eligible:
        concerns.append(fresher_fit.reason)
    elif fresher_fit.entry_signal:
        seniority_component = 15.0
        reasons.append(fresher_fit.reason)
    else:
        # Unknown/unlabelled roles remain possible, but rank below postings
        # that explicitly welcome fresh graduates.
        seniority_component = 8.0
        reasons.append(fresher_fit.reason)

    work_mode_component = 0.0
    preferred_work_mode = preferences.get("work_mode", "any")
    if preferred_work_mode in ("any", None) or job.work_mode.value == preferred_work_mode:
        work_mode_component = 5.0
        if job.work_mode.value != "unknown":
            reasons.append(f"Work mode matches: {job.work_mode.value}")
    else:
        concerns.append(f"Work mode mismatch: job is {job.work_mode.value}, preferred {preferred_work_mode}")

    # Salary is recorded as a reason/concern but not scored. Most fresher
    # postings omit it, so missing salary data should not distort fit.
    minimum_salary = preferences.get("minimum_salary")
    if minimum_salary and job.salary_max:
        if job.salary_max >= minimum_salary:
            reasons.append("Salary range meets minimum expectation")
        else:
            concerns.append("Salary range may be below minimum expectation")

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

    cache: dict[tuple[str, tuple[str, ...]], Optional[str]] = {}

    def checker(job_skill: str, candidate_skills: set[str]) -> Optional[str]:
        if not candidate_skills:
            return None
        cache_key = (_normalize_skill(job_skill), tuple(sorted(candidate_skills)))
        if cache_key in cache:
            return cache[cache_key]
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
        normalized_response = response.strip().lower() if response else ""
        if normalized_response.startswith("yes"):
            cache[cache_key] = job_skill
            return job_skill
        if normalized_response.startswith("no"):
            cache[cache_key] = None
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
