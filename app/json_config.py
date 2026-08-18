"""Helpers for loading JSON configuration that may live either on disk
(local development) or in an environment variable containing raw JSON
content (production secrets, e.g. Northflank/Railway/Render secret vars).

Precedence: file on disk first, then the environment-variable fallback.
This lets local development keep real files under config/ untouched
(git-ignored) while production deployments paste the exact same JSON
content into a secret environment variable instead - either way works
without any code changes, and neither path throws if the other is used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigLoadError(RuntimeError):
    """Raised when neither the file nor the environment variable fallback
    provides valid, loadable JSON."""


def load_json_config(file_path: Path, env_json_value: str, label: str) -> dict[str, Any]:
    """Load a JSON object from `file_path` if it exists on disk, otherwise
    parse `env_json_value` (typically ``get_settings().some_field``) as raw
    JSON content. Raises ConfigLoadError with an actionable message if
    neither source is usable.
    """
    if str(file_path) not in ("", ".") and file_path.is_file():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigLoadError(f"{label}: {file_path} exists but is not valid JSON: {exc}") from exc

    value = (env_json_value or "").strip()
    if value:
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigLoadError(f"{label}: environment variable content is not valid JSON: {exc}") from exc

    raise ConfigLoadError(
        f"{label}: could not find {file_path} on disk, and no environment variable fallback "
        "was provided. For local development, create the file; for production, set the "
        "corresponding *_JSON environment variable to the file's raw JSON content."
    )
