"""Job agent - thin orchestration entrypoint for a scheduled job-search run.

Wires together repositories, job sources, Telegram and Sheets sync, and
delegates the actual run logic to JobSearchService (kept there so it stays
independently unit-testable without needing this wiring layer).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from app.db.repositories.jobs import JobRepository, JobSourceRepository
from app.db.repositories.notifications import NotificationRepository
from app.db.repositories.profiles import CandidateProfileRepository, JobPreferencesRepository
from app.db.repositories.runs import AgentRunRepository
from app.db.supabase import get_supabase_client
from app.jobs.discovery import (
    AshbySource,
    GreenhouseSource,
    HimalayasSource,
    JobSource,
    LeverSource,
    RemoteOKSource,
    RemotiveSource,
    WeWorkRemotelySource,
    WorkingNomadsSource,
)

# Cached ATS board tokens for the companies known to hire in India (see
# companies_hiring_in_india.txt), populated by running
# scripts/discover_ats_boards.py occasionally. Reading a cached file rather
# than probing ~700 companies live on every discovery run keeps
# run_discovery.py fast. Missing/empty file just means no extra ATS boards
# are queried - never a hard failure.
_ATS_BOARDS_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "ats_boards.json"


def load_cached_ats_boards() -> dict[str, list[str]]:
    if not _ATS_BOARDS_FILE.is_file():
        return {"greenhouse": [], "lever": [], "ashby": []}
    try:
        data = json.loads(_ATS_BOARDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"greenhouse": [], "lever": [], "ashby": []}
    return {
        "greenhouse": data.get("greenhouse", []),
        "lever": data.get("lever", []),
        "ashby": data.get("ashby", []),
    }
from app.jobs.matcher import make_llm_semantic_skill_checker
from app.llm.provider import get_job_matching_provider
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

    llm_provider = get_job_matching_provider()
    semantic_skill_checker = make_llm_semantic_skill_checker(llm_provider)

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


def default_sources(
    greenhouse_boards: Optional[list[str]] = None,
    lever_companies: Optional[list[str]] = None,
    ashby_companies: Optional[list[str]] = None,
    include_cached_ats_boards: bool = True,
) -> list[JobSource]:
    """The standard set of legitimate, publicly-accessible job sources.

    Only includes boards/feeds with genuine public APIs or RSS feeds - no
    scraping of platforms that prohibit it. Greenhouse/Lever/Ashby boards
    are company-specific: by default this also pulls in the cached set of
    known-live boards discovered from companies_hiring_in_india.txt (see
    scripts/discover_ats_boards.py), in addition to any explicitly passed
    tokens; the rest are aggregators that already return a broad mix of
    remote-friendly roles.
    """
    sources: list[JobSource] = [
        RemoteOKSource(),
        RemotiveSource(),
        WorkingNomadsSource(),
        HimalayasSource(),
        WeWorkRemotelySource(),
    ]

    greenhouse_boards = list(greenhouse_boards or [])
    lever_companies = list(lever_companies or [])
    ashby_companies = list(ashby_companies or [])

    if include_cached_ats_boards:
        cached = load_cached_ats_boards()
        greenhouse_boards = sorted(set(greenhouse_boards) | set(cached["greenhouse"]))
        lever_companies = sorted(set(lever_companies) | set(cached["lever"]))
        ashby_companies = sorted(set(ashby_companies) | set(cached["ashby"]))

    if greenhouse_boards:
        sources.insert(0, GreenhouseSource(board_tokens=greenhouse_boards))
    if lever_companies:
        sources.insert(0, LeverSource(company_slugs=lever_companies))
    if ashby_companies:
        sources.insert(0, AshbySource(company_slugs=ashby_companies))
    return sources


def run_job_search(sources: list[JobSource]) -> dict[str, Any]:
    client = get_supabase_client()
    profile_repo = CandidateProfileRepository(client)
    prefs_repo = JobPreferencesRepository(client)

    profile = profile_repo.get() or {}
    preferences = prefs_repo.get_for_profile(profile.get("id", "")) or {} if profile else {}

    service = build_job_search_service(sources)
    return service.run(profile, preferences)
