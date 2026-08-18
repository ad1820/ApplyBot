from app.jobs.deduplicator import compute_canonical_key, is_duplicate, canonical_url


def test_canonical_key_ignores_casing_and_whitespace():
    key_a = compute_canonical_key("Acme Inc", "Senior Backend Engineer", "Bangalore, India")
    key_b = compute_canonical_key("  acme inc ", "backend engineer", "bangalore india")
    assert key_a == key_b


def test_canonical_key_differs_for_different_jobs():
    key_a = compute_canonical_key("Acme", "Backend Engineer", "Bangalore")
    key_b = compute_canonical_key("Acme", "Frontend Engineer", "Bangalore")
    assert key_a != key_b


def test_is_duplicate_via_company_title_location():
    job_a = {"company": "Acme", "title": "Senior Backend Engineer", "location": "Bangalore"}
    job_b = {"company": "Acme", "title": "Backend Engineer", "location": "Bangalore"}
    assert is_duplicate(job_a, job_b) is True


def test_is_duplicate_via_canonical_url():
    job_a = {"company": "A", "title": "X", "location": "Y", "url": "https://x.com/job/1?utm=abc"}
    job_b = {"company": "B", "title": "Z", "location": "W", "url": "https://x.com/job/1/"}
    assert is_duplicate(job_a, job_b) is True


def test_is_duplicate_via_external_id_and_source():
    job_a = {"company": "A", "title": "X", "location": "Y", "source": "greenhouse", "external_id": "42"}
    job_b = {"company": "B", "title": "Z", "location": "W", "source": "greenhouse", "external_id": "42"}
    assert is_duplicate(job_a, job_b) is True


def test_not_duplicate_when_nothing_matches():
    job_a = {"company": "A", "title": "X", "location": "Y", "url": "https://a.com/1"}
    job_b = {"company": "B", "title": "Z", "location": "W", "url": "https://b.com/2"}
    assert is_duplicate(job_a, job_b) is False


def test_canonical_url_strips_query_and_fragment():
    assert canonical_url("https://x.com/job/1?a=1#frag") == "https://x.com/job/1"
    assert canonical_url(None) == ""
