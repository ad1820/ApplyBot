from pathlib import Path

from app.jobs.fresher_roles import load_fresher_hiring_roles


def test_load_fresher_hiring_roles_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    assert load_fresher_hiring_roles(missing) == []


def test_load_fresher_hiring_roles_expands_slash_and_parenthetical_variants(tmp_path):
    roles_file = tmp_path / "roles.txt"
    roles_file.write_text(
        "Software Development Engineer (SDE / SDE-1)\n"
        "QA Engineer / SDET (Software Development Engineer in Test)\n"
        "\n"
        "Associate Product Manager (APM)\n",
        encoding="utf-8",
    )

    roles = load_fresher_hiring_roles(roles_file)
    lowered = {r.lower() for r in roles}

    assert "software development engineer" in lowered
    assert "sde" in lowered
    assert "sde-1" in lowered
    assert "qa engineer" in lowered
    assert "sdet" in lowered
    assert "software development engineer in test" in lowered
    assert "associate product manager" in lowered
    assert "apm" in lowered


def test_load_fresher_hiring_roles_deduplicates_case_insensitively(tmp_path):
    roles_file = tmp_path / "roles.txt"
    roles_file.write_text("SDE\nsde\nSDE\n", encoding="utf-8")
    roles = load_fresher_hiring_roles(roles_file)
    assert len(roles) == 1


def test_load_fresher_hiring_roles_real_file_loads_without_error():
    # Sanity check against the actual project file, if present.
    project_root = Path(__file__).resolve().parent.parent
    roles_file = project_root / "fresher_hiring_roles.txt"
    if roles_file.is_file():
        roles = load_fresher_hiring_roles(roles_file)
        assert len(roles) > 0
        assert any("SDE" in r or "Software" in r for r in roles)
