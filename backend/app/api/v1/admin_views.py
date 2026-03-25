from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from app.api.v1.admin_auth import AdminTokenAuthentication, IsAuthenticatedAdmin
from app.api.v1.admin_serializers import (
    AdminLoginSerializer,
    AdminRegisterSerializer,
    AdminTrendFilterSerializer,
    ConsultationCloseSerializer,
    ConsultationNoteCreateSerializer,
)
from app.api.v1.admin_services import (
    close_consultation_session,
    create_client_note,
    get_active_client_sessions,
    get_admin_profile,
    get_admin_dashboard_summary,
    get_admin_trend_report,
    get_all_clients,
    get_client_detail,
    get_client_recommendation_report,
    get_style_report,
    login_admin,
    register_admin,
)
from app.models_django import Client


class AdminProtectedAPIView(APIView):
    authentication_classes = [AdminTokenAuthentication]
    permission_classes = [IsAuthenticatedAdmin]


class AdminRegisterView(APIView):
    @extend_schema(summary="Register admin", request=AdminRegisterSerializer, responses={201: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = AdminRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = register_admin(payload=serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload, status=status.HTTP_201_CREATED)


class AdminLoginView(APIView):
    @extend_schema(summary="Login admin", request=AdminLoginSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = login_admin(**serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class AdminProfileView(AdminProtectedAPIView):
    @extend_schema(summary="Get current admin profile", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(get_admin_profile(admin=request.user))


class AdminDashboardView(AdminProtectedAPIView):
    @extend_schema(summary="Admin dashboard summary", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(get_admin_dashboard_summary(admin=request.user))


class ActiveClientSessionsView(AdminProtectedAPIView):
    @extend_schema(summary="Active client sessions", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(get_active_client_sessions(admin=request.user))


class AllClientsView(AdminProtectedAPIView):
    @extend_schema(
        summary="All clients for admin",
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response(get_all_clients(query=request.query_params.get("q", ""), admin=request.user))


class AdminClientDetailView(AdminProtectedAPIView):
    @extend_schema(
        summary="Admin client detail",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        client = get_object_or_404(Client, id=request.query_params.get("client_id"))
        try:
            return Response(get_client_detail(client=client, admin=request.user))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)


class AdminClientRecommendationView(AdminProtectedAPIView):
    @extend_schema(
        summary="Admin client recommendation report",
        parameters=[OpenApiParameter("client_id", OpenApiTypes.INT, OpenApiParameter.QUERY, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        client = get_object_or_404(Client, id=request.query_params.get("client_id"))
        try:
            return Response(get_client_recommendation_report(client=client, admin=request.user))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)


class ConsultationNoteView(AdminProtectedAPIView):
    @extend_schema(summary="Create client consultation note", request=ConsultationNoteCreateSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = ConsultationNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = get_object_or_404(Client, id=serializer.validated_data["client_id"])
        try:
            payload = create_client_note(
                client=client,
                consultation_id=serializer.validated_data["consultation_id"],
                content=serializer.validated_data["content"],
                admin=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class ConsultationCloseView(AdminProtectedAPIView):
    @extend_schema(summary="Close consultation session", request=ConsultationCloseSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = ConsultationCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = close_consultation_session(consultation_id=serializer.validated_data["consultation_id"], admin=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class AdminTrendReportView(AdminProtectedAPIView):
    @extend_schema(
        summary="Admin weekly trend report",
        parameters=[
            OpenApiParameter("days", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("target_length", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("target_vibe", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("scalp_type", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("hair_colour", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("budget_range", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("age_decade", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("age_segment", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("age_group", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        serializer = AdminTrendFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        days = data.pop("days", 7)
        return Response(get_admin_trend_report(days=days, filters=data, admin=request.user))


class StyleReportView(AdminProtectedAPIView):
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
        return Response(get_style_report(style_id=style_id, days=days, admin=request.user))

