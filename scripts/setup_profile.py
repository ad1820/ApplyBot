"""Set up / update your candidate profile and job preferences in Supabase.

Config-driven, same pattern as scripts/sync_skills.py: edit the JSON files
below, then run this script. Safe to re-run any time - it upserts, so it
never creates duplicate rows (this is a single-user system: one profile,
one preferences row).

Each JSON source can come from either a file on disk (local development)
or an environment variable containing the same JSON content (production
secrets, e.g. Northflank) - whichever is present is used, so the exact
same command works unchanged in both environments:

    File (dev)                          Env var fallback (production)
    config/candidate_profile.json       CANDIDATE_PROFILE_JSON
    config/job_preferences.json         JOB_PREFERENCES_JSON
    config/candidate_skills.json        (synced separately via sync_skills.py)

Then run:
    python scripts/setup_profile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running this script directly regardless of the current working
# directory - see scripts/sync_skills.py for why this is needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.repositories.profiles import CandidateProfileRepository, JobPreferencesRepository  # noqa: E402
from app.db.supabase import get_supabase_client  # noqa: E402
from app.json_config import ConfigLoadError, load_json_config  # noqa: E402

PROFILE_FILE = _PROJECT_ROOT / "config" / "candidate_profile.json"
PREFERENCES_FILE = _PROJECT_ROOT / "config" / "job_preferences.json"

_VALID_WORK_MODES = {"remote", "hybrid", "onsite", "any"}


def _load_json(path: Path) -> dict:
    """Retained for the test suite / direct callers that pass an explicit
    file path with no env fallback needed."""
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def main() -> None:
    settings = get_settings()

    try:
        profile_data = load_json_config(PROFILE_FILE, settings.candidate_profile_json, "candidate_profile")
    except ConfigLoadError as exc:
        print(
            f"{exc}\nFor local development: copy config/candidate_profile.example.json to "
            "config/candidate_profile.json and fill in your real details.\n"
            "For production: set CANDIDATE_PROFILE_JSON to the same JSON content."
        )
        return

    try:
        preferences_data = load_json_config(PREFERENCES_FILE, settings.job_preferences_json, "job_preferences")
    except ConfigLoadError as exc:
        print(
            f"{exc}\nFor local development: create config/job_preferences.json (see "
            "config/job_preferences.example.json).\n"
            "For production: set JOB_PREFERENCES_JSON to the same JSON content."
        )
        return

    profile_data.pop("_comment", None)
    preferences_data.pop("_comment", None)

    if not profile_data.get("name") or not profile_data.get("email"):
        print("candidate_profile.json must include at least 'name' and 'email'.")
        return

    work_mode = preferences_data.get("work_mode", "any")
    if work_mode not in _VALID_WORK_MODES:
        print(f"job_preferences.json 'work_mode' must be one of {_VALID_WORK_MODES}, got: {work_mode!r}")
        return

    client = get_supabase_client()
    profile_repo = CandidateProfileRepository(client)
    prefs_repo = JobPreferencesRepository(client)

    # Skills are managed separately via config/candidate_skills.json +
    # scripts/sync_skills.py - don't let this script wipe them out if the
    # profile file doesn't mention skills at all.
    profile_data.pop("skills", None)

    profile = profile_repo.upsert(profile_data)
    print(f"Profile saved: {profile['name']} ({profile['id']})")

    prefs = prefs_repo.upsert(profile["id"], preferences_data)
    print("Preferences saved:")
    for key in (
        "preferred_roles",
        "preferred_technologies",
        "preferred_locations",
        "work_mode",
        "minimum_salary",
        "fresher_friendly_only",
        "excluded_companies",
    ):
        if key in prefs:
            print(f"  {key}: {prefs[key]}")

    print("\nDone. Run scripts/sync_skills.py separately to update your skills list.")


if __name__ == "__main__":
    main()
