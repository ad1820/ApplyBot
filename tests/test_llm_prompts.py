from app.llm.prompts import (
    cover_letter_prompt,
    generative_answer_prompt,
    resume_analysis_prompt,
    semantic_skill_check_prompt,
)


def test_semantic_skill_check_prompt_includes_skill_and_candidate_skills():
    system, user = semantic_skill_check_prompt("pytorch", {"scikit-learn", "python"})
    assert "pytorch" in user
    assert "python" in user
    assert "scikit-learn" in user
    assert "yes or no" in user.lower()
    assert "strict" in system.lower()


def test_resume_analysis_prompt_forbids_fabrication_and_requests_json():
    system, user = resume_analysis_prompt("Job needs Python", "My resume text", {"skills": ["Python"]})
    assert "never invent" in system.lower() or "must never invent" in system.lower()
    assert "json" in system.lower()
    assert "My resume text" in user
    assert "Job needs Python" in user


def test_cover_letter_prompt_forbids_fabrication():
    system, user = cover_letter_prompt("Job description", "Resume content", {"name": "Alice"})
    assert "never invent" in system.lower()
    assert "Resume content" in user
    assert "Job description" in user


def test_generative_answer_prompt_grounds_in_profile():
    system, user = generative_answer_prompt("Why do you want to work here?", {"name": "Alice"}, "Job description")
    assert "never invent" in system.lower()
    assert "Why do you want to work here?" in user
    assert "Job description" in user
