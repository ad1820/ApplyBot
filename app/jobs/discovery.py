"""Job source abstraction.

Each concrete JobSource is responsible for fetching raw postings from one
place and returning them as normalized Job objects. We only integrate with
official/public APIs or user-provided data - no unauthorized scraping or
automation of platforms that prohibit it (e.g. LinkedIn).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from app.jobs.models import Job, WorkMode


class JobSource(ABC):
    name: str = "unknown"

    @abstractmethod
    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        """Return normalized jobs matching the given preferences."""
        raise NotImplementedError


def _guess_work_mode(text: str | None) -> WorkMode:
    if not text:
        return WorkMode.UNKNOWN
    lowered = text.lower()
    if "remote" in lowered:
        return WorkMode.REMOTE
    if "hybrid" in lowered:
        return WorkMode.HYBRID
    if "onsite" in lowered or "on-site" in lowered or "in office" in lowered:
        return WorkMode.ONSITE
    return WorkMode.UNKNOWN


class GreenhouseSource(JobSource):
    """Uses Greenhouse's public job board API (no auth required, permitted
    for programmatic access): https://boards-api.greenhouse.io/v1/boards/{board}/jobs
    """

    name = "greenhouse"

    def __init__(self, board_tokens: list[str], client: httpx.Client | None = None):
        self.board_tokens = board_tokens
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        jobs: list[Job] = []
        for board in self.board_tokens:
            try:
                url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
                response = self._client.get(url)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                # One board being unavailable must not break the whole run.
                continue
            for raw in data.get("jobs", []):
                jobs.append(self._normalize(raw, board))
        return jobs

    def _normalize(self, raw: dict[str, Any], board: str) -> Job:
        location = (raw.get("location") or {}).get("name")
        content = raw.get("content") or ""
        return Job(
            external_id=str(raw.get("id")),
            source=self.name,
            company=board,
            title=raw.get("title", "Unknown Title"),
            location=location,
            work_mode=_guess_work_mode(f"{location} {content}"),
            description=content,
            url=raw.get("absolute_url"),
            posted_at=_parse_datetime(raw.get("updated_at")),
            discovered_at=datetime.now(timezone.utc),
        )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class LeverSource(JobSource):
    """Uses Lever's public postings API (no auth required, permitted for
    programmatic access): https://api.lever.co/v0/postings/{company}?mode=json
    """

    name = "lever"

    def __init__(self, company_slugs: list[str], client: httpx.Client | None = None):
        self.company_slugs = company_slugs
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        jobs: list[Job] = []
        for company in self.company_slugs:
            try:
                url = f"https://api.lever.co/v0/postings/{company}?mode=json"
                response = self._client.get(url)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                # One company's board being unavailable must not break the
                # whole run.
                continue
            if not isinstance(data, list):
                continue
            for raw in data:
                jobs.append(self._normalize(raw, company))
        return jobs

    def _normalize(self, raw: dict[str, Any], company: str) -> Job:
        categories = raw.get("categories") or {}
        location = categories.get("location")
        description = raw.get("descriptionPlain") or raw.get("description") or ""
        commitment = categories.get("commitment") or ""
        return Job(
            external_id=str(raw.get("id")),
            source=self.name,
            company=company,
            title=raw.get("text", "Unknown Title"),
            location=location,
            work_mode=_guess_work_mode(f"{location} {commitment} {description}"),
            description=description,
            url=raw.get("hostedUrl") or raw.get("applyUrl"),
            posted_at=_parse_lever_timestamp(raw.get("createdAt")),
            discovered_at=datetime.now(timezone.utc),
        )


def _parse_lever_timestamp(value: Any) -> datetime | None:
    """Lever's createdAt is epoch milliseconds, not an ISO string."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


class AshbySource(JobSource):
    """Uses Ashby's public job board API (no auth required, permitted for
    programmatic access): https://api.ashbyhq.com/posting-api/job-board/{company}
    """

    name = "ashby"

    def __init__(self, company_slugs: list[str], client: httpx.Client | None = None):
        self.company_slugs = company_slugs
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        jobs: list[Job] = []
        for company in self.company_slugs:
            try:
                url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
                response = self._client.get(url)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                continue
            for raw in data.get("jobs", []):
                jobs.append(self._normalize(raw, company))
        return jobs

    def _normalize(self, raw: dict[str, Any], company: str) -> Job:
        location = raw.get("location")
        description = raw.get("descriptionPlain") or raw.get("descriptionHtml") or ""
        workplace_type = raw.get("workplaceType") or ""
        return Job(
            external_id=str(raw.get("id")),
            source=self.name,
            company=company,
            title=raw.get("title", "Unknown Title"),
            location=location,
            work_mode=_guess_work_mode(f"{location} {workplace_type} {description}"),
            description=description,
            url=raw.get("jobUrl") or raw.get("applyUrl"),
            posted_at=_parse_datetime(raw.get("publishedAt")),
            discovered_at=datetime.now(timezone.utc),
        )


class RemoteOKSource(JobSource):
    """Uses RemoteOK's public JSON feed: https://remoteok.com/api
    Documented as free for personal/non-commercial use with attribution.
    """

    name = "remoteok"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"})

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        try:
            response = self._client.get("https://remoteok.com/api")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        jobs = []
        for raw in data:
            if not isinstance(raw, dict) or "id" not in raw or "position" not in raw:
                continue  # first element is a metadata/legal notice, not a job
            jobs.append(self._normalize(raw))
        return jobs

    def _normalize(self, raw: dict[str, Any]) -> Job:
        description = raw.get("description") or ""
        tags = raw.get("tags") or []
        return Job(
            external_id=str(raw.get("id")),
            source=self.name,
            company=raw.get("company", "Unknown"),
            title=raw.get("position", "Unknown Title"),
            location=raw.get("location") or "Remote",
            work_mode=WorkMode.REMOTE,
            description=description,
            skills=[str(t) for t in tags],
            url=raw.get("url") or raw.get("apply_url"),
            posted_at=_parse_datetime(raw.get("date")),
            discovered_at=datetime.now(timezone.utc),
        )


class RemotiveSource(JobSource):
    """Uses Remotive's public API: https://remotive.com/api/remote-jobs
    Per Remotive's terms, results should link back and credit Remotive as
    the source (handled by pointing the "Apply" link directly at the job's
    own URL as returned by the API).
    """

    name = "remotive"

    def __init__(self, category: str = "software-dev", client: httpx.Client | None = None):
        self.category = category
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        try:
            response = self._client.get(
                "https://remotive.com/api/remote-jobs", params={"category": self.category}
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return [self._normalize(raw) for raw in data.get("jobs", [])]

    def _normalize(self, raw: dict[str, Any]) -> Job:
        description = raw.get("description") or ""
        tags = raw.get("tags") or []
        return Job(
            external_id=str(raw.get("id")),
            source=self.name,
            company=raw.get("company_name", "Unknown"),
            title=raw.get("title", "Unknown Title"),
            location=raw.get("candidate_required_location") or "Remote",
            work_mode=WorkMode.REMOTE,
            description=description,
            skills=[str(t) for t in tags],
            url=raw.get("url"),
            posted_at=_parse_datetime(raw.get("publication_date")),
            discovered_at=datetime.now(timezone.utc),
        )


class WorkingNomadsSource(JobSource):
    """Uses WorkingNomads' public exposed-jobs JSON feed:
    https://www.workingnomads.com/api/exposed_jobs/
    """

    name = "workingnomads"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        try:
            response = self._client.get("https://www.workingnomads.com/api/exposed_jobs/")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return [self._normalize(raw) for raw in data]

    def _normalize(self, raw: dict[str, Any]) -> Job:
        description = raw.get("description") or ""
        tags = raw.get("tags") or ""
        skills = [t.strip() for t in tags.split(",")] if isinstance(tags, str) else list(tags)
        return Job(
            external_id=raw.get("url"),
            source=self.name,
            company=raw.get("company_name", "Unknown"),
            title=raw.get("title", "Unknown Title"),
            location=raw.get("location") or "Remote",
            work_mode=WorkMode.REMOTE,
            description=description,
            skills=skills,
            url=raw.get("url"),
            posted_at=_parse_datetime(raw.get("pub_date")),
            discovered_at=datetime.now(timezone.utc),
        )


class HimalayasSource(JobSource):
    """Uses Himalayas' public jobs API: https://himalayas.app/jobs/api"""

    name = "himalayas"

    def __init__(self, limit: int = 100, client: httpx.Client | None = None):
        self.limit = limit
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        try:
            response = self._client.get("https://himalayas.app/jobs/api", params={"limit": self.limit})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        return [self._normalize(raw) for raw in data.get("jobs", [])]

    def _normalize(self, raw: dict[str, Any]) -> Job:
        description = raw.get("excerpt") or ""
        categories = raw.get("categories") or []
        locations = raw.get("locationRestrictions") or []
        location = ", ".join(locations) if locations else "Remote"
        return Job(
            external_id=(raw.get("companySlug", "") + "-" + raw.get("title", "")) or None,
            source=self.name,
            company=raw.get("companyName", "Unknown"),
            title=raw.get("title", "Unknown Title"),
            location=location,
            work_mode=WorkMode.REMOTE,
            description=description,
            skills=[str(c) for c in categories],
            salary_min=raw.get("minSalary"),
            salary_max=raw.get("maxSalary"),
            currency=raw.get("currency"),
            url=raw.get("applicationLink") or raw.get("guid"),
            discovered_at=datetime.now(timezone.utc),
        )


class WeWorkRemotelySource(JobSource):
    """Uses We Work Remotely's public RSS feed for the programming category:
    https://weworkremotely.com/categories/remote-programming-jobs.rss
    """

    name = "weworkremotely"

    def __init__(
        self,
        feed_url: str = "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        client: httpx.Client | None = None,
    ):
        self.feed_url = feed_url
        self._client = client or httpx.Client(timeout=15.0)

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        import xml.etree.ElementTree as ET

        try:
            response = self._client.get(self.feed_url)
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except (httpx.HTTPError, ET.ParseError):
            return []

        jobs = []
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            region_el = item.find("region")
            raw_title = (title_el.text or "").strip() if title_el is not None else "Unknown Title"
            # WWR RSS titles are formatted "Company: Job Title"
            if ":" in raw_title:
                company, _, title = raw_title.partition(":")
                company, title = company.strip(), title.strip()
            else:
                company, title = "Unknown", raw_title
            jobs.append(
                Job(
                    external_id=link_el.text if link_el is not None else None,
                    source=self.name,
                    company=company,
                    title=title or "Unknown Title",
                    location=(region_el.text or "Remote").strip() if region_el is not None else "Remote",
                    work_mode=WorkMode.REMOTE,
                    description=(desc_el.text or "") if desc_el is not None else "",
                    url=link_el.text if link_el is not None else None,
                    discovered_at=datetime.now(timezone.utc),
                )
            )
        return jobs


class UserProvidedSource(JobSource):
    """Allows the user to manually supply job postings (e.g. pasted job
    description + URL) instead of relying on any external scraping."""

    name = "user_provided"

    def __init__(self, jobs: list[dict[str, Any]] | None = None):
        self._jobs = jobs or []

    def search_jobs(self, preferences: dict[str, Any]) -> list[Job]:
        jobs = []
        for raw in self._jobs:
            jobs.append(
                Job(
                    external_id=raw.get("external_id"),
                    source=self.name,
                    company=raw.get("company", "Unknown"),
                    title=raw.get("title", "Unknown Title"),
                    location=raw.get("location"),
                    work_mode=_guess_work_mode(raw.get("work_mode") or raw.get("description")),
                    description=raw.get("description"),
                    skills=raw.get("skills", []),
                    url=raw.get("url"),
                    discovered_at=datetime.now(timezone.utc),
                )
            )
        return jobs
