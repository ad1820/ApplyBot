"""Supabase client factory.

Supabase is the single source of truth for all persistent state. This
module provides a memoized client so the rest of the app never re-creates
connections needlessly, and raises a clear error if it is used without the
required environment variables configured.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


class SupabaseNotConfiguredError(RuntimeError):
    """Raised when Supabase credentials are missing but a client was requested."""


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    if not settings.supabase_configured():
        raise SupabaseNotConfiguredError(
            "SUPABASE_URL and SUPABASE_KEY must be set to use the Supabase client."
        )
    return create_client(settings.supabase_url, settings.supabase_key)


def reset_client_cache() -> None:
    """Used by tests after monkeypatching env vars."""
    get_supabase_client.cache_clear()
