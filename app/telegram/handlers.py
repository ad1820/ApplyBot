"""Telegram command handlers.

Each handler is a plain function taking a ``BotContext`` (repositories +
bot client) and the command arguments, and returning the text to send back.
Kept free of any Telegram-framework-specific plumbing so they're easy to
unit test by calling them directly with fake repositories.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.resume_agent import analyze_resume
from app.db.repositories.applications import ApplicationRepository
from app.db.repositories.jobs import JobRepository
from app.db.repositories.analytics import compute_funnel_stats, AnalyticsEventRepository
from app.db.repositories.profiles import CandidateProfileRepository
from app.db.repositories.resumes import MasterResumeRepository, TailoredResumeRepository
from app.jobs.models import Job, JobStatus, can_transition
from app.llm.base import LLMProvider
from app.telegram.messages import (
    HELP_TEXT,
    escape_html,
    format_application_confirmation,
    format_job_detail,
    format_resume_analysis,
    format_resume_approved,
    format_stats,
    format_status_update,
)


@dataclass
class BotContext:
    jobs: JobRepository
    applications: ApplicationRepository
    analytics: AnalyticsEventRepository
    profiles: Optional[CandidateProfileRepository] = None
    master_resumes: Optional[MasterResumeRepository] = None
    tailored_resumes: Optional[TailoredResumeRepository] = None
    llm_provider: Optional[LLMProvider] = None


def handle_start() -> str:
    return "👋 Welcome to your Job Application Agent. Use /help to see available commands."


def handle_help() -> str:
    return HELP_TEXT


def handle_today(ctx: BotContext) -> str:
    jobs = ctx.jobs.list_recent(limit=50)
    today = datetime.now(timezone.utc).date()
    todays_jobs = [
        j for j in jobs
        if j.get("discovered_at") and str(j["discovered_at"])[:10] == str(today)
    ]
    if not todays_jobs:
        return "No new jobs discovered today yet."
    return "\n\n".join(format_job_detail(j) for j in todays_jobs)


def handle_jobs(ctx: BotContext, limit: int = 10) -> str:
    jobs = ctx.jobs.list_recent(limit=limit)
    if not jobs:
        return "No jobs found."
    return "\n\n".join(format_job_detail(j) for j in jobs)


def handle_job(ctx: BotContext, job_id: str) -> str:
    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."
    return format_job_detail(job)


def handle_done(ctx: BotContext, job_id: str, resume_version: Optional[str] = None) -> str:
    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."
    ctx.jobs.set_status(job_id, JobStatus.APPLIED.value)
    application = ctx.applications.record_applied(job_id, resume_version=resume_version)
    ctx.analytics.record("APPLIED", job_id=job_id)
    applied_at = str(application.get("applied_at", ""))[:10]
    return format_application_confirmation(job, applied_at)


def handle_skip(ctx: BotContext, job_id: str) -> str:
    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."
    current = JobStatus(job["status"])
    if not can_transition(current, JobStatus.SKIPPED):
        return f"Cannot skip job {escape_html(job_id)} from status {escape_html(current.value)}."
    ctx.jobs.set_status(job_id, JobStatus.SKIPPED.value)
    ctx.analytics.record("SKIPPED", job_id=job_id)
    return f"⏭ Job {escape_html(job_id)} marked as skipped."


def handle_status(ctx: BotContext, job_id: str) -> str:
    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."
    return f"Job {escape_html(job_id)} status: {escape_html(job['status'])}"


def handle_applied(ctx: BotContext) -> str:
    applications = ctx.applications.list_all()
    if not applications:
        return "No applications recorded yet."
    lines = []
    for app in applications:
        job = ctx.jobs.get(app["job_id"])
        title = job["title"] if job else "Unknown"
        company = job["company"] if job else "Unknown"
        lines.append(
            f"{escape_html(title)} @ {escape_html(company)} - {escape_html(app['status'])} "
            f"(Job ID: {escape_html(app['job_id'])})"
        )
    return "\n".join(lines)


def handle_stats(ctx: BotContext) -> str:
    events = ctx.analytics.list_all()
    stats = compute_funnel_stats(events)
    return format_stats(stats)


_STATUS_COMMANDS = {
    "interview": JobStatus.INTERVIEW,
    "rejected": JobStatus.REJECTED,
    "offer": JobStatus.OFFER,
    "withdraw": JobStatus.WITHDRAWN,
}


def handle_status_transition(ctx: BotContext, command: str, job_id: str) -> str:
    target = _STATUS_COMMANDS.get(command)
    if target is None:
        return f"Unknown command: {escape_html(command)}"
    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."
    current = JobStatus(job["status"])
    if not can_transition(current, target):
        return f"Cannot move job {escape_html(job_id)} from {escape_html(current.value)} to {escape_html(target.value)}."
    ctx.jobs.set_status(job_id, target.value)
    updated = ctx.applications.set_status(job_id, target.value if target.value != "WITHDRAWN" else "WITHDRAWN")
    ctx.analytics.record(target.value, job_id=job_id)
    return format_status_update(job, target.value)


def handle_set_resume(ctx: BotContext, resume_text: str) -> str:
    """V2: store a new master resume version (never overwrites old ones)."""
    if not ctx.master_resumes:
        return "Resume storage is not configured."
    if not resume_text.strip():
        return "Please send your resume text after the command, e.g.:\n/setresume (paste your resume here)"
    resume = ctx.master_resumes.create_new_version(resume_text.strip())
    return f"✅ Master resume saved as version {escape_html(resume['version'])}."


def _job_dict_to_model(job: dict) -> Job:
    from app.jobs.models import WorkMode

    work_mode_value = job.get("work_mode") or "unknown"
    try:
        work_mode = WorkMode(work_mode_value)
    except ValueError:
        work_mode = WorkMode.UNKNOWN
    return Job(
        id=job.get("id"),
        external_id=job.get("external_id"),
        source=job.get("source", "unknown"),
        company=job.get("company", "Unknown"),
        title=job.get("title", "Unknown Title"),
        location=job.get("location"),
        work_mode=work_mode,
        skills=job.get("skills") or [],
        description=job.get("description"),
        url=job.get("url"),
    )


def handle_resume_analysis(ctx: BotContext, job_id: str) -> str:
    """V2: /resume <job_id> - compare master resume against a job and
    propose (but never auto-apply) a tailored resume."""
    if not (ctx.master_resumes and ctx.tailored_resumes and ctx.profiles and ctx.llm_provider):
        return "Resume analysis is not configured."

    job = ctx.jobs.get(job_id)
    if not job:
        return f"Job {escape_html(job_id)} not found."

    master_resume = ctx.master_resumes.get_latest()
    if not master_resume:
        return "No master resume on file yet. Send /setresume (your resume text) first."

    profile = ctx.profiles.get() or {}
    job_model = _job_dict_to_model(job)

    analysis = analyze_resume(job_model, master_resume["content"], profile, ctx.llm_provider)

    ctx.tailored_resumes.create(
        {
            "job_id": job_id,
            "master_resume_version": master_resume["version"],
            "content": analysis.tailored_resume,
            "match_score": analysis.match_score,
            "strong_skills": analysis.strong_skills,
            "missing_skills": analysis.missing_skills,
            "suggested_changes": analysis.suggested_changes,
            "approved": False,
        }
    )

    return format_resume_analysis(job, analysis)


def handle_approve_resume(ctx: BotContext, job_id: str) -> str:
    """V2: approve the most recent tailored resume draft for a job."""
    if not ctx.tailored_resumes:
        return "Resume storage is not configured."
    drafts = ctx.tailored_resumes.list_for_job(job_id)
    if not drafts:
        return f"No tailored resume draft found for job {escape_html(job_id)}. Run /resume {escape_html(job_id)} first."
    latest = sorted(drafts, key=lambda d: d.get("created_at") or "", reverse=True)[0]
    approved = ctx.tailored_resumes.approve(latest["id"])
    return format_resume_approved(job_id, approved)


_STATUS_TRANSITION_COMMANDS = ("interview", "rejected", "offer", "withdraw")


def dispatch_command(ctx: BotContext, text: str) -> str:
    """Parse a raw Telegram message's text and dispatch it to the right
    handler. Shared by both the long-polling script
    (scripts/telegram_polling.py) and the FastAPI webhook endpoint
    (app.main:telegram_webhook) so command behavior is identical regardless
    of which transport delivered the update."""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return "Unknown command. Use /help to see available commands."
    command = parts[0].lower().lstrip("/")
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "start":
        return handle_start()
    if command == "help":
        return handle_help()
    if command == "today":
        return handle_today(ctx)
    if command == "jobs":
        return handle_jobs(ctx)
    if command == "job":
        return handle_job(ctx, arg)
    if command == "done":
        return handle_done(ctx, arg)
    if command == "skip":
        return handle_skip(ctx, arg)
    if command == "status":
        return handle_status(ctx, arg)
    if command == "applied":
        return handle_applied(ctx)
    if command == "stats":
        return handle_stats(ctx)
    if command in _STATUS_TRANSITION_COMMANDS:
        return handle_status_transition(ctx, command, arg)
    if command == "setresume":
        return handle_set_resume(ctx, arg)
    if command == "resume":
        return handle_resume_analysis(ctx, arg)
    if command == "approveresume":
        return handle_approve_resume(ctx, arg)
    return "Unknown command. Use /help to see available commands."


def build_bot_context_from_settings() -> BotContext:
    """Construct a BotContext wired to real Supabase repositories and the
    configured LLM provider. Used by both the polling script and the
    webhook endpoint so wiring only lives in one place."""
    from app.db.repositories.analytics import AnalyticsEventRepository
    from app.db.supabase import get_supabase_client
    from app.llm.provider import get_llm_provider

    client = get_supabase_client()
    return BotContext(
        jobs=JobRepository(client),
        applications=ApplicationRepository(client),
        analytics=AnalyticsEventRepository(client),
        profiles=CandidateProfileRepository(client),
        master_resumes=MasterResumeRepository(client),
        tailored_resumes=TailoredResumeRepository(client),
        llm_provider=get_llm_provider(),
    )
