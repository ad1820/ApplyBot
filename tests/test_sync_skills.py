"""Tests for scripts/sync_skills.py's file-or-env-JSON fallback logic."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "sync_skills.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_skills", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_skills_module():
    return _load_module()


def test_main_syncs_from_file(tmp_path, sync_skills_module, monkeypatch, fake_client):
    skills_path = tmp_path / "candidate_skills.json"
    skills_path.write_text(json.dumps({"skills": ["Python", "Docker"]}), encoding="utf-8")

    monkeypatch.setattr(sync_skills_module, "SKILLS_FILE", skills_path)
    monkeypatch.setattr(sync_skills_module, "get_supabase_client", lambda: fake_client)

    from app.db.repositories.profiles import CandidateProfileRepository

    CandidateProfileRepository(fake_client).upsert({"name": "Alice", "email": "a@example.com"})

    sync_skills_module.main()

    profile = CandidateProfileRepository(fake_client).get()
    assert profile["skills"] == ["Python", "Docker"]


def test_main_falls_back_to_env_json_when_file_missing(tmp_path, sync_skills_module, monkeypatch, fake_client):
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(sync_skills_module, "SKILLS_FILE", missing_path)
    monkeypatch.setattr(sync_skills_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setenv("CANDIDATE_SKILLS_JSON", json.dumps({"skills": ["Rust", "Go"]}))

    from app.config import get_settings
    from app.db.repositories.profiles import CandidateProfileRepository

    CandidateProfileRepository(fake_client).upsert({"name": "Alice", "email": "a@example.com"})

    get_settings.cache_clear()
    sync_skills_module.main()
    get_settings.cache_clear()

    profile = CandidateProfileRepository(fake_client).get()
    assert profile["skills"] == ["Rust", "Go"]


def test_main_reports_actionable_error_when_neither_source_available(tmp_path, sync_skills_module, monkeypatch, capsys):
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(sync_skills_module, "SKILLS_FILE", missing_path)
    monkeypatch.setenv("CANDIDATE_SKILLS_JSON", "")

    from app.config import get_settings

    get_settings.cache_clear()
    sync_skills_module.main()
    get_settings.cache_clear()

    captured = capsys.readouterr()
    assert "CANDIDATE_SKILLS_JSON" in captured.out


def test_main_handles_no_profile_yet(tmp_path, sync_skills_module, monkeypatch, fake_client, capsys):
    skills_path = tmp_path / "candidate_skills.json"
    skills_path.write_text(json.dumps({"skills": ["Python"]}), encoding="utf-8")

    monkeypatch.setattr(sync_skills_module, "SKILLS_FILE", skills_path)
    monkeypatch.setattr(sync_skills_module, "get_supabase_client", lambda: fake_client)

    sync_skills_module.main()

    captured = capsys.readouterr()
    assert "No candidate profile found" in captured.out
