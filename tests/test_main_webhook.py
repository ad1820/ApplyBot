"""Tests for the FastAPI /telegram/webhook endpoint - verifies it actually
dispatches commands and replies (not just acknowledges receipt), using the
same dispatch_command logic as the polling script."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.telegram.handlers import BotContext


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.main as main_module

    main_module.settings = get_settings()
    return TestClient(main_module.app)


def test_webhook_rejects_when_telegram_not_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from app.config import get_settings

    get_settings.cache_clear()

    import app.main as main_module

    main_module.settings = get_settings()
    test_client = TestClient(main_module.app)

    response = test_client.post("/telegram/webhook", json={"message": {"chat": {"id": 1}, "text": "/help"}})
    assert response.status_code == 503

    get_settings.cache_clear()


def test_webhook_acknowledges_non_text_updates(client, monkeypatch, fake_client):
    from app.telegram.handlers import build_bot_context_from_settings

    monkeypatch.setattr(
        "app.telegram.handlers.build_bot_context_from_settings",
        lambda: BotContext(jobs=None, applications=None, analytics=None),
    )

    response = client.post("/telegram/webhook", json={"update_id": 1, "callback_query": {}})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_dispatches_command_and_sends_reply(client, monkeypatch, fake_client):
    from app.db.repositories.analytics import AnalyticsEventRepository
    from app.db.repositories.applications import ApplicationRepository
    from app.db.repositories.jobs import JobRepository

    ctx = BotContext(
        jobs=JobRepository(fake_client),
        applications=ApplicationRepository(fake_client),
        analytics=AnalyticsEventRepository(fake_client),
    )
    monkeypatch.setattr("app.telegram.handlers.build_bot_context_from_settings", lambda: ctx)

    sent_messages = []

    class FakeTelegramBot:
        def __init__(self, token):
            pass

        def send_message(self, chat_id, text, **kwargs):
            sent_messages.append((chat_id, text))
            return {"result": {"message_id": 1}}

    monkeypatch.setattr("app.telegram.bot.TelegramBot", FakeTelegramBot)

    response = client.post(
        "/telegram/webhook",
        json={"update_id": 1, "message": {"chat": {"id": 999}, "text": "/help"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(sent_messages) == 1
    assert sent_messages[0][0] == "999"
    assert "Available commands" in sent_messages[0][1]


def test_webhook_never_500s_even_if_dispatch_fails(client, monkeypatch):
    def broken_context():
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr("app.telegram.handlers.build_bot_context_from_settings", broken_context)

    response = client.post(
        "/telegram/webhook",
        json={"update_id": 1, "message": {"chat": {"id": 999}, "text": "/help"}},
    )

    # Must still acknowledge with 200 so Telegram doesn't retry forever.
    assert response.status_code == 200
    assert response.json() == {"ok": True}
