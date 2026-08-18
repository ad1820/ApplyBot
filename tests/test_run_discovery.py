"""Tests for scripts/run_discovery.py's main() exit-code/status logic.

The script is a thin CLI wrapper around app.agents.job_agent.run_job_search;
these tests patch that function to avoid any real network/Supabase calls.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_discovery.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_discovery", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_discovery_module():
    return _load_module()


def test_main_returns_zero_on_completed_run(run_discovery_module, monkeypatch, capsys):
    monkeypatch.setattr(
        run_discovery_module,
        "run_job_search",
        lambda sources: {"run_id": "1", "jobs_found": 5, "jobs_new": 5, "jobs_duplicate": 0, "jobs_notified": 2, "error": None},
    )
    exit_code = run_discovery_module.main()
    assert exit_code == 0


def test_main_returns_one_on_partial_run(run_discovery_module, monkeypatch):
    monkeypatch.setattr(
        run_discovery_module,
        "run_job_search",
        lambda sources: {"run_id": "1", "jobs_found": 5, "jobs_new": 3, "jobs_duplicate": 2, "jobs_notified": 1, "error": "one source failed"},
    )
    exit_code = run_discovery_module.main()
    assert exit_code == 1


def test_main_returns_one_and_does_not_crash_on_unexpected_exception(run_discovery_module, monkeypatch):
    def boom(sources):
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(run_discovery_module, "run_job_search", boom)
    exit_code = run_discovery_module.main()
    assert exit_code == 1


def test_main_passes_greenhouse_boards_from_argv(run_discovery_module, monkeypatch):
    captured = {}

    def fake_default_sources(greenhouse_boards=None):
        captured["boards"] = greenhouse_boards
        return []

    monkeypatch.setattr(run_discovery_module, "default_sources", fake_default_sources)
    monkeypatch.setattr(run_discovery_module, "run_job_search", lambda sources: {"run_id": "1", "error": None})
    monkeypatch.setattr(run_discovery_module.sys, "argv", ["run_discovery.py", "stripe", "discord"])

    run_discovery_module.main()
    assert captured["boards"] == ["stripe", "discord"]


def test_main_defaults_to_none_boards_when_no_argv(run_discovery_module, monkeypatch):
    captured = {}

    def fake_default_sources(greenhouse_boards=None):
        captured["boards"] = greenhouse_boards
        return []

    monkeypatch.setattr(run_discovery_module, "default_sources", fake_default_sources)
    monkeypatch.setattr(run_discovery_module, "run_job_search", lambda sources: {"run_id": "1", "error": None})
    monkeypatch.setattr(run_discovery_module.sys, "argv", ["run_discovery.py"])

    run_discovery_module.main()
    assert captured["boards"] is None
