from app.config import Settings


def test_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "null"
    assert settings.app_timezone == "UTC"
    assert settings.supabase_configured() is False
    assert settings.telegram_configured() is False


def test_settings_configured_flags():
    settings = Settings(_env_file=None, supabase_url="https://x.supabase.co", supabase_key="key", telegram_bot_token="token")
    assert settings.supabase_configured() is True
    assert settings.telegram_configured() is True


def test_supabase_url_strips_trailing_slash():
    settings = Settings(_env_file=None, supabase_url="https://x.supabase.co/", supabase_key="key")
    assert settings.supabase_url == "https://x.supabase.co"


def test_supabase_url_strips_accidental_rest_v1_suffix():
    settings = Settings(_env_file=None, supabase_url="https://x.supabase.co/rest/v1", supabase_key="key")
    assert settings.supabase_url == "https://x.supabase.co"


def test_supabase_url_strips_accidental_rest_v1_suffix_with_trailing_slash():
    settings = Settings(_env_file=None, supabase_url="https://x.supabase.co/rest/v1/", supabase_key="key")
    assert settings.supabase_url == "https://x.supabase.co"
