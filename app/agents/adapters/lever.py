"""Lever application platform adapter."""
from __future__ import annotations

from app.agents.adapters.base import ApplicationAdapter, ExtractedQuestion


class LeverAdapter(ApplicationAdapter):
    platform_name = "lever"

    def detect(self, url: str) -> bool:
        return "lever.co" in url

    def inspect(self, url: str) -> dict:
        return {"url": url, "platform": self.platform_name}

    def extract_questions(self, page_data: dict) -> list[ExtractedQuestion]:
        raw_questions = page_data.get("questions", [])
        return [
            ExtractedQuestion(
                text=q.get("text", ""),
                required=q.get("required", False),
                field_type=q.get("type", "text"),
            )
            for q in raw_questions
        ]
