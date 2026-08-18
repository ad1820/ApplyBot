"""Centralised application configuration.

All configuration is loaded from environment variables (optionally via a
local .env file for development). Nothing here should ever be hard-coded
with real secrets - see .env.example for the full list of expected vars.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the project root (this file's parent's parent),
# not the current working directory, so scripts still find it correctly
# when invoked as `python D:\Job_Applier\scripts\some_script.py` from an
# unrelated directory (e.g. C:\).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    @field_validator("supabase_url")
    @classmethod
    def _normalize_supabase_url(cls, value: str) -> str:
        """Strip trailing slashes and an accidentally-included /rest/v1 (or
        similar) suffix. supabase-py appends its own path segments (e.g.
        /rest/v1/<table>) to whatever base URL is configured, so a trailing
        slash or an extra path segment here produces a malformed request URL
        and PostgREST responds with PGRST125 ("Invalid path specified in
        request URL"). SUPABASE_URL should be just the project base URL,
        e.g. https://xxxxx.supabase.co
        """
        value = value.strip().rstrip("/")
        for suffix in ("/rest/v1", "/rest", "/auth/v1", "/storage/v1"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # LLM
    llm_provider: str = "null"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # Google Sheets credentials. In local development, point
    # GOOGLE_SERVICE_ACCOUNT_FILE at a JSON key file on disk. In production
    # (e.g. Northflank secrets), paste the file's raw JSON content into
    # GOOGLE_SERVICE_ACCOUNT_JSON instead - the file path is tried first,
    # then this env var is used as a fallback, so either way works without
    # code changes. (python-dotenv can parse a single-line JSON value fine;
    # it just can't parse the *file itself* being pasted with real newlines.)
    google_service_account_file: str = ""
    google_service_account_json: str = ""
    google_sheets_spreadsheet_id: str = ""

    # Candidate profile / preferences / skills configuration. Same
    # file-or-env-JSON fallback pattern as Google credentials above: in
    # development these live as files under config/ (git-ignored where they
    # contain PII); in production paste the same JSON content into the
    # matching *_JSON environment variable.
    candidate_profile_json: str = ""
    job_preferences_json: str = ""
    candidate_skills_json: str = ""

    # App
    app_timezone: str = "UTC"
    log_level: str = "INFO"
    job_search_schedule: str = "08:00"
    scheduler_secret: str = ""

    # Only jobs scoring at or above this match percentage are pushed as
    # Telegram notifications (still persisted below the threshold so they
    # remain visible via /jobs, just not pushed proactively).
    minimum_match_score: float = 80.0

    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached so we don't re-parse the environment on every call, but tests can
    call ``get_settings.cache_clear()`` if they need to reload after
    monkeypatching environment variables.
    """
    return Settings()
