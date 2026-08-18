"""V2: Cover Letter Agent.

Generates job-specific cover letters using only truthful information from
the candidate profile and resume. Never invents experience. Falls back to
an empty string (caller decides how to handle) if the LLM is unavailable -
we do not fabricate a cover letter with template-guessed claims.
"""
from __future__ import annotations

from typing import Any

from app.llm.base import LLMError, LLMProvider


def generate_cover_letter(
    job_description: str,
    resume_content: str,
    candidate_profile: dict[str, Any],
    llm_provider: LLMProvider,
) -> str:
    try:
        return llm_provider.generate_cover_letter(job_description, resume_content, candidate_profile)
    except LLMError:
        return ""
