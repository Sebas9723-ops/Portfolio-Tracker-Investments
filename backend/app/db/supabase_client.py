from supabase import create_client, Client
from functools import lru_cache
from app.config import get_settings


@lru_cache
def get_admin_client() -> Client:
    """Service-role client — bypasses RLS. Use for server-side operations."""
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)


@lru_cache
def get_anon_client() -> Client:
    """Anon client — respects RLS. Use for user-scoped auth flows."""
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_ANON_KEY)
