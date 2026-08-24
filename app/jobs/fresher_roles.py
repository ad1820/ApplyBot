"""Loader for fresher_hiring_roles.txt - a curated list of job-title
patterns commonly used for entry-level/fresher hiring in India (SDE, SWE,
SDET, GET, MTS-1, etc.), used to broaden role-title matching beyond
whatever a user has explicitly listed in config/job_preferences.json.

Kept as plain data (not stored in Supabase) since it's a shared reference
list, not something specific to a single candidate's preferences.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROLES_FILE = Path(__file__).resolve().parent.parent.parent / "fresher_hiring_roles.txt"


def _split_role_line(line: str) -> list[str]:
    """Expand a single line like "Software Development Engineer (SDE /
    SDE-1)" into multiple standalone role phrases: the base phrase itself,
    plus each slash-separated alternative both outside and inside any
    parenthetical, e.g. ["Software Development Engineer", "SDE", "SDE-1"].
    """
    line = line.strip()
    if not line:
        return []

    paren_contents = re.findall(r"\(([^)]*)\)", line)
    base = re.sub(r"\([^)]*\)", "", line).strip()

    variants: list[str] = []
    for part in base.split("/"):
        part = part.strip()
        if part:
            variants.append(part)
    for content in paren_contents:
        for part in content.split("/"):
            part = part.strip()
            if part:
                variants.append(part)
    return variants


def load_fresher_hiring_roles(path: Path | None = None) -> list[str]:
    """Return the deduplicated, order-preserved list of role phrases from
    fresher_hiring_roles.txt. Missing file just yields an empty list -
    never a hard failure, since this is an optional matching enhancement."""
    file_path = path or _ROLES_FILE
    if not file_path.is_file():
        return []

    seen: set[str] = set()
    roles: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        for role in _split_role_line(line):
            key = role.lower()
            if key not in seen:
                seen.add(key)
                roles.append(role)
    return roles
