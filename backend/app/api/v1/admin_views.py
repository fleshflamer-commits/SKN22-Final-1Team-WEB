from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from app.api.v1.admin_serializers import (
    AdminTrendFilterSerializer,
    ConsultationCloseSerializer,
    ConsultationNoteCreateSerializer,
    PartnerLoginSerializer,
    PartnerRegisterSerializer,
)
from app.api.v1.admin_services import (
    close_consultation_session,
    create_customer_note,
    get_active_customer_sessions,
    get_admin_dashboard_summary,
    get_admin_trend_report,
    get_all_customers,
    get_customer_detail,
    get_customer_recommendation_report,
    get_style_report,
    login_partner,
    register_partner,
)
from app.models_django import Customer


class PartnerRegisterView(APIView):
    @extend_schema(summary="Register partner", request=PartnerRegisterSerializer, responses={201: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = PartnerRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = register_partner(payload=serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload, status=status.HTTP_201_CREATED)


class PartnerLoginView(APIView):
    @extend_schema(summary="Login partner", request=PartnerLoginSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = PartnerLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = login_partner(**serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class AdminDashboardView(APIView):
    @extend_schema(summary="Admin dashboard summary", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(get_admin_dashboard_summary())


class ActiveCustomerSessionsView(APIView):
    @extend_schema(summary="Active customer sessions", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(get_active_customer_sessions())


class AllCustomersView(APIView):
    @extend_schema(
        summary="All customers for admin",
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response(get_all_customers(query=request.query_params.get("q", "")))


class AdminCustomerDetailView(APIView):
    @extend_schema(
        summary="Admin customer detail",
        parameters=[OpenApiParameter("customer_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        customer = get_object_or_404(Customer, id=request.query_params.get("customer_id"))
        return Response(get_customer_detail(customer=customer))


class AdminCustomerRecommendationView(APIView):
    @extend_schema(
        summary="Admin customer recommendation report",
        parameters=[OpenApiParameter("customer_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        customer = get_object_or_404(Customer, id=request.query_params.get("customer_id"))
        return Response(get_customer_recommendation_report(customer=customer))


class ConsultationNoteView(APIView):
    @extend_schema(summary="Create customer consultation note", request=ConsultationNoteCreateSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = ConsultationNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = get_object_or_404(Customer, id=serializer.validated_data["customer_id"])
        try:
            payload = create_customer_note(
                customer=customer,
                consultation_id=serializer.validated_data["consultation_id"],
                content=serializer.validated_data["content"],
                partner_id=serializer.validated_data.get("partner_id"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class ConsultationCloseView(APIView):
    @extend_schema(summary="Close consultation session", request=ConsultationCloseSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = ConsultationCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = close_consultation_session(consultation_id=serializer.validated_data["consultation_id"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class AdminTrendReportView(APIView):
    @extend_schema(
        summary="Admin weekly trend report",
        parameters=[
            OpenApiParameter("days", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("target_length", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("target_vibe", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("scalp_type", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("hair_colour", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("budget_range", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        serializer = AdminTrendFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        days = data.pop("days", 7)
        return Response(get_admin_trend_report(days=days, filters=data))


class StyleReportView(APIView):
    @extend_schema(
        summary="Style report for admin",
        parameters=[
            OpenApiParameter("style_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("days", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        style_id = int(request.query_params.get("style_id"))
        days = int(request.query_params.get("days", 7))
        return Response(get_style_report(style_id=style_id, days=days))
