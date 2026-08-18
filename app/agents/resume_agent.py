"""V2: Resume Agent.

Compares a job description against the master resume + candidate profile
and produces a match analysis and (only after explicit user approval) a
tailored resume. This agent must NEVER invent experience, skills, jobs,
degrees, certifications or projects the candidate does not actually have.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jobs.matcher import score_job
from app.jobs.models import Job
from app.llm.base import LLMError, LLMProvider


@dataclass
class ResumeAnalysis:
    match_score: float
    strong_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    suggested_changes: list[str] = field(default_factory=list)
    tailored_resume: str = ""


def analyze_resume(
    job: Job,
    master_resume_content: str,
    candidate_profile: dict[str, Any],
    llm_provider: LLMProvider,
) -> ResumeAnalysis:
    """Deterministic skills-overlap analysis, optionally enriched by the LLM
    for phrasing/ordering suggestions. Falls back to deterministic-only
    output if the LLM call fails."""
    deterministic = score_job(job, candidate_profile, {})

    suggested_changes: list[str] = []
    if deterministic.matching_skills:
        suggested_changes.append(
            "Emphasize these matching skills near the top of the resume: "
            + ", ".join(deterministic.matching_skills)
        )
    if deterministic.missing_skills:
        suggested_changes.append(
            "Do not claim experience with: " + ", ".join(deterministic.missing_skills)
            + " - these are missing from the candidate profile."
        )

    tailored_resume = master_resume_content
    try:
        llm_result = llm_provider.analyze_resume(
            job_description=job.description or "",
            master_resume=master_resume_content,
            candidate_profile=candidate_profile,
        )
        if llm_result:
            suggested_changes.extend(llm_result.get("suggested_changes", []))
            tailored_resume = llm_result.get("tailored_resume", tailored_resume)
    except LLMError:
        # Degrade gracefully - deterministic analysis is still fully valid.
        pass

    return ResumeAnalysis(
        match_score=deterministic.match_score,
        strong_skills=deterministic.matching_skills,
        missing_skills=deterministic.missing_skills,
        suggested_changes=suggested_changes,
        tailored_resume=tailored_resume,
    )
