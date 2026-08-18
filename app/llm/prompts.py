"""Centralised job-search-related LLM prompts.

Every prompt used anywhere in the job-search / resume / application-answer
pipeline lives here, so it's easy to find, review, and tune in one place
instead of being scattered across matcher/agent modules. Each function
returns a ``(system_prompt, user_prompt)`` tuple.

Safety constraints baked into every prompt below (per project policy):
- Never fabricate skills, jobs, degrees, certifications, or projects that
  are not present in the candidate's actual profile/resume.
- When uncertain, prefer omission or a conservative/negative answer over a
  confident-sounding guess.
- Deterministic code always remains the primary decision-maker; the LLM is
  only ever a secondary, strictly-bounded opinion (see app/jobs/matcher.py
  and app/agents/resume_agent.py for how callers degrade gracefully on
  LLMError or empty/invalid responses).
"""
from __future__ import annotations

from typing import Any


def semantic_skill_check_prompt(job_skill: str, candidate_skills: set[str]) -> tuple[str, str]:
    """Used by app.jobs.matcher.make_llm_semantic_skill_checker as a strict,
    score-reducing-or-neutral fallback for skills not covered by the
    deterministic skills taxonomy."""
    system = (
        "You are a strict technical skills classifier. You only ever answer "
        "with a single word: yes or no. You never grant credit for a skill "
        "the candidate does not plausibly already have an adjacent skill for."
    )
    user = (
        f"A candidate has these skills: {', '.join(sorted(candidate_skills))}.\n"
        f"A job requires: '{job_skill}'.\n"
        f"Is '{job_skill}' a closely related/transferable skill to ANY of the "
        "candidate's skills (e.g. same family of tools/frameworks, not just "
        "the same broad category)? Be strict - only answer 'yes' if a "
        "candidate with those skills could realistically pick up this specific "
        "tool quickly because of a very similar one they already know.\n"
        "Answer with exactly one word: yes or no."
    )
    return system, user


def resume_analysis_prompt(
    job_description: str, master_resume: str, candidate_profile: dict[str, Any]
) -> tuple[str, str]:
    """Used by LLMProvider.analyze_resume - semantic resume/job match
    analysis and (optionally) a tailored resume draft.

    The model is instructed to respond in strict JSON so the provider can
    parse it deterministically; any parse failure must be treated by the
    caller as "no LLM enrichment available" rather than crashing.
    """
    system = (
        "You are a resume-matching assistant for a job application tool. "
        "You must NEVER invent or imply skills, jobs, employers, degrees, "
        "certifications, or projects that are not explicitly present in the "
        "candidate's master resume or profile below. If something the job "
        "wants is missing from the resume, say it is missing - do not soften "
        "or hide the gap, and do not fabricate a plausible-sounding fix. "
        "You may reorder, re-emphasize, and rephrase the candidate's real "
        "content, but you may not add new factual claims.\n\n"
        "Respond with ONLY a valid JSON object (no prose, no markdown code "
        "fences) with exactly these keys:\n"
        '{"strong_skills": [...], "missing_skills": [...], '
        '"suggested_changes": [...], "tailored_resume": "..."}'
    )
    user = (
        f"Candidate profile (ground truth - do not exceed this):\n{candidate_profile}\n\n"
        f"Master resume (ground truth - do not exceed this):\n{master_resume}\n\n"
        f"Job description:\n{job_description}\n\n"
        "Analyze the match and produce the JSON object described in the "
        "system prompt. 'tailored_resume' should be a lightly reordered / "
        "re-emphasized version of the master resume for this specific job - "
        "not a rewrite that adds anything new."
    )
    return system, user


def cover_letter_prompt(
    job_description: str, resume_content: str, candidate_profile: dict[str, Any]
) -> tuple[str, str]:
    """Used by LLMProvider.generate_cover_letter."""
    system = (
        "You write concise, honest cover letters for a job application tool. "
        "You must only use facts present in the candidate's resume and "
        "profile provided below. Never invent experience, employers, "
        "achievements, metrics, or skills. If you cannot find enough real "
        "material to make a strong case, write a shorter, more modest "
        "letter rather than fabricating content. Keep it under 250 words, "
        "professional but not generic, and specific to the job description."
    )
    user = (
        f"Candidate profile:\n{candidate_profile}\n\n"
        f"Resume:\n{resume_content}\n\n"
        f"Job description:\n{job_description}\n\n"
        "Write the cover letter now."
    )
    return system, user


def generative_answer_prompt(
    question: str, candidate_profile: dict[str, Any], job_description: str
) -> tuple[str, str]:
    """Used by LLMProvider.answer_generative_question for open-ended
    application questions (e.g. "Why do you want to work here?")."""
    system = (
        "You answer open-ended job application questions on behalf of a "
        "candidate. You must only draw on the facts in the candidate's "
        "profile provided below - never invent experience, motivations, or "
        "accomplishments that aren't supported by it. Keep answers concise "
        "(2-5 sentences), specific rather than generic, and honest. If the "
        "profile doesn't give you enough to answer specifically, write a "
        "brief, genuine answer rather than padding with cliches."
    )
    user = (
        f"Candidate profile:\n{candidate_profile}\n\n"
        f"Job description:\n{job_description}\n\n"
        f"Application question: {question}\n\n"
        "Write the answer now."
    )
    return system, user
