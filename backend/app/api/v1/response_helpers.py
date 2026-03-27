from __future__ import annotations

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import APIView


ERROR_CONTRACT_FIELDS = ["error_code", "message", "detail"]


def get_error_contract_snapshot() -> dict:
    return {
        "mode": "compat_envelope",
        "fields": ERROR_CONTRACT_FIELDS,
        "detail_compatibility": True,
        "validation_detail_supported": True,
        "envelope_supported": True,
    }


def error_response(
    message: str,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    error_code: str = "bad_request",
    detail: object | None = None,
    **extra: object,
) -> Response:
    payload = {
        "error_code": error_code,
        "message": message,
        "detail": detail if detail is not None else message,
    }
    payload.update(extra)
    return Response(payload, status=status_code)


def detail_response(
    message: str,
    *,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    error_code: str = "bad_request",
    **extra: object,
) -> Response:
    return error_response(
        message,
        status_code=status_code,
        error_code=error_code,
        detail=extra.pop("detail", None),
        **extra,
    )


def validation_error_response(
    detail: object,
    *,
    message: str = "Validation failed.",
    error_code: str = "validation_error",
    status_code: int = status.HTTP_400_BAD_REQUEST,
    **extra: object,
) -> Response:
    return error_response(
        message,
        status_code=status_code,
        error_code=error_code,
        detail=detail,
        **extra,
    )


def exception_to_error_response(exc: Exception) -> Response | None:
    if isinstance(exc, exceptions.ValidationError):
        return validation_error_response(exc.detail)

    if isinstance(exc, exceptions.AuthenticationFailed):
        return error_response(
            str(exc.detail),
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="authentication_failed",
            detail=exc.detail,
        )

    if isinstance(exc, exceptions.NotAuthenticated):
        return error_response(
            str(exc.detail),
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="not_authenticated",
            detail=exc.detail,
        )

    if isinstance(exc, exceptions.PermissionDenied):
        return error_response(
            str(exc.detail),
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="permission_denied",
            detail=exc.detail,
        )

    if isinstance(exc, exceptions.NotFound):
        return error_response(
            str(exc.detail),
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
            detail=exc.detail,
        )

    if isinstance(exc, exceptions.ParseError):
        return error_response(
            str(exc.detail),
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="parse_error",
            detail=exc.detail,
        )

    return None


class CompatEnvelopeAPIView(APIView):
    def handle_exception(self, exc):
        response = exception_to_error_response(exc)
        if response is not None:
            response.exception = True
            return response
        return super().handle_exception(exc)
