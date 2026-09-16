"""Orchestrates a full job-search run: discovery -> dedup -> matching ->
persistence -> Sheets sync -> notification, with restart-safe run tracking.

Supabase (agent_runs / jobs / notifications tables) is the single source of
truth. Every operation here is written to be idempotent so re-running after
a crash never duplicates jobs or notifications.

Google Sheets is kept in sync with exactly what gets pushed to Telegram:
only jobs that clear role, fresher, location, and minimum-score filters are
synced to Sheets or notified. Every job is still
persisted in Supabase regardless of score (visible via /jobs), but Sheets
and Telegram only ever show the same, genuinely strong matches.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.db.repositories.jobs import JobRepository, JobSourceRepository
from app.db.repositories.notifications import NotificationRepository
from app.db.repositories.runs import AgentRunRepository
from app.jobs.deduplicator import compute_canonical_key
from app.jobs.discovery import JobSource
from app.jobs.matcher import (
    assess_fresher_fit,
    assess_location_fit,
    role_priority_for_title,
    score_job,
    title_matches_preferred_roles,
)
from app.jobs.models import Job, JobStatus
from app.logging_config import get_logger, log_event
from app.telegram.bot import TelegramBot
from app.telegram.messages import format_company_digest

logger = get_logger(__name__)


class JobSearchService:
    def __init__(
        self,
        job_repo: JobRepository,
        job_source_repo: JobSourceRepository,
        run_repo: AgentRunRepository,
        notification_repo: NotificationRepository,
        sources: list[JobSource],
        telegram_bot: Optional[TelegramBot] = None,
        telegram_chat_id: Optional[str] = None,
        sheets_sync_fn=None,
        minimum_match_score: float = 80.0,
        semantic_skill_checker: Optional[Callable[[str, set[str]], Optional[str]]] = None,
    ):
        self.job_repo = job_repo
        self.job_source_repo = job_source_repo
        self.run_repo = run_repo
        self.notification_repo = notification_repo
        self.sources = sources
        self.telegram_bot = telegram_bot
        self.telegram_chat_id = telegram_chat_id
        self.sheets_sync_fn = sheets_sync_fn
        self.minimum_match_score = minimum_match_score
        self.semantic_skill_checker = semantic_skill_checker

    def run(self, profile: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
        run = self.run_repo.start_run(source="scheduled")
        run_id = run["id"]
        counters = {"jobs_found": 0, "jobs_new": 0, "jobs_duplicate": 0, "jobs_notified": 0}
        last_error: Optional[str] = None
        notified_jobs: list[dict[str, Any]] = []

        for source in self.sources:
            try:
                raw_jobs = source.search_jobs(preferences)
            except Exception as exc:  # noqa: BLE001 - one source failing must not abort the run
                last_error = f"{source.name} discovery failed: {exc}"
                log_event(logger, "error", last_error, run_id=run_id, operation="discovery", status="FAILED")
                continue

            for job in raw_jobs:
                try:
                    self._process_job(job, profile, preferences, counters, run_id, notified_jobs)
                except Exception as exc:  # noqa: BLE001 - one bad job must not abort the run
                    title = getattr(job, "title", "<unknown>")
                    company = getattr(job, "company", "<unknown>")
                    last_error = f"Failed processing job {title} @ {company}: {exc}"
                    log_event(logger, "error", last_error, run_id=run_id, operation="process_job", status="FAILED")
                    continue

        self._notify_digest(notified_jobs, counters, run_id)

        self.run_repo.update_counters(run_id, **counters)
        if last_error:
            self.run_repo.partial_run(run_id, error_message=last_error, **counters)
        else:
            self.run_repo.complete_run(run_id, **counters)

        return {"run_id": run_id, **counters, "error": last_error}

    def _process_job(
        self,
        job: Job,
        profile: dict[str, Any],
        preferences: dict[str, Any],
        counters: dict[str, int],
        run_id: str,
        notified_jobs: list[dict[str, Any]],
    ) -> None:
        counters["jobs_found"] += 1
        
        canonical_key = compute_canonical_key(job.company, job.title, job.location, job.external_id)
        existing = self.job_repo.find_by_canonical_key(canonical_key)

        if existing:
            counters["jobs_duplicate"] += 1
            self.job_source_repo.add_source(existing["id"], job.source, job.external_id, job.url)
            return

        preferred_roles = preferences.get("preferred_roles") or []
        role_matches = not preferred_roles or title_matches_preferred_roles(job.title, preferred_roles)

        fresher_only = preferences.get(
            "fresher_friendly_only",
            float(profile.get("years_of_experience") or 0) <= 1,
        )
        fresher_fit = assess_fresher_fit(job, profile, preferences)
        fresher_matches = not fresher_only or fresher_fit.eligible

        preferred_locations = preferences.get("preferred_locations") or []
        location_fit = assess_location_fit(job)
        location_matches = not preferred_locations or location_fit.eligible

        # Only spend LLM quota after the deterministic gates pass. Rejected
        # jobs are still scored and persisted, but use deterministic matching
        # exclusively so unrelated titles never consume provider RPM.
        semantic_checker = (
            self.semantic_skill_checker
            if role_matches and fresher_matches and location_matches
            else None
        )
        match = score_job(job, profile, preferences, semantic_skill_checker=semantic_checker)
        payload = {
            "external_id": job.external_id,
            "source": job.source,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "work_mode": job.work_mode.value,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "currency": job.currency,
            "description": job.description,
            "requirements": job.requirements,
            "skills": job.skills,
            "url": job.url,
            "canonical_key": canonical_key,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            "match_score": match.match_score,
            "matching_skills": match.matching_skills,
            "related_skills": match.related_skills,
            "missing_skills": match.missing_skills,
            "matching_reasons": match.matching_reasons,
            "concerns": match.concerns,
            "status": JobStatus.DISCOVERED.value,
        }
        created = self.job_repo.create(payload)
        counters["jobs_new"] += 1
        self.job_source_repo.add_source(created["id"], job.source, job.external_id, job.url)

        if not role_matches:
            # Hard filter: the job is persisted (so it's still visible via
            # /jobs) but is not pushed as a Telegram notification and not
            # synced to Sheets, since its title doesn't match any role the
            # candidate is looking for.
            log_event(
                logger, "info", "Job title does not match preferred roles - notification skipped",
                run_id=run_id, job_id=created["id"], operation="role_filter", status="SKIPPED",
            )
            return

        if not fresher_matches:
            log_event(
                logger, "info", "Job is not fresher friendly - notification skipped",
                run_id=run_id, job_id=created["id"], operation="fresher_filter", status="SKIPPED",
                reason=fresher_fit.reason,
            )
            return

        if not location_matches:
            log_event(
                logger, "info", "Job is outside candidate location eligibility - notification skipped",
                run_id=run_id, job_id=created["id"], operation="location_filter", status="SKIPPED",
                reason=location_fit.reason,
            )
            return

        if match.match_score < self.minimum_match_score:
            # Hard filter: below the configured minimum match threshold -
            # persisted but not notified and not synced to Sheets. Sheets
            # mirrors exactly what gets sent to Telegram, so only genuinely
            # strong matches ever show up in either place.
            log_event(
                logger, "info", "Job below minimum match score - notification skipped",
                run_id=run_id, job_id=created["id"], operation="score_filter", status="SKIPPED",
                match_score=match.match_score, minimum_match_score=self.minimum_match_score,
            )
            return

        # From here on the job has cleared both the role and score filters -
        # sync it to Sheets (best-effort) and queue it for the end-of-run
        # grouped Telegram digest (see _notify_digest) rather than pushing
        # an individual message immediately - a run finding many matches at
        # once should produce one message to scan, not one push per job.
        if self.sheets_sync_fn:
            try:
                self.sheets_sync_fn(created)
            except Exception as exc:  # noqa: BLE001 - Sheets must never block the pipeline
                log_event(logger, "error", "sheets sync failed", run_id=run_id, job_id=created["id"], error=str(exc))

        self._queue_notification(created, notified_jobs)

    def _queue_notification(self, job: dict[str, Any], notified_jobs: list[dict[str, Any]]) -> None:
        if not self.telegram_bot or not self.telegram_chat_id:
            return
        if self.notification_repo.already_sent(job["id"]):
            return
        self.notification_repo.record_pending(job["id"])
        notified_jobs.append(job)

    def _notify_digest(self, notified_jobs: list[dict[str, Any]], counters: dict[str, int], run_id: str) -> None:
        """Send exactly one grouped-by-company message for every job queued
        during this run (see _queue_notification), instead of one push per
        job. Tapping a company's inline button later shows that company's
        jobs (see app.telegram.handlers.handle_company_jobs_callback and
        the /companies command) - both read live from Supabase, so this
        digest itself only needs to announce which companies matched.
        """
        if not notified_jobs or not self.telegram_bot or not self.telegram_chat_id:
            return
        notified_jobs.sort(key=lambda job: role_priority_for_title(job.get("title") or ""))
        text, markup = format_company_digest(notified_jobs)
        try:
            response = self.telegram_bot.send_message(self.telegram_chat_id, text, reply_markup=markup)
            message_id = str(response.get("result", {}).get("message_id", ""))
            for job in notified_jobs:
                self.notification_repo.mark_sent(job["id"], message_id)
                self.job_repo.set_status(job["id"], JobStatus.NOTIFIED.value)
                counters["jobs_notified"] += 1
        except Exception as exc:  # noqa: BLE001 - notification failure must not abort the run
            for job in notified_jobs:
                self.notification_repo.mark_failed(job["id"], str(exc))
            log_event(logger, "error", "telegram digest notification failed", run_id=run_id, error=str(exc))
