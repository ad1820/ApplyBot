"""FastAPI application entrypoint.

Exposes:
- GET /health              basic liveness + best-effort DB connectivity check
- POST /run/job-search      scheduled trigger (e.g. Supabase Cron -> HTTP)
- POST /telegram/webhook    Telegram webhook receiver for bot commands
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


@app.get("/health")
def health() -> dict[str, Any]:
    status: dict[str, Any] = {"status": "ok"}

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

    payload = await request.json()
    logger.info("Received telegram update")
    # Command dispatch is intentionally left to a dedicated polling/webhook
    # wiring script (see scripts/telegram_polling.py) which shares the same
    # app.telegram.handlers functions. This endpoint acknowledges receipt so
    # Telegram doesn't retry, while full dispatch logic is testable in
    # isolation via app.telegram.handlers.
    return {"ok": True}
