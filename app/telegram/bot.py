"""Minimal Telegram Bot API client built on httpx.

Deliberately lightweight (no polling framework) - the bot never
auto-submits applications; it only notifies and reacts to commands the user
sends. Webhook or polling wiring happens in scripts/handlers, this module
just wraps the HTTP calls.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramError(RuntimeError):
    pass


class TelegramBot:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is required")
        self.token = token
        self._base_url = _API_BASE.format(token=token)
        self._client = client or httpx.Client(timeout=15.0)

    def get_me(self) -> dict[str, Any]:
        response = self._client.get(f"{self._base_url}/getMe")
        response.raise_for_status()
        return response.json()

    def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: Optional[dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = self._client.post(f"{self._base_url}/sendMessage", json=payload)
        response.raise_for_status()
        return response.json()

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        response = self._client.post(f"{self._base_url}/answerCallbackQuery", json=payload)
        response.raise_for_status()
        return response.json()

    def get_updates(self, offset: Optional[int] = None, timeout: int = 30) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        response = self._client.get(f"{self._base_url}/getUpdates", params=params)
        response.raise_for_status()
        return response.json()


def apply_url_button(url: str, label: str = "Apply") -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": label, "url": url}]]}
