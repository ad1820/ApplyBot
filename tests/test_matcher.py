from app.jobs.matcher import apply_llm_boost, score_job
from app.jobs.models import Job, WorkMode


def make_job(**overrides):
    defaults = dict(
        source="test",
        company="Acme",
        title="Backend Engineer",
        location="Bangalore",
        work_mode=WorkMode.REMOTE,
        skills=["Python", "FastAPI", "Docker", "Kubernetes"],
        description="",
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_score_job_strong_match():
    job = make_job()
    profile = {"skills": ["Python", "FastAPI", "Docker"]}
    preferences = {"preferred_locations": ["Bangalore"], "work_mode": "remote"}

    result = score_job(job, profile, preferences)

    assert result.match_score > 50
    assert "python" in result.matching_skills
    assert "kubernetes" in result.missing_skills
    assert any("Bangalore" in r for r in result.matching_reasons)


def test_score_job_no_skills_listed_falls_back_to_description():
    job = make_job(skills=[], description="We use Python and Docker daily")
    profile = {"skills": ["Python", "Docker"]}
    result = score_job(job, profile, {})
    assert "python" in result.matching_skills
    assert "docker" in result.matching_skills


def test_score_job_excluded_company_flagged():
    job = make_job(company="BadCo")
    profile = {"skills": ["Python"]}
    preferences = {"excluded_companies": ["BadCo"]}
    result = score_job(job, profile, preferences)
    assert any("excluded" in c for c in result.concerns)


def test_score_job_deterministic_without_llm():
    job = make_job()
    profile = {"skills": ["Python"]}
    result_1 = score_job(job, profile, {})
    result_2 = score_job(job, profile, {})
    assert result_1.match_score == result_2.match_score


def test_apply_llm_boost_blends_scores():
    from app.jobs.matcher import MatchResult

    base = MatchResult(match_score=60.0)
    boosted = apply_llm_boost(base, {"semantic_score": 90, "reasons": ["Great culture fit"]})
    assert boosted.match_score == 60.0 * 0.7 + 90 * 0.3
    assert "Great culture fit" in boosted.matching_reasons


def test_apply_llm_boost_noop_when_no_analysis():
    from app.jobs.matcher import MatchResult

    base = MatchResult(match_score=60.0)
    result = apply_llm_boost(base, None)
    assert result is base


def test_score_job_penalizes_mismatched_role_title():
    # A sales role should score low for a candidate looking for Backend Engineer roles,
    # even if the company happens to also use Python internally.
    job = make_job(title="Account Executive, Enterprise", skills=[])
    profile = {"skills": ["Python", "FastAPI", "Docker"]}
    preferences = {"preferred_roles": ["Backend Engineer", "Software Engineer"]}

    result = score_job(job, profile, preferences)

    assert any("does not match any preferred role" in c for c in result.concerns)


def test_score_job_rewards_matching_role_title_variants():
    job = make_job(title="Senior Backend Engineer II", skills=["Python"])
    profile = {"skills": ["Python"]}
    preferences = {"preferred_roles": ["Backend Engineer"]}

    result = score_job(job, profile, preferences)

    assert any("Title matches a preferred role" in r for r in result.matching_reasons)


def test_score_job_neutral_when_no_preferred_roles_configured():
    job = make_job(title="Anything Goes", skills=[])
    profile = {"skills": []}
    result = score_job(job, profile, {})
    assert not any("does not match any preferred role" in c for c in result.concerns)


def test_mismatched_role_scores_lower_than_matching_role():
    profile = {"skills": ["Python"]}
    preferences = {"preferred_roles": ["Backend Engineer"]}

    matching_job = make_job(title="Backend Engineer", skills=["Python"])
    mismatched_job = make_job(title="Account Executive", skills=["Python"])

    matching_result = score_job(matching_job, profile, preferences)
    mismatched_result = score_job(mismatched_job, profile, preferences)

    assert matching_result.match_score > mismatched_result.match_score


def test_related_skill_gives_partial_credit_not_full_credit():
    # Candidate has scikit-learn, job wants pytorch - related but not exact.
    job = make_job(skills=["pytorch"])
    profile_related = {"skills": ["scikit-learn"]}
    profile_exact = {"skills": ["pytorch"]}

    related_result = score_job(job, profile_related, {})
    exact_result = score_job(job, profile_exact, {})

    assert "pytorch" in related_result.related_skills
    assert "pytorch" not in related_result.matching_skills
    assert related_result.match_score < exact_result.match_score
    assert related_result.match_score > 0


def test_completely_unrelated_skill_counted_as_missing():
    job = make_job(skills=["kubernetes"])
    profile = {"skills": ["photoshop"]}
    result = score_job(job, profile, {})
    assert "kubernetes" in result.missing_skills
    assert "kubernetes" not in result.related_skills


def test_semantic_skill_checker_can_grant_partial_credit_for_unmapped_skill():
    job = make_job(skills=["some-niche-tool"])
    profile = {"skills": ["python"]}

    def checker(job_skill, candidate_skills):
        return job_skill if job_skill == "some-niche-tool" else None

    result = score_job(job, profile, {}, semantic_skill_checker=checker)
    assert "some-niche-tool" in result.related_skills
    assert "some-niche-tool" not in result.missing_skills


def test_semantic_skill_checker_returning_none_still_counts_as_missing():
    job = make_job(skills=["some-niche-tool"])
    profile = {"skills": ["python"]}

    def checker(job_skill, candidate_skills):
        return None

    result = score_job(job, profile, {}, semantic_skill_checker=checker)
    assert "some-niche-tool" in result.missing_skills


def test_india_location_scores_well_for_location_component():
    job = make_job(location="Bangalore, India", work_mode=WorkMode.ONSITE)
    result = score_job(job, {"skills": []}, {})
    assert any("compatible with India-based" in r for r in result.matching_reasons)


def test_remote_job_scores_well_regardless_of_country():
    job = make_job(location="San Francisco, USA", work_mode=WorkMode.REMOTE)
    result = score_job(job, {"skills": []}, {})
    assert any("compatible with India-based" in r for r in result.matching_reasons)


def test_onsite_non_india_no_visa_mention_is_penalized():
    job = make_job(location="San Francisco, USA", work_mode=WorkMode.ONSITE, description="Standard SF office role.")
    result = score_job(job, {"skills": []}, {})
    assert any("not in India" in c for c in result.concerns)


def test_onsite_non_india_with_visa_sponsorship_mentioned_is_not_penalized():
    job = make_job(
        location="San Francisco, USA",
        work_mode=WorkMode.ONSITE,
        description="We offer visa sponsorship for the right candidate.",
    )
    result = score_job(job, {"skills": []}, {})
    assert any("visa" in r.lower() for r in result.matching_reasons)


def test_senior_title_penalized_for_fresher():
    job = make_job(title="Senior Backend Engineer")
    result = score_job(job, {"skills": []}, {})
    assert any("senior-level" in c for c in result.concerns)


def test_entry_level_title_rewarded_for_fresher():
    job = make_job(title="Junior Backend Engineer")
    result = score_job(job, {"skills": []}, {})
    assert any("entry-level" in r.lower() for r in result.matching_reasons)


def test_unlabeled_seniority_stays_neutral():
    job = make_job(title="Backend Engineer", description="")
    senior_job = make_job(title="Staff Backend Engineer")
    result = score_job(job, {"skills": []}, {})
    senior_result = score_job(senior_job, {"skills": []}, {})
    assert result.match_score > senior_result.match_score


def test_seniority_keywords_in_description_do_not_cause_false_positives():
    # Regression test: "intern" must not match inside "internet", and
    # description text mentioning "graduate" as an education requirement
    # must not cause the role itself to be treated as entry-level, since
    # seniority signals are only trusted from the job title.
    job = make_job(
        title="Backend Engineer, Core Technology",
        description="Our mission is to increase the GDP of the internet. Candidates should be a graduate of a CS program.",
    )
    result = score_job(job, {"skills": []}, {})
    assert not any("entry-level" in r.lower() for r in result.matching_reasons)


def test_seniority_word_boundary_does_not_match_substrings_in_title():
    # "Manager" inside a compound word should not trigger, but a real
    # "Manager" title word should.
    job = make_job(title="Engagement Manager")
    result = score_job(job, {"skills": []}, {})
    assert any("senior-level" in c for c in result.concerns)
