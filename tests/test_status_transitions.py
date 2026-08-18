from app.jobs.models import JobStatus, can_transition


def test_valid_transition_discovered_to_notified():
    assert can_transition(JobStatus.DISCOVERED, JobStatus.NOTIFIED) is True


def test_valid_transition_notified_to_applied():
    assert can_transition(JobStatus.NOTIFIED, JobStatus.APPLIED) is True


def test_invalid_transition_rejected_to_offer():
    assert can_transition(JobStatus.REJECTED, JobStatus.OFFER) is False


def test_invalid_transition_skipped_to_offer_directly():
    assert can_transition(JobStatus.SKIPPED, JobStatus.OFFER) is False


def test_same_status_is_always_allowed():
    assert can_transition(JobStatus.APPLIED, JobStatus.APPLIED) is True


def test_terminal_statuses_have_no_outgoing_transitions_except_withdraw_from_offer():
    assert can_transition(JobStatus.REJECTED, JobStatus.APPLIED) is False
    assert can_transition(JobStatus.WITHDRAWN, JobStatus.APPLIED) is False
    assert can_transition(JobStatus.OFFER, JobStatus.WITHDRAWN) is True
