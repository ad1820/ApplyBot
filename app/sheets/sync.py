"""Google Sheets synchronization.

Google Sheets is a reporting layer only - it must never become the source
of truth, and its unavailability must never block the core job pipeline.
Any sync failure is caught and reported back to the caller so it can be
retried on a later run rather than crashing the whole process.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional

from app.logging_config import get_logger, log_event

logger = get_logger(__name__)

SHEET_COLUMNS = [
    "Date Found",
    "Company",
    "Role",
    "Location",
    "Work Mode",
    "Match Score",
    "Status",
    "Application Date",
    "Resume Version",
    "Referral Potential",
    "Job URL",
    "Notes",
]


def job_to_row(job: dict[str, Any], application: Optional[dict[str, Any]] = None, referral: Optional[dict[str, Any]] = None) -> list[Any]:
    return [
        str(job.get("discovered_at") or "")[:10],
        job.get("company", ""),
        job.get("title", ""),
        job.get("location", ""),
        job.get("work_mode", ""),
        job.get("match_score", ""),
        job.get("status", ""),
        str((application or {}).get("applied_at") or "")[:10],
        (application or {}).get("resume_version", ""),
        (referral or {}).get("potential", ""),
        job.get("url", ""),
        (application or {}).get("notes", ""),
    ]


class SheetsClient:
    """Thin wrapper around gspread, built lazily so importing this module
    never requires Google credentials to be present (e.g. during tests).

    Accepts credentials either as a file path on disk (local development)
    or as the raw JSON content of the service account key (production
    secrets).
    """

    def __init__(self, service_account_file: str = "", service_account_json: str = "", spreadsheet_id: str = ""):
        self.service_account_file = service_account_file
        self.service_account_json = service_account_json
        self.spreadsheet_id = spreadsheet_id
        self._spreadsheet = None
        self._master_worksheet = None

    def _connect(self):
        import gspread
        from google.oauth2.service_account import Credentials
        from app.json_config import ConfigLoadError, load_json_config

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        try:
            info = load_json_config(
                Path(self.service_account_file) if self.service_account_file else Path(""),
                self.service_account_json,
                "Google service account credentials",
            )
        except ConfigLoadError as exc:
            raise RuntimeError(str(exc)) from exc
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        
        self._spreadsheet = client.open_by_key(self.spreadsheet_id)
        self._master_worksheet = self._get_or_create_worksheet("Jobs")
        return self._master_worksheet
        
    def _apply_formatting(self, worksheet: Any) -> None:
        """Applies good-looking formatting to a newly created worksheet."""
        try:
            worksheet.freeze(rows=1)
            # Bold header with dark background, light text
            worksheet.format(
                "A1:L1",
                {
                    "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                    "horizontalAlignment": "CENTER",
                }
            )
        except Exception as exc:
            logger.warning(f"Failed to apply formatting to worksheet {worksheet.title}: {exc}")

    def _get_or_create_worksheet(self, title: str) -> Any:
        import gspread
        if not self._spreadsheet:
            self._connect()
        try:
            return self._spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = self._spreadsheet.add_worksheet(title, rows=1000, cols=len(SHEET_COLUMNS))
            worksheet.append_row(SHEET_COLUMNS)
            self._apply_formatting(worksheet)
            return worksheet

    def append_row(self, row: list[Any], date_str: str) -> None:
        if not self._master_worksheet:
            self._connect()
            
        # Append to master sheet
        self._master_worksheet.append_row(row, table_range="A1")
        
        # Append to date-specific sheet
        if date_str:
            try:
                date_ws = self._get_or_create_worksheet(date_str)
                date_ws.append_row(row, table_range="A1")
            except Exception as exc:
                logger.warning(f"Failed to append row to date worksheet {date_str}: {exc}")


def build_sheets_client_from_settings() -> Optional[SheetsClient]:
    """Build a SheetsClient from app settings, or return None if Sheets
    sync isn't configured."""
    from app.config import get_settings

    settings = get_settings()
    has_credentials = bool(settings.google_service_account_file or settings.google_service_account_json)
    if not has_credentials or not settings.google_sheets_spreadsheet_id:
        return None
    return SheetsClient(
        service_account_file=settings.google_service_account_file,
        service_account_json=settings.google_service_account_json,
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
    )


def sync_job_row(client: Optional[SheetsClient], job: dict[str, Any], application: Optional[dict[str, Any]] = None, referral: Optional[dict[str, Any]] = None) -> bool:
    """Best-effort sync of a single job row. Returns True on success, False
    on failure (never raises) so callers can log/retry without disrupting
    the main pipeline."""
    if client is None:
        log_event(logger, "info", "Sheets sync skipped: not configured", job_id=str(job.get("id")))
        return False
    try:
        row = job_to_row(job, application, referral)
        date_str = str(job.get("discovered_at") or "")[:10]
        if not date_str:
            date_str = datetime.date.today().isoformat()
            
        client.append_row(row, date_str=date_str)
        log_event(logger, "info", "Sheets sync succeeded", job_id=str(job.get("id")), operation="sheets_sync", status="SUCCESS")
        return True
    except Exception as exc:  # noqa: BLE001 - must never crash the pipeline
        log_event(
            logger, "error", "Sheets sync failed", job_id=str(job.get("id")),
            operation="sheets_sync", status="FAILED", error=str(exc),
        )
        return False
