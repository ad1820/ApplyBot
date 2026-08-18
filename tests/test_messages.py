from app.telegram.messages import (
    HELP_TEXT,
    escape_html,
    format_application_confirmation,
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
