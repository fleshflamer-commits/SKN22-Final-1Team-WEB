import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from app.models_django import ConsultationRequest, Client, FormerRecommendation, Style


class CancelStyleSelectionApiTests(APITestCase):
    def setUp(self):
        self.client_profile = Client.objects.create(
            name="Cancel Tester",
            phone="01012345678",
            gender="F",
        )
        self.style = Style.objects.create(
            name="Soft Layered Bob",
            vibe="natural",
            description="Soft layered bob for cancel flow testing.",
        )

    def test_cancel_without_recommendation_id_uses_active_consultation_selection(self):
        batch_id = uuid.uuid4()
        selected_row = FormerRecommendation.objects.create(
            client=self.client_profile,
            style=self.style,
            batch_id=batch_id,
            source="generated",
            style_id_snapshot=self.style.id,
            style_name_snapshot=self.style.name,
            style_description_snapshot=self.style.description,
            keywords=["natural"],
            sample_image_url="styles/soft-layered-bob.jpg",
            simulation_image_url="captures/result.jpg",
            llm_explanation="Best match for testing.",
            match_score=92.0,
            rank=1,
            is_chosen=True,
            chosen_at=timezone.now(),
            is_sent_to_admin=True,
            sent_at=timezone.now(),
        )
        sibling_row = FormerRecommendation.objects.create(
            client=self.client_profile,
            style=self.style,
            batch_id=batch_id,
            source="generated",
            style_id_snapshot=self.style.id,
            style_name_snapshot=self.style.name,
            style_description_snapshot=self.style.description,
            keywords=["natural"],
            sample_image_url="styles/soft-layered-bob.jpg",
            simulation_image_url="captures/result-2.jpg",
            llm_explanation="Second option for testing.",
            match_score=88.0,
            rank=2,
            is_chosen=False,
            is_sent_to_admin=True,
            sent_at=timezone.now(),
        )
        consultation = ConsultationRequest.objects.create(
            client=self.client_profile,
            selected_style=self.style,
            selected_recommendation=selected_row,
            source="current_recommendations",
            status="PENDING",
            is_active=True,
            is_read=False,
        )

        response = self.client.post(
            "/api/v1/analysis/cancel/",
            {"client_id": self.client_profile.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(response.data["next_action"], "client_input")

        selected_row.refresh_from_db()
        sibling_row.refresh_from_db()
        consultation.refresh_from_db()

        self.assertFalse(selected_row.is_chosen)
        self.assertIsNone(selected_row.chosen_at)
        self.assertFalse(selected_row.is_sent_to_admin)
        self.assertIsNone(selected_row.sent_at)
        self.assertFalse(sibling_row.is_chosen)
        self.assertFalse(sibling_row.is_sent_to_admin)
        self.assertIsNone(sibling_row.sent_at)
        self.assertFalse(consultation.is_active)
        self.assertEqual(consultation.status, "CANCELLED")
        self.assertTrue(consultation.is_read)
        self.assertIsNotNone(consultation.closed_at)

    def test_cancel_with_unknown_recommendation_id_returns_400(self):
        response = self.client.post(
            "/api/v1/analysis/cancel/",
            {
                "client_id": self.client_profile.id,
                "recommendation_id": 999999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_cancel_is_safe_when_repeated_after_first_cancel(self):
        batch_id = uuid.uuid4()
        selected_row = FormerRecommendation.objects.create(
            client=self.client_profile,
            style=self.style,
            batch_id=batch_id,
            source="generated",
            style_id_snapshot=self.style.id,
            style_name_snapshot=self.style.name,
            style_description_snapshot=self.style.description,
            keywords=["natural"],
            sample_image_url="styles/soft-layered-bob.jpg",
            simulation_image_url="captures/result.jpg",
            llm_explanation="Best match for repeated cancel testing.",
            match_score=92.0,
            rank=1,
            is_chosen=True,
            chosen_at=timezone.now(),
            is_sent_to_admin=True,
            sent_at=timezone.now(),
        )
        ConsultationRequest.objects.create(
            client=self.client_profile,
            selected_style=self.style,
            selected_recommendation=selected_row,
            source="current_recommendations",
            status="PENDING",
            is_active=True,
            is_read=False,
        )

        first_response = self.client.post(
            "/api/v1/analysis/cancel/",
            {"client_id": self.client_profile.id},
            format="json",
        )
        second_response = self.client.post(
            "/api/v1/analysis/cancel/",
            {"client_id": self.client_profile.id},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertFalse(first_response.data["idempotent"])
        self.assertTrue(second_response.data["idempotent"])
        self.assertEqual(ConsultationRequest.objects.filter(client=self.client_profile, is_active=True).count(), 0)

