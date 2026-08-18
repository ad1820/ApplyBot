import pytest

from tests.fake_supabase import FakeSupabaseClient


@pytest.fixture
def fake_client() -> FakeSupabaseClient:
    return FakeSupabaseClient()
