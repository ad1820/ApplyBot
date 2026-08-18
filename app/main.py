"""FastAPI application entrypoint.

Exposes:
- GET /health              basic liveness + best-effort DB connectivity check
- POST /run/job-search      scheduled trigger (e.g. Supabase Cron -> HTTP)
- POST /telegram/webhook    Telegram webhook receiver - dispatches commands
                            and replies, using the exact same
                            app.telegram.handlers.dispatch_command logic as
                            scripts/telegram_polling.py, so behavior is
                            identical whether you run a long-polling worker
                            or point Telegram's webhook at this endpoint
                            (useful when your hosting plan has no free
                            always-on worker process, e.g. Render's free
                            tier only covers the Web Service).
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.telegram.bot import TelegramBot

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(title="Job Application Agent", version="0.1.0")

# Bumped whenever a deploy-verification is needed - lets us confirm via
# GET /health that a given Render deploy actually picked up the latest
# code, rather than guessing from indirect behavior.
_BUILD_MARKER = "webhook-hardening-2026-08-18"


@app.get("/health")
def health() -> dict[str, Any]:
    status: dict[str, Any] = {"status": "ok", "build": _BUILD_MARKER}

    if settings.supabase_configured():
        try:
            from app.db.supabase import get_supabase_client

            client = get_supabase_client()
            client.table("agent_runs").select("id").limit(1).execute()
            status["supabase"] = "connected"
        except Exception as exc:  # noqa: BLE001
            status["status"] = "degraded"
            status["supabase"] = f"error: {exc}"
    else:
        status["status"] = "degraded"
        status["supabase"] = "not_configured"

    status["telegram"] = "configured" if settings.telegram_configured() else "not_configured"
    return status


@app.post("/run/job-search")
def trigger_job_search(x_scheduler_secret: str = Header(default="")) -> dict[str, Any]:
    if settings.scheduler_secret and x_scheduler_secret != settings.scheduler_secret:
        raise HTTPException(status_code=401, detail="Invalid scheduler secret")

    from app.agents.job_agent import default_sources, run_job_search

    result = run_job_search(default_sources())
    return result


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    if not settings.telegram_configured():
        raise HTTPException(status_code=503, detail="Telegram not configured")

    # Everything below is wrapped in one broad try/except - a webhook
    # handler must NEVER return a non-2xx response to Telegram for any
    # reason (malformed/unexpected payload shape, a Supabase/LLM hiccup,
    # etc.), since Telegram will otherwise retry the same update
    # indefinitely and/or mark the webhook as failing.
    try:
        from app.telegram.bot import TelegramBot
        from app.telegram.handlers import build_bot_context_from_settings, dispatch_command

        payload = await request.json()
        message = payload.get("message")
        if not message or "text" not in message:
            # Non-text updates (edited messages, callback queries, etc.)
            # are acknowledged but not acted on for now.
            return {"ok": True}

        chat_id = str(message["chat"]["id"])
        ctx = build_bot_context_from_settings()
        reply = dispatch_command(ctx, message["text"])
        bot = TelegramBot(settings.telegram_bot_token)
        bot.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001 - see comment above
        logger.error("Failed to handle telegram webhook update: %s", exc, exc_info=True)

    return {"ok": True}
