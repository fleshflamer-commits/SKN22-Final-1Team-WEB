from __future__ import annotations

import json
from urllib import error, parse, request

from django.conf import settings


def verify_business_number(*, business_number: str) -> dict:
    api_url = (getattr(settings, "BUSINESS_VERIFICATION_API_URL", "") or "").strip()
    service_key = (getattr(settings, "BUSINESS_VERIFICATION_SERVICE_KEY", "") or "").strip()
    if not api_url or not service_key:
        return {
            "verification_status": "checksum_only",
            "verified": None,
            "source": "local_checksum",
            "message": "External business verification API is not configured.",
        }

    payload = json.dumps({"b_no": [business_number]}).encode("utf-8")
    query = parse.urlencode({"serviceKey": service_key, "returnType": "JSON"})
    req = request.Request(
        url=f"{api_url}?{query}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "verification_status": "api_error",
            "verified": None,
            "source": "nts_status_api",
            "message": str(exc),
        }

    data_rows = parsed.get("data") or []
    first_row = data_rows[0] if data_rows else {}
    tax_type = (first_row.get("tax_type") or "").strip()
    business_status = (first_row.get("b_stt") or first_row.get("b_stt_cd") or "").strip()
    closed_date = (first_row.get("end_dt") or "").strip()
    is_valid = bool(first_row) and not closed_date and business_status not in {"폐업", "휴업"}

    return {
        "verification_status": ("verified" if is_valid else "rejected"),
        "verified": is_valid,
        "source": "nts_status_api",
        "message": (tax_type or business_status or "verified" if is_valid else "status rejected"),
        "raw": first_row,
    }
