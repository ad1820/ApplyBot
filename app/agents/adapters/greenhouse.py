"""Greenhouse application platform adapter.

Detection is purely URL-pattern based; inspection/extraction operate on
data the caller supplies (e.g. fetched HTML/JSON) rather than the adapter
performing unauthorized scraping itself.
"""
from __future__ import annotations

from app.agents.adapters.base import ApplicationAdapter, ExtractedQuestion


class GreenhouseAdapter(ApplicationAdapter):
    platform_name = "greenhouse"

    def detect(self, url: str) -> bool:
        return "greenhouse.io" in url or "boards.greenhouse.io" in url

    def inspect(self, url: str) -> dict:
        return {"url": url, "platform": self.platform_name}

    def extract_questions(self, page_data: dict) -> list[ExtractedQuestion]:
        raw_questions = page_data.get("questions", [])
        return [
            ExtractedQuestion(
                text=q.get("label", ""),
                required=q.get("required", False),
                field_type=q.get("type", "text"),
            )
            for q in raw_questions
        ]
