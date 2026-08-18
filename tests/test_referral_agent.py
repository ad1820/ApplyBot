from app.agents.referral_agent import assess_referral_potential


def test_high_referral_potential_with_strong_match_and_contacts():
    job = {"title": "Backend Engineer", "company": "Acme", "match_score": 92, "description": "We are a fast-growing startup"}
    result = assess_referral_potential(job, {"name": "Alice"}, known_contacts_at_company=True)
    assert result.potential == "HIGH"
    assert result.draft_message is not None
    assert "Alice" in result.draft_message


def test_low_referral_potential_with_weak_signals():
    job = {"title": "Backend Engineer", "company": "BigCorp", "match_score": 40, "description": "Large established enterprise"}
    result = assess_referral_potential(job, {"name": "Alice"}, known_contacts_at_company=False)
    assert result.potential == "LOW"
    assert result.draft_message is None


def test_referral_agent_never_auto_sends_only_drafts():
    job = {"title": "Backend Engineer", "company": "Acme", "match_score": 90, "description": "startup"}
    result = assess_referral_potential(job, {"name": "Alice"})
    # The agent only returns a draft string - sending is entirely up to the user.
    assert isinstance(result.draft_message, str)
