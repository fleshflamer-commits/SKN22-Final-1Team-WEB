import os
import threading
import uuid

from django.conf import settings
from django.shortcuts import get_object_or_404
from PIL import Image, ImageOps
from rest_framework import parsers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from app.api.v1.django_serializers import (
    CustomerCheckSerializer,
    CustomerRegisterSerializer,
    RecommendationListResponseSerializer,
    SurveySerializer,
)
from app.api.v1.services_django import (
    confirm_style_selection,
    get_current_recommendations,
    get_former_recommendations,
    get_trend_recommendations,
    run_mirrai_analysis_pipeline,
    upsert_survey,
)
from app.models_django import CaptureRecord, Customer


class LoginView(APIView):
    @extend_schema(
        summary="Customer login",
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
            return Response({"detail": "전화번호가 필요합니다."}, status=status.HTTP_400_BAD_REQUEST)

        customer = Customer.objects.filter(phone=phone).first()
        if not customer:
            return Response({"detail": "사용자를 찾을 수 없습니다."}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "access_token": f"mock-token-{customer.id}",
                "token_type": "bearer",
                "customer_id": customer.id,
            }
        )


class CustomerCheckView(APIView):
    @extend_schema(summary="Check customer", request=CustomerCheckSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        customer = Customer.objects.filter(phone=phone).first()

        if not customer:
            return Response({"is_existing": False})

        return Response(
            {
                "is_existing": True,
                "name": customer.name,
                "gender": customer.gender,
                "customer_id": customer.id,
            }
        )


class RegisterView(APIView):
    @extend_schema(summary="Register customer", request=CustomerRegisterSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        phone = request.data.get("phone", "").replace("-", "").strip()
        if Customer.objects.filter(phone=phone).exists():
            return Response({"detail": "이미 등록된 번호입니다."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = CustomerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save(phone=phone)

        return Response(
            {
                "status": "success",
                "customer_id": customer.id,
                "access_token": f"mock-token-{customer.id}",
                "token_type": "bearer",
            },
            status=status.HTTP_201_CREATED,
        )


class SurveyView(APIView):
    @extend_schema(summary="Submit survey", request=SurveySerializer, responses={200: SurveySerializer})
    def post(self, request):
        customer_id = request.data.get("customer") or request.data.get("customer_id")
        customer = get_object_or_404(Customer, id=customer_id)
        survey = upsert_survey(customer, request.data)
        return Response(SurveySerializer(survey).data)


class CaptureUploadView(APIView):
    parser_classes = (parsers.MultiPartParser, parsers.FormParser)

    @extend_schema(
        summary="Upload capture",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "file": {"type": "string", "format": "binary"},
                },
                "required": ["customer_id", "file"],
            }
        },
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        customer_id = request.data.get("customer_id")
        customer = get_object_or_404(Customer, id=customer_id)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "파일이 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(file_obj.name)[1]
        filename = f"{uuid.uuid4()}{ext}"
        upload_path = os.path.join(settings.MEDIA_ROOT, "captures", filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)

        with open(upload_path, "wb+") as destination:
            for chunk in file_obj.chunks():
                destination.write(chunk)

        processed_path = upload_path + ".processed.jpg"
        with Image.open(upload_path) as img:
            img = ImageOps.exif_transpose(img)
            img.convert("RGB").save(processed_path, "JPEG")

        record = CaptureRecord.objects.create(
            customer=customer,
            original_path=upload_path,
            processed_path=processed_path,
            filename=file_obj.name,
            status="PENDING",
        )

        threading.Thread(target=run_mirrai_analysis_pipeline, args=(record.id,), daemon=True).start()
        return Response({"status": "success", "record_id": record.id})


class FormerRecommendationView(APIView):
    @extend_schema(
        summary="Get former recommendations",
        parameters=[OpenApiParameter("customer_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        customer_id = request.query_params.get("customer_id")
        customer = get_object_or_404(Customer, id=customer_id)
        return Response(get_former_recommendations(customer))


class RecommendationView(APIView):
    @extend_schema(
        summary="Get current recommendations",
        parameters=[OpenApiParameter("customer_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        customer_id = request.query_params.get("customer_id")
        customer = get_object_or_404(Customer, id=customer_id)
        return Response(get_current_recommendations(customer))


class TrendView(APIView):
    @extend_schema(
        summary="Get salon trend styles",
        parameters=[OpenApiParameter("days", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False)],
        responses={200: RecommendationListResponseSerializer},
    )
    def get(self, request):
        days = int(request.query_params.get("days", 30))
        return Response(get_trend_recommendations(days=days))


class ConfirmView(APIView):
    @extend_schema(
        summary="Confirm selected style and send to admins",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "integer"},
                    "recommendation_id": {"type": "integer"},
                    "style_id": {"type": "integer"},
                    "source": {"type": "string", "example": "current_recommendations"},
                    "direct_consultation": {"type": "boolean", "default": False},
                },
                "required": ["customer_id"],
            }
        },
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        customer = get_object_or_404(Customer, id=request.data.get("customer_id"))
        try:
            payload = confirm_style_selection(
                customer=customer,
                recommendation_id=request.data.get("recommendation_id"),
                style_id=request.data.get("style_id"),
                source=request.data.get("source", "current_recommendations"),
                direct_consultation=bool(request.data.get("direct_consultation", False)),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class ConsultView(ConfirmView):
    pass
