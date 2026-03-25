from __future__ import annotations

from functools import lru_cache

from django.conf import settings

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover
    Client = object  # type: ignore[assignment]
    create_client = None


def is_supabase_configured() -> bool:
    return bool(
        settings.SUPABASE_URL
        and settings.SUPABASE_SERVER_KEY
        and settings.SUPABASE_BUCKET
        and create_client
    )


@lru_cache(maxsize=1)
def get_supabase_client() -> Client | None:
    if not is_supabase_configured():
        return None
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVER_KEY)
