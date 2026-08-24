"""Structured logging setup.

Produces log lines with timestamp, run_id, job_id, operation, status and
error fields where available, and never logs secrets (tokens, API keys,
passwords) or unnecessary candidate PII.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

_SENSITIVE_KEYS = {
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "supabase_key",
    "telegram_bot_token",
    "llm_api_key",
    "google_service_account_file",
    "google_service_account_json",
    "candidate_profile_json",
    "job_preferences_json",
    "candidate_skills_json",
    "private_key",
}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in _SENSITIVE_KEYS):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(_redact(extra_fields))
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    
    formatter = StructuredFormatter()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)
    
    # File handler
    from pathlib import Path
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: str,
    message: str,
    *,
    run_id: str | None = None,
    job_id: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    **extra: Any,
) -> None:
    fields = {
        "run_id": run_id,
        "job_id": job_id,
        "operation": operation,
        "status": status,
        **extra,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    getattr(logger, level.lower())(message, extra={"extra_fields": fields})
