"""Tests for scripts/telegram_polling.py's startup webhook-cleanup and
409-Conflict retry behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "telegram_polling.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("telegram_polling", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def polling_module():
    return _load_module()


class FakeBot:
    def __init__(
        self,
        webhook_url="",
        conflict_then_success=False,
        timeout_then_success=False,
        transport_error_then_success=False,
    ):
        self._webhook_url = webhook_url
        self.deleted_webhook = False
        self.conflict_then_success = conflict_then_success
        self.timeout_then_success = timeout_then_success
        self.transport_error_then_success = transport_error_then_success
        self._get_updates_calls = 0
        self.sent_messages = []

    def get_webhook_info(self):
        return {"result": {"url": self._webhook_url}}

    def delete_webhook(self):
        self.deleted_webhook = True
        self._webhook_url = ""
        return {"ok": True, "result": True}

    def get_updates(self, offset=None, timeout=30):
        self._get_updates_calls += 1
        if self.conflict_then_success and self._get_updates_calls == 1:
            request = httpx.Request("GET", "https://api.telegram.org/fake/getUpdates")
            response = httpx.Response(409, request=request)
            raise httpx.HTTPStatusError("409 Conflict", request=request, response=response)
        if self.timeout_then_success and self._get_updates_calls == 1:
            request = httpx.Request("GET", "https://api.telegram.org/fake/getUpdates")
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        if self.transport_error_then_success and self._get_updates_calls == 1:
            request = httpx.Request("GET", "https://api.telegram.org/fake/getUpdates")
            raise httpx.ConnectError("Connection reset", request=request)
        # Next call (or first, if no simulated failure): raise
        # StopIteration-like signal via a sentinel exception so the
        # infinite loop in main() terminates cleanly for the test.
        raise _StopPolling()

    def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append((chat_id, text))

    def answer_callback_query(self, callback_query_id, text=None):
        pass


class _StopPolling(Exception):
    pass


def test_main_deletes_webhook_when_one_is_set(polling_module, monkeypatch):
    fake_bot = FakeBot(webhook_url="https://example.com/telegram/webhook")
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())

    with pytest.raises(_StopPolling):
        polling_module.main()

    assert fake_bot.deleted_webhook is True


def test_main_does_not_delete_webhook_when_none_set(polling_module, monkeypatch):
    fake_bot = FakeBot(webhook_url="")
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())

    with pytest.raises(_StopPolling):
        polling_module.main()

    assert fake_bot.deleted_webhook is False


def test_main_retries_after_409_conflict_instead_of_crashing(polling_module, monkeypatch):
    fake_bot = FakeBot(webhook_url="", conflict_then_success=True)
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())
    monkeypatch.setattr(polling_module.time, "sleep", lambda seconds: None)

    with pytest.raises(_StopPolling):
        polling_module.main()

    # First call raised 409, second call raised _StopPolling - proves the
    # loop caught the 409 and retried rather than propagating it.
    assert fake_bot._get_updates_calls == 2


def test_main_continues_after_read_timeout_instead_of_crashing(polling_module, monkeypatch):
    """Regression test: a ReadTimeout during long-polling (e.g. the HTTP
    client's own timeout firing before Telegram responds, or simply no new
    updates arriving in the window) is a normal occurrence and must not
    crash the script."""
    fake_bot = FakeBot(webhook_url="", timeout_then_success=True)
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())

    with pytest.raises(_StopPolling):
        polling_module.main()

    assert fake_bot._get_updates_calls == 2


def test_main_retries_after_transport_error_instead_of_crashing(polling_module, monkeypatch):
    fake_bot = FakeBot(webhook_url="", transport_error_then_success=True)
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())
    monkeypatch.setattr(polling_module.time, "sleep", lambda seconds: None)

    with pytest.raises(_StopPolling):
        polling_module.main()

    assert fake_bot._get_updates_calls == 2


class _OneUpdateThenStopBot(FakeBot):
    """Returns exactly one text update on the first call, then stops the
    loop on the second call - used to test message-sending behavior for a
    single processed update."""

    def __init__(self, reply_text, **kwargs):
        super().__init__(**kwargs)
        self.reply_text = reply_text

    def get_updates(self, offset=None, timeout=30):
        self._get_updates_calls += 1
        if self._get_updates_calls == 1:
            return {
                "result": [
                    {
                        "update_id": 1,
                        "message": {"chat": {"id": 999}, "text": "/jobs"},
                    }
                ]
            }
        raise _StopPolling()


def test_main_splits_long_reply_into_multiple_sent_messages(polling_module, monkeypatch):
    """Regression test: Telegram rejects sendMessage with a 400 Bad Request
    if text exceeds 4096 chars (e.g. /jobs with many results) - the polling
    loop must chunk long replies rather than sending one oversized message
    (which previously crashed the whole long-running process)."""
    long_reply = "z" * 9000
    fake_bot = _OneUpdateThenStopBot(reply_text=long_reply)
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())
    monkeypatch.setattr(polling_module, "dispatch_command_with_markup", lambda ctx, text: (long_reply, None))
    monkeypatch.setattr(polling_module.time, "sleep", lambda seconds: None)

    with pytest.raises(_StopPolling):
        polling_module.main()

    assert len(fake_bot.sent_messages) > 1
    assert all(len(text) <= 4096 for _, text in fake_bot.sent_messages)
    assert "".join(text for _, text in fake_bot.sent_messages) == long_reply


def test_main_logs_and_continues_when_handling_an_update_raises(polling_module, monkeypatch):
    """A bad update (unexpected payload, transient DB/LLM error, etc.) must
    not crash this long-running local process."""
    fake_bot = _OneUpdateThenStopBot(reply_text="")
    monkeypatch.setattr(polling_module, "TelegramBot", lambda token: fake_bot)
    monkeypatch.setattr(polling_module, "build_bot_context_from_settings", lambda: object())

    def broken_dispatch(ctx, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(polling_module, "dispatch_command_with_markup", broken_dispatch)
    monkeypatch.setattr(polling_module.time, "sleep", lambda seconds: None)

    with pytest.raises(_StopPolling):
        polling_module.main()

    # No message was sent (dispatch failed), but the loop kept going and
    # reached the second get_updates call, proving it didn't propagate the
    # RuntimeError from handling the first update.
    assert fake_bot.sent_messages == []
    assert fake_bot._get_updates_calls == 2
