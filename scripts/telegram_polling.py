"""Simple long-polling runner for the Telegram bot.

Intended for local development, or for a small always-on process if you
have somewhere free/cheap to run one. If your hosting plan doesn't include
a free always-on worker (e.g. Render's free tier only covers the Web
Service), use a Telegram webhook pointed at your deployed FastAPI app's
POST /telegram/webhook instead (see app/main.py) - both paths share the
exact same command dispatch logic in
app.telegram.handlers.dispatch_command, so behavior is identical either way.
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
from app.logging_config import configure_logging, get_logger
from app.telegram.bot import TelegramBot
from app.telegram.handlers import build_bot_context_from_settings, dispatch_command

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def main() -> None:
    ctx = build_bot_context_from_settings()
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
            reply = dispatch_command(ctx, message["text"])
            bot.send_message(chat_id, reply)
        time.sleep(1)


if __name__ == "__main__":
    main()
