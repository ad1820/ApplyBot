"""One command that does everything: starts the Telegram bot (so /jobs,
/done, /companies, etc. respond immediately) on a background thread, then
runs a discovery pass in the foreground - exactly like scripts/run_discovery.py
(same Sheets sync + grouped Telegram notification behavior), then keeps the
process alive so the bot keeps responding until you stop it.

This is still a manually-triggered command (you decide when to run
discovery, same as before) - the only difference from running
run_discovery.py and telegram_polling.py in two separate terminals is that
this starts both with a single command.

Usage:
    python scripts/run_agent.py
    python scripts/run_agent.py stripe discord   # optional Greenhouse boards

Press Ctrl+C to stop both the discovery process (if still running) and the
Telegram polling loop.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.agents.job_agent import default_sources, run_job_search  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.logging_config import configure_logging, get_logger, log_event  # noqa: E402
from app.telegram.bot import TelegramBot  # noqa: E402
from app.telegram.handlers import build_bot_context_from_settings  # noqa: E402

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def _start_polling_thread() -> threading.Thread:
    from scripts.telegram_polling import run_polling_loop

    ctx = build_bot_context_from_settings()
    bot = TelegramBot(settings.telegram_bot_token)

    # Telegram only delivers updates via ONE transport at a time - clear any
    # previously-set webhook so long-polling can start, same as
    # scripts/telegram_polling.py's main().
    webhook_info = bot.get_webhook_info()
    if webhook_info.get("result", {}).get("url"):
        logger.info("Removing existing Telegram webhook so polling can start")
        bot.delete_webhook()

    thread = threading.Thread(target=run_polling_loop, args=(ctx, bot), daemon=True, name="telegram-polling")
    thread.start()
    return thread


def main() -> int:
    greenhouse_boards = sys.argv[1:] or None

    polling_thread = None
    if settings.telegram_configured():
        logger.info("Starting Telegram bot in the background")
        polling_thread = _start_polling_thread()
    else:
        logger.info("Telegram not configured - skipping bot startup, discovery will still run")

    log_event(logger, "info", "Starting manual job discovery run", operation="run_agent")
    try:
        result = run_job_search(default_sources(greenhouse_boards=greenhouse_boards))
    except Exception as exc:  # noqa: BLE001 - top-level guard, same as run_discovery.py
        log_event(logger, "error", "Job discovery run crashed", operation="run_agent", status="FAILED", error=str(exc))
        result = None

    if result is not None:
        status = "PARTIAL" if result.get("error") else "COMPLETED"
        log_event(
            logger, "info" if status == "COMPLETED" else "error",
            f"Job discovery run finished: {status}",
            operation="run_agent", status=status,
            run_id=result.get("run_id"),
            jobs_found=result.get("jobs_found"),
            jobs_new=result.get("jobs_new"),
            jobs_duplicate=result.get("jobs_duplicate"),
            jobs_notified=result.get("jobs_notified"),
        )
        print(result)

    if polling_thread is not None:
        logger.info("Discovery finished. Telegram bot is still running - use /jobs, /companies, etc. Press Ctrl+C to stop.")
        try:
            polling_thread.join()
        except KeyboardInterrupt:
            logger.info("Stopping.")
            return 0

    return 0 if result is not None and not result.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
