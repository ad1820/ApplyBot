from app.config import get_settings
from app.sheets.sync import build_sheets_client_from_settings, job_to_row, sync_job_row


def test_job_to_row_maps_columns_correctly():
    job = {
        "discovered_at": "2026-08-17T10:00:00",
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Bangalore",
        "work_mode": "remote",
        "match_score": 91,
        "status": "NOTIFIED",
        "url": "https://acme.com/job/1",
    }
    application = {"applied_at": "2026-08-18T00:00:00", "resume_version": "v1", "notes": "n/a"}
    referral = {"potential": "HIGH"}

    row = job_to_row(job, application, referral)

    assert row[0] == "2026-08-17"
    assert row[1] == "Acme"
    assert row[2] == "Backend Engineer"
    assert row[9] == "HIGH"
    assert row[10] == "https://acme.com/job/1"


def test_sync_job_row_returns_false_when_client_not_configured():
    result = sync_job_row(None, {"id": "1"})
    assert result is False


def test_sync_job_row_never_raises_on_failure():
    class BrokenClient:
        def append_row(self, row):
            raise RuntimeError("Sheets API is down")

    result = sync_job_row(BrokenClient(), {"id": "1", "company": "Acme", "title": "Engineer"})
    assert result is False


def test_append_row_always_anchors_to_column_a():
    """Regression test: a prior manual/irregular row in the sheet must never
    cause subsequent appended rows to drift into the wrong columns. The
    underlying gspread worksheet.append_row must always be called with
    table_range="A1" so it never infers table boundaries from stray content."""
    captured = {}

    class FakeWorksheet:
        def append_row(self, row, table_range=None):
            captured["row"] = row
            captured["table_range"] = table_range

    from app.sheets.sync import SheetsClient

    client = SheetsClient(service_account_file="unused", spreadsheet_id="sheet-1")
    client._master_worksheet = FakeWorksheet()

    client.append_row(["2026-08-18", "Acme", "Backend Engineer"], date_str="2026-08-18")

    assert captured["table_range"] == "A1"
    assert captured["row"] == ["2026-08-18", "Acme", "Backend Engineer"]


def test_build_sheets_client_from_settings_none_when_unconfigured(monkeypatch):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    get_settings.cache_clear()
    assert build_sheets_client_from_settings() is None
    get_settings.cache_clear()


def test_build_sheets_client_from_settings_uses_file_path(monkeypatch):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "C:\\secrets\\google.json")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-123")
    get_settings.cache_clear()

    client = build_sheets_client_from_settings()
    assert client is not None
    assert client.service_account_file == "C:\\secrets\\google.json"
    assert client.spreadsheet_id == "sheet-123"
    get_settings.cache_clear()


def test_build_sheets_client_from_settings_uses_env_json_fallback(monkeypatch):
    # No file path configured at all - only the raw JSON content env var.
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-456")
    get_settings.cache_clear()

    client = build_sheets_client_from_settings()
    assert client is not None
    assert client.service_account_file == ""
    assert client.service_account_json == '{"type": "service_account"}'
    assert client.spreadsheet_id == "sheet-456"
    get_settings.cache_clear()


def test_sheets_client_connect_uses_file_path_when_present(tmp_path, monkeypatch):
    import json

    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")

    captured = {}

    class FakeCredentials:
        @staticmethod
        def from_service_account_info(info, scopes):
            captured["info"] = info
            return "fake-creds"

    class FakeGspreadClient:
        def open_by_key(self, key):
            raise RuntimeError("stop here - we only care that credentials loaded correctly")

    def fake_authorize(creds):
        return FakeGspreadClient()

    import gspread as real_gspread

    monkeypatch.setattr(real_gspread, "authorize", fake_authorize)

    from app.sheets.sync import SheetsClient

    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials", FakeCredentials, raising=False
    )

    client = SheetsClient(service_account_file=str(key_file), spreadsheet_id="sheet-1")
    try:
        client._connect()
    except RuntimeError:
        pass  # expected - we stop before actually calling the real Sheets API

    assert captured["info"] == {"type": "service_account"}


def test_sheets_client_connect_falls_back_to_env_json(monkeypatch):
    import json

    captured = {}

    class FakeCredentials:
        @staticmethod
        def from_service_account_info(info, scopes):
            captured["info"] = info
            return "fake-creds"

    class FakeGspreadClient:
        def open_by_key(self, key):
            raise RuntimeError("stop here - we only care that credentials loaded correctly")

    def fake_authorize(creds):
        return FakeGspreadClient()

    import gspread as real_gspread

    monkeypatch.setattr(real_gspread, "authorize", fake_authorize)
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials", FakeCredentials, raising=False
    )

    from app.sheets.sync import SheetsClient

    client = SheetsClient(
        service_account_file="",
        service_account_json=json.dumps({"type": "service_account", "client_email": "x@y.com"}),
        spreadsheet_id="sheet-1",
    )
    try:
        client._connect()
    except RuntimeError:
        pass

    assert captured["info"]["client_email"] == "x@y.com"
