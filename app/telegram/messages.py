"""Telegram message templates.

Pure formatting functions - no I/O - so they're trivially unit testable.

All messages are sent with parse_mode="HTML" (see app/telegram/bot.py). Any
dynamic content (job titles, company names, LLM-generated suggestions,
etc.) must be HTML-escaped before interpolation, since raw "<", ">", or "&"
characters make Telegram reject the entire message with a 400 Bad Request -
this previously broke /help (literal "<id>" placeholders) and would break
any job whose title/company contains such characters (e.g. "R&D Engineer").
"""
from __future__ import annotations

from html import escape as _escape
from typing import Any


def escape_html(value: Any) -> str:
    """HTML-escape a value for safe interpolation into an HTML-mode message."""
    return _escape(str(value), quote=False)


# Short alias used throughout this module for brevity.
_e = escape_html


def format_job_notification(job: dict[str, Any]) -> str:
    matching = job.get("matching_skills") or []
    related = job.get("related_skills") or []
    concerns = job.get("concerns") or []

    lines = [
        "🤖 <b>New Job</b>",
        "",
        f"<b>{_e(job.get('title', 'Unknown Title'))}</b>",
        _e(job.get("company", "Unknown Company")),
        "",
        f"Match: {_e(job.get('match_score', 0))}%",
        "",
        f"Location: {_e(job.get('location') or 'Unknown')}",
        f"Work Mode: {_e(job.get('work_mode', 'unknown'))}",
        "",
    ]
    if matching:
        lines.append("Strong matches:")
        lines.extend(f"✓ {_e(skill)}" for skill in matching)
        lines.append("")
    if related:
        lines.append("Related/transferable:")
        lines.extend(f"~ {_e(skill)}" for skill in related)
        lines.append("")
    if concerns:
        lines.append("Concerns:")
        lines.extend(f"⚠ {_e(concern)}" for concern in concerns)
        lines.append("")
    lines.append("Apply:")
    lines.append(_e(job.get("url") or "N/A"))
    lines.append("")
    lines.append(f"Job ID: {_e(job.get('id'))}")
    return "\n".join(lines)


def format_application_confirmation(job: dict[str, Any], applied_at: str) -> str:
    return "\n".join(
        [
            "✅ <b>Application recorded.</b>",
            "",
            _e(job.get("title", "Unknown Title")),
            _e(job.get("company", "Unknown Company")),
            "",
            "Applied:",
            _e(applied_at),
            "",
            "Job ID:",
            _e(job.get("id")),
        ]
    )


def format_status_update(job: dict[str, Any], status: str) -> str:
    return "\n".join(
        [
            f"📌 Status updated: <b>{_e(status)}</b>",
            "",
            _e(job.get("title", "Unknown Title")),
            _e(job.get("company", "Unknown Company")),
            "",
            f"Job ID: {_e(job.get('id'))}",
        ]
    )


def format_stats(stats: dict[str, Any]) -> str:
    return "\n".join(
        [
            "📊 <b>Stats</b>",
            "",
            f"Applications: {_e(stats.get('applications', 0))}",
            f"Interviews: {_e(stats.get('interviews', 0))}",
            f"Interview rate: {_e(stats.get('interview_rate', 0))}%",
            f"Rejections: {_e(stats.get('rejections', 0))}",
            f"Rejection rate: {_e(stats.get('rejection_rate', 0))}%",
            f"Offers: {_e(stats.get('offers', 0))}",
            f"Offer rate: {_e(stats.get('offer_rate', 0))}%",
        ]
    )


def format_job_detail(job: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"<b>{_e(job.get('title', 'Unknown Title'))}</b>",
            _e(job.get("company", "Unknown Company")),
            "",
            f"Status: {_e(job.get('status'))}",
            f"Match: {_e(job.get('match_score', 0))}%",
            f"Location: {_e(job.get('location') or 'Unknown')}",
            f"Work Mode: {_e(job.get('work_mode', 'unknown'))}",
            "",
            _e(job.get("url") or "N/A"),
            "",
            f"Job ID: {_e(job.get('id'))}",
        ]
    )


def format_resume_analysis(job: dict[str, Any], analysis: Any) -> str:
    lines = [
        "📄 <b>Resume Analysis</b>",
        "",
        f"{_e(job.get('title', 'Unknown Title'))} @ {_e(job.get('company', 'Unknown Company'))}",
        "",
        f"Match: {_e(analysis.match_score)}%",
        "",
    ]
    if analysis.strong_skills:
        lines.append("Strong:")
        lines.extend(f"✓ {_e(s)}" for s in analysis.strong_skills)
        lines.append("")
    if analysis.missing_skills:
        lines.append("Missing:")
        lines.extend(f"✗ {_e(s)}" for s in analysis.missing_skills)
        lines.append("")
    if analysis.suggested_changes:
        lines.append("Suggested changes:")
        for i, change in enumerate(analysis.suggested_changes, start=1):
            lines.append(f"{i}. {_e(change)}")
        lines.append("")
    lines.append(f"Approve tailored resume? Send /approveresume {_e(job.get('id'))}")
    return "\n".join(lines)


def format_resume_approved(job_id: str, tailored_resume: dict[str, Any]) -> str:
    return "\n".join(
        [
            "✅ <b>Tailored resume approved.</b>",
            "",
            f"Job ID: {_e(job_id)}",
            f"Based on master resume version: {_e(tailored_resume.get('master_resume_version'))}",
        ]
    )


# Note: this text is sent with parse_mode="HTML", so angle brackets must be
# HTML-escaped (&lt;id&gt; instead of <id>) - otherwise Telegram's HTML
# parser treats "<id>" as an unrecognized/unclosed tag and rejects the
# entire sendMessage call with a 400 Bad Request.
HELP_TEXT = "\n".join(
    [
        "Available commands:",
        "/today - jobs discovered today",
        "/jobs - recent jobs",
        "/job &lt;id&gt; - job detail",
        "/done &lt;id&gt; - mark job as applied",
        "/skip &lt;id&gt; - skip a job",
        "/status &lt;id&gt; - show job status",
        "/applied - list applications",
        "/stats - application statistics",
        "/preferences - view/update preferences",
        "/interview &lt;id&gt; - mark interview stage",
        "/rejected &lt;id&gt; - mark rejected",
        "/offer &lt;id&gt; - mark offer received",
        "/withdraw &lt;id&gt; - withdraw application",
        "/setresume &lt;text&gt; - save your master resume (V2)",
        "/resume &lt;id&gt; - resume analysis for a job (V2)",
        "/approveresume &lt;id&gt; - approve the tailored resume draft (V2)",
    ]
)
