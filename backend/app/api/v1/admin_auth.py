from __future__ import annotations

from django.conf import settings
from django.core import signing
from rest_framework import authentication
from rest_framework import exceptions
from rest_framework.permissions import BasePermission

from app.models_django import AdminAccount


TOKEN_SALT = "mirrai.admin.auth.v1"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 12


def build_admin_token(*, admin: AdminAccount) -> str:
    payload = {
        "type": "admin",
        "admin_id": admin.id,
        "role": admin.role,
        "store_name": admin.store_name,
    }
    return signing.dumps(
        payload,
        key=settings.SECRET_KEY,
        salt=TOKEN_SALT,
        compress=True,
    )


def decode_admin_token(token: str) -> dict:
    try:
        payload = signing.loads(
            token,
            key=settings.SECRET_KEY,
            salt=TOKEN_SALT,
            max_age=TOKEN_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise exceptions.AuthenticationFailed("Admin token expired.") from exc
    except signing.BadSignature as exc:
        raise exceptions.AuthenticationFailed("Invalid admin token.") from exc

    if payload.get("type") != "admin":
        raise exceptions.AuthenticationFailed("Unsupported token type.")
    return payload


class AdminTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).decode("utf-8").strip()
        if not auth_header:
            return None

        keyword, _, token = auth_header.partition(" ")
        if keyword.lower() != self.keyword.lower() or not token:
            raise exceptions.AuthenticationFailed("Authorization header must use Bearer token.")

        payload = decode_admin_token(token)
        admin = AdminAccount.objects.filter(id=payload["admin_id"], is_active=True).first()
        if admin is None:
            raise exceptions.AuthenticationFailed("Admin account not found.")
        return admin, payload


class IsAuthenticatedAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        return isinstance(getattr(request, "user", None), AdminAccount)
