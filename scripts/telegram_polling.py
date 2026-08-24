"""Simple long-polling runner for the Telegram bot.

Run this on your own machine whenever you want to interact with the bot
(/jobs, /done, /setresume, etc.) - see DAILY_RUN.md for the everyday
workflow. No hosting or always-on server required: start it when you want
replies, stop it (Ctrl+C) when you're done. Telegram queues updates while
this isn't running, so nothing is lost - just re-send a command once it's
back up.

If you ever do deploy this app somewhere with a public HTTPS endpoint, you
could instead point a Telegram webhook at POST /telegram/webhook (see
app/main.py), which shares the exact same command dispatch logic in
app.telegram.handlers.dispatch_command - but that's entirely optional.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

# Allow running this script directly (e.g. `python scripts/telegram_polling.py`
# from any working directory) - see scripts/sync_skills.py for why this is
# needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.telegram.bot import TelegramBot
from app.telegram.handlers import build_bot_context_from_settings, dispatch_callback_query, dispatch_command_with_markup
from app.telegram.messages import chunk_message

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def _handle_update(ctx, bot: TelegramBot, update: dict) -> None:
    """Process a single Telegram update (text message or inline-keyboard
    callback_query). Shared between run_polling_loop and any caller that
    wants identical per-update handling (e.g. scripts/run_agent.py running
    this loop on a background thread alongside a manual discovery run)."""
    message = update.get("message")
    callback_query = update.get("callback_query")

    if message and "text" in message:
        chat_id = str(message["chat"]["id"])
        reply, markup = dispatch_command_with_markup(ctx, message["text"])
        # Telegram rejects messages over ~4096 chars with a 400 Bad
        # Request (e.g. /today or /jobs with many results) - split into
        # multiple messages rather than letting that crash the loop. The
        # inline keyboard (if any) only makes sense on the final chunk.
        chunks = chunk_message(reply)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            bot.send_message(chat_id, chunk, reply_markup=markup if is_last else None)
        return

    if callback_query:
        chat_id = str(callback_query["message"]["chat"]["id"])
        callback_data = callback_query.get("data", "")
        reply = dispatch_callback_query(ctx, callback_data)
        bot.answer_callback_query(callback_query["id"])
        for chunk in chunk_message(reply):
            bot.send_message(chat_id, chunk)


def run_polling_loop(ctx, bot: TelegramBot) -> None:
    """The long-polling loop itself, extracted so it can be reused by both
    this script's main() and scripts/run_agent.py (which runs it on a
    background thread alongside a manual discovery run)."""
    offset = None
    logger.info("Starting Telegram polling loop")
    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=30)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                # Another poller instance is likely running somewhere else
                # with the same bot token (Telegram allows only one). Wait
                # and retry rather than crashing - if you started a second
                # instance by mistake, stop it; otherwise this resolves
                # itself once the other instance's long-poll request ends.
                logger.error(
                    "409 Conflict from Telegram - another getUpdates poller "
                    "may already be running with this bot token. Retrying in 5s."
                )
                time.sleep(5)
                continue
            raise
        except httpx.TimeoutException:
            # Normal for long-polling: Telegram (or an intermediate proxy/
            # network hiccup) didn't respond within the window. This simply
            # means no new updates arrived - not an error - so just poll
            # again immediately.
            continue
        except httpx.TransportError as exc:
            # Transient network issues (DNS hiccup, connection reset, etc.)
            # must not crash a long-running local process - log and retry.
            logger.error("Network error while polling Telegram, retrying in 5s: %s", exc)
            time.sleep(5)
            continue

        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            try:
                _handle_update(ctx, bot, update)
            except Exception as exc:  # noqa: BLE001
                # A single bad update (unexpected payload shape, a
                # transient Supabase/LLM error, etc.) must not kill this
                # long-running local process - log it and keep polling so
                # the rest of your commands keep working.
                logger.error("Failed to handle update %s: %s", update.get("update_id"), exc, exc_info=True)
        time.sleep(1)


def main() -> None:
    ctx = build_bot_context_from_settings()
    bot = TelegramBot(settings.telegram_bot_token)

    # Telegram only delivers updates via ONE transport at a time. If a
    # webhook was ever set (e.g. while testing a hosted deployment), it
    # must be removed before long-polling will work - otherwise every
    # getUpdates call fails with 409 Conflict. This makes switching back to
    # local polling always work with no manual deleteWebhook step.
    webhook_info = bot.get_webhook_info()
    if webhook_info.get("result", {}).get("url"):
        logger.info("Removing existing Telegram webhook so polling can start")
        bot.delete_webhook()

    run_polling_loop(ctx, bot)


if __name__ == "__main__":
    main()
