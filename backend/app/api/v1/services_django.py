import logging
import uuid
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from app.api.v1.recommendation_logic import STYLE_CATALOG, build_preference_vector
from app.models_django import CaptureRecord, ConsultationRequest, Customer, FaceAnalysis, FormerRecommendation, Style, StyleSelection, Survey
from app.services.ai_facade import generate_recommendation_batch, simulate_face_analysis


logger = logging.getLogger(__name__)


def build_default_survey_context(customer_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        customer_id=customer_id,
        target_length=None,
        target_vibe=None,
        scalp_type=None,
        hair_colour=None,
        budget_range=None,
        preference_vector=[0.0] * 20,
    )


def ensure_catalog_styles() -> dict[int, Style]:
    styles_by_id: dict[int, Style] = {
        style.id: style
        for style in Style.objects.filter(id__in=[profile.style_id for profile in STYLE_CATALOG])
    }
    for profile in STYLE_CATALOG:
        if profile.style_id in styles_by_id:
            continue
        styles_by_id[profile.style_id] = Style.objects.create(
            id=profile.style_id,
            name=profile.fallback_name,
            vibe=(profile.vibe_tags[0] if profile.vibe_tags else "natural").title(),
            description=profile.fallback_description,
            image_url=profile.fallback_sample_image_url,
        )
    return styles_by_id


def get_latest_survey(customer: Customer):
    return Survey.objects.filter(customer=customer).order_by("-created_at").first()


def get_latest_analysis(customer: Customer):
    return FaceAnalysis.objects.filter(customer=customer).order_by("-created_at").first()


def get_latest_capture(customer: Customer):
    return CaptureRecord.objects.filter(customer=customer).order_by("-created_at").first()


def build_survey_snapshot(customer: Customer) -> dict | None:
    survey = get_latest_survey(customer)
    if not survey:
        return None
    return {
        "target_length": survey.target_length,
        "target_vibe": survey.target_vibe,
        "scalp_type": survey.scalp_type,
        "hair_colour": survey.hair_colour,
        "budget_range": survey.budget_range,
        "preference_vector": survey.preference_vector or [],
        "created_at": survey.created_at.isoformat(),
    }


def upsert_survey(customer: Customer, payload: dict) -> Survey:
    preference_vector = build_preference_vector(
        target_length=payload.get("target_length"),
        target_vibe=payload.get("target_vibe"),
        scalp_type=payload.get("scalp_type"),
        hair_colour=payload.get("hair_colour"),
        budget_range=payload.get("budget_range"),
    )
    survey, _ = Survey.objects.update_or_create(
        customer=customer,
        defaults={
            "target_length": payload.get("target_length"),
            "target_vibe": payload.get("target_vibe"),
            "scalp_type": payload.get("scalp_type"),
            "hair_colour": payload.get("hair_colour"),
            "budget_range": payload.get("budget_range"),
            "preference_vector": preference_vector,
        },
    )
    return survey


def persist_generated_batch(*, customer: Customer, capture_record: CaptureRecord | None, survey, analysis: FaceAnalysis) -> tuple[str, list[FormerRecommendation]]:
    styles_by_id = ensure_catalog_styles()
    survey_payload = {
        "target_length": getattr(survey, "target_length", None),
        "target_vibe": getattr(survey, "target_vibe", None),
        "scalp_type": getattr(survey, "scalp_type", None),
        "hair_colour": getattr(survey, "hair_colour", None),
        "budget_range": getattr(survey, "budget_range", None),
    }
    items = generate_recommendation_batch(
        customer_id=customer.id,
        survey_data=survey_payload,
        analysis_data={
            "face_shape": analysis.face_shape,
            "golden_ratio_score": analysis.golden_ratio_score,
            "image_url": analysis.image_url,
        },
        styles_by_id=styles_by_id,
    )

    batch_id = uuid.uuid4()
    rows: list[FormerRecommendation] = []
    for item in items:
        style = styles_by_id.get(item["style_id"])
        rows.append(
            FormerRecommendation(
                customer=customer,
                capture_record=capture_record,
                style=style,
                batch_id=batch_id,
                source="generated",
                style_id_snapshot=item["style_id"],
                style_name_snapshot=item["style_name"],
                style_description_snapshot=item.get("style_description", ""),
                keywords=item.get("keywords", []),
                sample_image_url=item.get("sample_image_url"),
                simulation_image_url=item.get("simulation_image_url"),
                llm_explanation=item.get("llm_explanation"),
                match_score=item.get("match_score"),
                rank=item.get("rank", 0),
            )
        )
    FormerRecommendation.objects.bulk_create(rows)
    return str(batch_id), list(FormerRecommendation.objects.filter(batch_id=batch_id).order_by("rank", "id"))


def _serialize_row(row: FormerRecommendation) -> dict:
    return {
        "recommendation_id": row.id,
        "batch_id": row.batch_id,
        "source": row.source,
        "style_id": row.style_id_snapshot,
        "style_name": row.style_name_snapshot,
        "style_description": row.style_description_snapshot or "",
        "keywords": row.keywords or [],
        "sample_image_url": row.sample_image_url,
        "simulation_image_url": row.simulation_image_url,
        "synthetic_image_url": row.simulation_image_url,
        "llm_explanation": row.llm_explanation or "",
        "reasoning": row.llm_explanation or "",
        "match_score": row.match_score or 0.0,
        "rank": row.rank,
        "is_chosen": row.is_chosen,
        "created_at": row.created_at,
    }


def _build_empty_response(*, source: str, message: str, next_action: str | None = None, next_actions: list[str] | None = None) -> dict:
    payload = {
        "status": "empty",
        "source": source,
        "message": message,
        "items": [],
    }
    if next_action:
        payload["next_action"] = next_action
    if next_actions:
        payload["next_actions"] = next_actions
    return payload


def get_former_recommendations(customer: Customer) -> dict:
    latest_generated = (
        FormerRecommendation.objects.filter(customer=customer, source="generated")
        .order_by("-created_at")
        .first()
    )
    queryset = FormerRecommendation.objects.filter(customer=customer)
    if latest_generated:
        latest_batch_has_choice = queryset.filter(batch_id=latest_generated.batch_id, is_chosen=True).exists()
        if not latest_batch_has_choice:
            queryset = queryset.exclude(batch_id=latest_generated.batch_id)

    rows = list(queryset.order_by("-is_chosen", "-chosen_at", "-created_at")[:5])
    if not rows:
        return _build_empty_response(
            source="former_recommendations",
            message="저장된 기존 스타일이 아직 없어요. 트렌드를 보거나 새 촬영을 진행해보세요.",
            next_actions=["trend", "capture"],
        )

    return {
        "status": "ready",
        "source": "former_recommendations",
        "items": [_serialize_row(row) for row in rows],
    }


def _ensure_current_batch(customer: Customer) -> tuple[str | None, list[FormerRecommendation], str | None]:
    latest_analysis = get_latest_analysis(customer)
    latest_capture = get_latest_capture(customer)
    latest_survey = get_latest_survey(customer)
    latest_batch = (
        FormerRecommendation.objects.filter(customer=customer, source="generated")
        .order_by("-created_at")
        .first()
    )

    if not latest_capture or not latest_analysis:
        return None, [], "needs_capture"

    needs_regeneration = latest_batch is None
    if latest_batch and latest_capture and latest_batch.created_at < latest_capture.created_at:
        needs_regeneration = True
    if latest_batch and latest_analysis and latest_batch.created_at < latest_analysis.created_at:
        needs_regeneration = True
    if latest_batch and latest_survey and latest_batch.created_at < latest_survey.created_at:
        needs_regeneration = True

    if needs_regeneration:
        survey_context = latest_survey or build_default_survey_context(customer.id)
        _, rows = persist_generated_batch(
            customer=customer,
            capture_record=latest_capture,
            survey=survey_context,
            analysis=latest_analysis,
        )
        return (str(rows[0].batch_id) if rows else None), rows, None

    rows = list(
        FormerRecommendation.objects.filter(customer=customer, batch_id=latest_batch.batch_id).order_by("rank", "id")
    )
    return str(latest_batch.batch_id), rows, None


def get_current_recommendations(customer: Customer) -> dict:
    latest_survey = get_latest_survey(customer)
    latest_capture = get_latest_capture(customer)
    latest_analysis = get_latest_analysis(customer)

    if not latest_capture and not latest_survey:
        return {
            "status": "needs_input",
            "source": "current_recommendations",
            "message": "아직 취향을 알려주지 않으셨어요. 설문을 진행하거나 바로 촬영을 시작해주세요.",
            "next_actions": ["survey", "capture"],
            "items": [],
        }

    if not latest_capture or not latest_analysis:
        return {
            "status": "needs_capture",
            "source": "current_recommendations",
            "message": "정면 사진 촬영이 아직 없어요. 촬영을 진행하면 새 시뮬레이션 5개를 보여드릴게요.",
            "next_action": "capture",
            "items": [],
        }

    batch_id, rows, status_code = _ensure_current_batch(customer)
    if status_code == "needs_capture":
        return {
            "status": "needs_capture",
            "source": "current_recommendations",
            "message": "촬영 데이터가 아직 준비되지 않았어요. 먼저 캡처를 진행해주세요.",
            "next_action": "capture",
            "items": [],
        }

    if not rows:
        return _build_empty_response(
            source="current_recommendations",
            message="생성된 추천 결과가 아직 없어요. 다시 촬영을 진행해주세요.",
            next_action="capture",
        )

    message = "최신 촬영 데이터를 기준으로 새 시뮬레이션 5개를 불러왔어요."
    if latest_survey is None:
        message = "설문 없이 얼굴 분석만으로 새 시뮬레이션 5개를 생성했어요."

    return {
        "status": "ready",
        "source": "current_recommendations",
        "batch_id": batch_id,
        "message": message,
        "items": [_serialize_row(row) for row in rows],
    }


def get_trend_recommendations(*, days: int = 30) -> dict:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    popular_style_ids = (
        StyleSelection.objects.filter(created_at__gte=cutoff)
        .values("style_id")
        .annotate(selection_count=Count("id"))
        .order_by("-selection_count", "style_id")[:5]
    )

    items: list[dict] = []
    for rank, item in enumerate(popular_style_ids, start=1):
        style = Style.objects.filter(id=item["style_id"]).first()
        if not style:
            continue
        items.append(
            {
                "source": "trend",
                "style_id": style.id,
                "style_name": style.name,
                "style_description": style.description or f"최근 {days}일 동안 매장에서 많이 확정된 스타일입니다.",
                "keywords": [style.vibe] if style.vibe else [],
                "sample_image_url": style.image_url,
                "simulation_image_url": style.image_url,
                "synthetic_image_url": style.image_url,
                "llm_explanation": style.description or f"최근 {days}일 동안 매장에서 많이 확정된 스타일입니다.",
                "reasoning": f"최근 {days}일 확정 건수를 기준으로 정렬한 트렌드 추천입니다.",
                "match_score": float(item["selection_count"]),
                "rank": rank,
                "is_chosen": False,
            }
        )

    if not items:
        styles_by_id = ensure_catalog_styles()
        fallback_ids = [201, 203, 205, 204, 207]
        for rank, style_id in enumerate(fallback_ids, start=1):
            style = styles_by_id[style_id]
            items.append(
                {
                    "source": "trend",
                    "style_id": style.id,
                    "style_name": style.name,
                    "style_description": style.description or "",
                    "keywords": [style.vibe] if style.vibe else [],
                    "sample_image_url": style.image_url,
                    "simulation_image_url": style.image_url,
                    "synthetic_image_url": style.image_url,
                    "llm_explanation": "최근 30일 확정 데이터가 부족해 기본 트렌드 카탈로그를 보여드리고 있어요.",
                    "reasoning": "fallback trend catalog",
                    "match_score": 0.0,
                    "rank": rank,
                    "is_chosen": False,
                }
            )

    return {
        "status": "ready",
        "source": "trend",
        "days": days,
        "items": items,
    }


def confirm_style_selection(
    *,
    customer: Customer,
    recommendation_id: int | None = None,
    style_id: int | None = None,
    source: str = "current_recommendations",
    direct_consultation: bool = False,
) -> dict:
    latest_analysis = get_latest_analysis(customer)
    survey_snapshot = build_survey_snapshot(customer)
    analysis_snapshot = {}
    if latest_analysis:
        analysis_snapshot = {
            "face_shape": latest_analysis.face_shape,
            "golden_ratio": latest_analysis.golden_ratio_score,
            "image_url": latest_analysis.image_url,
        }

    selected_style = None
    selected_row = None
    if recommendation_id is not None:
        selected_row = FormerRecommendation.objects.filter(id=recommendation_id, customer=customer).first()
        if not selected_row:
            raise ValueError("선택한 추천 결과를 찾지 못했습니다.")

        FormerRecommendation.objects.filter(customer=customer, batch_id=selected_row.batch_id).update(
            is_chosen=False,
            chosen_at=None,
        )
        selected_row.is_chosen = True
        selected_row.chosen_at = timezone.now()
        selected_row.is_sent_to_admin = True
        selected_row.sent_at = timezone.now()
        selected_row.save(update_fields=["is_chosen", "chosen_at", "is_sent_to_admin", "sent_at"])
        style_id = selected_row.style_id_snapshot
        selected_style = selected_row.style or Style.objects.filter(id=style_id).first()

    if selected_style is None and style_id is not None:
        selected_style = Style.objects.filter(id=style_id).first()

    if not direct_consultation and selected_style is None:
        raise ValueError("선택한 스타일 정보가 없습니다.")

    if recommendation_id is None and selected_style is not None and source == "trend":
        explanation = selected_style.description or "매장 트렌드에서 선택한 스타일입니다."
        selected_row = FormerRecommendation.objects.create(
            customer=customer,
            style=selected_style,
            batch_id=uuid.uuid4(),
            source="trend",
            style_id_snapshot=selected_style.id,
            style_name_snapshot=selected_style.name,
            style_description_snapshot=selected_style.description or "",
            keywords=[selected_style.vibe] if selected_style.vibe else [],
            sample_image_url=selected_style.image_url,
            simulation_image_url=selected_style.image_url,
            llm_explanation=explanation,
            match_score=None,
            rank=1,
            is_chosen=not direct_consultation,
            chosen_at=(timezone.now() if not direct_consultation else None),
            is_sent_to_admin=True,
            sent_at=timezone.now(),
        )

    if not direct_consultation and selected_style is not None:
        StyleSelection.objects.create(
            customer=customer,
            selected_recommendation=selected_row,
            style_id=selected_style.id,
            source=source,
            survey_snapshot=survey_snapshot,
            match_score=(selected_row.match_score if selected_row else None),
            is_sent_to_designer=True,
        )

    ConsultationRequest.objects.filter(customer=customer, is_active=True).update(
        is_active=False,
        status="CLOSED",
        closed_at=timezone.now(),
        is_read=True,
    )

    consultation = ConsultationRequest.objects.create(
        customer=customer,
        selected_style=(None if direct_consultation else selected_style),
        selected_recommendation=selected_row,
        source=source,
        survey_snapshot=survey_snapshot,
        analysis_data_snapshot=analysis_snapshot,
        status="PENDING",
        is_active=True,
        is_read=False,
    )

    return {
        "status": "success",
        "consultation_id": consultation.id,
        "selected_style_id": (selected_style.id if selected_style else None),
        "selected_style_name": (selected_style.name if selected_style else None),
        "source": source,
        "direct_consultation": direct_consultation,
        "recommendation_id": (selected_row.id if selected_row else None),
        "message": (
            "디자이너에게 직접 상담 요청을 전달했습니다."
            if direct_consultation
            else "선택한 스타일과 분석 결과를 디자이너에게 전달했습니다."
        ),
    }


def run_mirrai_analysis_pipeline(record_id: int):
    try:
        with transaction.atomic():
            record = CaptureRecord.objects.select_for_update().get(id=record_id)
            if record.status != "PENDING":
                return

            record.status = "PROCESSING"
            record.save(update_fields=["status", "updated_at"])

        simulated = simulate_face_analysis(image_url=record.processed_path)
        analysis = FaceAnalysis.objects.create(
            customer=record.customer,
            face_shape=simulated["face_shape"],
            golden_ratio_score=simulated["golden_ratio_score"],
            image_url=simulated["image_url"],
        )

        survey = get_latest_survey(record.customer) or build_default_survey_context(record.customer_id)
        persist_generated_batch(customer=record.customer, capture_record=record, survey=survey, analysis=analysis)

        record.status = "DONE"
        record.save(update_fields=["status", "updated_at"])
        logger.info("[PIPELINE SUCCESS] Record %s processed.", record_id)

    except Exception as exc:
        logger.error("[PIPELINE ERROR] Record %s: %s", record_id, exc)
        CaptureRecord.objects.filter(id=record_id).update(status="FAILED", error_note=str(exc))
