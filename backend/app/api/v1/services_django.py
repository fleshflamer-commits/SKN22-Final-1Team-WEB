import logging
import uuid
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from app.api.v1.recommendation_logic import STYLE_CATALOG, build_preference_vector
from app.models_django import (
    CaptureRecord,
    ConsultationRequest,
    Client,
    FaceAnalysis,
    FormerRecommendation,
    AdminAccount,
    Style,
    StyleSelection,
    Survey,
)
from app.services.age_profile import build_client_age_profile, client_matches_age_profile
from app.services.ai_facade import explain_style, generate_recommendation_batch, simulate_face_analysis
from app.services.storage_service import resolve_storage_reference


logger = logging.getLogger(__name__)


def build_default_survey_context(client_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        client_id=client_id,
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


def _style_reference(style_id: int, *, styles_by_id: dict[int, Style] | None = None) -> dict:
    styles_by_id = styles_by_id or ensure_catalog_styles()
    style = styles_by_id.get(style_id) or Style.objects.filter(id=style_id).first()
    profile = next((item for item in STYLE_CATALOG if item.style_id == style_id), None)
    sample_image_url = None
    if style and style.image_url:
        sample_image_url = resolve_storage_reference(style.image_url)
    elif profile:
        sample_image_url = resolve_storage_reference(profile.fallback_sample_image_url)

    return {
        "sample_image_url": sample_image_url,
        "style_name": (style.name if style else (profile.fallback_name if profile else f"Style {style_id}")),
        "style_description": (style.description if style else (profile.fallback_description if profile else "")) or "",
        "keywords": list(profile.keywords) if profile else ([style.vibe] if style and style.vibe else []),
    }


def get_latest_survey(client: Client):
    return Survey.objects.filter(client=client).order_by("-created_at").first()


def get_latest_analysis(client: Client):
    return FaceAnalysis.objects.filter(client=client).order_by("-created_at").first()


def get_latest_capture(client: Client):
    return (
        CaptureRecord.objects.filter(client=client, status="DONE")
        .order_by("-created_at")
        .first()
    )


def get_latest_capture_attempt(client: Client):
    return CaptureRecord.objects.filter(client=client).order_by("-created_at").first()


def build_survey_snapshot(client: Client) -> dict | None:
    survey = get_latest_survey(client)
    if not survey:
        return None
    return {
        "target_length": survey.target_length,
        "target_vibe": survey.target_vibe,
        "scalp_type": survey.scalp_type,
        "hair_colour": survey.hair_colour,
        "budget_range": survey.budget_range,
        "preference_vector": survey.preference_vector or [],
        "age_profile": build_client_age_profile(client),
        "created_at": survey.created_at.isoformat(),
    }


def build_recommendation_regeneration_snapshot(
    *,
    client: Client,
    survey,
    analysis: FaceAnalysis | None,
    source: str,
    capture_record: CaptureRecord | None = None,
) -> dict:
    engine_payload = build_recommendation_engine_payload(
        client=client,
        survey=survey,
        analysis=analysis,
        source=source,
        capture_record=capture_record,
    )
    return {
        "version": "vector-only-v1",
        "source": source,
        "client_id": client.id,
        "survey_data": {
            "target_length": getattr(survey, "target_length", None),
            "target_vibe": getattr(survey, "target_vibe", None),
            "scalp_type": getattr(survey, "scalp_type", None),
            "hair_colour": getattr(survey, "hair_colour", None),
            "budget_range": getattr(survey, "budget_range", None),
            "preference_vector": getattr(survey, "preference_vector", None) or [],
            "age_profile": build_client_age_profile(client),
        },
        "analysis_data": (
            {
                "face_shape": analysis.face_shape,
                "golden_ratio_score": analysis.golden_ratio_score,
                "landmark_snapshot": analysis.landmark_snapshot,
            }
            if analysis
            else None
        ),
        "engine_payload": engine_payload,
    }


def upsert_survey(client: Client, payload: dict) -> Survey:
    preference_vector = build_preference_vector(
        target_length=payload.get("target_length"),
        target_vibe=payload.get("target_vibe"),
        scalp_type=payload.get("scalp_type"),
        hair_colour=payload.get("hair_colour"),
        budget_range=payload.get("budget_range"),
    )
    survey, _ = Survey.objects.update_or_create(
        client=client,
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


def build_recommendation_engine_payload(
    *,
    client: Client,
    survey,
    analysis: FaceAnalysis | None,
    source: str,
    capture_record: CaptureRecord | None = None,
) -> dict:
    survey_data = {
        "target_length": getattr(survey, "target_length", None),
        "target_vibe": getattr(survey, "target_vibe", None),
        "scalp_type": getattr(survey, "scalp_type", None),
        "hair_colour": getattr(survey, "hair_colour", None),
        "budget_range": getattr(survey, "budget_range", None),
        "preference_vector": getattr(survey, "preference_vector", None) or [],
        "age_profile": build_client_age_profile(client),
    }
    analysis_data = (
        {
            "face_shape": analysis.face_shape,
            "golden_ratio_score": analysis.golden_ratio_score,
            "image_url": resolve_storage_reference(analysis.image_url),
            "landmark_snapshot": analysis.landmark_snapshot,
            "capture_record_id": (capture_record.id if capture_record else None),
            "image_storage_policy": (
                (capture_record.privacy_snapshot or {}).get("storage_policy")
                if capture_record is not None
                else "vector_only"
            ),
        }
        if analysis
        else {}
    )
    return {
        "version": "recommendation-engine-v2",
        "source": source,
        "client_id": client.id,
        "survey_data": survey_data,
        "analysis_data": analysis_data,
    }


def persist_generated_batch(
    *,
    client: Client,
    capture_record: CaptureRecord | None,
    survey,
    analysis: FaceAnalysis,
) -> tuple[str, list[FormerRecommendation]]:
    styles_by_id = ensure_catalog_styles()
    engine_payload = build_recommendation_engine_payload(
        client=client,
        survey=survey,
        analysis=analysis,
        source="generated",
        capture_record=capture_record,
    )
    items = generate_recommendation_batch(
        client_id=engine_payload["client_id"],
        survey_data=engine_payload["survey_data"],
        analysis_data=engine_payload["analysis_data"],
        styles_by_id=styles_by_id,
    )
    regeneration_snapshot = build_recommendation_regeneration_snapshot(
        client=client,
        survey=survey,
        analysis=analysis,
        source="generated",
        capture_record=capture_record,
    )

    batch_id = uuid.uuid4()
    rows: list[FormerRecommendation] = []
    for item in items:
        style = styles_by_id.get(item["style_id"])
        rows.append(
            FormerRecommendation(
                client=client,
                capture_record=capture_record,
                style=style,
                batch_id=batch_id,
                source="generated",
                style_id_snapshot=item["style_id"],
                style_name_snapshot=item["style_name"],
                style_description_snapshot=item.get("style_description", ""),
                keywords=item.get("keywords", []),
                sample_image_url=None,
                simulation_image_url=None,
                regeneration_snapshot=regeneration_snapshot,
                llm_explanation=item.get("llm_explanation"),
                reasoning_snapshot=item.get("reasoning_snapshot"),
                match_score=item.get("match_score"),
                rank=item.get("rank", 0),
            )
        )
    FormerRecommendation.objects.bulk_create(rows)
    return str(batch_id), list(FormerRecommendation.objects.filter(batch_id=batch_id).order_by("rank", "id"))


def persist_survey_only_batch(
    *,
    client: Client,
    survey,
) -> tuple[str, list[FormerRecommendation]]:
    styles_by_id = ensure_catalog_styles()
    items = generate_recommendation_batch(
        client_id=client.id,
        survey_data={
            "target_length": getattr(survey, "target_length", None),
            "target_vibe": getattr(survey, "target_vibe", None),
            "scalp_type": getattr(survey, "scalp_type", None),
            "hair_colour": getattr(survey, "hair_colour", None),
            "budget_range": getattr(survey, "budget_range", None),
            "preference_vector": getattr(survey, "preference_vector", None) or [],
            "age_profile": build_client_age_profile(client),
        },
        analysis_data={},
        styles_by_id=styles_by_id,
    )
    regeneration_snapshot = build_recommendation_regeneration_snapshot(
        client=client,
        survey=survey,
        analysis=None,
        source="survey_only",
    )

    batch_id = uuid.uuid4()
    rows: list[FormerRecommendation] = []
    for item in items:
        style = styles_by_id.get(item["style_id"])
        rows.append(
            FormerRecommendation(
                client=client,
                capture_record=None,
                style=style,
                batch_id=batch_id,
                source="survey_only",
                style_id_snapshot=item["style_id"],
                style_name_snapshot=item["style_name"],
                style_description_snapshot=item.get("style_description", ""),
                keywords=item.get("keywords", []),
                sample_image_url=None,
                simulation_image_url=None,
                regeneration_snapshot=regeneration_snapshot,
                llm_explanation=item.get("llm_explanation"),
                reasoning_snapshot=item.get("reasoning_snapshot"),
                match_score=item.get("match_score"),
                rank=item.get("rank", 0),
            )
        )
    FormerRecommendation.objects.bulk_create(rows)
    return str(batch_id), list(FormerRecommendation.objects.filter(batch_id=batch_id).order_by("rank", "id"))


def regenerate_recommendation_simulation(
    *,
    client: Client,
    recommendation_id: int,
) -> dict:
    row = FormerRecommendation.objects.filter(id=recommendation_id, client=client).first()
    if row is None:
        raise ValueError("The recommendation to regenerate could not be found.")
    if not row.regeneration_snapshot:
        raise ValueError("This recommendation does not support simulation regeneration.")

    snapshot = row.regeneration_snapshot or {}
    engine_payload = snapshot.get("engine_payload") or {
        "client_id": client.id,
        "survey_data": (snapshot.get("survey_data") or {}),
        "analysis_data": (snapshot.get("analysis_data") or {}),
    }
    styles_by_id = ensure_catalog_styles()
    items = generate_recommendation_batch(
        client_id=engine_payload["client_id"],
        survey_data=engine_payload.get("survey_data") or {},
        analysis_data=engine_payload.get("analysis_data") or {},
        styles_by_id=styles_by_id,
    )
    regenerated_card = next((item for item in items if item.get("style_id") == row.style_id_snapshot), None)
    if regenerated_card is None:
        style_reference = _style_reference(row.style_id_snapshot, styles_by_id=styles_by_id)
        regenerated_card = {
            "style_id": row.style_id_snapshot,
            "style_name": row.style_name_snapshot or style_reference["style_name"],
            "style_description": row.style_description_snapshot or style_reference["style_description"],
            "sample_image_url": style_reference["sample_image_url"],
            "simulation_image_url": None,
            "llm_explanation": row.llm_explanation or "",
            "keywords": row.keywords or style_reference["keywords"],
            "reasoning_snapshot": row.reasoning_snapshot or {"summary": row.llm_explanation or ""},
            "match_score": row.match_score,
            "rank": row.rank,
        }

    explanation = explain_style(card=regenerated_card)
    reasoning_snapshot = {
        **(regenerated_card.get("reasoning_snapshot") or row.reasoning_snapshot or {}),
        "regenerated": True,
        "source": row.source,
        "regenerated_at": timezone.now().isoformat(),
    }
    return {
        "status": "success",
        "recommendation_id": row.id,
        "client_id": client.id,
        "image_policy": "vector_only",
        "can_regenerate_simulation": True,
        "item": {
            "id": row.id,
            "recommendation_id": row.id,
            "style_id": regenerated_card.get("style_id", row.style_id_snapshot),
            "style_name": explanation.get("style_name") or regenerated_card.get("style_name") or row.style_name_snapshot,
            "name": explanation.get("style_name") or regenerated_card.get("style_name") or row.style_name_snapshot,
            "name_en": explanation.get("style_name") or regenerated_card.get("style_name") or row.style_name_snapshot,
            "style_description": regenerated_card.get("style_description") or row.style_description_snapshot or "",
            "description": explanation.get("llm_explanation") or regenerated_card.get("style_description") or row.style_description_snapshot or "",
            "sample_image_url": explanation.get("sample_image_url") or regenerated_card.get("sample_image_url"),
            "imageUrl": explanation.get("sample_image_url") or regenerated_card.get("sample_image_url"),
            "simulation_image_url": explanation.get("simulation_image_url") or regenerated_card.get("simulation_image_url"),
            "synthetic_image_url": explanation.get("simulation_image_url") or regenerated_card.get("simulation_image_url"),
            "llm_explanation": explanation.get("llm_explanation") or regenerated_card.get("llm_explanation") or row.llm_explanation or "",
            "keywords": explanation.get("keywords") or regenerated_card.get("keywords") or row.keywords or [],
            "tags": explanation.get("keywords") or regenerated_card.get("keywords") or row.keywords or [],
            "reasoning_snapshot": reasoning_snapshot,
            "match_score": regenerated_card.get("match_score", row.match_score),
            "match": int(round(regenerated_card.get("match_score", row.match_score) or 0)),
            "rank": regenerated_card.get("rank", row.rank),
            "image_policy": "vector_only",
            "can_regenerate_simulation": True,
        },
        "message": "The simulation payload has been regenerated from the stored vector snapshot.",
    }


def serialize_recommendation_row(row: FormerRecommendation) -> dict:
    reasoning_snapshot = row.reasoning_snapshot or {}
    style_reference = _style_reference(
        row.style_id_snapshot,
        styles_by_id=({row.style_id_snapshot: row.style} if row.style else None),
    )
    uses_vector_only_policy = bool(row.regeneration_snapshot)
    sample_image_url = style_reference["sample_image_url"] or resolve_storage_reference(row.sample_image_url)
    simulation_image_url = None if uses_vector_only_policy else resolve_storage_reference(row.simulation_image_url)
    style_name = row.style_name_snapshot or style_reference["style_name"]
    style_description = row.style_description_snapshot or style_reference["style_description"]
    keywords = row.keywords or style_reference["keywords"]
    match_score = row.match_score or 0.0
    description = row.llm_explanation or style_description or ""
    return {
        "id": row.id,
        "recommendation_id": row.id,
        "batch_id": row.batch_id,
        "source": row.source,
        "style_id": row.style_id_snapshot,
        "style_name": style_name,
        "name": style_name,
        "name_en": style_name,
        "style_description": style_description,
        "description": description,
        "keywords": keywords,
        "tags": keywords,
        "sample_image_url": sample_image_url,
        "imageUrl": sample_image_url,
        "simulation_image_url": simulation_image_url,
        "synthetic_image_url": simulation_image_url,
        "llm_explanation": row.llm_explanation or "",
        "reasoning": reasoning_snapshot.get("summary") or row.llm_explanation or "",
        "reasoning_snapshot": reasoning_snapshot,
        "match_score": match_score,
        "match": int(round(match_score)),
        "rank": row.rank,
        "is_chosen": row.is_chosen,
        "image_policy": ("vector_only" if uses_vector_only_policy else "legacy_asset_store"),
        "can_regenerate_simulation": uses_vector_only_policy,
        "created_at": row.created_at,
    }


def _serialize_row(row: FormerRecommendation) -> dict:
    return serialize_recommendation_row(row)


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


def serialize_capture_status(record: CaptureRecord) -> dict:
    privacy_snapshot = record.privacy_snapshot or {}
    payload = {
        "record_id": record.id,
        "status": record.status.lower(),
        "face_count": record.face_count,
        "error_note": record.error_note,
        "landmark_snapshot": record.landmark_snapshot,
        "deidentified_image_url": resolve_storage_reference(record.deidentified_path),
        "privacy_snapshot": privacy_snapshot,
        "image_storage_policy": privacy_snapshot.get("storage_policy", "asset_store"),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if record.status in {"NEEDS_RETAKE", "FAILED"}:
        payload["next_action"] = "capture"
    return payload


def get_former_recommendations(client: Client) -> dict:
    latest_generated = (
        FormerRecommendation.objects.filter(client=client, source__in=["generated", "survey_only"])
        .order_by("-created_at")
        .first()
    )
    queryset = FormerRecommendation.objects.filter(client=client)
    if latest_generated:
        latest_batch_has_choice = queryset.filter(batch_id=latest_generated.batch_id, is_chosen=True).exists()
        if not latest_batch_has_choice:
            queryset = queryset.exclude(batch_id=latest_generated.batch_id)

    rows = list(queryset.order_by("-is_chosen", "-chosen_at", "-created_at")[:5])
    if not rows:
        return _build_empty_response(
            source="former_recommendations",
            message="No previous recommendation history is available yet. Start with trend cards or upload a new capture.",
            next_actions=["trend", "capture"],
        )

    return {
        "status": "ready",
        "source": "former_recommendations",
        "recommendation_mode": "history",
        "items": [_serialize_row(row) for row in rows],
    }


def _ensure_current_batch(client: Client) -> tuple[str | None, list[FormerRecommendation], str | None]:
    latest_analysis = get_latest_analysis(client)
    latest_capture = get_latest_capture(client)
    latest_survey = get_latest_survey(client)
    latest_batch = (
        FormerRecommendation.objects.filter(client=client, source__in=["generated", "survey_only"])
        .order_by("-created_at")
        .first()
    )

    survey_only_mode = latest_survey is not None and (latest_capture is None or latest_analysis is None)
    if survey_only_mode:
        needs_regeneration = latest_batch is None or latest_batch.source != "survey_only"
        if latest_batch and latest_survey and latest_batch.created_at < latest_survey.created_at:
            needs_regeneration = True

        if needs_regeneration:
            _, rows = persist_survey_only_batch(
                client=client,
                survey=latest_survey,
            )
            return (str(rows[0].batch_id) if rows else None), rows, "survey_only"

        rows = list(
            FormerRecommendation.objects.filter(client=client, batch_id=latest_batch.batch_id).order_by("rank", "id")
        )
        return str(latest_batch.batch_id), rows, "survey_only"

    if not latest_capture or not latest_analysis:
        return None, [], "needs_capture"

    needs_regeneration = latest_batch is None or latest_batch.source != "generated"
    if latest_batch and latest_capture and latest_batch.created_at < latest_capture.created_at:
        needs_regeneration = True
    if latest_batch and latest_analysis and latest_batch.created_at < latest_analysis.created_at:
        needs_regeneration = True
    if latest_batch and latest_survey and latest_batch.created_at < latest_survey.created_at:
        needs_regeneration = True

    if needs_regeneration:
        survey_context = latest_survey or build_default_survey_context(client.id)
        _, rows = persist_generated_batch(
            client=client,
            capture_record=latest_capture,
            survey=survey_context,
            analysis=latest_analysis,
        )
        return (str(rows[0].batch_id) if rows else None), rows, "generated"

    rows = list(
        FormerRecommendation.objects.filter(client=client, batch_id=latest_batch.batch_id).order_by("rank", "id")
    )
    return str(latest_batch.batch_id), rows, "generated"


def get_current_recommendations(client: Client) -> dict:
    latest_capture_attempt = get_latest_capture_attempt(client)
    latest_survey = get_latest_survey(client)
    latest_capture = get_latest_capture(client)
    latest_analysis = get_latest_analysis(client)

    if (
        latest_capture is None
        and latest_capture_attempt is not None
        and latest_capture_attempt.status in {"NEEDS_RETAKE", "FAILED"}
    ):
        return {
            "status": "needs_capture",
            "source": "current_recommendations",
            "recommendation_mode": "capture_required",
            "message": latest_capture_attempt.error_note or "Face detection did not succeed. Please retake a front-facing photo.",
            "next_action": "capture",
            "capture_required_for_full_result": True,
            "items": [],
        }

    if not latest_capture and not latest_survey:
        return {
            "status": "needs_input",
            "source": "current_recommendations",
            "recommendation_mode": "needs_input",
            "message": "No survey or capture data is available yet. Start with the survey or upload a capture.",
            "next_actions": ["survey", "capture"],
            "items": [],
        }

    batch_id, rows, status_code = _ensure_current_batch(client)
    if status_code == "needs_capture":
        return {
            "status": "needs_capture",
            "source": "current_recommendations",
            "recommendation_mode": "capture_required",
            "message": "Capture data is not ready yet. Please complete capture before requesting current recommendations.",
            "next_action": "capture",
            "capture_required_for_full_result": True,
            "items": [],
        }

    if not rows:
        return _build_empty_response(
            source="current_recommendations",
            message="No recommendation batch is available yet. Please retake the capture and try again.",
            next_action="capture",
        )

    if status_code == "survey_only":
        return {
            "status": "ready",
            "source": "current_recommendations",
            "recommendation_mode": "survey_only",
            "batch_id": batch_id,
            "message": "The current Top-5 recommendations were generated from survey data only. Adding a capture can improve personalization.",
            "next_actions": ["capture"],
            "capture_required_for_full_result": True,
            "items": [_serialize_row(row) for row in rows],
        }

    message = "The latest Top-5 recommendations were generated from the most recent capture and analysis."
    if latest_survey is None:
        message = "The latest Top-5 recommendations were generated from face analysis only because survey data is not available."

    return {
        "status": "ready",
        "source": "current_recommendations",
        "recommendation_mode": "capture_analysis",
        "batch_id": batch_id,
        "message": message,
        "capture_required_for_full_result": False,
        "items": [_serialize_row(row) for row in rows],
    }


def get_trend_recommendations(*, days: int = 30, client: Client | None = None) -> dict:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    target_age_profile = build_client_age_profile(client) if client else None
    selections = list(
        StyleSelection.objects.filter(created_at__gte=cutoff, is_sent_to_admin=True)
        .select_related("client")
        .order_by("-created_at")
    )
    scoped_selections = selections
    trend_scope = "global"
    if target_age_profile:
        exact_group_matches = [
            row
            for row in selections
            if client_matches_age_profile(row.client, age_group=target_age_profile["age_group"])
        ]
        decade_matches = [
            row
            for row in selections
            if client_matches_age_profile(row.client, age_decade=target_age_profile["age_decade"])
        ]
        if exact_group_matches:
            scoped_selections = exact_group_matches
            trend_scope = "age_group"
        elif decade_matches:
            scoped_selections = decade_matches
            trend_scope = "age_decade"

    popular_style_ids = []
    if scoped_selections:
        popular_style_ids = (
            StyleSelection.objects.filter(id__in=[row.id for row in scoped_selections])
            .values("style_id")
            .annotate(selection_count=Count("id"))
            .order_by("-selection_count", "style_id")[:5]
        )

    items: list[dict] = []
    for rank, item in enumerate(popular_style_ids, start=1):
        style = Style.objects.filter(id=item["style_id"]).first()
        if not style:
            continue
        trend_summary = f"recent confirmed selections in the last {days} days"
        if trend_scope == "age_group" and target_age_profile:
            trend_summary = f"{target_age_profile['age_group']} selections in the last {days} days"
        elif trend_scope == "age_decade" and target_age_profile:
            trend_summary = f"{target_age_profile['age_decade']} selections in the last {days} days"
        items.append(
            {
                "source": "trend",
                "style_id": style.id,
                "style_name": style.name,
                "style_description": style.description or f"This style has been selected frequently in the last {days} days.",
                "keywords": [style.vibe] if style.vibe else [],
                "sample_image_url": resolve_storage_reference(style.image_url),
                "simulation_image_url": resolve_storage_reference(style.image_url),
                "synthetic_image_url": resolve_storage_reference(style.image_url),
                "llm_explanation": style.description or f"This style has been selected frequently in the last {days} days.",
                "reasoning": f"Sorted by confirmed selection count over the last {days} days.",
                "reasoning_snapshot": {
                    "summary": trend_summary,
                    "selection_count": int(item["selection_count"]),
                    "days": days,
                    "source": "trend",
                    "trend_scope": trend_scope,
                    "age_profile": target_age_profile,
                },
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
                    "sample_image_url": resolve_storage_reference(style.image_url),
                    "simulation_image_url": resolve_storage_reference(style.image_url),
                    "synthetic_image_url": resolve_storage_reference(style.image_url),
                    "llm_explanation": "Recent confirmed-selection data is limited, so the default trend catalog is shown.",
                    "reasoning": "fallback trend catalog",
                    "reasoning_snapshot": {
                        "summary": "fallback trend catalog",
                        "selection_count": 0,
                        "days": days,
                        "source": "trend",
                        "trend_scope": trend_scope,
                        "age_profile": target_age_profile,
                    },
                    "match_score": 0.0,
                    "rank": rank,
                    "is_chosen": False,
                }
            )

    return {
        "status": "ready",
        "source": "trend",
        "recommendation_mode": "trend",
        "days": days,
        "trend_scope": trend_scope,
        "age_profile": target_age_profile,
        "items": items,
    }


def confirm_style_selection(
    *,
    client: Client,
    recommendation_id: int | None = None,
    style_id: int | None = None,
    admin_id: int | None = None,
    source: str = "current_recommendations",
    direct_consultation: bool = False,
) -> dict:
    latest_analysis = get_latest_analysis(client)
    survey_snapshot = build_survey_snapshot(client)
    analysis_snapshot = {}
    if latest_analysis:
        analysis_snapshot = {
            "face_shape": latest_analysis.face_shape,
            "golden_ratio": latest_analysis.golden_ratio_score,
            "image_url": resolve_storage_reference(latest_analysis.image_url),
            "landmark_snapshot": latest_analysis.landmark_snapshot,
        }

    selected_style = None
    selected_row = None
    admin = AdminAccount.objects.filter(id=admin_id).first() if admin_id else None
    if recommendation_id is not None:
        selected_row = FormerRecommendation.objects.filter(id=recommendation_id, client=client).first()
        if not selected_row:
            raise ValueError("The selected recommendation could not be found.")

        FormerRecommendation.objects.filter(client=client, batch_id=selected_row.batch_id).update(
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

    if recommendation_id is None and selected_style is not None and source == "current_recommendations":
        selected_row = (
            FormerRecommendation.objects.filter(
                client=client,
                source="generated",
                style_id_snapshot=selected_style.id,
            )
            .order_by("-created_at")
            .first()
        )
        if selected_row:
            FormerRecommendation.objects.filter(client=client, batch_id=selected_row.batch_id).update(
                is_chosen=False,
                chosen_at=None,
            )
            selected_row.is_chosen = True
            selected_row.chosen_at = timezone.now()
            selected_row.is_sent_to_admin = True
            selected_row.sent_at = timezone.now()
            selected_row.save(update_fields=["is_chosen", "chosen_at", "is_sent_to_admin", "sent_at"])

    if not direct_consultation and selected_style is None:
        raise ValueError("Style information is required to confirm a selection.")

    if recommendation_id is None and selected_style is not None and source == "trend":
        explanation = selected_style.description or "This style was selected from the current salon trend list."
        regeneration_snapshot = build_recommendation_regeneration_snapshot(
            client=client,
            survey=(get_latest_survey(client) or build_default_survey_context(client.id)),
            analysis=latest_analysis,
            source="trend",
        )
        selected_row = FormerRecommendation.objects.create(
            client=client,
            style=selected_style,
            batch_id=uuid.uuid4(),
            source="trend",
            style_id_snapshot=selected_style.id,
            style_name_snapshot=selected_style.name,
            style_description_snapshot=selected_style.description or "",
            keywords=[selected_style.vibe] if selected_style.vibe else [],
            sample_image_url=None,
            simulation_image_url=None,
            regeneration_snapshot=regeneration_snapshot,
            llm_explanation=explanation,
            reasoning_snapshot={
                "summary": "trend selection promoted to consultation",
                "source": "trend",
            },
            match_score=None,
            rank=1,
            is_chosen=not direct_consultation,
            chosen_at=(timezone.now() if not direct_consultation else None),
            is_sent_to_admin=True,
            sent_at=timezone.now(),
        )

    if not direct_consultation and selected_style is not None:
        StyleSelection.objects.create(
            client=client,
            selected_recommendation=selected_row,
            style_id=selected_style.id,
            source=source,
            survey_snapshot=survey_snapshot,
            match_score=(selected_row.match_score if selected_row else None),
            is_sent_to_admin=True,
        )

    ConsultationRequest.objects.filter(client=client, is_active=True).update(
        is_active=False,
        status="CLOSED",
        closed_at=timezone.now(),
        is_read=True,
    )

    consultation = ConsultationRequest.objects.create(
        client=client,
        selected_style=(None if direct_consultation else selected_style),
        selected_recommendation=selected_row,
        admin=admin,
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
        "consultation_status": consultation.status,
        "consultationStatus": consultation.status,
        "current_step": "consultation",
        "currentStep": "consultation",
        "interaction_status": "confirmed_waiting_admin",
        "interactionStatus": "confirmed_waiting_admin",
        "selected_style_id": (selected_style.id if selected_style else None),
        "selected_style_name": (selected_style.name if selected_style else None),
        "source": source,
        "direct_consultation": direct_consultation,
        "recommendation_id": (selected_row.id if selected_row else None),
        "message": (
            "A direct consultation request has been sent to the admin."
            if direct_consultation
            else "The selected style and analysis summary have been handed off to the admin."
        ),
    }


def _resolve_cancellable_recommendation(
    *,
    client: Client,
    recommendation_id: int | None = None,
) -> FormerRecommendation | None:
    if recommendation_id is not None:
        selected_row = FormerRecommendation.objects.filter(id=recommendation_id, client=client).first()
        if not selected_row:
            raise ValueError("The recommendation to cancel could not be found.")
        return selected_row

    active_consultation = (
        ConsultationRequest.objects.filter(client=client, is_active=True)
        .select_related("selected_recommendation")
        .order_by("-created_at")
        .first()
    )
    if active_consultation and active_consultation.selected_recommendation_id:
        return active_consultation.selected_recommendation

    return (
        FormerRecommendation.objects.filter(client=client, is_chosen=True)
        .order_by("-chosen_at", "-created_at")
        .first()
    )


def cancel_style_selection(
    *,
    client: Client,
    recommendation_id: int | None = None,
    source: str = "current_recommendations",
) -> dict:
    cancelled_at = timezone.now()
    selected_row = _resolve_cancellable_recommendation(
        client=client,
        recommendation_id=recommendation_id,
    )

    with transaction.atomic():
        ConsultationRequest.objects.filter(client=client, is_active=True).update(
            is_active=False,
            status="CANCELLED",
            closed_at=cancelled_at,
            is_read=True,
        )

        if selected_row is not None:
            FormerRecommendation.objects.filter(client=client, batch_id=selected_row.batch_id).update(
                is_chosen=False,
                chosen_at=None,
                is_sent_to_admin=False,
                sent_at=None,
            )
            updated_rows = StyleSelection.objects.filter(
                client=client,
                selected_recommendation=selected_row,
                is_sent_to_admin=True,
            ).update(is_sent_to_admin=False)
            if updated_rows == 0:
                latest_selection = (
                    StyleSelection.objects.filter(
                        client=client,
                        style_id=selected_row.style_id_snapshot,
                        is_sent_to_admin=True,
                    )
                    .order_by("-created_at")
                    .first()
                )
                if latest_selection is not None:
                    latest_selection.is_sent_to_admin = False
                    latest_selection.save(update_fields=["is_sent_to_admin"])

    return {
        "status": "cancelled",
        "client_id": client.id,
        "source": source,
        "next_action": "client_input",
        "nextAction": "client_input",
        "current_step": "client_input",
        "currentStep": "client_input",
        "interaction_status": "selection_cancelled",
        "interactionStatus": "selection_cancelled",
        "consultation_status": "CANCELLED",
        "consultationStatus": "CANCELLED",
        "message": "The selected style has been cancelled and the flow can return to the client input step.",
    }


def run_mirrai_analysis_pipeline(record_id: int, processed_bytes: bytes | None = None):
    try:
        with transaction.atomic():
            record = CaptureRecord.objects.select_for_update().get(id=record_id)
            if record.status != "PENDING":
                return

            record.status = "PROCESSING"
            record.save(update_fields=["status", "updated_at"])

        analysis_input_url = resolve_storage_reference(record.processed_path)
        simulated = simulate_face_analysis(
            image_url=analysis_input_url,
            image_bytes=(processed_bytes if record.processed_path is None else None),
        )
        analysis = FaceAnalysis.objects.create(
            client=record.client,
            face_shape=simulated["face_shape"],
            golden_ratio_score=simulated["golden_ratio_score"],
            image_url=record.processed_path,
            landmark_snapshot=record.landmark_snapshot or simulated.get("landmark_snapshot"),
        )

        survey = get_latest_survey(record.client) or build_default_survey_context(record.client_id)
        persist_generated_batch(client=record.client, capture_record=record, survey=survey, analysis=analysis)

        record.status = "DONE"
        record.save(update_fields=["status", "updated_at"])
        logger.info("[PIPELINE SUCCESS] Record %s processed.", record_id)

    except Exception as exc:
        logger.error("[PIPELINE ERROR] Record %s: %s", record_id, exc)
        CaptureRecord.objects.filter(id=record_id).update(status="FAILED", error_note=str(exc))

