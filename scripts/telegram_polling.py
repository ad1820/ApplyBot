"""Simple long-polling runner for the Telegram bot.

Intended for local development / a single always-on worker process. In
production the scheduled job-search trigger runs via Supabase Cron -> the
FastAPI /run/job-search endpoint, but a live chat interface still needs
either polling (this script) or a webhook (app.main:telegram_webhook).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running this script directly (e.g. `python scripts/telegram_polling.py`
# from any working directory) - see scripts/sync_skills.py for why this is
# needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.analytics import AnalyticsEventRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.profiles import CandidateProfileRepository
from app.db.repositories.resumes import MasterResumeRepository, TailoredResumeRepository
from app.db.supabase import get_supabase_client
from app.llm.provider import get_llm_provider
from app.logging_config import configure_logging, get_logger
from app.telegram.bot import TelegramBot
from app.telegram.handlers import (
    BotContext,
    handle_applied,
    handle_approve_resume,
    handle_done,
    handle_help,
    handle_job,
    handle_jobs,
    handle_resume_analysis,
    handle_set_resume,
    handle_skip,
    handle_start,
    handle_stats,
    handle_status,
    handle_status_transition,
    handle_today,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def dispatch(ctx: BotContext, text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower().lstrip("/")
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "start":
        return handle_start()
    if command == "help":
        return handle_help()
    if command == "today":
        return handle_today(ctx)
    if command == "jobs":
        return handle_jobs(ctx)
    if command == "job":
        return handle_job(ctx, arg)
    if command == "done":
        return handle_done(ctx, arg)
    if command == "skip":
        return handle_skip(ctx, arg)
    if command == "status":
        return handle_status(ctx, arg)
    if command == "applied":
        return handle_applied(ctx)
    if command == "stats":
        return handle_stats(ctx)
    if command in ("interview", "rejected", "offer", "withdraw"):
        return handle_status_transition(ctx, command, arg)
    if command == "setresume":
        return handle_set_resume(ctx, arg)
    if command == "resume":
        return handle_resume_analysis(ctx, arg)
    if command == "approveresume":
        return handle_approve_resume(ctx, arg)
    return "Unknown command. Use /help to see available commands."


def main() -> None:
    client = get_supabase_client()
    ctx = BotContext(
        jobs=JobRepository(client),
        applications=ApplicationRepository(client),
        analytics=AnalyticsEventRepository(client),
        profiles=CandidateProfileRepository(client),
        master_resumes=MasterResumeRepository(client),
        tailored_resumes=TailoredResumeRepository(client),
        llm_provider=get_llm_provider(),
    )
    bot = TelegramBot(settings.telegram_bot_token)
    offset = None
    logger.info("Starting Telegram polling loop")
    while True:
        updates = bot.get_updates(offset=offset, timeout=30)
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or "text" not in message:
                continue
            chat_id = str(message["chat"]["id"])
            reply = dispatch(ctx, message["text"])
            bot.send_message(chat_id, reply)
        time.sleep(1)


if __name__ == "__main__":
    main()
