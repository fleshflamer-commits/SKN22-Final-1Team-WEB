from django.http import JsonResponse
from django.shortcuts import render


def health_check(request):
    return JsonResponse({"status": "django_running", "framework": "Django"})


def _render_shell(request, *, template_name: str, title: str, subtitle: str, api_map: list[dict]):
    return render(
        request,
        template_name,
        {
            "page_title": title,
            "page_subtitle": subtitle,
            "api_map": api_map,
        },
    )


def home_page(request):
    return _render_shell(
        request,
        template_name="pages/home.html",
        title="MirrAI Django Shell",
        subtitle="Front integration placeholder pages backed by Django-first APIs.",
        api_map=[
            {"label": "Client APIs", "value": "/api/v1/auth, /api/v1/survey, /api/v1/analysis/*"},
            {"label": "Admin APIs", "value": "/api/v1/admin/*"},
            {"label": "Docs", "value": "/docs/"},
        ],
    )


def client_login_page(request):
    return _render_shell(
        request,
        template_name="pages/client_login.html",
        title="Client Login Shell",
        subtitle="Template placeholder for the frontend team to bind to Django APIs.",
        api_map=[
            {"label": "Check", "value": "POST /api/v1/auth/check/"},
            {"label": "Register", "value": "POST /api/v1/auth/register/"},
            {"label": "Login", "value": "POST /api/v1/auth/login/"},
        ],
    )


def client_survey_page(request):
    return _render_shell(
        request,
        template_name="pages/client_survey.html",
        title="Client Survey Shell",
        subtitle="Survey and capture pages are scaffolded in Django templates so the frontend can replace them gradually.",
        api_map=[
            {"label": "Survey Submit", "value": "POST /api/v1/survey/"},
            {"label": "Capture Upload", "value": "POST /api/v1/capture/upload/"},
            {"label": "Capture Status", "value": "GET /api/v1/capture/status/"},
        ],
    )


def client_recommendation_page(request):
    return _render_shell(
        request,
        template_name="pages/client_recommendations.html",
        title="Client Recommendation Shell",
        subtitle="Former, trend, and current recommendations are separated and ready for frontend binding.",
        api_map=[
            {"label": "Former", "value": "GET /api/v1/analysis/former-recommendations/"},
            {"label": "Current", "value": "GET /api/v1/analysis/recommendations/"},
            {"label": "Trend", "value": "GET /api/v1/analysis/trend/"},
            {"label": "Confirm", "value": "POST /api/v1/analysis/confirm/"},
            {"label": "Cancel", "value": "POST /api/v1/analysis/cancel/"},
        ],
    )


def admin_login_page(request):
    return _render_shell(
        request,
        template_name="pages/admin_login.html",
        title="Admin Login Shell",
        subtitle="Admin login and registration placeholders for the future frontend implementation.",
        api_map=[
            {"label": "Admin Register", "value": "POST /api/v1/admin/auth/register/"},
            {"label": "Admin Login", "value": "POST /api/v1/admin/auth/login/"},
        ],
    )


def admin_dashboard_page(request):
    return _render_shell(
        request,
        template_name="pages/admin_dashboard.html",
        title="Admin Dashboard Shell",
        subtitle="Dashboard, active clients, trend report, and style report endpoints are already prepared in Django.",
        api_map=[
            {"label": "Dashboard", "value": "GET /api/v1/admin/dashboard/"},
            {"label": "Active Clients", "value": "GET /api/v1/admin/clients/active/"},
            {"label": "Client Detail", "value": "GET /api/v1/admin/clients/detail/"},
            {"label": "Trend Report", "value": "GET /api/v1/admin/trend-report/"},
            {"label": "Style Report", "value": "GET /api/v1/admin/style-report/"},
        ],
    )

