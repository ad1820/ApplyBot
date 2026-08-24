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


# ─── New multi-provider chain config fields ───────────────────────────────────

def test_gemini_fields_default_empty_key_with_model_defaults():
    settings = Settings(_env_file=None)
    assert settings.gemini_api_key == ""
    assert settings.gemini_primary_model == "gemini-3.5-flash-lite"
    assert settings.gemini_fallback_model == "gemini-3.1-flash-lite"


def test_nvidia_nim_fields_default_empty_key_with_model_default():
    settings = Settings(_env_file=None)
    assert settings.nvidia_nim_api_key == ""
    assert settings.nvidia_nim_model == "meta/muse-glimmer-30b"


def test_groq_fields_default_empty():
    settings = Settings(_env_file=None)
    assert settings.groq_api_key == ""
    assert settings.groq_models == ""


def test_gemini_fields_can_be_set():
    settings = Settings(
        _env_file=None,
        gemini_api_key="my-key",
        gemini_primary_model="gemini-3.5-flash-lite",
        gemini_fallback_model="gemini-3.1-flash-lite",
    )
    assert settings.gemini_api_key == "my-key"
    assert settings.gemini_primary_model == "gemini-3.5-flash-lite"
    assert settings.gemini_fallback_model == "gemini-3.1-flash-lite"


def test_nvidia_nim_model_can_be_overridden():
    settings = Settings(_env_file=None, nvidia_nim_api_key="nk", nvidia_nim_model="some/other-model")
    assert settings.nvidia_nim_model == "some/other-model"


def test_groq_multi_model_field():
    settings = Settings(_env_file=None, groq_api_key="gk", groq_models="openai/gpt-oss-120b,openai/gpt-oss-20b")
    assert settings.groq_models == "openai/gpt-oss-120b,openai/gpt-oss-20b"


def test_no_anthropic_fields_on_settings():
    """Anthropic has been fully removed — Settings must not have any Anthropic fields."""
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "anthropic_api_key")
    assert not hasattr(settings, "anthropic_model")

