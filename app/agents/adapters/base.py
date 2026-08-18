"""Application platform adapter abstraction.

Different application-tracking systems (Greenhouse, Lever, Workday, Ashby,
generic company pages) structure their forms differently. Adapters are
responsible only for *detecting* the platform and *extracting questions* -
they never submit anything.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExtractedQuestion:
    text: str
    required: bool = False
    field_type: str = "text"  # text | select | boolean | file


class ApplicationAdapter(ABC):
    platform_name: str = "generic"

    @abstractmethod
    def detect(self, url: str) -> bool:
        """Return True if this adapter can handle the given application URL."""
        raise NotImplementedError

    @abstractmethod
    def inspect(self, url: str) -> dict:
        """Fetch/describe the application page. Returns raw metadata."""
        raise NotImplementedError

    @abstractmethod
    def extract_questions(self, page_data: dict) -> list[ExtractedQuestion]:
        """Extract the list of application questions from inspected page data."""
        raise NotImplementedError
