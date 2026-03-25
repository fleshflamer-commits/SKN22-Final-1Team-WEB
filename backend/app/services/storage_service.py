from __future__ import annotations

import mimetypes
import uuid
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from storage3.types import CreateOrUpdateBucketOptions

from app.services.supabase_client import get_supabase_client


def _guess_mime(filename: str, default: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or default


@lru_cache(maxsize=1)
def ensure_supabase_bucket() -> bool:
    if not settings.SUPABASE_USE_REMOTE_STORAGE:
        return False

    client = get_supabase_client()
    if client is None:
        return False

    options = CreateOrUpdateBucketOptions(
        public=settings.SUPABASE_BUCKET_PUBLIC,
        file_size_limit=settings.SUPABASE_BUCKET_FILE_SIZE_LIMIT,
        allowed_mime_types=settings.SUPABASE_ALLOWED_MIME_TYPES,
    )
    try:
        client.storage.get_bucket(settings.SUPABASE_BUCKET)
        client.storage.update_bucket(settings.SUPABASE_BUCKET, options)
    except Exception:
        client.storage.create_bucket(settings.SUPABASE_BUCKET, options=options)
    return True


def _store_locally(
    *,
    original_name: str,
    original_bytes: bytes,
    processed_bytes: bytes,
    original_ext: str,
    deidentified_bytes: bytes | None = None,
) -> tuple[str, str, str, str | None]:
    filename_root = str(uuid.uuid4())
    original_filename = f"{filename_root}{original_ext}"
    processed_filename = f"{filename_root}.processed.jpg"
    deidentified_filename = f"{filename_root}.deidentified.jpg"

    capture_dir = Path(settings.MEDIA_ROOT) / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)

    original_path = capture_dir / original_filename
    processed_path = capture_dir / processed_filename
    original_path.write_bytes(original_bytes)
    processed_path.write_bytes(processed_bytes)
    deidentified_path = None
    if deidentified_bytes:
        deidentified_path = capture_dir / deidentified_filename
        deidentified_path.write_bytes(deidentified_bytes)

    return original_filename, str(original_path), str(processed_path), (str(deidentified_path) if deidentified_path else None)


def _store_in_supabase(
    *,
    original_name: str,
    original_bytes: bytes,
    processed_bytes: bytes,
    original_ext: str,
    deidentified_bytes: bytes | None = None,
) -> tuple[str, str, str, str | None] | None:
    if not settings.SUPABASE_USE_REMOTE_STORAGE:
        return None

    client = get_supabase_client()
    if client is None:
        return None
    ensure_supabase_bucket()

    filename_root = str(uuid.uuid4())
    original_filename = f"{filename_root}{original_ext}"
    processed_filename = f"{filename_root}.processed.jpg"
    deidentified_filename = f"{filename_root}.deidentified.jpg"
    original_key = f"captures/{original_filename}"
    processed_key = f"captures/{processed_filename}"
    deidentified_key = f"captures/{deidentified_filename}"

    bucket = client.storage.from_(settings.SUPABASE_BUCKET)
    bucket.upload(
        original_key,
        original_bytes,
        file_options={"content-type": _guess_mime(original_name, "application/octet-stream")},
    )
    bucket.upload(
        processed_key,
        processed_bytes,
        file_options={"content-type": "image/jpeg"},
    )
    stored_deidentified_key = None
    if deidentified_bytes:
        bucket.upload(
            deidentified_key,
            deidentified_bytes,
            file_options={"content-type": "image/jpeg"},
        )
        stored_deidentified_key = deidentified_key
    return original_filename, original_key, processed_key, stored_deidentified_key


def resolve_storage_reference(reference: str | None) -> str | None:
    if not reference:
        return reference

    if reference.startswith(("http://", "https://", "/")):
        return reference

    if not settings.SUPABASE_USE_REMOTE_STORAGE:
        return reference

    client = get_supabase_client()
    if client is None:
        return reference

    bucket = client.storage.from_(settings.SUPABASE_BUCKET)
    if settings.SUPABASE_BUCKET_PUBLIC:
        return bucket.get_public_url(reference)

    signed = bucket.create_signed_url(reference, settings.SUPABASE_SIGNED_URL_EXPIRES_IN)
    if isinstance(signed, dict):
        return signed.get("signedURL") or signed.get("signedUrl") or reference
    return getattr(signed, "signedURL", None) or getattr(signed, "signedUrl", None) or reference


def store_capture_assets(
    *,
    original_name: str,
    original_bytes: bytes,
    processed_bytes: bytes,
    original_ext: str,
    deidentified_bytes: bytes | None = None,
) -> tuple[str, str, str, str | None]:
    remote_result = _store_in_supabase(
        original_name=original_name,
        original_bytes=original_bytes,
        processed_bytes=processed_bytes,
        original_ext=original_ext,
        deidentified_bytes=deidentified_bytes,
    )
    if remote_result:
        return remote_result
    return _store_locally(
        original_name=original_name,
        original_bytes=original_bytes,
        processed_bytes=processed_bytes,
        original_ext=original_ext,
        deidentified_bytes=deidentified_bytes,
    )
