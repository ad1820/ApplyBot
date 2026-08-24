"""One-shot job-discovery entrypoint. Run this yourself whenever you want a
fresh batch of jobs - 2-3 times a day, on your own schedule, no hosting or
cron dependency required. See DAILY_RUN.md for the everyday workflow.

This wraps the exact same logic as the FastAPI POST /run/job-search
endpoint (app.main:trigger_job_search) - both call
app.agents.job_agent.run_job_search(default_sources(...)) - so behavior is
identical whether you run this script directly or (if you ever do deploy
somewhere) trigger it via HTTP or a scheduler.

Usage:
    python scripts/run_discovery.py

Optional: pass Greenhouse board tokens as arguments to also pull specific
companies' postings, e.g.:
    python scripts/run_discovery.py stripe discord

Exits with status 0 on COMPLETED, 1 on FAILED/PARTIAL or any error.
Re-running right after a previous run is always safe - duplicate jobs are
detected and skipped, never re-notified.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running this script directly regardless of the current working
# directory - see scripts/sync_skills.py for why this is needed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.agents.job_agent import default_sources, run_job_search  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.logging_config import configure_logging, get_logger, log_event  # noqa: E402

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


def main() -> int:
    greenhouse_boards = sys.argv[1:] or None

    log_event(logger, "info", "Starting scheduled job discovery run", operation="run_discovery")
    try:
        result = run_job_search(default_sources(greenhouse_boards=greenhouse_boards))
    except Exception as exc:  # noqa: BLE001 - top-level guard so the process exits cleanly for the scheduler
        log_event(logger, "error", "Job discovery run crashed", operation="run_discovery", status="FAILED", error=str(exc))
        return 1

    # A non-None "error" means the run finished but at least one source or
    # job failed along the way (recorded as PARTIAL in agent_runs) - the
    # run itself did not crash. A hard crash is caught separately above.
    status = "PARTIAL" if result.get("error") else "COMPLETED"
    log_event(
        logger, "info" if status == "COMPLETED" else "error",
        f"Job discovery run finished: {status}",
        operation="run_discovery", status=status,
        run_id=result.get("run_id"),
        jobs_found=result.get("jobs_found"),
        jobs_new=result.get("jobs_new"),
        jobs_duplicate=result.get("jobs_duplicate"),
        jobs_notified=result.get("jobs_notified"),
    )
    print(result)
    return 0 if status == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
