"""V2: Answer Engine.

Classifies application questions into four categories and answers them
accordingly:

- PROFILE_FACT: answered directly from the candidate profile.
- DERIVED_FACT: derived deterministically from resume/profile (e.g. years
  of experience with a technology).
- GENERATIVE: answered via the LLM (e.g. "Why do you want to work here?").
- SENSITIVE: never guessed. We look for a previously user-approved answer;
  if none exists, the caller must ask the user explicitly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from app.llm.base import LLMError, LLMProvider

PROFILE_FACT_PATTERNS = [
    r"\bname\b", r"\bemail\b", r"\bphone\b", r"\blocation\b", r"\baddress\b",
]

DERIVED_FACT_PATTERNS = [
    r"years? of experience", r"experience with", r"how many years",
    r"proficien(cy|t)", r"familiar with",
]

SENSITIVE_PATTERNS = [
    r"sponsorship", r"relocat", r"expected salary", r"salary expectation",
    r"work authorization", r"visa", r"security clearance", r"notice period",
]

GENERATIVE_PATTERNS = [
    r"why do you want", r"why should we", r"describe", r"tell us about",
    r"most challenging", r"greatest strength", r"greatest weakness",
]


@dataclass
class AnswerResult:
    answer: Optional[str]
    source: str  # PROFILE | DERIVED | GENERATED | USER_APPROVED | NEEDS_USER_INPUT
    category: str


def classify_question(question_text: str) -> str:
    lowered = question_text.lower()
    if any(re.search(p, lowered) for p in SENSITIVE_PATTERNS):
        return "SENSITIVE"
    if any(re.search(p, lowered) for p in PROFILE_FACT_PATTERNS):
        return "PROFILE_FACT"
    if any(re.search(p, lowered) for p in DERIVED_FACT_PATTERNS):
        return "DERIVED_FACT"
    if any(re.search(p, lowered) for p in GENERATIVE_PATTERNS):
        return "GENERATIVE"
    # Default to sensitive/ambiguous: never guess if unsure.
    return "SENSITIVE"


_PROFILE_FIELD_MAP = {
    r"\bname\b": "name",
    r"\bemail\b": "email",
    r"\bphone\b": "phone",
    r"\blocation\b|\baddress\b": "location",
}


def answer_profile_fact(question_text: str, candidate_profile: dict[str, Any]) -> Optional[str]:
    lowered = question_text.lower()
    for pattern, field in _PROFILE_FIELD_MAP.items():
        if re.search(pattern, lowered):
            value = candidate_profile.get(field)
            if value:
                return str(value)
    return None


def answer_derived_fact(question_text: str, candidate_profile: dict[str, Any]) -> Optional[str]:
    lowered = question_text.lower()
    skills = {s.lower() for s in candidate_profile.get("skills", [])}
    for skill in skills:
        if skill in lowered:
            years = candidate_profile.get("years_of_experience")
            if years is not None:
                return f"Yes, approximately {years} years of experience, including with {skill}."
            return f"Yes, experience with {skill}."
    return None


def answer_generative(
    question_text: str,
    candidate_profile: dict[str, Any],
    job_description: str,
    llm_provider: LLMProvider,
) -> Optional[str]:
    try:
        result = llm_provider.answer_generative_question(question_text, candidate_profile, job_description)
        return result or None
    except LLMError:
        return None


def answer_question(
    question_text: str,
    candidate_profile: dict[str, Any],
    job_description: str,
    llm_provider: LLMProvider,
    previously_approved_answer: Optional[str] = None,
) -> AnswerResult:
    category = classify_question(question_text)

    if category == "SENSITIVE":
        if previously_approved_answer:
            return AnswerResult(answer=previously_approved_answer, source="USER_APPROVED", category=category)
        return AnswerResult(answer=None, source="NEEDS_USER_INPUT", category=category)

    if category == "PROFILE_FACT":
        answer = answer_profile_fact(question_text, candidate_profile)
        if answer:
            return AnswerResult(answer=answer, source="PROFILE", category=category)
        return AnswerResult(answer=None, source="NEEDS_USER_INPUT", category=category)

    if category == "DERIVED_FACT":
        answer = answer_derived_fact(question_text, candidate_profile)
        if answer:
            return AnswerResult(answer=answer, source="DERIVED", category=category)
        return AnswerResult(answer=None, source="NEEDS_USER_INPUT", category=category)

    # GENERATIVE
    answer = answer_generative(question_text, candidate_profile, job_description, llm_provider)
    if answer:
        return AnswerResult(answer=answer, source="GENERATED", category=category)
    return AnswerResult(answer=None, source="NEEDS_USER_INPUT", category=category)
