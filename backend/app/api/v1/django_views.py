import io
import threading

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, ImageOps
from rest_framework import exceptions, parsers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from app.api.v1.client_auth import TOKEN_MAX_AGE_SECONDS, ClientTokenAuthentication, build_client_token
from app.api.v1.django_serializers import (
    ClientCheckSerializer,
    ClientRegisterSerializer,
    ClientSerializer,
    RecommendationListResponseSerializer,
    SurveySerializer,
)
from app.api.v1.services_django import (
    cancel_style_selection,
    confirm_style_selection,
    get_current_recommendations,
    get_former_recommendations,
    get_trend_recommendations,
    regenerate_recommendation_simulation,
    run_mirrai_analysis_pipeline,
    serialize_capture_status,
    upsert_survey,
)
from app.models_django import CaptureRecord, Client
from app.services.age_profile import build_client_age_profile
from app.services.capture_validation import sanitize_original_upload, validate_capture_image
from app.services.face_processing import build_deidentified_capture, extract_landmark_snapshot
from app.services.storage_service import store_capture_assets


def _serialize_client_summary(client: Client) -> dict:
    return ClientSerializer(client).data


def _serialize_client_auth_payload(client: Client, *, include_token: bool = True) -> dict:
    age_profile = build_client_age_profile(client) or {}
    payload = {
        "status": "success",
        "is_authenticated": True,
        "is_existing": True,
        "client_id": client.id,
        "name": client.name,
        "gender": client.gender,
        "phone": client.phone,
        "age": age_profile.get("current_age"),
        "age_decade": age_profile.get("age_decade"),
        "age_segment": age_profile.get("age_segment"),
        "age_group": age_profile.get("age_group"),
        "image_storage_consent": client.image_storage_consent,
        "image_storage_consented_at": client.image_storage_consented_at,
        "next_action": "dashboard",
        "nextAction": "dashboard",
        "client": _serialize_client_summary(client),
        "clientSummary": _serialize_client_summary(client),
    }
    if include_token:
        payload.update(
            {
                "access_token": build_client_token(client=client),
                "token_type": "bearer",
                "expires_in": TOKEN_MAX_AGE_SECONDS,
            }
        )
    return payload


def _parse_bool_value(raw_value, *, default: bool | None = None) -> bool | None:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value

    value = str(raw_value).strip().lower()
    if value in {"true", "1", "yes", "y", "on"}:
        return True
    if value in {"false", "0", "no", "n", "off"}:
        return False
    raise exceptions.ValidationError("Boolean input is not valid.")


def _resolve_client_from_request(request, *, client_id=None, required: bool = True) -> Client | None:
    authenticated_client = getattr(request, "user", None)
    if isinstance(authenticated_client, Client):
        if client_id is not None and str(authenticated_client.id) != str(client_id):
            raise exceptions.PermissionDenied("The authenticated client does not match the requested client.")
        return authenticated_client

    if settings.MIRRAI_REQUIRE_CLIENT_AUTH:
        raise exceptions.NotAuthenticated("Client authentication is required.")

    if client_id in (None, ""):
        if required:
            raise exceptions.ValidationError({"client_id": "client_id is required."})
        return None
    return get_object_or_404(Client, id=client_id)


def _normalize_survey_payload(payload: dict) -> dict:
    normalized = dict(payload)
    selections = normalized.get("selections")
    if not isinstance(selections, dict):
        return normalized

    alias_map = {
        "target_length": "target_length",
        "length": "target_length",
        "target_vibe": "target_vibe",
        "vibe": "target_vibe",
        "scalp_type": "scalp_type",
        "hair_condition": "scalp_type",
        "hair_colour": "hair_colour",
        "hair_color": "hair_colour",
        "color": "hair_colour",
        "budget_range": "budget_range",
        "budget": "budget_range",
    }

    for raw_key, raw_value in selections.items():
        key = alias_map.get(str(raw_key).strip().lower())
        if key and not normalized.get(key):
            normalized[key] = raw_value

    # Frontend currently keeps survey answers as a generic ordered selections object.
    # When explicit field names are absent, preserve the UI order for backend mapping.
    ordered_values = [value for value in selections.values()]
    ordered_targets = [
        "target_length",
        "target_vibe",
        "scalp_type",
        "hair_colour",
        "budget_range",
    ]
    for target_key, raw_value in zip(ordered_targets, ordered_values):
        if not normalized.get(target_key):
            normalized[target_key] = raw_value

    normalized["selection_snapshot"] = selections

    return normalized


class ClientContextAPIView(APIView):
    authentication_classes = [ClientTokenAuthentication]


class LoginView(ClientContextAPIView):
    @extend_schema(
        summary="Log in client",
        request={
            "application/json": {
                "type": "object",
                "properties": {"phone": {"type": "string", "example": "010-9999-8888"}},
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        if not phone:
            return Response({"detail": "Phone number is required."}, status=status.HTTP_400_BAD_REQUEST)

        client = Client.objects.filter(phone=phone).first()
        if not client:
            return Response({"detail": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(_serialize_client_auth_payload(client))


class ClientCheckView(ClientContextAPIView):
    @extend_schema(summary="Check existing client", request=ClientCheckSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        client = Client.objects.filter(phone=phone).first()
        if not client:
            return Response(
                {
                    "status": "empty",
                    "is_authenticated": False,
                    "is_existing": False,
                    "next_action": "register",
                    "nextAction": "register",
                }
            )

        return Response(_serialize_client_auth_payload(client, include_token=False))


class RegisterView(ClientContextAPIView):
    @extend_schema(summary="Register new client", request=ClientRegisterSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        if Client.objects.filter(phone=phone).exists():
            return Response({"detail": "This phone number is already registered."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ClientRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = serializer.save(phone=phone)

        return Response(
            {
                "status": "success",
                **_serialize_client_auth_payload(client),
            },
            status=status.HTTP_201_CREATED,
        )


class ClientProfileView(ClientContextAPIView):
    @extend_schema(summary="Get current client profile", responses={200: ClientSerializer})
    def get(self, request):
        client = _resolve_client_from_request(request, required=True)
        return Response(_serialize_client_auth_payload(client, include_token=False))


class SurveyView(ClientContextAPIView):
    @extend_schema(summary="Submit client survey", request=SurveySerializer, responses={200: SurveySerializer})
    def post(self, request):
        payload = _normalize_survey_payload(request.data)
        client_id = payload.get("client") or payload.get("client_id")
        client = _resolve_client_from_request(request, client_id=client_id)
        survey = upsert_survey(client, payload)
        response_payload = SurveySerializer(survey).data
        response_payload["status"] = "success"
        response_payload["next_action"] = "recommendation"
        response_payload["selection_snapshot"] = payload.get("selection_snapshot", {})
        return Response(response_payload)


class CaptureUploadView(ClientContextAPIView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    @extend_schema(
        summary="Upload client capture",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "file": {"type": "string", "format": "binary"},
                    "image_storage_consent": {"type": "boolean"},
                },
                "required": ["client_id", "file"],
            }
        },
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client_id = request.data.get("client_id")
        client = _resolve_client_from_request(request, client_id=client_id)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "Image file is required."}, status=status.HTTP_400_BAD_REQUEST)

        original_bytes = file_obj.read()
        original_ext = "." + file_obj.name.split(".")[-1] if "." in file_obj.name else ".jpg"
        try:
            with Image.open(io.BytesIO(original_bytes)) as image:
                image = ImageOps.exif_transpose(image)
                sanitized_original_bytes, sanitized_ext = sanitize_original_upload(
                    image=image,
                    original_ext=original_ext,
                )
                processed_buffer = io.BytesIO()
                image.convert("RGB").save(processed_buffer, "JPEG")
                processed_bytes = processed_buffer.getvalue()
        except OSError:
            return Response({"detail": "Unsupported or invalid image file."}, status=status.HTTP_400_BAD_REQUEST)

        consent_override = _parse_bool_value(
            request.data.get("image_storage_consent", request.data.get("agree_image_storage")),
            default=None,
        )
        if consent_override is not None:
            client.image_storage_consent = consent_override
            client.image_storage_consented_at = timezone.now() if consent_override else None
            client.save(update_fields=["image_storage_consent", "image_storage_consented_at"])

        validation = validate_capture_image(processed_bytes=processed_bytes)
        landmark_snapshot = extract_landmark_snapshot(processed_bytes=processed_bytes)
        should_persist_capture_images = settings.MIRRAI_PERSIST_CAPTURE_IMAGES and client.image_storage_consent

        if should_persist_capture_images:
            deidentified_bytes, privacy_snapshot = build_deidentified_capture(
                processed_bytes=processed_bytes,
                landmark_snapshot=landmark_snapshot,
            )
            stored_filename, original_path, processed_path, deidentified_path = store_capture_assets(
                original_name=file_obj.name,
                original_bytes=sanitized_original_bytes,
                processed_bytes=processed_bytes,
                original_ext=sanitized_ext,
                deidentified_bytes=deidentified_bytes,
            )
            privacy_snapshot = {
                **privacy_snapshot,
                "storage_policy": "asset_store",
                "client_image_storage_consent": True,
                "consent_source": "client_profile",
            }
        else:
            stored_filename = None
            original_path = None
            processed_path = None
            deidentified_path = None
            privacy_snapshot = {
                "metadata_removed": True,
                "deidentification_applied": False,
                "storage_policy": "vector_only",
                "persisted_assets": [],
                "reason": (
                    "capture_images_not_persisted"
                    if not settings.MIRRAI_PERSIST_CAPTURE_IMAGES
                    else "client_no_image_storage_consent"
                ),
                "client_image_storage_consent": bool(client.image_storage_consent),
                "consent_source": "client_profile",
            }

        record = CaptureRecord.objects.create(
            client=client,
            original_path=original_path,
            processed_path=processed_path,
            filename=stored_filename,
            status=validation["status"],
            face_count=validation["face_count"],
            landmark_snapshot=landmark_snapshot,
            deidentified_path=deidentified_path,
            privacy_snapshot=privacy_snapshot,
            error_note=(None if validation["is_valid"] else validation["message"]),
        )

        if not validation["is_valid"]:
            return Response(
                {
                    "status": "needs_retake",
                    "record_id": record.id,
                    "face_count": validation["face_count"],
                    "reason_code": validation["reason_code"],
                    "message": validation["message"],
                    "next_action": "capture",
                    "privacy_snapshot": privacy_snapshot,
                }
            )

        thread_args = (record.id,)
        thread_kwargs = {}
        if not should_persist_capture_images:
            thread_kwargs["processed_bytes"] = processed_bytes
        threading.Thread(
            target=run_mirrai_analysis_pipeline,
            args=thread_args,
            kwargs=thread_kwargs,
            daemon=True,
        ).start()
        return Response(
            {
                "status": "success",
                "record_id": record.id,
                "face_count": validation["face_count"],
                "message": validation["message"],
                "privacy_snapshot": privacy_snapshot,
            }
        )


class CaptureStatusView(ClientContextAPIView):
    @extend_schema(
        summary="Get capture processing status",
        parameters=[OpenApiParameter("record_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        record = get_object_or_404(CaptureRecord, id=request.query_params.get("record_id"))
        _resolve_client_from_request(request, client_id=record.client_id)
        return Response(serialize_capture_status(record))


class FormerRecommendationView(ClientContextAPIView):
    @extend_schema(
        summary="Get former recommendation history",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        client_id = request.query_params.get("client_id")
        client = _resolve_client_from_request(request, client_id=client_id)
        return Response(get_former_recommendations(client))


class RecommendationView(ClientContextAPIView):
    @extend_schema(
        summary="Get current recommendations",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        client_id = request.query_params.get("client_id")
        client = _resolve_client_from_request(request, client_id=client_id)
        return Response(get_current_recommendations(client))


class TrendView(ClientContextAPIView):
    @extend_schema(
        summary="Get trend-based style recommendations",
        parameters=[
            OpenApiParameter("days", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        days = int(request.query_params.get("days", 30))
        client_id = request.query_params.get("client_id")
        client = _resolve_client_from_request(request, client_id=client_id, required=False) if client_id else None
        return Response(get_trend_recommendations(days=days, client=client))


class ConfirmView(ClientContextAPIView):
    @extend_schema(
        summary="Confirm selected style and hand off to admin",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "recommendation_id": {"type": "integer"},
                    "style_id": {"type": "integer"},
                    "admin_id": {"type": "integer"},
                    "source": {"type": "string", "example": "current_recommendations"},
                    "direct_consultation": {"type": "boolean", "default": False},
                },
                "required": ["client_id"],
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client = _resolve_client_from_request(request, client_id=request.data.get("client_id"))
        try:
            payload = confirm_style_selection(
                client=client,
                recommendation_id=request.data.get("recommendation_id"),
                style_id=request.data.get("style_id"),
                admin_id=request.data.get("admin_id"),
                source=request.data.get("source", "current_recommendations"),
                direct_consultation=bool(request.data.get("direct_consultation", False)),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class CancelView(ClientContextAPIView):
    @extend_schema(
        summary="Cancel selected style and return to client input",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "recommendation_id": {"type": "integer"},
                    "source": {"type": "string", "example": "current_recommendations"},
                },
                "required": ["client_id"],
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client = _resolve_client_from_request(request, client_id=request.data.get("client_id"))
        try:
            payload = cancel_style_selection(
                client=client,
                recommendation_id=request.data.get("recommendation_id"),
                source=request.data.get("source", "current_recommendations"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class RegenerateSimulationView(ClientContextAPIView):
    @extend_schema(
        summary="Regenerate simulation preview from stored vector snapshot",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "recommendation_id": {"type": "integer"},
                },
                "required": ["client_id", "recommendation_id"],
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client = _resolve_client_from_request(request, client_id=request.data.get("client_id"))
        try:
            recommendation_id = int(request.data.get("recommendation_id"))
            payload = regenerate_recommendation_simulation(
                client=client,
                recommendation_id=recommendation_id,
            )
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class ConsultView(ConfirmView):
    pass
