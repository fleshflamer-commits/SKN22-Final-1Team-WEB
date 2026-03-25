from django.urls import path

from app.front_views import (
    admin_dashboard_page,
    admin_login_page,
    client_login_page,
    client_recommendation_page,
    client_survey_page,
    health_check,
    home_page,
)


urlpatterns = [
    path("", home_page, name="front-home"),
    path("health/", health_check, name="health-check"),
    path("client/login/", client_login_page, name="client-login-shell"),
    path("client/survey/", client_survey_page, name="client-survey-shell"),
    path("client/recommendations/", client_recommendation_page, name="client-recommendation-shell"),
    path("admin-panel/login/", admin_login_page, name="admin-login-shell"),
    path("admin-panel/dashboard/", admin_dashboard_page, name="admin-dashboard-shell"),
]

