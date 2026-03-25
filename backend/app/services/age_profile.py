from __future__ import annotations

from django.utils import timezone


MIN_SUPPORTED_AGE = 1
MAX_SUPPORTED_AGE = 120


def normalize_age_input(value) -> int:
    if value in (None, ""):
        raise ValueError("Age is required.")

    try:
        age = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Age must be a whole number.") from exc

    if age < MIN_SUPPORTED_AGE or age > MAX_SUPPORTED_AGE:
        raise ValueError(f"Age must be between {MIN_SUPPORTED_AGE} and {MAX_SUPPORTED_AGE}.")
    return age


def estimate_birth_year_from_age(age: int, *, reference_date=None) -> int:
    reference_date = reference_date or timezone.localdate()
    return int(reference_date.year) - int(age) + 1


def current_age_from_birth_year(birth_year_estimate: int | None, *, reference_date=None) -> int | None:
    if not birth_year_estimate:
        return None
    reference_date = reference_date or timezone.localdate()
    return int(reference_date.year) - int(birth_year_estimate) + 1


def age_decade_label(age: int | None) -> str | None:
    if age is None:
        return None
    decade = (int(age) // 10) * 10
    return f"{decade}대"


def age_segment_label(age: int | None) -> str | None:
    if age is None:
        return None
    tail = int(age) % 10
    if tail <= 3:
        return "초반"
    if tail <= 6:
        return "중반"
    return "후반"


def age_group_label(age: int | None) -> str | None:
    decade = age_decade_label(age)
    segment = age_segment_label(age)
    if not decade or not segment:
        return None
    return f"{decade} {segment}"


def build_age_profile(*, age: int | None = None, birth_year_estimate: int | None = None, reference_date=None) -> dict | None:
    current_age = age
    if current_age is None:
        current_age = current_age_from_birth_year(birth_year_estimate, reference_date=reference_date)
    if current_age is None:
        return None

    return {
        "current_age": int(current_age),
        "age_decade": age_decade_label(current_age),
        "age_segment": age_segment_label(current_age),
        "age_group": age_group_label(current_age),
    }


def build_client_age_profile(client, *, reference_date=None) -> dict | None:
    birth_year_estimate = getattr(client, "birth_year_estimate", None)
    age_input = getattr(client, "age_input", None)
    return build_age_profile(
        age=None if birth_year_estimate else age_input,
        birth_year_estimate=birth_year_estimate,
        reference_date=reference_date,
    )


def client_matches_age_profile(
    client,
    *,
    age_decade: str | None = None,
    age_segment: str | None = None,
    age_group: str | None = None,
) -> bool:
    profile = build_client_age_profile(client)
    if not profile:
        return False
    if age_group and profile["age_group"] != age_group:
        return False
    if age_decade and profile["age_decade"] != age_decade:
        return False
    if age_segment and profile["age_segment"] != age_segment:
        return False
    return True

