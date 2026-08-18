"""Tests for app.json_config's file-or-env-JSON fallback loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.json_config import ConfigLoadError, load_json_config


def test_loads_from_file_when_it_exists(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"name": "Alice"}), encoding="utf-8")

    result = load_json_config(path, "", "test_config")
    assert result == {"name": "Alice"}


def test_falls_back_to_env_json_when_file_missing(tmp_path):
    path = tmp_path / "does_not_exist.json"
    env_value = json.dumps({"name": "Bob"})

    result = load_json_config(path, env_value, "test_config")
    assert result == {"name": "Bob"}


def test_file_takes_precedence_over_env_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"name": "FromFile"}), encoding="utf-8")
    env_value = json.dumps({"name": "FromEnv"})

    result = load_json_config(path, env_value, "test_config")
    assert result == {"name": "FromFile"}


def test_raises_when_neither_source_available(tmp_path):
    path = tmp_path / "does_not_exist.json"

    with pytest.raises(ConfigLoadError) as exc_info:
        load_json_config(path, "", "test_config")
    assert "test_config" in str(exc_info.value)


def test_raises_on_malformed_json_in_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("not valid json{{{", encoding="utf-8")

    with pytest.raises(ConfigLoadError):
        load_json_config(path, "", "test_config")


def test_raises_on_malformed_json_in_env_fallback(tmp_path):
    path = tmp_path / "does_not_exist.json"

    with pytest.raises(ConfigLoadError):
        load_json_config(path, "not valid json{{{", "test_config")


def test_handles_empty_path_string_gracefully():
    # Some callers pass Path("") when no file path is configured at all -
    # this must fall through to the env var rather than crashing.
    result = load_json_config(Path(""), json.dumps({"ok": True}), "test_config")
    assert result == {"ok": True}


def test_whitespace_only_env_value_is_treated_as_absent(tmp_path):
    path = tmp_path / "does_not_exist.json"
    with pytest.raises(ConfigLoadError):
        load_json_config(path, "   ", "test_config")
