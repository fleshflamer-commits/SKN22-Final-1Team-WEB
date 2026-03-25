from datetime import date

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from app.api.v1.admin_services import get_admin_trend_report
from app.api.v1.services_django import ensure_catalog_styles
from app.models_django import Client, StyleSelection
from app.services.age_profile import current_age_from_birth_year, estimate_birth_year_from_age


class ClientAgeFeatureTests(APITestCase):
    def test_register_client_accepts_ages_alias_and_persists_age_profile(self):
        current_year = timezone.localdate().year

        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "name": "Age Tester",
                "gender": "F",
                "phone": "01012345678",
                "ages": 26,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        client = Client.objects.get(id=response.data["client_id"])
        self.assertEqual(client.age_input, 26)
        self.assertEqual(client.birth_year_estimate, current_year - 26 + 1)
        self.assertEqual(response.data["age"], 26)
        self.assertEqual(response.data["age_decade"], "20대")
        self.assertEqual(response.data["age_segment"], "중반")
        self.assertEqual(response.data["age_group"], "20대 중반")

    def test_age_rolls_forward_on_new_year_without_db_rewrite(self):
        birth_year_estimate = estimate_birth_year_from_age(26, reference_date=date(2026, 12, 31))

        age_on_dec_31 = current_age_from_birth_year(birth_year_estimate, reference_date=date(2026, 12, 31))
        age_on_jan_1 = current_age_from_birth_year(birth_year_estimate, reference_date=date(2027, 1, 1))

        self.assertEqual(age_on_dec_31, 26)
        self.assertEqual(age_on_jan_1, 27)

    def test_trend_endpoint_scopes_to_client_age_group(self):
        ensure_catalog_styles()
        young_a = Client.objects.create(
            name="Young A",
            phone="01020000001",
            gender="F",
            age_input=23,
            birth_year_estimate=timezone.localdate().year - 23 + 1,
        )
        young_b = Client.objects.create(
            name="Young B",
            phone="01020000002",
            gender="F",
            age_input=21,
            birth_year_estimate=timezone.localdate().year - 21 + 1,
        )
        older = Client.objects.create(
            name="Older",
            phone="01020000003",
            gender="F",
            age_input=38,
            birth_year_estimate=timezone.localdate().year - 38 + 1,
        )

        StyleSelection.objects.create(client=young_a, style_id=201, source="current_recommendations")
        StyleSelection.objects.create(client=young_b, style_id=201, source="current_recommendations")
        StyleSelection.objects.create(client=older, style_id=204, source="current_recommendations")

        response = self.client.get(f"/api/v1/analysis/trend/?days=30&client_id={young_a.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["trend_scope"], "age_group")
        self.assertEqual(response.data["age_profile"]["age_group"], "20대 초반")
        self.assertEqual(response.data["items"][0]["style_id"], 201)

    def test_admin_trend_report_supports_age_filters_and_breakdown(self):
        ensure_catalog_styles()
        twenties = Client.objects.create(
            name="Twenties",
            phone="01030000001",
            gender="F",
            age_input=24,
            birth_year_estimate=timezone.localdate().year - 24 + 1,
        )
        thirties = Client.objects.create(
            name="Thirties",
            phone="01030000002",
            gender="M",
            age_input=37,
            birth_year_estimate=timezone.localdate().year - 37 + 1,
        )

        StyleSelection.objects.create(client=twenties, style_id=201, source="current_recommendations")
        StyleSelection.objects.create(client=thirties, style_id=204, source="current_recommendations")

        report = get_admin_trend_report(days=30, filters={"age_decade": "20대"})

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["kpi"]["total_confirmations"], 1)
        self.assertEqual(report["age_decade_distribution"][0]["age_decade"], "20대")
        self.assertEqual(report["ranking"][0]["style_id"], 201)

