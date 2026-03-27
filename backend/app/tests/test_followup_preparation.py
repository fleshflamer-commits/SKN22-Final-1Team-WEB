import os
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from app.api.v1.admin_auth import build_admin_refresh_token, build_client_refresh_token, get_admin_auth_policy_snapshot
from app.api.v1.response_helpers import detail_response, get_error_contract_snapshot
from app.api.v1.services_django import persist_generated_batch
from app.models_django import AdminAccount, CaptureRecord, Client, FaceAnalysis, Survey


class ContractPreparationSnapshotTests(SimpleTestCase):
    def test_error_contract_snapshot_reports_current_compat_envelope_mode(self):
        payload = get_error_contract_snapshot()

        self.assertEqual(payload["mode"], "compat_envelope")
        self.assertEqual(payload["fields"], ["error_code", "message", "detail"])
        self.assertTrue(payload["detail_compatibility"])
        self.assertTrue(payload["validation_detail_supported"])
        self.assertTrue(payload["envelope_supported"])

    def test_detail_response_keeps_legacy_detail_field(self):
        response = detail_response("Phone number is required.", error_code="validation_error")

        self.assertEqual(response.data["error_code"], "validation_error")
        self.assertEqual(response.data["message"], "Phone number is required.")
        self.assertEqual(response.data["detail"], "Phone number is required.")

    def test_admin_auth_policy_snapshot_reports_refresh_support(self):
        payload = get_admin_auth_policy_snapshot()

        self.assertEqual(payload["token_type"], "bearer")
        self.assertTrue(payload["refresh_token_supported"])
        self.assertGreater(payload["token_max_age_seconds"], 0)
        self.assertGreater(payload["refresh_token_max_age_seconds"], payload["token_max_age_seconds"])


class RegenerateSimulationEndpointTests(APITestCase):
    @mock.patch.dict(os.environ, {"MIRRAI_AI_PROVIDER": "local"}, clear=False)
    def test_regenerate_simulation_endpoint_returns_card_for_vector_only_row(self):
        client = Client.objects.create(name="Regen Tester", phone="01012121212", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="soft",
            scalp_type="normal",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[0.6] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Oval",
            golden_ratio_score=0.89,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )

        response = self.client.post(
            "/api/v1/analysis/regenerate-simulation/",
            {"recommendation_id": rows[0].id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["recommendation_id"], rows[0].id)
        self.assertEqual(response.data["image_policy"], "vector_only")
        self.assertEqual(response.data["card"]["style_id"], rows[0].style_id_snapshot)
        self.assertFalse(response.data["card"]["can_regenerate_simulation"])
        self.assertEqual(response.data["card"]["regeneration_remaining_count"], 0)
        self.assertIn("regenerated", response.data["card"]["reasoning_snapshot"])

        second_response = self.client.post(
            "/api/v1/analysis/regenerate-simulation/",
            {"recommendation_id": rows[0].id},
            format="json",
        )
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch.dict(os.environ, {"MIRRAI_AI_PROVIDER": "local"}, clear=False)
    def test_regenerate_simulation_endpoint_accepts_snapshot_and_style_id(self):
        client = Client.objects.create(name="Snapshot Tester", phone="01034343434", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="short",
            target_vibe="chic",
            scalp_type="normal",
            hair_colour="black",
            budget_range="10-15",
            preference_vector=[0.4] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Oval",
            golden_ratio_score=0.9,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )
        snapshot = rows[0].regeneration_snapshot

        response = self.client.post(
            "/api/v1/analysis/regenerate-simulation/",
            {
                "regeneration_snapshot": snapshot,
                "style_id": rows[0].style_id_snapshot,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertIsNone(response.data["recommendation_id"])
        self.assertEqual(response.data["style_id"], rows[0].style_id_snapshot)
        self.assertEqual(response.data["regeneration_remaining_count"], 0)


class RetryRecommendationFlowTests(APITestCase):
    @mock.patch.dict(os.environ, {"MIRRAI_AI_PROVIDER": "local"}, clear=False)
    def test_current_recommendations_expose_single_retry_before_consultation(self):
        client = Client.objects.create(name="Retry Ready", phone="01091919191", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="long",
            target_vibe="natural",
            scalp_type="waved",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[0.5] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Oval",
            golden_ratio_score=0.9,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )

        response = self.client.get(f"/api/v1/analysis/recommendations/?client_id={client.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["recommendation_stage"], "initial")
        self.assertTrue(response.data["can_retry_recommendations"])
        self.assertEqual(response.data["retry_recommendations_remaining_count"], 1)
        self.assertIn("retry_recommendations", response.data["next_actions"])

    @mock.patch.dict(os.environ, {"MIRRAI_AI_PROVIDER": "local"}, clear=False)
    def test_retry_recommendations_creates_retry_batch_and_disables_second_retry(self):
        client = Client.objects.create(name="Retry Flow", phone="01092929292", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="long",
            target_vibe="natural",
            scalp_type="waved",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[0.5] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Round",
            golden_ratio_score=0.78,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )

        response = self.client.post(
            "/api/v1/analysis/retry-recommendations/",
            {"client_id": client.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["recommendation_stage"], "retry")
        self.assertFalse(response.data["can_retry_recommendations"])
        self.assertEqual(response.data["retry_recommendations_remaining_count"], 0)
        self.assertEqual(response.data["retry_recommendations_policy"]["preference_weight"], 70)
        self.assertEqual(response.data["retry_recommendations_policy"]["face_total_weight"], 30)
        self.assertEqual(response.data["next_actions"], ["consultation"])
        self.assertEqual(response.data["items"][0]["reasoning_snapshot"]["scoring_profile"], "retry_preference_dominant")

        second_response = self.client.post(
            "/api/v1/analysis/retry-recommendations/",
            {"client_id": client.id},
            format="json",
        )
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch.dict(os.environ, {"MIRRAI_AI_PROVIDER": "local"}, clear=False)
    def test_retry_recommendations_is_blocked_after_consultation_starts(self):
        client = Client.objects.create(name="Retry Locked", phone="01093939393", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="chic",
            scalp_type="straight",
            hair_colour="black",
            budget_range="10-15",
            preference_vector=[0.5] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Oval",
            golden_ratio_score=0.88,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )

        consult_response = self.client.post(
            "/api/v1/analysis/confirm/",
            {
                "client_id": client.id,
                "direct_consultation": True,
                "recommendation_id": rows[0].id,
                "source": "current_recommendations",
            },
            format="json",
        )
        self.assertEqual(consult_response.status_code, status.HTTP_200_OK)

        retry_response = self.client.post(
            "/api/v1/analysis/retry-recommendations/",
            {"client_id": client.id},
            format="json",
        )
        self.assertEqual(retry_response.status_code, status.HTTP_400_BAD_REQUEST)


class RefreshTokenEndpointTests(APITestCase):
    def test_client_refresh_validation_error_uses_compat_envelope(self):
        response = self.client.post(
            "/api/v1/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error_code"], "validation_error")
        self.assertEqual(response.data["message"], "Validation failed.")
        self.assertIn("refresh_token", response.data["detail"])

    def test_client_refresh_endpoint_returns_new_tokens(self):
        client = Client.objects.create(name="Client Refresh", phone="01056565656", gender="F")
        refresh_token = build_client_refresh_token(client=client)

        response = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh_token": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["client_id"], client.id)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertGreater(response.data["refresh_expires_in"], response.data["expires_in"])

    def test_client_refresh_invalid_token_uses_compat_envelope(self):
        response = self.client.post(
            "/api/v1/auth/refresh/",
            {"refresh_token": "invalid-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error_code"], "authentication_failed")
        self.assertIn("message", response.data)
        self.assertIn("detail", response.data)

    def test_admin_refresh_endpoint_returns_new_tokens(self):
        admin = AdminAccount.objects.create(
            name="Refresh Admin",
            store_name="MirrAI Refresh",
            role="owner",
            phone="01078787878",
            business_number="1234567890",
            password_hash=make_password("plain-password"),
        )
        refresh_token = build_admin_refresh_token(admin=admin)

        response = self.client.post(
            "/api/v1/admin/auth/refresh/",
            {"refresh_token": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["admin_id"], admin.id)
        self.assertIn("access_token", response.data)
        self.assertIn("refresh_token", response.data)
        self.assertGreater(response.data["refresh_expires_in"], response.data["expires_in"])

    def test_admin_refresh_validation_error_uses_compat_envelope(self):
        response = self.client.post(
            "/api/v1/admin/auth/refresh/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error_code"], "validation_error")
        self.assertEqual(response.data["message"], "Validation failed.")
        self.assertIn("refresh_token", response.data["detail"])
