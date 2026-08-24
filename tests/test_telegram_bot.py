"""Tests for app.telegram.bot.TelegramBot - all mocked via
httpx.MockTransport, no live network calls."""
from __future__ import annotations

import httpx
import pytest

from app.telegram.bot import TelegramBot, TelegramError


def make_bot(handler) -> TelegramBot:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramBot("fake-token", client=client)


def test_bot_requires_token():
    with pytest.raises(TelegramError):
        TelegramBot("")


def test_get_updates_success():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "result": []})

    bot = make_bot(handler)
    result = bot.get_updates()
    assert result["ok"] is True


def test_get_updates_raises_http_status_error_on_409():
    def handler(request):
        return httpx.Response(409, json={"ok": False, "description": "Conflict"})

    bot = make_bot(handler)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        bot.get_updates()
    assert exc_info.value.response.status_code == 409


def test_delete_webhook_calls_correct_endpoint():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "result": True})

    bot = make_bot(handler)
    result = bot.delete_webhook()
    assert result["result"] is True
    assert "deleteWebhook" in captured["url"]


def test_get_webhook_info_returns_url():
    def handler(request):
        return httpx.Response(200, json={"ok": True, "result": {"url": "https://example.com/hook"}})

    bot = make_bot(handler)
    result = bot.get_webhook_info()
    assert result["result"]["url"] == "https://example.com/hook"


def test_get_updates_uses_timeout_longer_than_long_poll_window():
    """The HTTP request timeout must exceed the Telegram long-poll
    `timeout` param, otherwise httpx raises ReadTimeout right before
    Telegram would have responded. Regression test for that bug."""
    captured = {}

    def handler(request):
        return httpx.Response(200, json={"ok": True, "result": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    original_build_request = client.build_request

    def spy_build_request(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return original_build_request(*args, **kwargs)

    client.build_request = spy_build_request
    bot = TelegramBot("fake-token", client=client)
    bot.get_updates(timeout=30)

    request_timeout = captured["timeout"]
    assert isinstance(request_timeout, httpx.Timeout)
    assert request_timeout.read > 30


def test_send_message_includes_reply_markup_when_provided():
    captured = {}

    def handler(request):
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    bot = make_bot(handler)
    bot.send_message("123", "hello", reply_markup={"inline_keyboard": [[]]})
    assert captured["body"]["reply_markup"] == {"inline_keyboard": [[]]}
