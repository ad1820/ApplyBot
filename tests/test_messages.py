from app.telegram.messages import (
    HELP_TEXT,
    company_callback_hash,
    escape_html,
    format_application_confirmation,
    format_company_digest,
    format_company_jobs,
    format_company_list,
    format_job_notification,
    format_stats,
)


def test_format_job_notification_contains_key_fields():
    job = {
        "id": "1527",
        "title": "Backend Engineer",
        "company": "XYZ",
        "match_score": 92,
        "location": "Bangalore",
        "work_mode": "hybrid",
        "matching_skills": ["Python", "FastAPI"],
        "concerns": ["Kubernetes"],
        "url": "https://xyz.com/apply/1",
    }
    text = format_job_notification(job)
    assert "Backend Engineer" in text
    assert "92%" in text
    assert "Python" in text
    assert "Kubernetes" in text
    assert "https://xyz.com/apply/1" in text
    assert "1527" in text


def test_format_application_confirmation():
    job = {"id": "1527", "title": "Backend Engineer", "company": "XYZ"}
    text = format_application_confirmation(job, "17 Aug 2026")
    assert "Application recorded" in text
    assert "17 Aug 2026" in text


_ALLOWED_HTML_TAGS = ("<b>", "</b>")


def _strip_allowed_tags(text: str) -> str:
    for tag in _ALLOWED_HTML_TAGS:
        text = text.replace(tag, "")
    return text


def test_help_text_has_no_unescaped_angle_brackets():
    # Regression test: literal "<id>"/"<text>" placeholders previously broke
    # every /help reply with a Telegram 400 Bad Request, since the message
    # is sent with parse_mode="HTML" and Telegram's parser rejects unknown
    # tags. Only our own <b>/</b> tags are allowed to remain.
    remaining = _strip_allowed_tags(HELP_TEXT)
    assert "<" not in remaining
    assert ">" not in remaining
    assert "&lt;id&gt;" in HELP_TEXT


def test_escape_html_escapes_angle_brackets_and_ampersand():
    assert escape_html("<script>") == "&lt;script&gt;"
    assert escape_html("R&D Engineer") == "R&amp;D Engineer"
    assert escape_html(42) == "42"


def test_format_job_notification_escapes_dynamic_html_special_characters():
    job = {
        "id": "1",
        "title": "R&D Engineer <Senior>",
        "company": "Acme <script>alert(1)</script>",
        "match_score": 90,
        "location": "Bangalore",
        "work_mode": "remote",
        "matching_skills": ["C++"],
        "url": "https://x.com",
    }
    text = format_job_notification(job)
    remaining = _strip_allowed_tags(text)
    assert "<" not in remaining
    assert ">" not in remaining
    assert "&amp;" in text
    assert "&lt;Senior&gt;" in text


def test_format_stats():
    stats = {"applications": 42, "interviews": 8, "interview_rate": 19.0, "rejections": 10, "rejection_rate": 24.0, "offers": 2, "offer_rate": 5.0}
    text = format_stats(stats)
    assert "42" in text
    assert "19.0%" in text


def test_company_callback_hash_deterministic_and_case_insensitive():
    assert company_callback_hash("OpenAI") == company_callback_hash("openai")
    assert company_callback_hash("OpenAI") == company_callback_hash(" OpenAI ")
    assert company_callback_hash("OpenAI") != company_callback_hash("Acme")
    # Must fit comfortably within Telegram's 64-byte callback_data limit.
    assert len(f"co:{company_callback_hash('A Very Long Company Name Inc.')}") <= 64


def test_format_company_digest_groups_and_counts_by_company():
    jobs = [
        {"company": "Acme", "title": "Backend Engineer"},
        {"company": "Acme", "title": "Platform Engineer"},
        {"company": "OpenAI", "title": "Research Engineer"},
    ]
    text, markup = format_company_digest(jobs)
    assert "3 new matching jobs" in text
    assert "2 companies" in text

    buttons = [btn for row in markup["inline_keyboard"] for btn in row]
    labels = {btn["text"] for btn in buttons}
    assert labels == {"Acme (2)", "OpenAI (1)"}
    for btn in buttons:
        assert btn["callback_data"].startswith("co:")


def test_format_company_digest_singular_wording_for_one_job_one_company():
    jobs = [{"company": "Acme", "title": "Backend Engineer"}]
    text, _ = format_company_digest(jobs)
    assert "1 new matching job" in text
    assert "new matching jobs" not in text
    assert "1 company" in text
    assert "1 companies" not in text


def test_format_company_jobs_renders_all_jobs_for_company():
    jobs = [
        {"id": "1", "title": "Backend Engineer", "company": "Acme", "match_score": 90, "url": "https://x.com/1"},
        {"id": "2", "title": "Platform Engineer", "company": "Acme", "match_score": 85, "url": "https://x.com/2"},
    ]
    text = format_company_jobs("Acme", jobs)
    assert "Acme" in text
    assert "2 matching roles" in text
    assert "Backend Engineer" in text
    assert "Platform Engineer" in text


def test_format_company_jobs_empty_list():
    text = format_company_jobs("Acme", [])
    assert "No matching jobs" in text
    assert "Acme" in text


def test_format_company_list_empty_returns_friendly_message_no_buttons():
    text, markup = format_company_list([])
    assert "No notified jobs yet" in text
    assert markup == {}
