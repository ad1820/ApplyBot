"""Job agent - thin orchestration entrypoint for a scheduled job-search run.

Wires together repositories, job sources, Telegram and Sheets sync, and
delegates the actual run logic to JobSearchService (kept there so it stays
independently unit-testable without needing this wiring layer).
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.db.repositories.jobs import JobRepository, JobSourceRepository
from app.db.repositories.notifications import NotificationRepository
from app.db.repositories.profiles import CandidateProfileRepository, JobPreferencesRepository
from app.db.repositories.runs import AgentRunRepository
from app.db.supabase import get_supabase_client
from app.jobs.discovery import (
    GreenhouseSource,
    HimalayasSource,
    JobSource,
    RemoteOKSource,
    RemotiveSource,
    WeWorkRemotelySource,
    WorkingNomadsSource,
)
from app.jobs.matcher import make_llm_semantic_skill_checker
from app.llm.provider import get_llm_provider
from app.services.job_search_service import JobSearchService
from app.sheets.sync import build_sheets_client_from_settings, sync_job_row
from app.telegram.bot import TelegramBot


def build_job_search_service(sources: list[JobSource]) -> JobSearchService:
    client = get_supabase_client()
    settings = get_settings()

    telegram_bot: Optional[TelegramBot] = None
    if settings.telegram_configured():
        telegram_bot = TelegramBot(settings.telegram_bot_token)

    sheets_client = build_sheets_client_from_settings()
    sheets_sync_fn = (lambda job: sync_job_row(sheets_client, job)) if sheets_client else None

    llm_provider = get_llm_provider()
    semantic_skill_checker = make_llm_semantic_skill_checker(llm_provider) if llm_provider.name != "null" else None

    return JobSearchService(
        job_repo=JobRepository(client),
        job_source_repo=JobSourceRepository(client),
        run_repo=AgentRunRepository(client),
        notification_repo=NotificationRepository(client),
        sources=sources,
        telegram_bot=telegram_bot,
        telegram_chat_id=settings.telegram_chat_id or None,
        sheets_sync_fn=sheets_sync_fn,
        minimum_match_score=settings.minimum_match_score,
        semantic_skill_checker=semantic_skill_checker,
    )


def default_sources(greenhouse_boards: Optional[list[str]] = None) -> list[JobSource]:
    """The standard set of legitimate, publicly-accessible job sources.

    Only includes boards/feeds with genuine public APIs or RSS feeds - no
    scraping of platforms that prohibit it. Greenhouse boards are
    company-specific so they must be supplied explicitly (e.g. from
    preferences or config); the rest are aggregators that already return a
    broad mix of remote-friendly roles.
    """
    sources: list[JobSource] = [
        RemoteOKSource(),
        RemotiveSource(),
        WorkingNomadsSource(),
        HimalayasSource(),
        WeWorkRemotelySource(),
    ]
    if greenhouse_boards:
        sources.insert(0, GreenhouseSource(board_tokens=greenhouse_boards))
    return sources


def run_job_search(sources: list[JobSource]) -> dict[str, Any]:
    client = get_supabase_client()
    profile_repo = CandidateProfileRepository(client)
    prefs_repo = JobPreferencesRepository(client)

    profile = profile_repo.get() or {}
    preferences = prefs_repo.get_for_profile(profile.get("id", "")) or {} if profile else {}

    service = build_job_search_service(sources)
    return service.run(profile, preferences)
