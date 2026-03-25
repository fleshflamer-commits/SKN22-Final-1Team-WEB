from dataclasses import dataclass
from typing import Iterable


FACE_WEIGHT = 40.0
RATIO_WEIGHT = 20.0
PREFERENCE_WEIGHT = 40.0
VECTOR_DIMENSION = 20


@dataclass(frozen=True)
class StyleProfile:
    style_id: int
    fallback_name: str
    fallback_description: str
    fallback_sample_image_url: str
    keywords: tuple[str, ...]
    face_shapes: tuple[str, ...]
    ratio_modes: tuple[str, ...]
    length_tags: tuple[str, ...]
    vibe_tags: tuple[str, ...]
    scalp_tags: tuple[str, ...]
    color_tags: tuple[str, ...]
    budget_tags: tuple[str, ...]


STYLE_CATALOG: tuple[StyleProfile, ...] = (
    StyleProfile(
        style_id=201,
        fallback_name="Side-Parted Lob",
        fallback_description="Rounded cheeks are balanced with a longer side silhouette.",
        fallback_sample_image_url="/media/styles/201.jpg",
        keywords=("lob", "side part", "balance"),
        face_shapes=("round", "oval"),
        ratio_modes=("cover", "balanced"),
        length_tags=("bob", "medium"),
        vibe_tags=("chic", "natural"),
        scalp_tags=("straight", "waved"),
        color_tags=("black", "brown", "ash"),
        budget_tags=("mid", "high"),
    ),
    StyleProfile(
        style_id=202,
        fallback_name="Textured C-Curl Bob",
        fallback_description="Soft texture helps reduce heaviness around the jaw line.",
        fallback_sample_image_url="/media/styles/202.jpg",
        keywords=("bob", "texture", "soft"),
        face_shapes=("round", "square", "oval"),
        ratio_modes=("cover", "balanced"),
        length_tags=("short", "bob"),
        vibe_tags=("natural", "cute"),
        scalp_tags=("straight", "damaged"),
        color_tags=("black", "brown"),
        budget_tags=("low", "mid"),
    ),
    StyleProfile(
        style_id=203,
        fallback_name="Soft Hush Layer",
        fallback_description="Layer placement adds movement while preserving a light front line.",
        fallback_sample_image_url="/media/styles/203.jpg",
        keywords=("layer", "soft", "movement"),
        face_shapes=("square", "long", "oval"),
        ratio_modes=("cover", "balanced"),
        length_tags=("medium", "long"),
        vibe_tags=("natural", "elegant"),
        scalp_tags=("waved", "curly", "damaged"),
        color_tags=("brown", "ash", "bleach"),
        budget_tags=("mid", "high"),
    ),
    StyleProfile(
        style_id=204,
        fallback_name="Sleek Mini Bob",
        fallback_description="A compact silhouette works best when facial balance is already strong.",
        fallback_sample_image_url="/media/styles/204.jpg",
        keywords=("mini bob", "sleek", "clean"),
        face_shapes=("oval", "long"),
        ratio_modes=("expose", "balanced"),
        length_tags=("short", "bob"),
        vibe_tags=("chic", "elegant"),
        scalp_tags=("straight",),
        color_tags=("black", "brown", "ash"),
        budget_tags=("mid", "high"),
    ),
    StyleProfile(
        style_id=205,
        fallback_name="Elegant S-Curl Medium",
        fallback_description="Front softness and side volume help soften strong contours.",
        fallback_sample_image_url="/media/styles/205.jpg",
        keywords=("s curl", "volume", "elegant"),
        face_shapes=("square", "triangle", "round"),
        ratio_modes=("cover", "balanced"),
        length_tags=("medium",),
        vibe_tags=("elegant", "natural"),
        scalp_tags=("waved", "curly"),
        color_tags=("brown", "ash"),
        budget_tags=("high",),
    ),
    StyleProfile(
        style_id=206,
        fallback_name="Full Layer Long Wave",
        fallback_description="Long layers give vertical flow while keeping side balance.",
        fallback_sample_image_url="/media/styles/206.jpg",
        keywords=("long wave", "layer", "flow"),
        face_shapes=("triangle", "square", "oval"),
        ratio_modes=("balanced", "expose"),
        length_tags=("long",),
        vibe_tags=("elegant", "natural"),
        scalp_tags=("waved", "curly"),
        color_tags=("brown", "ash", "bleach"),
        budget_tags=("high",),
    ),
    StyleProfile(
        style_id=207,
        fallback_name="Airy Short Bob",
        fallback_description="Airy volume around the crown reduces flatness without adding weight.",
        fallback_sample_image_url="/media/styles/207.jpg",
        keywords=("short bob", "airy", "crown volume"),
        face_shapes=("round", "square"),
        ratio_modes=("cover",),
        length_tags=("short", "bob"),
        vibe_tags=("cute", "natural"),
        scalp_tags=("straight", "damaged"),
        color_tags=("black", "brown"),
        budget_tags=("low", "mid"),
    ),
)


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def _contains_any(value: str, keywords: Iterable[str]) -> bool:
    return any(keyword in value for keyword in keywords)


def canonical_length(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("숏", "쇼트", "short")):
        return "short"
    if _contains_any(value, ("보브", "단발", "bob", "lob")):
        return "bob"
    if _contains_any(value, ("중단발", "미디", "medium", "semilong", "semi")):
        return "medium"
    if _contains_any(value, ("롱", "긴머리", "long")):
        return "long"
    return "unknown"


def canonical_vibe(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("청순", "큐트", "cute")):
        return "cute"
    if _contains_any(value, ("시크", "chic")):
        return "chic"
    if _contains_any(value, ("자연", "내추럴", "natural", "casual")):
        return "natural"
    if _contains_any(value, ("우아", "엘레강", "elegant", "섹시", "sexy")):
        return "elegant"
    return "unknown"


def canonical_scalp(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("직모", "straight")):
        return "straight"
    if _contains_any(value, ("웨이브", "wave")):
        return "waved"
    if _contains_any(value, ("곱슬", "curl")):
        return "curly"
    if _contains_any(value, ("손상", "damaged")):
        return "damaged"
    return "unknown"


def canonical_color(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("흑발", "검정", "black")):
        return "black"
    if _contains_any(value, ("브라운", "brown")):
        return "brown"
    if _contains_any(value, ("애쉬", "ash")):
        return "ash"
    if _contains_any(value, ("브리치", "탈색", "bleach")):
        return "bleach"
    return "unknown"


def canonical_budget(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("3만원이하", "3만이하", "below3")):
        return "low"
    if _contains_any(value, ("3만5만", "3만에서5만", "5만원이하", "from3to5")):
        return "mid"
    if _contains_any(value, ("5만10만", "5만에서10만", "10만원이하", "from5to10", "10만")):
        return "high"
    if _contains_any(value, ("10만원이상", "10만이상", "over10")):
        return "high"
    return "unknown"


def canonical_face_shape(value: str | None) -> str:
    value = _normalize_text(value)
    if _contains_any(value, ("둥근", "round")):
        return "round"
    if _contains_any(value, ("계란", "타원", "oval")):
        return "oval"
    if _contains_any(value, ("긴", "long")):
        return "long"
    if _contains_any(value, ("각진", "square")):
        return "square"
    if _contains_any(value, ("역삼각", "triangle", "heart")):
        return "triangle"
    return "unknown"


def build_preference_vector(
    *,
    target_length: str | None,
    target_vibe: str | None,
    scalp_type: str | None,
    hair_colour: str | None,
    budget_range: str | None,
) -> list[float]:
    vector: list[float] = []
    vector.extend(_one_hot(canonical_length(target_length), ("short", "bob", "medium", "long")))
    vector.extend(_one_hot(canonical_vibe(target_vibe), ("cute", "chic", "natural", "elegant")))
    vector.extend(_one_hot(canonical_scalp(scalp_type), ("straight", "waved", "curly", "damaged")))
    vector.extend(_one_hot(canonical_color(hair_colour), ("black", "brown", "ash", "bleach")))
    vector.extend(_one_hot(canonical_budget(budget_range), ("low", "mid", "high", "unknown")))
    return vector[:VECTOR_DIMENSION]


def _one_hot(value: str, order: tuple[str, ...]) -> list[float]:
    vector = [0.0] * len(order)
    if value in order:
        vector[order.index(value)] = 1.0
    return vector


def infer_ratio_mode(score: float | None) -> str:
    if score is None:
        return "balanced"
    if score >= 0.9:
        return "expose"
    if score >= 0.82:
        return "balanced"
    return "cover"


def ratio_message(score: float | None) -> str:
    mode = infer_ratio_mode(score)
    if mode == "expose":
        return "Your facial balance is strong enough to suit styles that reveal the face line more clearly."
    if mode == "cover":
        return "A style with softer framing will help balance the side line and contour."
    return "A balanced silhouette is likely to feel more natural than a highly exposed line."


def score_recommendations(*, survey, analysis, styles_by_id: dict[int, object] | None = None) -> list[dict]:
    styles_by_id = styles_by_id or {}
    face_shape = canonical_face_shape(getattr(analysis, "face_shape", None))
    ratio_score = getattr(analysis, "golden_ratio_score", None)
    ratio_mode = infer_ratio_mode(ratio_score)

    length_tag = canonical_length(getattr(survey, "target_length", None))
    vibe_tag = canonical_vibe(getattr(survey, "target_vibe", None))
    scalp_tag = canonical_scalp(getattr(survey, "scalp_type", None))
    color_tag = canonical_color(getattr(survey, "hair_colour", None))
    budget_tag = canonical_budget(getattr(survey, "budget_range", None))

    results: list[dict] = []

    for profile in STYLE_CATALOG:
        face_score = _score_face(face_shape, profile)
        ratio_component = _score_ratio(ratio_mode, profile)
        preference_score, match_labels = _score_preference(
            length_tag=length_tag,
            vibe_tag=vibe_tag,
            scalp_tag=scalp_tag,
            color_tag=color_tag,
            budget_tag=budget_tag,
            profile=profile,
        )
        penalty = _score_penalty(
            length_tag=length_tag,
            vibe_tag=vibe_tag,
            profile=profile,
            preference_score=preference_score,
        )
        total = max(0.0, min(100.0, round(face_score + ratio_component + preference_score - penalty, 1)))

        style_model = styles_by_id.get(profile.style_id)
        style_name = getattr(style_model, "name", None) or profile.fallback_name
        style_description = getattr(style_model, "description", None) or profile.fallback_description
        sample_image_url = getattr(style_model, "image_url", None) or profile.fallback_sample_image_url
        explanation = build_llm_explanation(
            style_name=style_name,
            style_description=style_description,
            face_shape=face_shape,
            matched_labels=match_labels,
            ratio_score=ratio_score,
        )

        client_key = getattr(survey, "client_id", getattr(survey, "client", "0"))
        results.append(
            {
                "source": "generated",
                "style_id": profile.style_id,
                "style_name": style_name,
                "style_description": style_description,
                "keywords": list(profile.keywords),
                "sample_image_url": sample_image_url,
                "simulation_image_url": f"/media/synthetic/{client_key}_{profile.style_id}.jpg",
                "synthetic_image_url": f"/media/synthetic/{client_key}_{profile.style_id}.jpg",
                "llm_explanation": explanation,
                "reasoning": f"face {face_score:.1f}/40 | ratio {ratio_component:.1f}/20 | preference {preference_score:.1f}/40"
                + (f" | penalty -{penalty:.1f}" if penalty else ""),
                "reasoning_snapshot": {
                    "summary": f"face {face_score:.1f}/40 | ratio {ratio_component:.1f}/20 | preference {preference_score:.1f}/40"
                    + (f" | penalty -{penalty:.1f}" if penalty else ""),
                    "face_shape": face_shape,
                    "ratio_mode": ratio_mode,
                    "face_score": round(face_score, 1),
                    "ratio_score": round(ratio_component, 1),
                    "preference_score": round(preference_score, 1),
                    "penalty": round(penalty, 1),
                    "total_score": total,
                    "matched_labels": match_labels,
                    "style_keywords": list(profile.keywords),
                },
                "match_score": total,
            }
        )

    results.sort(key=lambda item: (-item["match_score"], item["style_id"]))
    for rank, item in enumerate(results[:5], start=1):
        item["rank"] = rank
    return results[:5]


def build_llm_explanation(
    *,
    style_name: str,
    style_description: str,
    face_shape: str,
    matched_labels: list[str],
    ratio_score: float | None,
) -> str:
    face_label = {
        "round": "둥근형",
        "oval": "계란형",
        "long": "긴형",
        "square": "각진형",
        "triangle": "역삼각형",
        "unknown": "중립형",
    }.get(face_shape, "중립형")
    if matched_labels:
        preference_text = "The style also aligns well with your preference signals (" + ", ".join(matched_labels) + ")."
    else:
        preference_text = "Preference data is limited, so the face analysis score carries more weight in this result."
    return (
        f"{style_name} is recommended as a strong match for a {face_label} profile. "
        f"{style_description} {preference_text} {ratio_message(ratio_score)}"
    )


def _score_face(face_shape: str, profile: StyleProfile) -> float:
    baseline = 18.0
    if face_shape == "unknown":
        return baseline
    if face_shape in profile.face_shapes:
        return FACE_WEIGHT
    if "oval" in profile.face_shapes:
        return 22.0
    return baseline


def _score_ratio(ratio_mode: str, profile: StyleProfile) -> float:
    if ratio_mode in profile.ratio_modes:
        return RATIO_WEIGHT
    if "balanced" in profile.ratio_modes:
        return 12.0
    return 8.0


def _score_preference(
    *,
    length_tag: str,
    vibe_tag: str,
    scalp_tag: str,
    color_tag: str,
    budget_tag: str,
    profile: StyleProfile,
) -> tuple[float, list[str]]:
    score = 0.0
    labels: list[str] = []

    if length_tag in profile.length_tags:
        score += 14.0
        labels.append("length")
    if vibe_tag in profile.vibe_tags:
        score += 12.0
        labels.append("vibe")
    if scalp_tag in profile.scalp_tags:
        score += 6.0
        labels.append("condition")
    if color_tag in profile.color_tags:
        score += 4.0
        labels.append("color")
    if budget_tag in profile.budget_tags:
        score += 4.0
        labels.append("budget")

    return min(PREFERENCE_WEIGHT, score), labels


def _score_penalty(*, length_tag: str, vibe_tag: str, profile: StyleProfile, preference_score: float) -> float:
    penalty = 0.0
    if length_tag != "unknown" and length_tag not in profile.length_tags:
        penalty += 6.0
    if vibe_tag != "unknown" and vibe_tag not in profile.vibe_tags:
        penalty += 4.0
    if preference_score < 10.0:
        penalty += 2.0
    return penalty

