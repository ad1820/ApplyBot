"""Sync candidate skills into the candidate_profiles.skills column in
Supabase.

This is the deterministic, user-owned source of truth for "what skills do I
actually have". Edit config/candidate_skills.json (local development), or
set CANDIDATE_SKILLS_JSON to the same JSON content (production secrets,
e.g. Northflank) - whichever is present is used - then run:

    python scripts/sync_skills.py

The matcher (app/jobs/matcher.py) always compares job requirements against
exactly this list (plus the semantic skill taxonomy for adjacent/related
tools, and an optional LLM opinion for anything neither covers) - it never
invents skills you didn't put in this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running this script directly (e.g. `python scripts/sync_skills.py`
# or `python D:\Job_Applier\scripts\sync_skills.py`) regardless of the
# current working directory - Python only puts the script's own folder on
# sys.path by default, not the project root, so `import app...` would
# otherwise fail with "ModuleNotFoundError: No module named 'app'".
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.repositories.profiles import CandidateProfileRepository  # noqa: E402
from app.db.supabase import get_supabase_client  # noqa: E402
from app.json_config import ConfigLoadError, load_json_config  # noqa: E402

SKILLS_FILE = _PROJECT_ROOT / "config" / "candidate_skills.json"


def main() -> None:
    settings = get_settings()
    try:
        data = load_json_config(SKILLS_FILE, settings.candidate_skills_json, "candidate_skills")
    except ConfigLoadError as exc:
        print(
            f"{exc}\nFor local development: copy config/candidate_skills.example.json to "
            "config/candidate_skills.json and fill in your real skills.\n"
            "For production: set CANDIDATE_SKILLS_JSON to the same JSON content."
        )
        return

    skills = data.get("skills", [])
    if not skills:
        print("No skills found in", SKILLS_FILE, "or CANDIDATE_SKILLS_JSON")
        return

    client = get_supabase_client()
    repo = CandidateProfileRepository(client)
    existing = repo.get()
    if not existing:
        print("No candidate profile found yet. Create one first (e.g. via a setup script) before syncing skills.")
        return

    updated = repo.upsert({"skills": skills})
    print(f"Synced {len(skills)} skills to candidate profile {updated['id']}:")
    for skill in skills:
        print(" -", skill)


if __name__ == "__main__":
    main()
