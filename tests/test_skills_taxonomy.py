from app.jobs.skills_taxonomy import are_related, find_related_candidate_skill


def test_exact_match_is_related():
    assert are_related("Python", "python") is True


def test_related_cluster_ml_frameworks():
    assert are_related("pytorch", "scikit-learn") is True
    assert are_related("pytorch", "tensorflow") is True


def test_unrelated_skills_are_not_related():
    assert are_related("pytorch", "photoshop") is False
    assert are_related("kubernetes", "excel") is False


def test_unknown_skill_not_in_taxonomy_is_not_related():
    assert are_related("some-random-tool-xyz", "python") is False


def test_find_related_candidate_skill_returns_match():
    candidate_skills = {"scikit-learn", "python"}
    result = find_related_candidate_skill("pytorch", candidate_skills)
    assert result == "scikit-learn"


def test_find_related_candidate_skill_returns_none_when_no_match():
    candidate_skills = {"photoshop"}
    result = find_related_candidate_skill("pytorch", candidate_skills)
    assert result is None
