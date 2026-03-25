import json
import os
from collections import Counter
from urllib import error, request

from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Count, Q
from django.utils import timezone

from app.api.v1.recommendation_logic import STYLE_CATALOG
from app.api.v1.services_django import ensure_catalog_styles, get_latest_analysis, get_latest_capture, get_latest_survey
from app.models_django import ConsultationRequest, Customer, CustomerSessionNote, FormerRecommendation, Partner, Style, StyleSelection


def _normalize_phone(value: str) -> str:
    return value.replace("-", "").strip()


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
        "image_url": analysis.image_url,
        "created_at": analysis.created_at,
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
        "image_url": style.image_url,
        "description": style.description or "",
        "keywords": keywords,
    }


def register_partner(*, payload: dict) -> dict:
    phone = _normalize_phone(payload["phone"])
    if Partner.objects.filter(phone=phone).exists():
        raise ValueError("이미 등록된 관리자 연락처입니다.")
    if Partner.objects.filter(business_number=payload["business_number"]).exists():
        raise ValueError("이미 등록된 사업자 번호입니다.")

    partner = Partner.objects.create(
        name=payload["name"],
        store_name=payload["store_name"],
        role=payload.get("role", "owner"),
        phone=phone,
        business_number=payload["business_number"],
        password_hash=make_password(payload["password"]),
    )
    return {
        "status": "success",
        "partner_id": partner.id,
        "access_token": f"mock-partner-token-{partner.id}",
        "token_type": "bearer",
    }


def login_partner(*, phone: str, password: str) -> dict:
    phone = _normalize_phone(phone)
    partner = Partner.objects.filter(phone=phone, is_active=True).first()
    if not partner or not check_password(password, partner.password_hash):
        raise ValueError("관리자 계정 정보를 확인해주세요.")
    return {
        "status": "success",
        "partner_id": partner.id,
        "partner_name": partner.name,
        "store_name": partner.store_name,
        "access_token": f"mock-partner-token-{partner.id}",
        "token_type": "bearer",
    }


def _today_customer_ids() -> set[int]:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    capture_ids = set(
        Customer.objects.filter(captures__created_at__gte=start).values_list("id", flat=True)
    )
    consult_ids = set(
        Customer.objects.filter(consultations__created_at__gte=start).values_list("id", flat=True)
    )
    return capture_ids | consult_ids


def _latest_active_consultations() -> list[ConsultationRequest]:
    rows = ConsultationRequest.objects.filter(is_active=True).select_related("customer", "selected_style", "selected_recommendation").order_by("-created_at")
    seen: set[int] = set()
    latest_rows: list[ConsultationRequest] = []
    for row in rows:
        if row.customer_id in seen:
            continue
        seen.add(row.customer_id)
        latest_rows.append(row)
    return latest_rows


def get_admin_dashboard_summary() -> dict:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    top_styles = []
    styles_by_id = ensure_catalog_styles()
    top_rows = (
        StyleSelection.objects.filter(created_at__gte=start)
        .values("style_id")
        .annotate(selection_count=Count("id"))
        .order_by("-selection_count", "style_id")[:5]
    )
    for row in top_rows:
        style = styles_by_id.get(row["style_id"]) or Style.objects.filter(id=row["style_id"]).first()
        top_styles.append(
            {
                "style_id": row["style_id"],
                "style_name": style.name if style else f"Style {row['style_id']}",
                "image_url": style.image_url if style else None,
                "selection_count": row["selection_count"],
            }
        )

    active_consultations = _latest_active_consultations()
    active_preview = [
        {
            "consultation_id": row.id,
            "customer_id": row.customer_id,
            "customer_name": row.customer.name,
            "phone": row.customer.phone,
            "has_unread_consultation": not row.is_read,
            "status": row.status,
            "selected_style_name": row.selected_style.name if row.selected_style else None,
            "created_at": row.created_at,
        }
        for row in active_consultations[:5]
    ]
    return {
        "status": "ready",
        "ai_engine": _ai_health(),
        "today_metrics": {
            "unique_visitors": len(_today_customer_ids()),
            "active_customers": len(active_consultations),
            "pending_consultations": sum(1 for row in active_consultations if not row.is_read),
            "confirmed_styles": StyleSelection.objects.filter(created_at__gte=start).count(),
        },
        "top_styles_today": top_styles,
        "active_customers_preview": active_preview,
    }


def get_active_customer_sessions() -> dict:
    active_rows = _latest_active_consultations()
    items = []
    for row in active_rows:
        recommendation_count = FormerRecommendation.objects.filter(customer_id=row.customer_id, batch_id=getattr(row.selected_recommendation, "batch_id", None)).count() if row.selected_recommendation else 0
        items.append(
            {
                "consultation_id": row.id,
                "customer_id": row.customer_id,
                "customer_name": row.customer.name,
                "phone": row.customer.phone,
                "status": row.status,
                "has_unread_consultation": not row.is_read,
                "selected_style_name": row.selected_style.name if row.selected_style else None,
                "recommendation_count": recommendation_count,
                "last_activity_at": row.created_at,
            }
        )
    return {"status": "ready", "items": items}


def get_all_customers(*, query: str = "") -> dict:
    queryset = Customer.objects.all().order_by("name", "id")
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(phone__icontains=query)
        )

    items = []
    for customer in queryset[:100]:
        latest_consult = customer.consultations.order_by("-created_at").first()
        items.append(
            {
                "customer_id": customer.id,
                "name": customer.name,
                "gender": customer.gender,
                "phone": customer.phone,
                "created_at": customer.created_at,
                "last_consulted_at": latest_consult.created_at if latest_consult else None,
                "has_active_consultation": customer.consultations.filter(is_active=True).exists(),
            }
        )
    return {"status": "ready", "items": items}


def get_customer_detail(*, customer: Customer) -> dict:
    latest_survey = get_latest_survey(customer)
    latest_analysis = get_latest_analysis(customer)
    active_consultation = customer.consultations.order_by("-created_at").first()
    notes = CustomerSessionNote.objects.filter(customer=customer).select_related("partner", "consultation").order_by("-created_at")[:20]
    return {
        "status": "ready",
        "customer": {
            "customer_id": customer.id,
            "name": customer.name,
            "gender": customer.gender,
            "phone": customer.phone,
            "created_at": customer.created_at,
        },
        "latest_survey": _serialize_survey(latest_survey),
        "latest_analysis": _serialize_analysis(latest_analysis),
        "active_consultation": (
            {
                "consultation_id": active_consultation.id,
                "status": active_consultation.status,
                "is_active": active_consultation.is_active,
                "is_read": active_consultation.is_read,
                "source": active_consultation.source,
                "created_at": active_consultation.created_at,
                "closed_at": active_consultation.closed_at,
            }
            if active_consultation
            else None
        ),
        "notes": [
            {
                "note_id": note.id,
                "consultation_id": note.consultation_id,
                "partner_id": note.partner_id,
                "partner_name": note.partner.name if note.partner else None,
                "content": note.content,
                "created_at": note.created_at,
            }
            for note in notes
        ],
    }


def get_customer_recommendation_report(*, customer: Customer) -> dict:
    latest_analysis = get_latest_analysis(customer)
    latest_survey = get_latest_survey(customer)
    latest_generated = FormerRecommendation.objects.filter(customer=customer, source="generated").order_by("-created_at").first()
    batch_rows = []
    if latest_generated:
        batch_rows = list(
            FormerRecommendation.objects.filter(customer=customer, batch_id=latest_generated.batch_id).order_by("rank", "id")
        )
    final_selected = FormerRecommendation.objects.filter(customer=customer, is_chosen=True).order_by("-chosen_at", "-created_at").first()
    return {
        "status": "ready",
        "customer": {
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
        },
        "latest_survey": _serialize_survey(latest_survey),
        "latest_analysis": _serialize_analysis(latest_analysis),
        "final_selected_style": (
            {
                "recommendation_id": final_selected.id,
                "style_id": final_selected.style_id_snapshot,
                "style_name": final_selected.style_name_snapshot,
                "sample_image_url": final_selected.sample_image_url,
                "simulation_image_url": final_selected.simulation_image_url,
                "llm_explanation": final_selected.llm_explanation,
                "match_score": final_selected.match_score,
                "chosen_at": final_selected.chosen_at,
            }
            if final_selected
            else None
        ),
        "latest_generated_batch": {
            "batch_id": (str(latest_generated.batch_id) if latest_generated else None),
            "items": [
                {
                    "recommendation_id": row.id,
                    "style_id": row.style_id_snapshot,
                    "style_name": row.style_name_snapshot,
                    "sample_image_url": row.sample_image_url,
                    "simulation_image_url": row.simulation_image_url,
                    "llm_explanation": row.llm_explanation,
                    "match_score": row.match_score,
                    "rank": row.rank,
                    "is_chosen": row.is_chosen,
                }
                for row in batch_rows
            ],
        },
    }


def create_customer_note(*, customer: Customer, consultation_id: int, content: str, partner_id: int | None = None) -> dict:
    consultation = ConsultationRequest.objects.filter(id=consultation_id, customer=customer).first()
    if not consultation:
        raise ValueError("상담 세션을 찾지 못했습니다.")

    partner = Partner.objects.filter(id=partner_id).first() if partner_id else None
    note = CustomerSessionNote.objects.create(
        consultation=consultation,
        customer=customer,
        partner=partner,
        content=content.strip(),
    )
    consultation.is_read = True
    consultation.status = "IN_PROGRESS"
    consultation.save(update_fields=["is_read", "status"])
    return {
        "status": "success",
        "note_id": note.id,
        "consultation_id": consultation.id,
        "message": "고객 관찰 메모가 저장되었습니다.",
    }


def close_consultation_session(*, consultation_id: int) -> dict:
    consultation = ConsultationRequest.objects.filter(id=consultation_id).select_related("customer").first()
    if not consultation:
        raise ValueError("상담 세션을 찾지 못했습니다.")

    consultation.is_active = False
    consultation.is_read = True
    consultation.status = "CLOSED"
    consultation.closed_at = timezone.now()
    consultation.save(update_fields=["is_active", "is_read", "status", "closed_at"])
    return {
        "status": "success",
        "consultation_id": consultation.id,
        "customer_id": consultation.customer_id,
        "message": "상담 세션이 종료되었습니다.",
    }


def _selection_matches_snapshot(selection: StyleSelection, filters: dict) -> bool:
    snapshot = selection.survey_snapshot or {}
    if not snapshot and hasattr(selection.customer, "survey"):
        survey = selection.customer.survey
        snapshot = {
            "target_length": survey.target_length,
            "target_vibe": survey.target_vibe,
            "scalp_type": survey.scalp_type,
            "hair_colour": survey.hair_colour,
            "budget_range": survey.budget_range,
        }

    for key, value in filters.items():
        if value in (None, ""):
            continue
        if snapshot.get(key) != value:
            return False
    return True


def get_admin_trend_report(*, days: int = 7, filters: dict | None = None) -> dict:
    filters = filters or {}
    cutoff = timezone.now() - timezone.timedelta(days=days)
    selections = list(
        StyleSelection.objects.filter(created_at__gte=cutoff).select_related("customer").order_by("-created_at")
    )
    filtered = [row for row in selections if _selection_matches_snapshot(row, filters)]

    counter = Counter(row.style_id for row in filtered)
    ranking = []
    for rank, (style_id, count) in enumerate(counter.most_common(10), start=1):
        style_data = _style_snapshot(style_id)
        ranking.append(
            {
                "rank": rank,
                "style_id": style_id,
                "style_name": style_data["style_name"],
                "image_url": style_data["image_url"],
                "selection_count": count,
                "keywords": style_data["keywords"],
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

    unique_customers = len({row.customer_id for row in filtered})
    return {
        "status": "ready",
        "days": days,
        "filters": filters,
        "kpi": {
            "unique_customers": unique_customers,
            "total_confirmations": len(filtered),
            "active_consultations": ConsultationRequest.objects.filter(is_active=True).count(),
        },
        "ranking": ranking,
        "distribution": distribution,
    }


def get_style_report(*, style_id: int, days: int = 7) -> dict:
    style_data = _style_snapshot(style_id)
    cutoff = timezone.now() - timezone.timedelta(days=days)
    recent_count = StyleSelection.objects.filter(style_id=style_id, created_at__gte=cutoff).count()
    chosen_count = FormerRecommendation.objects.filter(style_id_snapshot=style_id, is_chosen=True).count()

    related = []
    target_profile = next((item for item in STYLE_CATALOG if item.style_id == style_id), None)
    if target_profile:
        scored = []
        for profile in STYLE_CATALOG:
            if profile.style_id == style_id:
                continue
            score = len(set(target_profile.keywords) & set(profile.keywords))
            if target_profile.vibe_tags and profile.vibe_tags and set(target_profile.vibe_tags) & set(profile.vibe_tags):
                score += 1
            scored.append((score, profile.style_id))
        for _, related_style_id in sorted(scored, key=lambda item: (-item[0], item[1]))[:5]:
            related.append(_style_snapshot(related_style_id))

    return {
        "status": "ready",
        "style": {
            **style_data,
            "recent_selection_count": recent_count,
            "chosen_count": chosen_count,
        },
        "related_styles": related,
    }
