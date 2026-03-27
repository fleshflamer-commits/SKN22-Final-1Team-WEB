import io
import threading

from django.conf import settings
from django.shortcuts import get_object_or_404
from PIL import Image, ImageOps
from rest_framework import parsers, status
from rest_framework.response import Response

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from app.api.v1.admin_auth import issue_client_token_pair, refresh_client_access_token
from app.api.v1.response_helpers import CompatEnvelopeAPIView, detail_response
from app.api.v1.django_serializers import (
    ClientCheckSerializer,
    ClientRegisterSerializer,
    RegenerateSimulationRequestSerializer,
    RecommendationListResponseSerializer,
    RetryRecommendationRequestSerializer,
    SurveySerializer,
    TokenRefreshSerializer,
)
from app.api.v1.services_django import (
    cancel_style_selection,
    confirm_style_selection,
    get_current_recommendations,
    get_former_recommendations,
    get_trend_recommendations,
    regenerate_recommendation_simulation,
    retry_current_recommendations,
    run_mirrai_analysis_pipeline,
    serialize_capture_status,
    upsert_survey,
)
from app.models_django import CaptureRecord, Client
from app.services.age_profile import build_client_age_profile
from app.services.capture_validation import sanitize_original_upload, validate_capture_image
from app.services.face_processing import build_deidentified_capture, extract_landmark_snapshot
from app.services.storage_service import store_capture_assets


def _request_value(request, *keys: str):
    for key in keys:
        value = request.data.get(key)
        if value not in (None, ""):
            return value
    return None


def _query_value(request, *keys: str):
    for key in keys:
        value = request.query_params.get(key)
        if value not in (None, ""):
            return value
    return None


class LoginView(CompatEnvelopeAPIView):
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
            return detail_response("Phone number is required.", status_code=status.HTTP_400_BAD_REQUEST)

        client = Client.objects.filter(phone=phone).first()
        if not client:
            return detail_response("Client not found.", status_code=status.HTTP_404_NOT_FOUND)

        age_profile = build_client_age_profile(client) or {}
        return Response(
            {
                "client_id": client.id,
                "age": age_profile.get("current_age"),
                "age_decade": age_profile.get("age_decade"),
                "age_segment": age_profile.get("age_segment"),
                "age_group": age_profile.get("age_group"),
                **issue_client_token_pair(client=client),
            }
        )


class ClientRefreshView(CompatEnvelopeAPIView):
    @extend_schema(summary="Refresh client token", request=TokenRefreshSerializer, responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = refresh_client_access_token(refresh_token=serializer.validated_data["refresh_token"])
        except Exception as exc:
            return detail_response(
                str(exc),
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="authentication_failed",
            )
        return Response(payload)


class ClientCheckView(CompatEnvelopeAPIView):
    @extend_schema(summary="Check existing client", request=ClientCheckSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        client = Client.objects.filter(phone=phone).first()
        if not client:
            return Response({"is_existing": False})

        age_profile = build_client_age_profile(client) or {}
        return Response(
            {
                "is_existing": True,
                "name": client.name,
                "gender": client.gender,
                "client_id": client.id,
                "age": age_profile.get("current_age"),
                "age_decade": age_profile.get("age_decade"),
                "age_segment": age_profile.get("age_segment"),
                "age_group": age_profile.get("age_group"),
            }
        )


class RegisterView(CompatEnvelopeAPIView):
    @extend_schema(summary="Register new client", request=ClientRegisterSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        if Client.objects.filter(phone=phone).exists():
            return detail_response(
                "This phone number is already registered.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="validation_error",
            )

        serializer = ClientRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = serializer.save(phone=phone)

        age_profile = build_client_age_profile(client) or {}
        return Response(
            {
                "status": "success",
                "client_id": client.id,
                "age": age_profile.get("current_age"),
                "age_decade": age_profile.get("age_decade"),
                "age_segment": age_profile.get("age_segment"),
                "age_group": age_profile.get("age_group"),
                **issue_client_token_pair(client=client),
            },
            status=status.HTTP_201_CREATED,
        )


class SurveyView(CompatEnvelopeAPIView):
    @extend_schema(summary="Submit client survey", request=SurveySerializer, responses={200: SurveySerializer})
    def post(self, request):
        client_id = _request_value(request, "client", "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        survey = upsert_survey(client, request.data)
        return Response(SurveySerializer(survey).data)


class CaptureUploadView(CompatEnvelopeAPIView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    @extend_schema(
        summary="Upload client capture",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "file": {"type": "string", "format": "binary"},
                },
                "required": ["client_id", "file"],
            }
        },
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client_id = _request_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return detail_response("Image file is required.", status_code=status.HTTP_400_BAD_REQUEST)

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
            return detail_response("Unsupported or invalid image file.", status_code=status.HTTP_400_BAD_REQUEST)

        validation = validate_capture_image(processed_bytes=processed_bytes)
        landmark_snapshot = extract_landmark_snapshot(processed_bytes=processed_bytes)
        if settings.MIRRAI_PERSIST_CAPTURE_IMAGES:
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
                "reason": "capture_images_not_persisted",
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
        if not settings.MIRRAI_PERSIST_CAPTURE_IMAGES:
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


class CaptureStatusView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Get capture processing status",
        parameters=[OpenApiParameter("record_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        record = get_object_or_404(CaptureRecord, id=request.query_params.get("record_id"))
        return Response(serialize_capture_status(record))


class FormerRecommendationView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Get former recommendation history",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        client_id = _query_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        payload = get_former_recommendations(client)
        if request.query_params.get("customer_id"):
            return Response(payload.get("items", []))
        return Response(payload)


class RecommendationView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Get current recommendations",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        client_id = _query_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        payload = get_current_recommendations(client)
        if request.query_params.get("customer_id"):
            return Response(payload.get("items", []))
        return Response(payload)


class TrendView(CompatEnvelopeAPIView):
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
        client_id = _query_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id) if client_id else None
        return Response(get_trend_recommendations(days=days, client=client))


class RegenerateSimulationView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Regenerate simulation payload from vector-only snapshot",
        request=RegenerateSimulationRequestSerializer,
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        serializer = RegenerateSimulationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = regenerate_recommendation_simulation(**serializer.validated_data)
        except ValueError as exc:
            return detail_response(str(exc), status_code=status.HTTP_400_BAD_REQUEST, error_code="validation_error")
        return Response(payload)


class RetryRecommendationView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Retry the current recommendation batch once with preference-first scoring",
        request=RetryRecommendationRequestSerializer,
        responses={200: RecommendationListResponseSerializer, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        serializer = RetryRecommendationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client_id = serializer.validated_data.get("client_id") or serializer.validated_data.get("customer_id")
        if not client_id:
            return detail_response(
                "client_id is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="validation_error",
            )
        client = get_object_or_404(Client, id=client_id)
        try:
            payload = retry_current_recommendations(client)
        except ValueError as exc:
            return detail_response(str(exc), status_code=status.HTTP_400_BAD_REQUEST, error_code="validation_error")
        return Response(payload)


class SelectionView(CompatEnvelopeAPIView):
    @extend_schema(
        summary="Legacy selection staging endpoint",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "customer_id": {"type": "integer"},
                    "style_id": {"type": "integer"},
                },
                "required": ["style_id"],
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        client_id = _request_value(request, "client_id", "customer_id")
        style_id = _request_value(request, "style_id")
        if not client_id or not style_id:
            return detail_response(
                "Both client_id and style_id are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="validation_error",
            )
        client = get_object_or_404(Client, id=client_id)
        return Response(
            {
                "status": "selected",
                "client_id": client.id,
                "style_id": int(style_id),
                "message": "Selection has been staged for the follow-up consult request.",
            }
        )


class ConfirmView(CompatEnvelopeAPIView):
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
        client_id = _request_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        try:
            payload = confirm_style_selection(
                client=client,
                recommendation_id=_request_value(request, "recommendation_id"),
                style_id=_request_value(request, "style_id"),
                admin_id=request.data.get("admin_id"),
                source=request.data.get("source", "current_recommendations"),
                direct_consultation=bool(request.data.get("direct_consultation", False)),
            )
        except ValueError as exc:
            return detail_response(str(exc), status_code=status.HTTP_400_BAD_REQUEST, error_code="validation_error")
        return Response(payload)


class CancelView(CompatEnvelopeAPIView):
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
        client_id = _request_value(request, "client_id", "customer_id")
        client = get_object_or_404(Client, id=client_id)
        try:
            payload = cancel_style_selection(
                client=client,
                recommendation_id=_request_value(request, "recommendation_id"),
                source=request.data.get("source", "current_recommendations"),
            )
        except ValueError as exc:
            return detail_response(str(exc), status_code=status.HTTP_400_BAD_REQUEST, error_code="validation_error")
        return Response(payload)


class ConsultView(ConfirmView):
    pass

