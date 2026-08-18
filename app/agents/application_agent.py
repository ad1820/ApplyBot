"""V2: Application Assistant orchestration.

Detects the platform, extracts questions, classifies + answers them via the
answer engine, and returns everything for human review. Never submits an
application on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.agents.adapters.ashby import AshbyAdapter
from app.agents.adapters.base import ApplicationAdapter, ExtractedQuestion
from app.agents.adapters.generic import GenericAdapter, detect_adapter
from app.agents.adapters.greenhouse import GreenhouseAdapter
from app.agents.adapters.lever import LeverAdapter
from app.agents.answer_engine import AnswerResult, answer_question
from app.llm.base import LLMProvider

DEFAULT_ADAPTERS: list[ApplicationAdapter] = [GreenhouseAdapter(), LeverAdapter(), AshbyAdapter()]


@dataclass
class PreparedAnswer:
    question: ExtractedQuestion
    result: AnswerResult


def detect_platform(url: str, adapters: Optional[list[ApplicationAdapter]] = None) -> ApplicationAdapter:
    return detect_adapter(url, adapters or DEFAULT_ADAPTERS)


def prepare_answers(
    url: str,
    page_data: dict[str, Any],
    candidate_profile: dict[str, Any],
    job_description: str,
    llm_provider: LLMProvider,
    lookup_approved_answer,
    adapters: Optional[list[ApplicationAdapter]] = None,
) -> list[PreparedAnswer]:
    """`lookup_approved_answer` is a callable(question_text) -> Optional[str]
    so this function stays decoupled from the repository layer (and is thus
    trivially unit testable)."""
    adapter = detect_platform(url, adapters)
    questions = adapter.extract_questions(page_data)

    prepared: list[PreparedAnswer] = []
    for question in questions:
        approved = lookup_approved_answer(question.text)
        result = answer_question(
            question.text, candidate_profile, job_description, llm_provider, previously_approved_answer=approved
        )
        prepared.append(PreparedAnswer(question=question, result=result))
    return prepared
