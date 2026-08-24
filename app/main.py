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
        from app.telegram.handlers import (
            build_bot_context_from_settings,
            dispatch_callback_query,
            dispatch_command_with_markup,
        )
        from app.telegram.messages import chunk_message

        payload = await request.json()
        message = payload.get("message")
        callback_query = payload.get("callback_query")
        bot = TelegramBot(settings.telegram_bot_token)

        if message and "text" in message:
            chat_id = str(message["chat"]["id"])
            ctx = build_bot_context_from_settings()
            reply, markup = dispatch_command_with_markup(ctx, message["text"])
            # Telegram rejects messages over ~4096 chars with a 400 Bad
            # Request (e.g. /today or /jobs with many results) - split into
            # multiple messages rather than letting that raise inside this
            # try block. The inline keyboard (if any) only makes sense on
            # the final chunk.
            chunks = chunk_message(reply)
            for i, chunk in enumerate(chunks):
                is_last = i == len(chunks) - 1
                bot.send_message(chat_id, chunk, reply_markup=markup if is_last else None)
        elif callback_query and callback_query.get("message"):
            chat_id = str(callback_query["message"]["chat"]["id"])
            ctx = build_bot_context_from_settings()
            reply = dispatch_callback_query(ctx, callback_query.get("data", ""))
            bot.answer_callback_query(callback_query["id"])
            for chunk in chunk_message(reply):
                bot.send_message(chat_id, chunk)
        # Any other update shape (edited messages, malformed callback
        # queries, etc.) is acknowledged but not acted on.
    except Exception as exc:  # noqa: BLE001 - see comment above
        logger.error("Failed to handle telegram webhook update: %s", exc, exc_info=True)

    return {"ok": True}
