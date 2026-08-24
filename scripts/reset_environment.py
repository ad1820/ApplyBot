"""Reset the Job_Applier environment.
Deletes all jobs from the Supabase database (which cascades to sources,
notifications, applications, referrals, etc.) and clears the Google Sheets
worksheets to start from scratch.
"""
from __future__ import annotations

import logging

from app.db.supabase import get_supabase_client
from app.sheets.sync import build_sheets_client_from_settings
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def reset_supabase() -> None:
    settings = get_settings()
    if not settings.supabase_configured():
        logger.warning("Supabase not configured, skipping DB reset.")
        return

    client = get_supabase_client()
    logger.info("Connecting to Supabase to delete all jobs...")
    
    # We can delete all jobs by matching where id is not null (which is all rows)
    # The REST API requires a filter for deletes.
    try:
        response = client.table("jobs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        logger.info(f"Supabase reset successful. Deleted {len(response.data)} job records (cascading to related tables).")
    except Exception as exc:
        logger.error(f"Failed to reset Supabase: {exc}")


def reset_google_sheets() -> None:
    sheets_client = build_sheets_client_from_settings()
    if not sheets_client:
        logger.warning("Google Sheets not configured, skipping sheets reset.")
        return

    logger.info("Connecting to Google Sheets...")
    worksheet = sheets_client._connect()
    spreadsheet = worksheet.spreadsheet
    
    # Get all worksheets
    worksheets = spreadsheet.worksheets()
    logger.info(f"Found {len(worksheets)} existing worksheets.")
    
    # We must keep at least one worksheet before deleting others.
    # Create a fresh "Jobs" sheet (or a temporary one)
    import gspread
    from app.sheets.sync import SHEET_COLUMNS
    
    temp_name = "Temp_Jobs_Reset"
    fresh_sheet = spreadsheet.add_worksheet(temp_name, rows=1000, cols=len(SHEET_COLUMNS))
    
    # Delete all other worksheets
    for ws in worksheets:
        try:
            spreadsheet.del_worksheet(ws)
            logger.info(f"Deleted worksheet '{ws.title}'.")
        except Exception as exc:
            logger.error(f"Failed to delete worksheet '{ws.title}': {exc}")
            
    # Rename temp sheet to Jobs
    fresh_sheet.update_title("Jobs")
    
    # Apply basic formatting to the new master sheet
    fresh_sheet.append_row(SHEET_COLUMNS)
    
    # We'll rely on the new sync logic to format the sheets moving forward, 
    # but let's apply the basic header format to the master sheet now just in case.
    try:
        fresh_sheet.freeze(rows=1)
        fresh_sheet.format(
            "A1:L1",
            {
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                "horizontalAlignment": "CENTER",
            }
        )
    except Exception as exc:
        logger.warning(f"Failed to apply formatting to fresh sheet: {exc}")

    logger.info("Google Sheets reset successful. 'Jobs' worksheet recreated.")


def main() -> None:
    logger.info("Starting environment reset (DANGER!)...")
    reset_supabase()
    reset_google_sheets()
    logger.info("Environment reset complete.")


if __name__ == "__main__":
    main()

