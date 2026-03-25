from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

from app.api.v1.recommendation_logic import score_recommendations


app = FastAPI(title="MirrAI Internal AI Service")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version="1.1.0",
        description="Internal AI service for MirrAI recommendation generation and explanation.",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


class AnalyzeFaceRequest(BaseModel):
    image_url: str | None = None
    image_base64: str | None = None


class AnalyzeFaceResponse(BaseModel):
    face_shape: str
    golden_ratio_score: float
    image_url: str | None = None


class GenerateSimulationsRequest(BaseModel):
    client_id: int
    survey_data: dict = Field(default_factory=dict)
    analysis_data: dict


class GenerateSimulationsResponse(BaseModel):
    status: str
    items: list[dict]


class ExplainStyleRequest(BaseModel):
    card: dict


class ExplainStyleResponse(BaseModel):
    style_id: int | None = None
    style_name: str | None = None
    sample_image_url: str | None = None
    simulation_image_url: str | None = None
    llm_explanation: str | None = None
    keywords: list[str] = Field(default_factory=list)


def _simulate_face_analysis(image_url: str | None = None, image_base64: str | None = None) -> dict:
    return {
        "face_shape": "Oval",
        "golden_ratio_score": 0.92,
        "image_url": image_url,
    }


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "mirrai-internal-ai",
        "message": "Internal AI service for analysis and recommendation generation.",
    }


@app.get("/internal/health")
async def internal_health():
    return {"status": "ok", "role": "ai-microservice"}


@app.post("/internal/analyze-face", response_model=AnalyzeFaceResponse)
async def analyze_face(payload: AnalyzeFaceRequest):
    return _simulate_face_analysis(image_url=payload.image_url, image_base64=payload.image_base64)


@app.post("/internal/generate-simulations", response_model=GenerateSimulationsResponse)
async def generate_simulations(payload: GenerateSimulationsRequest):
    survey = SimpleNamespace(client_id=payload.client_id, **(payload.survey_data or {}))
    analysis = SimpleNamespace(**payload.analysis_data)
    items = score_recommendations(survey=survey, analysis=analysis)
    return {"status": "ready", "items": items}


@app.post("/internal/explain-style", response_model=ExplainStyleResponse)
async def explain_style(payload: ExplainStyleRequest):
    card = payload.card or {}
    return {
        "style_id": card.get("style_id"),
        "style_name": card.get("style_name"),
        "sample_image_url": card.get("sample_image_url"),
        "simulation_image_url": card.get("simulation_image_url"),
        "llm_explanation": card.get("llm_explanation"),
        "keywords": card.get("keywords", []),
    }

