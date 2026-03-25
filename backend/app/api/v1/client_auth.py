from __future__ import annotations

from django.conf import settings
from django.core import signing
from rest_framework import authentication
from rest_framework import exceptions

from app.models_django import Client


TOKEN_SALT = "mirrai.client.auth.v1"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


def build_client_token(*, client: Client) -> str:
    payload = {
        "type": "client",
        "client_id": client.id,
        "phone": client.phone,
    }
    return signing.dumps(
        payload,
        key=settings.SECRET_KEY,
        salt=TOKEN_SALT,
        compress=True,
    )


def decode_client_token(token: str) -> dict:
    try:
        payload = signing.loads(
            token,
            key=settings.SECRET_KEY,
            salt=TOKEN_SALT,
            max_age=TOKEN_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise exceptions.AuthenticationFailed("Client token expired.") from exc
    except signing.BadSignature as exc:
        raise exceptions.AuthenticationFailed("Invalid client token.") from exc

    if payload.get("type") != "client":
        raise exceptions.AuthenticationFailed("Unsupported token type.")
    return payload


class ClientTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).decode("utf-8").strip()
        if not auth_header:
            return None

        keyword, _, token = auth_header.partition(" ")
        if keyword.lower() != self.keyword.lower() or not token:
            raise exceptions.AuthenticationFailed("Authorization header must use Bearer token.")

        payload = decode_client_token(token)
        client = Client.objects.filter(id=payload["client_id"]).first()
        if client is None:
            raise exceptions.AuthenticationFailed("Client account not found.")
        return client, payload
