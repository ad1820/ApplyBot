"""Tests for scripts/setup_profile.py's pure logic (JSON loading/validation).

The script itself is a thin CLI wrapper; these tests exercise its helper
functions directly against temp files and a fake Supabase client so no
real Supabase project or filesystem side effects on the real config/ files
are needed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "setup_profile.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("setup_profile", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def setup_profile_module():
    return _load_module()


def test_load_json_strips_comment_key(tmp_path, setup_profile_module):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"_comment": "note", "name": "Alice"}), encoding="utf-8")
    data = setup_profile_module._load_json(path)
    assert "_comment" not in data
    assert data["name"] == "Alice"


def test_main_rejects_missing_required_fields(tmp_path, setup_profile_module, monkeypatch, capsys):
    profile_path = tmp_path / "candidate_profile.json"
    prefs_path = tmp_path / "job_preferences.json"
    profile_path.write_text(json.dumps({"name": "", "email": ""}), encoding="utf-8")
    prefs_path.write_text(json.dumps({"work_mode": "any"}), encoding="utf-8")

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", prefs_path)

    setup_profile_module.main()
    captured = capsys.readouterr()
    assert "must include at least" in captured.out


def test_main_rejects_invalid_work_mode(tmp_path, setup_profile_module, monkeypatch, capsys):
    profile_path = tmp_path / "candidate_profile.json"
    prefs_path = tmp_path / "job_preferences.json"
    profile_path.write_text(json.dumps({"name": "Alice", "email": "a@example.com"}), encoding="utf-8")
    prefs_path.write_text(json.dumps({"work_mode": "not-a-real-mode"}), encoding="utf-8")

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", prefs_path)

    setup_profile_module.main()
    captured = capsys.readouterr()
    assert "work_mode" in captured.out


def test_main_upserts_profile_and_preferences_without_touching_skills(
    tmp_path, setup_profile_module, monkeypatch, fake_client, capsys
):
    profile_path = tmp_path / "candidate_profile.json"
    prefs_path = tmp_path / "job_preferences.json"
    profile_path.write_text(
        json.dumps({"name": "Alice", "email": "a@example.com", "skills": ["should-be-ignored"]}),
        encoding="utf-8",
    )
    prefs_path.write_text(
        json.dumps({"preferred_roles": ["Backend Engineer"], "work_mode": "remote"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", prefs_path)
    monkeypatch.setattr(setup_profile_module, "get_supabase_client", lambda: fake_client)

    setup_profile_module.main()

    from app.db.repositories.profiles import CandidateProfileRepository, JobPreferencesRepository

    saved_profile = CandidateProfileRepository(fake_client).get()
    assert saved_profile["name"] == "Alice"
    assert "skills" not in saved_profile or saved_profile.get("skills") != ["should-be-ignored"]

    saved_prefs = JobPreferencesRepository(fake_client).get_for_profile(saved_profile["id"])
    assert saved_prefs["preferred_roles"] == ["Backend Engineer"]
    assert saved_prefs["work_mode"] == "remote"


def test_main_falls_back_to_env_json_when_files_missing(
    tmp_path, setup_profile_module, monkeypatch, fake_client
):
    # Neither file exists on disk - both should be sourced from env vars.
    missing_profile_path = tmp_path / "candidate_profile.json"
    missing_prefs_path = tmp_path / "job_preferences.json"

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", missing_profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", missing_prefs_path)
    monkeypatch.setattr(setup_profile_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setenv("CANDIDATE_PROFILE_JSON", json.dumps({"name": "EnvAlice", "email": "env@example.com"}))
    monkeypatch.setenv("JOB_PREFERENCES_JSON", json.dumps({"preferred_roles": ["SRE"], "work_mode": "hybrid"}))

    from app.config import get_settings

    get_settings.cache_clear()
    setup_profile_module.main()
    get_settings.cache_clear()

    from app.db.repositories.profiles import CandidateProfileRepository, JobPreferencesRepository

    saved_profile = CandidateProfileRepository(fake_client).get()
    assert saved_profile["name"] == "EnvAlice"

    saved_prefs = JobPreferencesRepository(fake_client).get_for_profile(saved_profile["id"])
    assert saved_prefs["work_mode"] == "hybrid"


def test_main_reports_actionable_error_when_neither_source_available(
    tmp_path, setup_profile_module, monkeypatch, capsys
):
    missing_profile_path = tmp_path / "candidate_profile.json"
    missing_prefs_path = tmp_path / "job_preferences.json"

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", missing_profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", missing_prefs_path)
    monkeypatch.setenv("CANDIDATE_PROFILE_JSON", "")
    monkeypatch.setenv("JOB_PREFERENCES_JSON", "")

    from app.config import get_settings

    get_settings.cache_clear()
    setup_profile_module.main()
    get_settings.cache_clear()

    captured = capsys.readouterr()
    assert "CANDIDATE_PROFILE_JSON" in captured.out


def test_main_is_idempotent_and_updates_existing_profile(
    tmp_path, setup_profile_module, monkeypatch, fake_client
):
    profile_path = tmp_path / "candidate_profile.json"
    prefs_path = tmp_path / "job_preferences.json"
    profile_path.write_text(json.dumps({"name": "Alice", "email": "a@example.com"}), encoding="utf-8")
    prefs_path.write_text(json.dumps({"work_mode": "any"}), encoding="utf-8")

    monkeypatch.setattr(setup_profile_module, "PROFILE_FILE", profile_path)
    monkeypatch.setattr(setup_profile_module, "PREFERENCES_FILE", prefs_path)
    monkeypatch.setattr(setup_profile_module, "get_supabase_client", lambda: fake_client)

    setup_profile_module.main()
    profile_path.write_text(json.dumps({"name": "Alice Updated", "email": "a@example.com"}), encoding="utf-8")
    setup_profile_module.main()

    from app.db.repositories.profiles import CandidateProfileRepository

    repo = CandidateProfileRepository(fake_client)
    all_profiles = repo._table().select("*").execute().data
    assert len(all_profiles) == 1
    assert all_profiles[0]["name"] == "Alice Updated"
