"""A no-op provider used when no LLM is configured, and in tests.

Ensures the system remains fully operable (deterministic matching, manual
flows) even without any LLM credentials.
"""
from __future__ import annotations

from typing import Any, Optional

from app.llm.base import LLMProvider


class NullProvider(LLMProvider):
    name = "null"

    def complete(self, prompt: str, *, system: Optional[str] = None, max_tokens: int = 512) -> str:
        return ""

    def analyze_job_match(self, job_description: str, candidate_profile: dict[str, Any]) -> dict[str, Any]:
        return {}

    def analyze_resume(self, job_description: str, master_resume: str, candidate_profile: dict[str, Any]) -> dict[str, Any]:
        return {
            "strong_skills": [],
            "missing_skills": [],
            "suggested_changes": [],
            "tailored_resume": master_resume,
        }

    def generate_cover_letter(self, job_description: str, resume_content: str, candidate_profile: dict[str, Any]) -> str:
        return ""

    def answer_generative_question(self, question: str, candidate_profile: dict[str, Any], job_description: str) -> str:
        return ""
