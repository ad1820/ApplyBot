"""Normalized job models and the job status state machine.

All job sources must produce this common shape regardless of where the raw
data came from.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    NOTIFIED = "NOTIFIED"
    INTERESTED = "INTERESTED"
    SKIPPED = "SKIPPED"
    APPLIED = "APPLIED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    OFFER = "OFFER"
    WITHDRAWN = "WITHDRAWN"


# Allowed transitions out of each status. Used to validate status changes
# rather than allowing arbitrary jumps (e.g. SKIPPED -> OFFER makes no sense).
ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.DISCOVERED: {JobStatus.NOTIFIED, JobStatus.SKIPPED},
    JobStatus.NOTIFIED: {JobStatus.INTERESTED, JobStatus.SKIPPED, JobStatus.APPLIED},
    JobStatus.INTERESTED: {JobStatus.APPLIED, JobStatus.SKIPPED},
    JobStatus.SKIPPED: {JobStatus.INTERESTED, JobStatus.APPLIED},
    JobStatus.APPLIED: {JobStatus.INTERVIEW, JobStatus.REJECTED, JobStatus.WITHDRAWN},
    JobStatus.INTERVIEW: {JobStatus.OFFER, JobStatus.REJECTED, JobStatus.WITHDRAWN},
    JobStatus.REJECTED: set(),
    JobStatus.OFFER: {JobStatus.WITHDRAWN},
    JobStatus.WITHDRAWN: set(),
}


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class Job(BaseModel):
    id: Optional[str] = None
    external_id: Optional[str] = None
    source: str
    company: str
    title: str
    location: Optional[str] = None
    work_mode: WorkMode = WorkMode.UNKNOWN
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    posted_at: Optional[datetime] = None
    discovered_at: Optional[datetime] = None
    match_score: Optional[float] = None
    status: JobStatus = JobStatus.DISCOVERED

    def canonical_key(self) -> str:
        """A stable key used for dedup, independent of URL formatting."""
        from app.jobs.deduplicator import compute_canonical_key

        return compute_canonical_key(self.company, self.title, self.location, self.external_id)
