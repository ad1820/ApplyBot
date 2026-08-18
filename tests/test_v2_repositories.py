from app.db.repositories.application_qa import ApplicationAnswerRepository, normalize_question
from app.db.repositories.referrals import ReferralAssessmentRepository
from app.db.repositories.resumes import MasterResumeRepository


def test_master_resume_versions_never_overwritten(fake_client):
    repo = MasterResumeRepository(fake_client)
    v1 = repo.create_new_version("Resume v1 content")
    v2 = repo.create_new_version("Resume v2 content")

    assert v1["version"] == 1
    assert v2["version"] == 2
    assert repo.get_version(1)["content"] == "Resume v1 content"
    assert repo.get_latest()["version"] == 2


def test_referral_assessment_repository(fake_client):
    repo = ReferralAssessmentRepository(fake_client)
    repo.create("job-1", "HIGH", "Strong match + startup")
    assessment = repo.get_for_job("job-1")
    assert assessment["potential"] == "HIGH"


def test_application_answer_repository_reuses_approved_answers(fake_client):
    repo = ApplicationAnswerRepository(fake_client)
    repo.save_answer("Are you willing to relocate?", "Yes", "USER_APPROVED", approved=True)

    found = repo.find_answer("are you WILLING to relocate?  ")
    assert found is not None
    assert found["answer"] == "Yes"


def test_normalize_question_collapses_whitespace_and_case():
    assert normalize_question("  Are You  Willing To Relocate? ") == "are you willing to relocate?"
