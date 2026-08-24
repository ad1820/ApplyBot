"""Tests for app.agents.job_agent - source wiring only (no live network
calls, no real Supabase client needed for these particular functions)."""
from __future__ import annotations

import json

from app.agents.job_agent import default_sources, load_cached_ats_boards
from app.jobs.discovery import (
    AshbySource,
    GreenhouseSource,
    HimalayasSource,
    LeverSource,
    RemoteOKSource,
    RemotiveSource,
    WeWorkRemotelySource,
    WorkingNomadsSource,
)


def test_load_cached_ats_boards_missing_file_returns_empty(monkeypatch, tmp_path):
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", missing)
    result = load_cached_ats_boards()
    assert result == {"greenhouse": [], "lever": [], "ashby": []}


def test_load_cached_ats_boards_reads_valid_file(monkeypatch, tmp_path):
    boards_file = tmp_path / "ats_boards.json"
    boards_file.write_text(
        json.dumps({"greenhouse": ["acme"], "lever": ["beta"], "ashby": ["gamma"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", boards_file)
    result = load_cached_ats_boards()
    assert result == {"greenhouse": ["acme"], "lever": ["beta"], "ashby": ["gamma"]}


def test_load_cached_ats_boards_invalid_json_returns_empty(monkeypatch, tmp_path):
    boards_file = tmp_path / "ats_boards.json"
    boards_file.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", boards_file)
    result = load_cached_ats_boards()
    assert result == {"greenhouse": [], "lever": [], "ashby": []}


def test_default_sources_always_includes_aggregator_sources(monkeypatch, tmp_path):
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", missing)
    sources = default_sources()
    names = {type(s) for s in sources}
    assert RemoteOKSource in names
    assert RemotiveSource in names
    assert WorkingNomadsSource in names
    assert HimalayasSource in names
    assert WeWorkRemotelySource in names


def test_default_sources_merges_explicit_and_cached_boards(monkeypatch, tmp_path):
    boards_file = tmp_path / "ats_boards.json"
    boards_file.write_text(
        json.dumps({"greenhouse": ["cached-co"], "lever": ["cached-lever"], "ashby": ["cached-ashby"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", boards_file)

    sources = default_sources(
        greenhouse_boards=["explicit-co"],
        lever_companies=["explicit-lever"],
        ashby_companies=["explicit-ashby"],
    )

    gh = next(s for s in sources if isinstance(s, GreenhouseSource))
    lever = next(s for s in sources if isinstance(s, LeverSource))
    ashby = next(s for s in sources if isinstance(s, AshbySource))
    assert set(gh.board_tokens) == {"explicit-co", "cached-co"}
    assert set(lever.company_slugs) == {"explicit-lever", "cached-lever"}
    assert set(ashby.company_slugs) == {"explicit-ashby", "cached-ashby"}


def test_default_sources_can_disable_cached_boards(monkeypatch, tmp_path):
    boards_file = tmp_path / "ats_boards.json"
    boards_file.write_text(
        json.dumps({"greenhouse": ["cached-co"], "lever": [], "ashby": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.agents.job_agent._ATS_BOARDS_FILE", boards_file)

    sources = default_sources(include_cached_ats_boards=False)
    assert not any(isinstance(s, GreenhouseSource) for s in sources)
    assert not any(isinstance(s, LeverSource) for s in sources)
    assert not any(isinstance(s, AshbySource) for s in sources)
