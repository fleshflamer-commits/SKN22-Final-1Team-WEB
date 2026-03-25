import json
import logging
import os
import base64
from types import SimpleNamespace
from urllib import error, request

from app.api.v1.recommendation_logic import score_recommendations


logger = logging.getLogger(__name__)


def _service_base_url() -> str:
    return os.environ.get("MIRRAI_AI_SERVICE_URL", "").rstrip("/")


def _post_json(path: str, payload: dict) -> dict | None:
    base_url = _service_base_url()
    if not base_url:
        return None

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Falling back to local AI facade after remote call failure: %s", exc)
        return None


def simulate_face_analysis(*, image_url: str | None = None, image_bytes: bytes | None = None) -> dict:
    payload = {"image_url": image_url}
    if image_bytes is not None:
        payload["image_base64"] = base64.b64encode(image_bytes).decode("ascii")
    remote = _post_json("/internal/analyze-face", payload)
    if remote:
        return remote
    return {
        "face_shape": "Oval",
        "golden_ratio_score": 0.92,
        "image_url": image_url,
    }


def generate_recommendation_batch(
    *,
    client_id: int,
    survey_data: dict | None,
    analysis_data: dict,
    styles_by_id: dict[int, object] | None = None,
) -> list[dict]:
    remote = _post_json(
        "/internal/generate-simulations",
        {
            "client_id": client_id,
            "survey_data": survey_data or {},
            "analysis_data": analysis_data,
        },
    )
    if remote and isinstance(remote.get("items"), list):
        return remote["items"]

    survey = SimpleNamespace(client_id=client_id, **(survey_data or {}))
    analysis = SimpleNamespace(**analysis_data)
    return score_recommendations(survey=survey, analysis=analysis, styles_by_id=styles_by_id)


def explain_style(*, card: dict) -> dict:
    remote = _post_json("/internal/explain-style", {"card": card})
    if remote:
        return remote
    return {
        "style_id": card.get("style_id"),
        "style_name": card.get("style_name"),
        "sample_image_url": card.get("sample_image_url"),
        "simulation_image_url": card.get("simulation_image_url"),
        "llm_explanation": card.get("llm_explanation"),
        "keywords": card.get("keywords", []),
    }

