"""Fallback adapter for application platforms without a dedicated adapter.

Always matches (detect() returns True) so it can be used as a last resort.
Extraction relies on generic keys since the page structure is unknown.
"""
from __future__ import annotations

from app.agents.adapters.base import ApplicationAdapter, ExtractedQuestion


class GenericAdapter(ApplicationAdapter):
    platform_name = "generic"

    def detect(self, url: str) -> bool:
        return True

    def inspect(self, url: str) -> dict:
        return {"url": url, "platform": self.platform_name}

    def extract_questions(self, page_data: dict) -> list[ExtractedQuestion]:
        raw_questions = page_data.get("questions", [])
        return [
            ExtractedQuestion(
                text=q.get("text") or q.get("label") or q.get("title") or "",
                required=bool(q.get("required") or q.get("isRequired")),
                field_type=q.get("type", "text"),
            )
            for q in raw_questions
        ]


def detect_adapter(url: str, adapters: list[ApplicationAdapter]) -> ApplicationAdapter:
    for adapter in adapters:
        if adapter.platform_name != "generic" and adapter.detect(url):
            return adapter
    return GenericAdapter()
