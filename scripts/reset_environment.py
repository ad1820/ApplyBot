"""Reset operational job-search data while preserving candidate identity.

Deletes jobs and all application-tracking history from Supabase, recreates
the Google Sheets tracker with only its header, and attempts to delete every
Telegram message whose ID was recorded by the application. Candidate profile,
job preferences, canonical skills, and master resume versions are preserved.

Usage:
    python scripts/reset_environment.py --confirm RESET
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.supabase import get_supabase_client  # noqa: E402
from app.sheets.sync import SHEET_COLUMNS, build_sheets_client_from_settings  # noqa: E402
from app.telegram.bot import TelegramBot  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_DIRECT_DELETE_TABLES = ("analytics_events", "application_answers", "agent_runs")
_PRESERVED_TABLES = ("candidate_profiles", "job_preferences", "master_resumes")


def _count_rows(client: Any, table: str) -> int:
    response = client.table(table).select("id", count="exact").limit(0).execute()
    return int(response.count or 0)


def _delete_all(client: Any, table: str, batch_size: int = 200) -> int:
    """Delete a table in bounded batches to avoid hosted DB timeouts."""
    deleted = 0
    while True:
        rows = client.table(table).select("id").limit(batch_size).execute().data or []
        ids = [row["id"] for row in rows]
        if not ids:
            return deleted
        client.table(table).delete().in_("id", ids).execute()
        deleted += len(ids)
        if deleted % 1000 == 0:
            logger.info("Deleted %d rows from %s...", deleted, table)


def get_tracked_telegram_message_ids(client: Any) -> list[int]:
    rows = client.table("notifications").select("telegram_message_id").execute().data or []
    message_ids: set[int] = set()
    for row in rows:
        value = row.get("telegram_message_id")
        if value:
            try:
                message_ids.add(int(value))
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid Telegram message ID: %r", value)
    return sorted(message_ids)


def reset_telegram(message_ids: list[int]) -> tuple[int, int]:
    """Delete recorded Telegram messages in batches of 100.

    The Bot API cannot list chat history and normally cannot delete messages
    older than 48 hours, so only IDs recorded in the notifications table can
    be attempted here.
    """
    settings = get_settings()
    if not settings.telegram_configured() or not settings.telegram_chat_id:
        logger.warning("Telegram is not configured; no chat messages were deleted.")
        return 0, len(message_ids)
    if not message_ids:
        logger.info("No tracked Telegram message IDs were present; nothing can be deleted through the Bot API.")
        return 0, 0

    bot = TelegramBot(settings.telegram_bot_token)
    deleted = 0
    failed = 0
    for start in range(0, len(message_ids), 100):
        batch = message_ids[start : start + 100]
        try:
            bot.delete_messages(settings.telegram_chat_id, batch)
            deleted += len(batch)
        except Exception as exc:  # noqa: BLE001 - report and continue remaining batches
            failed += len(batch)
            logger.warning("Telegram could not delete message batch %s: %s", batch, exc)
    logger.info("Telegram cleanup finished: %d deleted, %d unavailable.", deleted, failed)
    return deleted, failed


def reset_supabase(client: Any) -> dict[str, int]:
    """Clear operational tables; preserve profile, preferences, and resumes."""
    before = {table: _count_rows(client, table) for table in (*_DIRECT_DELETE_TABLES, "jobs")}

    # Analytics uses ON DELETE SET NULL and agent runs/application answers
    # are independent, so clear them explicitly. Deleting jobs then cascades
    # through sources, notifications, applications, tailored resumes, cover
    # letters, referrals, and job-specific application questions.
    for table in _DIRECT_DELETE_TABLES:
        _delete_all(client, table)
    _delete_all(client, "jobs")

    remaining = {table: _count_rows(client, table) for table in (*_DIRECT_DELETE_TABLES, "jobs")}
    if any(remaining.values()):
        raise RuntimeError(f"Supabase reset verification failed; rows remain: {remaining}")

    preserved = {table: _count_rows(client, table) for table in _PRESERVED_TABLES}
    logger.info("Supabase operational data cleared: %s", before)
    logger.info("Preserved candidate data: %s", preserved)
    return before


def reset_google_sheets() -> dict[str, int]:
    """Delete every existing tab and recreate a clean Jobs header tab."""
    sheets_client = build_sheets_client_from_settings()
    if not sheets_client:
        raise RuntimeError("Google Sheets is not configured; refusing to report a complete reset.")

    worksheet = sheets_client._connect()
    spreadsheet = worksheet.spreadsheet
    existing = spreadsheet.worksheets()
    before = {ws.title: len(ws.get_all_values()) for ws in existing}

    temp_name = "Jobs_Reset_In_Progress"
    try:
        stale = spreadsheet.worksheet(temp_name)
        spreadsheet.del_worksheet(stale)
    except Exception:  # worksheet does not exist
        pass

    fresh_sheet = spreadsheet.add_worksheet(temp_name, rows=1000, cols=len(SHEET_COLUMNS))
    for ws in existing:
        spreadsheet.del_worksheet(ws)
    fresh_sheet.update_title("Jobs")
    fresh_sheet.append_row(SHEET_COLUMNS)
    sheets_client._apply_formatting(fresh_sheet)

    remaining_sheets = spreadsheet.worksheets()
    remaining_values = remaining_sheets[0].get_all_values() if len(remaining_sheets) == 1 else []
    if len(remaining_sheets) != 1 or remaining_sheets[0].title != "Jobs" or remaining_values != [SHEET_COLUMNS]:
        raise RuntimeError("Google Sheets reset verification failed.")

    logger.info("Google Sheets cleared: %s", before)
    logger.info("Fresh Jobs sheet created with one header row.")
    return before


def main() -> int:
    parser = argparse.ArgumentParser(description="Permanently clear job-search operational history.")
    parser.add_argument("--confirm", help="Must be exactly RESET to authorize deletion.")
    args = parser.parse_args()
    if args.confirm != "RESET":
        parser.error("destructive reset requires --confirm RESET")

    settings = get_settings()
    if not settings.supabase_configured():
        raise RuntimeError("Supabase is not configured; reset aborted.")

    client = get_supabase_client()
    message_ids = get_tracked_telegram_message_ids(client)
    reset_telegram(message_ids)
    reset_supabase(client)
    reset_google_sheets()
    logger.info("Fresh-start reset complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
