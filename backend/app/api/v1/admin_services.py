import json
import os
import re
from collections import Counter
from urllib import error, request

from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Count, Q
from django.utils import timezone

from app.api.v1.admin_auth import TOKEN_MAX_AGE_SECONDS, build_admin_token
from app.api.v1.recommendation_logic import STYLE_CATALOG
from app.api.v1.services_django import (
    ensure_catalog_styles,
    get_latest_analysis,
    get_latest_capture_attempt,
    get_latest_survey,
    serialize_recommendation_row,
)
from app.models_django import AdminAccount, CaptureRecord, ConsultationRequest, Client, ClientSessionNote, FormerRecommendation, Style, StyleSelection
from app.services.age_profile import build_client_age_profile
from app.services.business_verification import verify_business_number
from app.services.storage_service import resolve_storage_reference


def _normalize_phone(value: str) -> str:
    return value.replace("-", "").strip()


def _normalize_business_number(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _format_business_number(value: str) -> str:
    return f"{value[:3]}-{value[3:5]}-{value[5:]}"


def _is_valid_business_number(value: str) -> bool:
    if len(value) != 10 or not value.isdigit():
        return False

    digits = [int(char) for char in value]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    checksum = sum(digit * weight for digit, weight in zip(digits[:9], weights))
    checksum += (digits[8] * 5) // 10
    expected = (10 - (checksum % 10)) % 10
    return digits[9] == expected


def _business_number_variants(value: str) -> set[str]:
    normalized = _normalize_business_number(value)
    if len(normalized) != 10:
        return {value}
    return {normalized, _format_business_number(normalized)}


def _ai_health() -> dict:
    base_url = os.environ.get("MIRRAI_AI_SERVICE_URL", "").rstrip("/")
    if not base_url:
        return {
            "status": "fallback",
            "mode": "local",
            "message": "AI service URL is not configured. Local fallback is active.",
            "checked_at": timezone.now(),
        }

    try:
        with request.urlopen(f"{base_url}/internal/health", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "status": "online",
            "mode": "remote",
            "message": payload.get("role", "ai-microservice"),
            "checked_at": timezone.now(),
        }
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "status": "offline",
            "mode": "remote",
            "message": str(exc),
            "checked_at": timezone.now(),
        }


def _serialize_survey(survey) -> dict | None:
    if not survey:
        return None
    return {
        "target_length": survey.target_length,
        "target_vibe": survey.target_vibe,
        "scalp_type": survey.scalp_type,
        "hair_colour": survey.hair_colour,
        "budget_range": survey.budget_range,
        "preference_vector": survey.preference_vector or [],
        "created_at": survey.created_at,
    }


def _serialize_analysis(analysis) -> dict | None:
    if not analysis:
        return None
    return {
        "face_shape": analysis.face_shape,
        "golden_ratio_score": analysis.golden_ratio_score,
        "image_url": resolve_storage_reference(analysis.image_url),
        "landmark_snapshot": analysis.landmark_snapshot,
        "created_at": analysis.created_at,
    }


def _serialize_capture(record: CaptureRecord) -> dict:
    privacy_snapshot = record.privacy_snapshot or {}
    return {
        "record_id": record.id,
        "status": record.status,
        "face_count": record.face_count,
        "landmark_snapshot": record.landmark_snapshot,
        "deidentified_image_url": resolve_storage_reference(record.deidentified_path),
        "privacy_snapshot": privacy_snapshot,
        "image_storage_policy": privacy_snapshot.get("storage_policy", "asset_store"),
        "error_note": record.error_note,
        "original_image_url": resolve_storage_reference(record.original_path),
        "processed_image_url": resolve_storage_reference(record.processed_path),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _style_snapshot(style_id: int) -> dict:
    styles_by_id = ensure_catalog_styles()
    style = styles_by_id.get(style_id) or Style.objects.filter(id=style_id).first()
    if not style:
        return {
            "style_id": style_id,
            "style_name": f"Style {style_id}",
            "image_url": None,
            "description": "",
            "keywords": [],
        }

    profile = next((item for item in STYLE_CATALOG if item.style_id == style_id), None)
    keywords = list(profile.keywords) if profile else ([style.vibe] if style.vibe else [])
    return {
        "style_id": style.id,
        "style_name": style.name,
        "image_url": resolve_storage_reference(style.image_url),
        "description": style.description or "",
        "keywords": keywords,
    }


def _style_catalog_profile(style_id: int):
    return next((item for item in STYLE_CATALOG if item.style_id == style_id), None)


def _budget_tags_to_price_range(budget_tags: tuple[str, ...] | list[str] | None) -> str | None:
    if not budget_tags:
        return None
    normalized = list(budget_tags)
    if normalized == ["low"]:
        return "5만원 이하"
    if normalized == ["mid"]:
        return "5~10만원"
    if normalized == ["high"]:
        return "10만원 이상"
    if normalized == ["low", "mid"]:
        return "5~10만원"
    if normalized == ["mid", "high"]:
        return "8~15만원"
    return " / ".join(normalized)


def _style_tags_to_length(length_tags: tuple[str, ...] | list[str] | None) -> str | None:
    if not length_tags:
        return None
    mapping = {
        "short": "숏",
        "bob": "보브",
        "medium": "중단발",
        "long": "롱",
    }
    return ", ".join(mapping.get(tag, tag) for tag in length_tags)


def _serialize_frontend_style(
    *,
    style_id: int,
    match_score: float | None = None,
    description_override: str | None = None,
    analysis=None,
) -> dict:
    style_data = _style_snapshot(style_id)
    profile = _style_catalog_profile(style_id)
    face_ratio_data = {
        "golden": (
            f"{analysis.golden_ratio_score:.2f}"
            if analysis is not None and analysis.golden_ratio_score is not None
            else None
        ),
        "forehead": (", ".join(profile.ratio_modes) if profile else None),
        "jaw": (", ".join(profile.vibe_tags) if profile else None),
        "suitableFaces": list(profile.face_shapes) if profile else [],
    }
    return {
        "id": style_id,
        "hairstyleId": style_id,
        "universalName": profile.fallback_name if profile else style_data["style_name"],
        "koreanName": style_data["style_name"],
        "keywords": style_data["keywords"],
        "matchRate": int(round(match_score or 0)),
        "description": description_override or style_data["description"],
        "faceRatioData": face_ratio_data,
        "priceRange": _budget_tags_to_price_range(profile.budget_tags if profile else None),
        "length": _style_tags_to_length(profile.length_tags if profile else None),
        "gender": "unisex",
        "imageUrl": style_data["image_url"],
        "image_url": style_data["image_url"],
    }


def _serialize_recommendation(row: FormerRecommendation) -> dict:
    return serialize_recommendation_row(row)


def _serialize_style_selection(selection: StyleSelection) -> dict:
    style_snapshot = _style_snapshot(selection.style_id)
    return {
        "selection_id": selection.id,
        "style_id": selection.style_id,
        "style_name": style_snapshot["style_name"],
        "image_url": style_snapshot["image_url"],
        "description": style_snapshot["description"],
        "source": selection.source,
        "match_score": selection.match_score,
        "is_sent_to_admin": selection.is_sent_to_admin,
        "created_at": selection.created_at,
    }


def _serialize_admin_profile(admin: AdminAccount) -> dict:
    formatted_business_number = (
        _format_business_number(admin.business_number)
        if len(admin.business_number) == 10 and admin.business_number.isdigit()
        else admin.business_number
    )
    return {
        "admin_id": admin.id,
        "id": admin.id,
        "name": admin.name,
        "display_name": admin.name,
        "displayName": admin.name,
        "store_name": admin.store_name,
        "storeName": admin.store_name,
        "role": admin.role,
        "phone": admin.phone,
        "business_number": formatted_business_number,
        "businessNumber": formatted_business_number,
        "business_verification_status": admin.business_verification_status,
        "businessVerificationStatus": admin.business_verification_status,
        "business_verification_snapshot": admin.business_verification_snapshot or {},
        "consent_snapshot": admin.consent_snapshot or {},
        "consented_at": admin.consented_at,
        "is_active": admin.is_active,
        "created_at": admin.created_at,
    }


def _client_age_fields(client: Client) -> dict:
    profile = build_client_age_profile(client) or {}
    return {
        "age": profile.get("current_age"),
        "age_decade": profile.get("age_decade"),
        "age_segment": profile.get("age_segment"),
        "age_group": profile.get("age_group"),
    }


def _admin_client_ids(admin: AdminAccount | None) -> set[int] | None:
    if admin is None:
        return None

    client_ids = set(
        ConsultationRequest.objects.filter(admin=admin).values_list("client_id", flat=True)
    )
    client_ids.update(
        ClientSessionNote.objects.filter(admin=admin).values_list("client_id", flat=True)
    )
    return client_ids


def _scoped_client_queryset(*, admin: AdminAccount | None = None):
    if admin is None:
        return Client.objects.all()

    client_ids = _admin_client_ids(admin)
    return Client.objects.filter(id__in=client_ids)


def _scoped_consultation_queryset(*, admin: AdminAccount | None = None):
    if admin is None:
        return ConsultationRequest.objects.all()

    return ConsultationRequest.objects.filter(admin=admin)


def _is_new_client(client: Client) -> bool:
    return timezone.now() - client.created_at <= timezone.timedelta(days=30)


def _format_visit_date(value) -> str | None:
    if value is None:
        return None
    return timezone.localtime(value).date().isoformat()


def _latest_client_activity_at(*, client: Client, admin: AdminAccount | None = None):
    consultation_queryset = client.consultations
    if admin is not None:
        consultation_queryset = consultation_queryset.filter(admin=admin)

    timestamps = [
        consultation_queryset.order_by("-created_at").values_list("created_at", flat=True).first(),
        client.captures.order_by("-created_at").values_list("created_at", flat=True).first(),
        client.style_selections.order_by("-created_at").values_list("created_at", flat=True).first(),
    ]
    timestamps = [value for value in timestamps if value is not None]
    if not timestamps:
        return client.created_at
    return max(timestamps)


def _latest_note(*, client: Client, admin: AdminAccount | None = None):
    queryset = ClientSessionNote.objects.filter(client=client).select_related("admin")
    if admin is not None:
        queryset = queryset.filter(admin=admin)
    return queryset.order_by("-created_at").first()


def _resolve_today_style(*, client: Client, latest_consultation=None):
    latest_selection = client.style_selections.order_by("-created_at").first()
    if latest_selection:
        style_snapshot = _style_snapshot(latest_selection.style_id)
        return {
            "style_id": latest_selection.style_id,
            "style_name": style_snapshot["style_name"],
        }

    if latest_consultation and latest_consultation.selected_style_id:
        style_snapshot = _style_snapshot(latest_consultation.selected_style_id)
        return {
            "style_id": latest_consultation.selected_style_id,
            "style_name": style_snapshot["style_name"],
        }

    if latest_consultation and latest_consultation.selected_recommendation:
        row = latest_consultation.selected_recommendation
        return {
            "style_id": row.style_id_snapshot,
            "style_name": row.style_name_snapshot,
        }

    return {"style_id": None, "style_name": None}


def _latest_confirmed_selection(*, client: Client):
    return (
        client.style_selections.filter(is_sent_to_admin=True)
        .order_by("-created_at")
        .first()
    )


def _latest_generated_batch_row(*, client: Client):
    return (
        FormerRecommendation.objects.filter(client=client, source__in=["generated", "survey_only"])
        .order_by("-created_at")
        .first()
    )


def _build_client_interaction_state(*, client: Client, admin: AdminAccount | None = None, latest_consultation=None) -> dict:
    if latest_consultation is None:
        consultation_queryset = client.consultations
        if admin is not None:
            consultation_queryset = consultation_queryset.filter(admin=admin)
        latest_consultation = consultation_queryset.order_by("-created_at").first()

    latest_capture_attempt = get_latest_capture_attempt(client)
    latest_survey = get_latest_survey(client)
    latest_batch = _latest_generated_batch_row(client=client)
    latest_selection = _latest_confirmed_selection(client=client)

    current_step = "client_input"
    interaction_status = "awaiting_client_input"
    interaction_status_label = "입력 대기"
    capture_required_for_full_result = False

    if latest_consultation and latest_consultation.is_active:
        current_step = "consultation"
        if latest_consultation.status == "IN_PROGRESS":
            interaction_status = "consultation_in_progress"
            interaction_status_label = "상담 진행 중"
        else:
            interaction_status = "confirmed_waiting_admin"
            interaction_status_label = "관리자 상담 대기"
    elif latest_consultation and latest_consultation.status == "CANCELLED":
        current_step = "client_input"
        interaction_status = "selection_cancelled"
        interaction_status_label = "스타일 취소 후 입력 단계 복귀"
    elif latest_consultation and latest_consultation.status == "CLOSED":
        current_step = "completed"
        interaction_status = "consultation_closed"
        interaction_status_label = "상담 종료"
    elif latest_selection is not None:
        current_step = "consultation"
        interaction_status = "style_confirmed"
        interaction_status_label = "스타일 확정"
    elif latest_capture_attempt is not None and latest_capture_attempt.status in {"NEEDS_RETAKE", "FAILED"}:
        current_step = "capture"
        interaction_status = "needs_retake"
        interaction_status_label = "재촬영 필요"
    elif latest_batch is not None:
        current_step = "recommendation"
        if latest_batch.source == "survey_only":
            interaction_status = "survey_recommendations_ready"
            interaction_status_label = "설문 기반 추천 준비"
            capture_required_for_full_result = True
        else:
            interaction_status = "recommendations_ready"
            interaction_status_label = "추천 결과 확인 가능"
    elif latest_capture_attempt is not None and latest_capture_attempt.status == "DONE":
        current_step = "capture"
        interaction_status = "capture_complete"
        interaction_status_label = "촬영 완료"
    elif latest_survey is not None:
        current_step = "survey"
        interaction_status = "survey_complete"
        interaction_status_label = "설문 완료"

    return {
        "current_step": current_step,
        "currentStep": current_step,
        "interaction_status": interaction_status,
        "interactionStatus": interaction_status,
        "interaction_status_label": interaction_status_label,
        "interactionStatusLabel": interaction_status_label,
        "consultation_status": (latest_consultation.status if latest_consultation else None),
        "consultationStatus": (latest_consultation.status if latest_consultation else None),
        "capture_required_for_full_result": capture_required_for_full_result,
        "captureRequiredForFullResult": capture_required_for_full_result,
    }


def _build_admin_survey_results(*, survey, survey_snapshot: dict | None = None) -> dict:
    survey_snapshot = survey_snapshot or {}
    preferences = survey_snapshot.get("preferences")
    if not isinstance(preferences, list):
        preferences = []
    return {
        "preferences": preferences,
        "length": survey.target_length if survey else survey_snapshot.get("target_length"),
        "budget": survey.budget_range if survey else survey_snapshot.get("budget_range"),
        "occasion": survey_snapshot.get("occasion"),
        "atmosphere": survey.target_vibe if survey else survey_snapshot.get("target_vibe"),
    }


def _serialize_recommendation_history_item(selection: StyleSelection, *, admin: AdminAccount | None = None) -> dict:
    style_snapshot = _style_snapshot(selection.style_id)
    consultation_queryset = ConsultationRequest.objects.filter(client=selection.client, selected_style_id=selection.style_id).select_related("admin")
    if admin is not None:
        consultation_queryset = consultation_queryset.filter(admin=admin)
    latest_consultation = consultation_queryset.order_by("-created_at").first()
    note_queryset = ClientSessionNote.objects.filter(client=selection.client)
    if latest_consultation:
        note_queryset = note_queryset.filter(consultation=latest_consultation)
    if admin is not None:
        note_queryset = note_queryset.filter(admin=admin)
    latest_note = note_queryset.order_by("-created_at").first()
    stylist_name = None
    if latest_consultation and latest_consultation.admin:
        stylist_name = latest_consultation.admin.name
    elif latest_note and latest_note.admin:
        stylist_name = latest_note.admin.name

    return {
        "date": _format_visit_date(selection.created_at),
        "styleName": style_snapshot["style_name"],
        "stylist": stylist_name or "MirrAI Admin",
        "result": "확정" if selection.is_sent_to_admin else "추천",
        "note": latest_note.content if latest_note else None,
    }


def _serialize_admin_client_card(*, client: Client, admin: AdminAccount | None = None) -> dict:
    latest_analysis = get_latest_analysis(client)
    latest_survey = get_latest_survey(client)
    consultation_queryset = client.consultations
    if admin is not None:
        consultation_queryset = consultation_queryset.filter(admin=admin)
    latest_consultation = consultation_queryset.order_by("-created_at").first()
    latest_note = _latest_note(client=client, admin=admin)
    today_style = _resolve_today_style(client=client, latest_consultation=latest_consultation)
    age_fields = _client_age_fields(client)
    interaction_state = _build_client_interaction_state(
        client=client,
        admin=admin,
        latest_consultation=latest_consultation,
    )
    return {
        "client_id": client.id,
        "id": client.id,
        "name": client.name,
        "phone": client.phone,
        "gender": client.gender,
        **age_fields,
        "is_new_client": _is_new_client(client),
        "isNew": _is_new_client(client),
        "face_shape": latest_analysis.face_shape if latest_analysis else None,
        "faceShape": latest_analysis.face_shape if latest_analysis else None,
        "golden_ratio": latest_analysis.golden_ratio_score if latest_analysis else None,
        "goldenRatio": latest_analysis.golden_ratio_score if latest_analysis else None,
        "last_visit": _format_visit_date(_latest_client_activity_at(client=client, admin=admin)),
        "lastVisit": _format_visit_date(_latest_client_activity_at(client=client, admin=admin)),
        "today_recommendation_id": today_style["style_id"],
        "todayRecommendationId": today_style["style_id"],
        "today_recommendation_name": today_style["style_name"],
        "todayRecommendationName": today_style["style_name"],
        "designer_note": latest_note.content if latest_note else "",
        "designerNote": latest_note.content if latest_note else "",
        "survey_results": _build_admin_survey_results(
            survey=latest_survey,
            survey_snapshot=(latest_consultation.survey_snapshot if latest_consultation else None),
        ),
        "surveyResults": _build_admin_survey_results(
            survey=latest_survey,
            survey_snapshot=(latest_consultation.survey_snapshot if latest_consultation else None),
        ),
        "created_at": client.created_at,
        "has_active_consultation": consultation_queryset.filter(is_active=True).exists(),
        "hasActiveConsultation": consultation_queryset.filter(is_active=True).exists(),
        **interaction_state,
    }


def get_admin_profile(*, admin: AdminAccount) -> dict:
    return {
        "status": "success",
        "is_authenticated": True,
        "next_action": "admin_dashboard",
        "admin": _serialize_admin_profile(admin),
    }


def register_admin(*, payload: dict) -> dict:
    phone = _normalize_phone(payload["phone"])
    business_number = _normalize_business_number(payload["business_number"])
    consent_snapshot = {
        "agree_terms": bool(payload.get("agree_terms")),
        "agree_privacy": bool(payload.get("agree_privacy")),
        "agree_third_party_sharing": bool(payload.get("agree_third_party_sharing")),
        "agree_marketing": bool(payload.get("agree_marketing", False)),
    }

    if AdminAccount.objects.filter(phone=phone).exists():
        raise ValueError("This phone number is already registered for an admin account.")
    if not _is_valid_business_number(business_number):
        raise ValueError("The business registration number is not valid.")
    if AdminAccount.objects.filter(Q(business_number__in=_business_number_variants(business_number))).exists():
        raise ValueError("This business registration number is already registered.")
    verification_snapshot = verify_business_number(business_number=business_number)
    if verification_snapshot["verification_status"] == "rejected":
        raise ValueError("The business registration number failed external verification.")

    admin = AdminAccount.objects.create(
        name=payload["name"],
        store_name=payload["store_name"],
        role=payload.get("role", "owner"),
        phone=phone,
        business_number=business_number,
        password_hash=make_password(payload["password"]),
        business_verification_status=verification_snapshot["verification_status"],
        business_verification_snapshot=verification_snapshot,
        consent_snapshot=consent_snapshot,
        consented_at=timezone.now(),
    )
    token = build_admin_token(admin=admin)
    return {
        "status": "success",
        "admin_id": admin.id,
        "admin": _serialize_admin_profile(admin),
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_MAX_AGE_SECONDS,
    }


def login_admin(*, phone: str, password: str) -> dict:
    phone = _normalize_phone(phone)
    admin = AdminAccount.objects.filter(phone=phone, is_active=True).first()
    if not admin or not check_password(password, admin.password_hash):
        raise ValueError("Please check the admin account credentials and try again.")
    token = build_admin_token(admin=admin)
    return {
        "status": "success",
        "admin": _serialize_admin_profile(admin),
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_MAX_AGE_SECONDS,
    }


def _today_client_ids(*, admin: AdminAccount | None = None) -> set[int]:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    clients = _scoped_client_queryset(admin=admin)
    capture_ids = set(clients.filter(captures__created_at__gte=start).values_list("id", flat=True))
    consult_ids = set(clients.filter(consultations__created_at__gte=start).values_list("id", flat=True))
    return capture_ids | consult_ids


def _latest_active_consultations(*, admin: AdminAccount | None = None) -> list[ConsultationRequest]:
    rows = _scoped_consultation_queryset(admin=admin).filter(is_active=True).select_related("client", "selected_style", "selected_recommendation").order_by("-created_at")
    seen: set[int] = set()
    latest_rows: list[ConsultationRequest] = []
    for row in rows:
        if row.client_id in seen:
            continue
        seen.add(row.client_id)
        latest_rows.append(row)
    return latest_rows


def get_admin_dashboard_summary(*, admin: AdminAccount | None = None) -> dict:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    styles_by_id = ensure_catalog_styles()
    admin_client_ids = _admin_client_ids(admin)
    style_selection_queryset = StyleSelection.objects.filter(created_at__gte=start, is_sent_to_admin=True)
    if admin is not None:
        style_selection_queryset = style_selection_queryset.filter(client_id__in=admin_client_ids)
    top_rows = (
        style_selection_queryset
        .values("style_id")
        .annotate(selection_count=Count("id"))
        .order_by("-selection_count", "style_id")[:5]
    )
    top_styles = []
    for row in top_rows:
        style = styles_by_id.get(row["style_id"]) or Style.objects.filter(id=row["style_id"]).first()
        top_styles.append(
            {
                "style_id": row["style_id"],
                "style_name": style.name if style else f"Style {row['style_id']}",
                "image_url": resolve_storage_reference(style.image_url) if style else None,
                "selection_count": row["selection_count"],
            }
        )

    active_consultations = _latest_active_consultations(admin=admin)
    active_preview = [
        {
            "consultation_id": row.id,
            "client_id": row.client_id,
            "client_name": row.client.name,
            "phone": row.client.phone,
            "has_unread_consultation": not row.is_read,
            "status": row.status,
            "selected_style_name": row.selected_style.name if row.selected_style else None,
            "created_at": row.created_at,
            **_build_client_interaction_state(client=row.client, admin=admin, latest_consultation=row),
        }
        for row in active_consultations[:5]
    ]
    closed_consultations = _scoped_consultation_queryset(admin=admin).filter(
        status="CLOSED",
        closed_at__gte=start,
    ).count()
    today_summary = {
        "total_visits": len(_today_client_ids(admin=admin)),
        "new_clients": _scoped_client_queryset(admin=admin).filter(created_at__gte=start).count(),
        "recommendations_completed": style_selection_queryset.count(),
        "consultations_closed": closed_consultations,
    }
    summary_cards = [
        {"key": "total_visits", "label": "오늘 방문 고객", "value": today_summary["total_visits"]},
        {"key": "new_clients", "label": "신규 등록", "value": today_summary["new_clients"]},
        {"key": "recommendations_completed", "label": "추천 완료", "value": today_summary["recommendations_completed"]},
        {"key": "consultations_closed", "label": "상담 종료", "value": today_summary["consultations_closed"]},
    ]
    return {
        "status": "ready",
        "ai_engine": _ai_health(),
        "today_metrics": {
            "unique_visitors": len(_today_client_ids(admin=admin)),
            "active_clients": len(active_consultations),
            "pending_consultations": sum(1 for row in active_consultations if not row.is_read),
            "confirmed_styles": style_selection_queryset.count(),
        },
        "today_summary": today_summary,
        "todaySummary": today_summary,
        "summary_cards": summary_cards,
        "summaryCards": summary_cards,
        "top_styles_today": top_styles,
        "topStylesToday": top_styles,
        "active_clients_preview": active_preview,
        "activeClientsPreview": active_preview,
    }


def get_active_client_sessions(*, admin: AdminAccount | None = None) -> dict:
    items = []
    for row in _latest_active_consultations(admin=admin):
        recommendation_count = 0
        if row.selected_recommendation:
            recommendation_count = FormerRecommendation.objects.filter(
                client_id=row.client_id,
                batch_id=row.selected_recommendation.batch_id,
            ).count()
        items.append(
            {
                "consultation_id": row.id,
                "client_id": row.client_id,
                "client_name": row.client.name,
                "phone": row.client.phone,
                "status": row.status,
                "has_unread_consultation": not row.is_read,
                "selected_style_name": row.selected_style.name if row.selected_style else None,
                "recommendation_count": recommendation_count,
                "last_activity_at": row.created_at,
                **_build_client_interaction_state(client=row.client, admin=admin, latest_consultation=row),
            }
        )
    return {"status": "ready", "items": items}


def get_all_clients(*, query: str = "", admin: AdminAccount | None = None) -> dict:
    queryset = _scoped_client_queryset(admin=admin).order_by("name", "id")
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(phone__icontains=query))

    items = []
    for client in queryset[:100]:
        card = _serialize_admin_client_card(client=client, admin=admin)
        latest_consult_queryset = client.consultations
        if admin is not None:
            latest_consult_queryset = latest_consult_queryset.filter(admin=admin)
        latest_consult = latest_consult_queryset.order_by("-created_at").first()
        card.update(
            {
                "last_consulted_at": latest_consult.created_at if latest_consult else None,
            }
        )
        items.append(card)

    dashboard_summary = get_admin_dashboard_summary(admin=admin)
    return {
        "status": "ready",
        "query": query,
        "total_count": queryset.count(),
        "items": items,
        "summary": dashboard_summary["today_summary"],
        "top_styles": dashboard_summary["top_styles_today"][:3],
    }


def get_client_detail(*, client: Client, admin: AdminAccount | None = None) -> dict:
    scoped_client_ids = _admin_client_ids(admin)
    if admin is not None and client.id not in scoped_client_ids:
        raise ValueError("Client is outside the current admin scope.")

    latest_survey = get_latest_survey(client)
    latest_analysis = get_latest_analysis(client)
    consultation_queryset = client.consultations
    if admin is not None:
        consultation_queryset = consultation_queryset.filter(admin=admin)
    latest_consultation = consultation_queryset.order_by("-created_at").first()
    notes_queryset = ClientSessionNote.objects.filter(client=client).select_related("admin", "consultation")
    if admin is not None:
        notes_queryset = notes_queryset.filter(admin=admin)
    notes = notes_queryset.order_by("-created_at")[:20]
    capture_history = client.captures.order_by("-created_at")[:20]
    analysis_history = client.face_analyses.order_by("-created_at")[:20]
    selection_history = client.style_selections.order_by("-created_at")[:20]
    chosen_recommendations = FormerRecommendation.objects.filter(client=client, is_chosen=True).order_by("-chosen_at", "-created_at")[:20]
    latest_note = notes.first()
    today_style = _resolve_today_style(client=client, latest_consultation=latest_consultation)
    recommendation_history = [
        _serialize_recommendation_history_item(selection, admin=admin)
        for selection in selection_history[:10]
    ]
    client_summary = {
        **_serialize_admin_client_card(client=client, admin=admin),
        "total_sessions": consultation_queryset.count(),
        "totalSessions": consultation_queryset.count(),
        "last_visit": _format_visit_date(_latest_client_activity_at(client=client, admin=admin)),
        "lastVisit": _format_visit_date(_latest_client_activity_at(client=client, admin=admin)),
        "today_recommendation_id": today_style["style_id"],
        "todayRecommendationId": today_style["style_id"],
        "today_recommendation_name": today_style["style_name"],
        "todayRecommendationName": today_style["style_name"],
        "designer_note": latest_note.content if latest_note else "",
        "designerNote": latest_note.content if latest_note else "",
        "recommendation_history": recommendation_history,
        "recommendationHistory": recommendation_history,
    }

    return {
        "status": "ready",
        "client": {
            "client_id": client.id,
            "name": client.name,
            "gender": client.gender,
            "phone": client.phone,
            **_client_age_fields(client),
            "created_at": client.created_at,
        },
        "client_summary": client_summary,
        "clientSummary": client_summary,
        "latest_survey": _serialize_survey(latest_survey),
        "latest_analysis": _serialize_analysis(latest_analysis),
        "capture_history": [_serialize_capture(record) for record in capture_history],
        "analysis_history": [_serialize_analysis(analysis) for analysis in analysis_history],
        "style_selection_history": [_serialize_style_selection(selection) for selection in selection_history],
        "chosen_recommendation_history": [_serialize_recommendation(row) for row in chosen_recommendations],
        "recommendation_history": recommendation_history,
        "recommendationHistory": recommendation_history,
        "designer_note": latest_note.content if latest_note else "",
        "designerNote": latest_note.content if latest_note else "",
        "active_consultation": (
            {
                "consultation_id": latest_consultation.id,
                "status": latest_consultation.status,
                "is_active": latest_consultation.is_active,
                "is_read": latest_consultation.is_read,
                "source": latest_consultation.source,
                "created_at": latest_consultation.created_at,
                "closed_at": latest_consultation.closed_at,
                **_build_client_interaction_state(client=client, admin=admin, latest_consultation=latest_consultation),
            }
            if latest_consultation
            else None
        ),
        "notes": [
            {
                "note_id": note.id,
                "consultation_id": note.consultation_id,
                "admin_id": note.admin_id,
                "admin_name": note.admin.name if note.admin else None,
                "content": note.content,
                "created_at": note.created_at,
            }
            for note in notes
        ],
    }


def get_client_recommendation_report(*, client: Client, admin: AdminAccount | None = None) -> dict:
    scoped_client_ids = _admin_client_ids(admin)
    if admin is not None and client.id not in scoped_client_ids:
        raise ValueError("Client is outside the current admin scope.")

    latest_analysis = get_latest_analysis(client)
    latest_survey = get_latest_survey(client)
    recommendation_queryset = FormerRecommendation.objects.filter(client=client, source__in=["generated", "survey_only"])
    if admin is not None:
        recommendation_queryset = recommendation_queryset.filter(client_id__in=scoped_client_ids)
    latest_generated = recommendation_queryset.order_by("-created_at").first()
    batch_rows = []
    if latest_generated:
        batch_rows = list(FormerRecommendation.objects.filter(client=client, batch_id=latest_generated.batch_id).order_by("rank", "id"))
    final_selected = FormerRecommendation.objects.filter(client=client, is_chosen=True).order_by("-chosen_at", "-created_at").first()
    consultation_queryset = client.consultations
    if admin is not None:
        consultation_queryset = consultation_queryset.filter(admin=admin)
    latest_consultation = consultation_queryset.order_by("-created_at").first()
    recommendation_items = [_serialize_recommendation(row) for row in batch_rows]
    frontend_styles = [
        _serialize_frontend_style(
            style_id=row.style_id_snapshot,
            match_score=row.match_score,
            description_override=(row.llm_explanation or row.style_description_snapshot),
            analysis=latest_analysis,
        )
        for row in batch_rows
    ]
    primary_batch_row = batch_rows[0] if batch_rows else latest_generated
    today_style_id = None
    if final_selected:
        today_style_id = final_selected.style_id_snapshot
    elif primary_batch_row:
        today_style_id = primary_batch_row.style_id_snapshot
    today_style = (
        _serialize_frontend_style(
            style_id=today_style_id,
            match_score=(final_selected.match_score if final_selected else primary_batch_row.match_score if primary_batch_row else None),
            description_override=(final_selected.llm_explanation if final_selected else primary_batch_row.llm_explanation if primary_batch_row else None),
            analysis=latest_analysis,
        )
        if today_style_id is not None
        else None
    )
    survey_results = _build_admin_survey_results(
        survey=latest_survey,
        survey_snapshot=(latest_consultation.survey_snapshot if latest_consultation else None),
    )
    ai_profile = {
        "faceShape": latest_analysis.face_shape if latest_analysis else None,
        "face_shape": latest_analysis.face_shape if latest_analysis else None,
        "goldenRatio": latest_analysis.golden_ratio_score if latest_analysis else None,
        "golden_ratio": latest_analysis.golden_ratio_score if latest_analysis else None,
    }
    client_summary = {
        **_serialize_admin_client_card(client=client, admin=admin),
        "surveyResults": survey_results,
        "todayRecommendationId": today_style["id"] if today_style else None,
        "todayRecommendationName": today_style["koreanName"] if today_style else None,
    }
    recommendation_mode = latest_generated.source if latest_generated else None
    capture_required_for_full_result = bool(latest_generated and latest_generated.source == "survey_only")

    return {
        "status": ("ready" if recommendation_items else "empty"),
        "client": {
            "client_id": client.id,
            "name": client.name,
            "phone": client.phone,
            **_client_age_fields(client),
        },
        "client_summary": client_summary,
        "clientSummary": client_summary,
        "latest_survey": _serialize_survey(latest_survey),
        "surveyResults": survey_results,
        "latest_analysis": _serialize_analysis(latest_analysis),
        "ai_profile": ai_profile,
        "aiProfile": ai_profile,
        "final_selected_style": (_serialize_recommendation(final_selected) if final_selected else None),
        "today_style": today_style,
        "todayStyle": today_style,
        "recommended_styles": frontend_styles,
        "recommendedStyles": frontend_styles,
        "items": recommendation_items,
        "recommendation_mode": recommendation_mode,
        "recommendationMode": recommendation_mode,
        "capture_required_for_full_result": capture_required_for_full_result,
        "captureRequiredForFullResult": capture_required_for_full_result,
        "has_recommendations": bool(recommendation_items),
        "latest_generated_batch": {
            "batch_id": str(latest_generated.batch_id) if latest_generated else None,
            "items": recommendation_items,
        },
    }


def create_client_note(*, client: Client, consultation_id: int, content: str, admin: AdminAccount | None = None) -> dict:
    consultation = ConsultationRequest.objects.filter(id=consultation_id, client=client).first()
    if not consultation:
        raise ValueError("The consultation session could not be found.")
    if admin is not None and consultation.admin_id not in (None, admin.id):
        raise ValueError("The consultation session is outside the current admin scope.")

    if admin is not None and consultation.admin_id is None:
        consultation.admin = admin
        consultation.save(update_fields=["admin"])

    note = ClientSessionNote.objects.create(
        consultation=consultation,
        client=client,
        admin=admin,
        content=content.strip(),
    )
    consultation.is_read = True
    consultation.status = "IN_PROGRESS"
    consultation.save(update_fields=["is_read", "status"])
    return {
        "status": "success",
        "note_id": note.id,
        "consultation_id": consultation.id,
        "message": "The consultation note has been saved.",
    }


def close_consultation_session(*, consultation_id: int, admin: AdminAccount | None = None) -> dict:
    consultation = ConsultationRequest.objects.filter(id=consultation_id).select_related("client").first()
    if not consultation:
        raise ValueError("The consultation session could not be found.")
    if admin is not None and consultation.admin_id not in (None, admin.id):
        raise ValueError("The consultation session is outside the current admin scope.")

    if admin is not None and consultation.admin_id is None:
        consultation.admin = admin

    consultation.is_active = False
    consultation.is_read = True
    consultation.status = "CLOSED"
    consultation.closed_at = timezone.now()
    update_fields = ["is_active", "is_read", "status", "closed_at"]
    if admin is not None and consultation.admin_id == admin.id:
        update_fields.append("admin")
    consultation.save(update_fields=update_fields)
    return {
        "status": "success",
        "consultation_id": consultation.id,
        "client_id": consultation.client_id,
        "message": "The consultation session has been closed.",
    }


def _selection_matches_snapshot(selection: StyleSelection, filters: dict) -> bool:
    snapshot = selection.survey_snapshot or {}
    if not snapshot and hasattr(selection.client, "survey"):
        survey = selection.client.survey
        snapshot = {
            "target_length": survey.target_length,
            "target_vibe": survey.target_vibe,
            "scalp_type": survey.scalp_type,
            "hair_colour": survey.hair_colour,
            "budget_range": survey.budget_range,
        }
    age_profile = build_client_age_profile(selection.client) or snapshot.get("age_profile") or {}

    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key == "age_decade":
            if age_profile.get("age_decade") != value:
                return False
            continue
        if key == "age_segment":
            if age_profile.get("age_segment") != value:
                return False
            continue
        if key == "age_group":
            if age_profile.get("age_group") != value:
                return False
            continue
        if snapshot.get(key) != value:
            return False
    return True


def get_admin_trend_report(*, days: int = 7, filters: dict | None = None, admin: AdminAccount | None = None) -> dict:
    filters = filters or {}
    cutoff = timezone.now() - timezone.timedelta(days=days)
    selections_queryset = (
        StyleSelection.objects.filter(created_at__gte=cutoff, is_sent_to_admin=True)
        .select_related("client")
        .order_by("-created_at")
    )
    scoped_client_ids = _admin_client_ids(admin)
    if admin is not None:
        selections_queryset = selections_queryset.filter(client_id__in=scoped_client_ids)
    selections = list(selections_queryset)
    filtered = [row for row in selections if _selection_matches_snapshot(row, filters)]

    counter = Counter(row.style_id for row in filtered)
    ranking = []
    for rank, (style_id, count) in enumerate(counter.most_common(10), start=1):
        style_data = _style_snapshot(style_id)
        profile = next((item for item in STYLE_CATALOG if item.style_id == style_id), None)
        ranking.append(
            {
                "id": style_id,
                "rank": rank,
                "style_id": style_id,
                "hairstyleId": style_id,
                "style_name": style_data["style_name"],
                "koreanName": style_data["style_name"],
                "universalName": profile.fallback_name if profile else style_data["style_name"],
                "image_url": style_data["image_url"],
                "imageUrl": style_data["image_url"],
                "selection_count": count,
                "count": count,
                "keywords": style_data["keywords"],
                "description": style_data["description"],
            }
        )

    distribution = [
        {
            "style_id": item["style_id"],
            "style_name": item["style_name"],
            "selection_count": item["selection_count"],
        }
        for item in ranking
    ]
    age_decade_counter = Counter()
    age_group_counter = Counter()
    for row in filtered:
        profile = build_client_age_profile(row.client)
        if not profile:
            continue
        if profile.get("age_decade"):
            age_decade_counter[profile["age_decade"]] += 1
        if profile.get("age_group"):
            age_group_counter[profile["age_group"]] += 1
    unique_clients = len({row.client_id for row in filtered})
    hairstyles = [
        {
            "id": item["style_id"],
            "hairstyleId": item["style_id"],
            "koreanName": item["koreanName"],
            "universalName": item["universalName"],
            "keywords": item["keywords"],
            "description": item["description"],
            "imageUrl": item["imageUrl"],
        }
        for item in ranking
    ]
    chart_data = [
        {
            "label": item["koreanName"],
            "value": item["count"],
        }
        for item in ranking
    ]
    return {
        "status": "ready",
        "days": days,
        "filters": filters,
        "kpi": {
            "unique_clients": unique_clients,
            "total_confirmations": len(filtered),
            "active_consultations": len(_latest_active_consultations(admin=admin)),
        },
        "ranking": ranking,
        "trend_report": ranking,
        "trendReport": ranking,
        "hairstyles": hairstyles,
        "chart_data": chart_data,
        "chartData": chart_data,
        "distribution": distribution,
        "age_decade_distribution": [
            {"age_decade": key, "selection_count": count}
            for key, count in age_decade_counter.most_common()
        ],
        "age_group_distribution": [
            {"age_group": key, "selection_count": count}
            for key, count in age_group_counter.most_common()
        ],
    }


def get_style_report(*, style_id: int, days: int = 7, admin: AdminAccount | None = None) -> dict:
    style_data = _style_snapshot(style_id)
    style_profile = _style_catalog_profile(style_id)
    cutoff = timezone.now() - timezone.timedelta(days=days)
    recent_queryset = StyleSelection.objects.filter(
        style_id=style_id,
        created_at__gte=cutoff,
        is_sent_to_admin=True,
    )
    chosen_queryset = FormerRecommendation.objects.filter(style_id_snapshot=style_id, is_chosen=True)
    scoped_client_ids = _admin_client_ids(admin)
    if admin is not None:
        recent_queryset = recent_queryset.filter(client_id__in=scoped_client_ids)
        chosen_queryset = chosen_queryset.filter(client_id__in=scoped_client_ids)
    recent_count = recent_queryset.count()
    chosen_count = chosen_queryset.count()

    related = []
    target_profile = next((item for item in STYLE_CATALOG if item.style_id == style_id), None)
    if target_profile:
        scored = []
        for related_profile in STYLE_CATALOG:
            if related_profile.style_id == style_id:
                continue
            score = len(set(target_profile.keywords) & set(related_profile.keywords))
            if set(target_profile.face_shapes) & set(related_profile.face_shapes):
                score += 1
            if set(target_profile.vibe_tags) & set(related_profile.vibe_tags):
                score += 1
            scored.append((score, related_profile.style_id))
        for _, related_style_id in sorted(scored, key=lambda item: (-item[0], item[1]))[:5]:
            related.append(_style_snapshot(related_style_id))

    return {
        "status": "ready",
        "style": {
            **style_data,
            "recent_selection_count": recent_count,
            "chosen_count": chosen_count,
        },
        "hairstyle": {
            **_serialize_frontend_style(style_id=style_id, analysis=None),
            "recentSelectionCount": recent_count,
            "chosenCount": chosen_count,
            "faceRatioData": {
                "golden": None,
                "forehead": (", ".join(style_profile.ratio_modes) if style_profile else None),
                "jaw": (", ".join(style_profile.vibe_tags) if style_profile else None),
                "suitableFaces": list(style_profile.face_shapes) if style_profile else [],
            },
        },
        "related_styles": related,
        "relatedHairstyles": [
            _serialize_frontend_style(style_id=item["style_id"], analysis=None)
            for item in related
        ],
    }

