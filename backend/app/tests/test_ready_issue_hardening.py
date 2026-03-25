import io
import shutil
import tempfile
import uuid
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from app.api.v1.admin_auth import build_admin_token
from app.api.v1.client_auth import build_client_token
from app.api.v1.services_django import persist_generated_batch
from app.models_django import AdminAccount, CaptureRecord, ConsultationRequest, Client, FaceAnalysis, Survey
from app.services.face_processing import build_deidentified_capture, extract_landmark_snapshot
from app.tests.test_issue_backlog_progress import build_valid_business_number


class ReadyIssueHardeningTests(APITestCase):
    def test_client_register_returns_signed_token_and_me_endpoint_uses_it(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {
                "name": "Signed Client",
                "gender": "F",
                "phone": "01070000000",
                "ages": 27,
                "agree_image_storage": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        token = response.data["access_token"]
        self.assertGreater(response.data["expires_in"], 0)
        self.assertTrue(response.data["image_storage_consent"])
        self.assertTrue(response.data["is_authenticated"])
        self.assertTrue(response.data["is_existing"])

        me_response = self.client.get(
            "/api/v1/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["client"]["phone"], "01070000000")
        self.assertTrue(me_response.data["client"]["image_storage_consent"])
        self.assertEqual(response.data["next_action"], "dashboard")
        self.assertEqual(response.data["client"]["name"], "Signed Client")

    def test_client_token_blocks_cross_client_survey_write(self):
        owner = Client.objects.create(name="Owner", phone="01071000000", gender="F")
        other = Client.objects.create(name="Other", phone="01072000000", gender="F")
        token = build_client_token(client=owner)

        response = self.client.post(
            "/api/v1/survey/",
            {
                "client_id": other.id,
                "target_length": "short",
                "target_vibe": "soft",
                "scalp_type": "normal",
                "hair_colour": "black",
                "budget_range": "10-15",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_client_check_returns_dashboard_hint_and_client_summary(self):
        client = Client.objects.create(name="Existing Client", phone="01079990000", gender="F")

        found_response = self.client.post(
            "/api/v1/auth/check/",
            {"phone": client.phone},
            format="json",
        )
        self.assertEqual(found_response.status_code, status.HTTP_200_OK)
        self.assertTrue(found_response.data["is_existing"])
        self.assertTrue(found_response.data["is_authenticated"])
        self.assertEqual(found_response.data["next_action"], "dashboard")
        self.assertEqual(found_response.data["nextAction"], "dashboard")
        self.assertEqual(found_response.data["client"]["name"], "Existing Client")
        self.assertEqual(found_response.data["clientSummary"]["name"], "Existing Client")

        missing_response = self.client.post(
            "/api/v1/auth/check/",
            {"phone": "01000000000"},
            format="json",
        )
        self.assertEqual(missing_response.status_code, status.HTTP_200_OK)
        self.assertFalse(missing_response.data["is_existing"])
        self.assertFalse(missing_response.data["is_authenticated"])
        self.assertEqual(missing_response.data["next_action"], "register")
        self.assertEqual(missing_response.data["nextAction"], "register")

    def test_client_login_and_me_share_common_contract_fields(self):
        client = Client.objects.create(name="Parity Client", phone="01078880000", gender="F")

        login_response = self.client.post(
            "/api/v1/auth/login/",
            {"phone": client.phone},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertTrue(login_response.data["is_authenticated"])
        self.assertEqual(login_response.data["next_action"], "dashboard")
        self.assertEqual(login_response.data["nextAction"], "dashboard")
        self.assertIn("access_token", login_response.data)
        self.assertEqual(login_response.data["clientSummary"]["name"], "Parity Client")

        me_response = self.client.get(
            "/api/v1/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {login_response.data['access_token']}",
        )
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertTrue(me_response.data["is_authenticated"])
        self.assertTrue(me_response.data["is_existing"])
        self.assertEqual(me_response.data["next_action"], "dashboard")
        self.assertEqual(me_response.data["nextAction"], "dashboard")
        self.assertEqual(me_response.data["client"]["name"], "Parity Client")

    def test_survey_accepts_frontend_style_selections_payload(self):
        client = Client.objects.create(name="Survey Client", phone="01070101010", gender="F")
        token = build_client_token(client=client)

        response = self.client.post(
            "/api/v1/survey/",
            {
                "client_id": client.id,
                "selections": {
                    "step1": "bob",
                    "step2": "natural",
                    "step3": "straight",
                    "step4": "brown",
                    "step5": "10만원이하",
                },
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["next_action"], "recommendation")
        self.assertEqual(response.data["target_length"], "bob")
        self.assertEqual(response.data["target_vibe"], "natural")
        self.assertEqual(response.data["selection_snapshot"]["step1"], "bob")

    def test_survey_explicit_fields_take_priority_over_generic_selections(self):
        client = Client.objects.create(name="Priority Client", phone="01070303030", gender="F")
        token = build_client_token(client=client)

        response = self.client.post(
            "/api/v1/survey/",
            {
                "client_id": client.id,
                "target_length": "long",
                "selections": {
                    "step1": "bob",
                    "step2": "natural",
                    "step3": "straight",
                    "step4": "brown",
                    "step5": "10만원이하",
                },
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["target_length"], "long")

    def test_current_recommendations_fall_back_to_survey_only_batch(self):
        client = Client.objects.create(name="Survey Only Client", phone="01070202020", gender="F")
        Survey.objects.create(
            client=client,
            target_length="bob",
            target_vibe="natural",
            scalp_type="straight",
            hair_colour="brown",
            budget_range="10만원이하",
            preference_vector=[1.0] * 20,
        )

        response = self.client.get(
            f"/api/v1/analysis/recommendations/?client_id={client.id}",
            HTTP_AUTHORIZATION=f"Bearer {build_client_token(client=client)}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual(response.data["source"], "current_recommendations")
        self.assertEqual(response.data["recommendation_mode"], "survey_only")
        self.assertEqual(response.data["next_actions"], ["capture"])
        self.assertTrue(response.data["capture_required_for_full_result"])
        self.assertEqual(len(response.data["items"]), 5)
        first_item = response.data["items"][0]
        self.assertEqual(first_item["source"], "survey_only")
        self.assertIn("name", first_item)
        self.assertIn("imageUrl", first_item)
        self.assertIn("match", first_item)

    @override_settings(MIRRAI_PERSIST_CAPTURE_IMAGES=True)
    def test_capture_upload_updates_client_consent_and_persists_assets(self):
        temp_media_root = tempfile.mkdtemp(prefix="mirrai-ready-hardening-")
        media_override = override_settings(MEDIA_ROOT=temp_media_root)
        media_override.enable()
        try:
            client = Client.objects.create(name="Consent Client", phone="01073000000", gender="F")
            buffer = io.BytesIO()
            Image.new("RGB", (640, 640), "gray").save(buffer, format="PNG")
            upload = SimpleUploadedFile("consent.png", buffer.getvalue(), content_type="image/png")

            class DummyThread:
                def __init__(self, *args, **kwargs):
                    self.args = args
                    self.kwargs = kwargs

                def start(self):
                    return None

            with (
                patch("app.api.v1.django_views.validate_capture_image", return_value={
                    "is_valid": True,
                    "status": "PENDING",
                    "face_count": 1,
                    "reason_code": "ok",
                    "message": "ready",
                }),
                patch("app.api.v1.django_views.threading.Thread", DummyThread),
            ):
                response = self.client.post(
                    "/api/v1/capture/upload/",
                    {
                        "client_id": str(client.id),
                        "file": upload,
                        "image_storage_consent": "true",
                    },
                    format="multipart",
                )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            client.refresh_from_db()
            record = CaptureRecord.objects.get(id=response.data["record_id"])
            self.assertTrue(client.image_storage_consent)
            self.assertIsNotNone(client.image_storage_consented_at)
            self.assertEqual(record.privacy_snapshot["storage_policy"], "asset_store")
            self.assertIsNotNone(record.original_path)
            self.assertIsNotNone(record.processed_path)
        finally:
            media_override.disable()
            shutil.rmtree(temp_media_root, ignore_errors=True)

    def test_regenerate_simulation_endpoint_returns_public_payload(self):
        client = Client.objects.create(name="Regen Client", phone="01074000000", gender="F")
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="soft",
            scalp_type="normal",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[1.0] * 20,
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
            golden_ratio_score=0.91,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )
        row = rows[0]
        self.assertEqual(
            row.regeneration_snapshot["engine_payload"]["analysis_data"]["image_storage_policy"],
            "vector_only",
        )
        self.assertEqual(
            row.regeneration_snapshot["engine_payload"]["analysis_data"]["landmark_snapshot"]["version"],
            "coarse-v1",
        )

        with (
            patch("app.api.v1.services_django.generate_recommendation_batch", return_value=[{
                "style_id": row.style_id_snapshot,
                "style_name": row.style_name_snapshot,
                "style_description": row.style_description_snapshot,
                "sample_image_url": "https://example.com/sample.png",
                "simulation_image_url": "https://example.com/sim.png",
                "llm_explanation": "regenerated",
                "keywords": row.keywords,
                "reasoning_snapshot": {"summary": "regenerated summary"},
                "match_score": row.match_score,
                "rank": row.rank,
            }]),
            patch("app.api.v1.services_django.explain_style", return_value={
                "style_id": row.style_id_snapshot,
                "style_name": row.style_name_snapshot,
                "sample_image_url": "https://example.com/sample.png",
                "simulation_image_url": "https://example.com/sim.png",
                "llm_explanation": "regenerated",
                "keywords": row.keywords,
            }),
        ):
            response = self.client.post(
                "/api/v1/analysis/regenerate-simulation/",
                {
                    "client_id": client.id,
                    "recommendation_id": row.id,
                },
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {build_client_token(client=client)}",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["item"]["style_id"], row.style_id_snapshot)
        self.assertTrue(response.data["can_regenerate_simulation"])
        self.assertEqual(response.data["image_policy"], "vector_only")
        self.assertEqual(response.data["item"]["simulation_image_url"], "https://example.com/sim.png")

    def test_deidentified_capture_applies_feature_mask(self):
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), "gray").save(buffer, format="JPEG")
        landmark_snapshot = extract_landmark_snapshot(processed_bytes=buffer.getvalue())
        if not landmark_snapshot.get("face_bbox"):
            landmark_snapshot = {
                "version": "coarse-v1",
                "face_count": 1,
                "image_size": {"width": 640, "height": 640},
                "face_bbox": {"x": 120, "y": 100, "width": 320, "height": 360},
                "landmarks": {
                    "left_eye": {"point": {"x": 220.0, "y": 230.0}},
                    "right_eye": {"point": {"x": 340.0, "y": 230.0}},
                    "nose_tip": {"point": {"x": 280.0, "y": 315.0}},
                    "mouth_center": {"point": {"x": 280.0, "y": 375.0}},
                },
            }

        deidentified_bytes, privacy_snapshot = build_deidentified_capture(
            processed_bytes=buffer.getvalue(),
            landmark_snapshot=landmark_snapshot,
        )

        self.assertIsNotNone(deidentified_bytes)
        self.assertTrue(privacy_snapshot["deidentification_applied"])
        self.assertTrue(privacy_snapshot["feature_mask_applied"])

    def test_admin_scope_returns_empty_list_and_blocks_other_admin_close(self):
        admin_owner = AdminAccount.objects.create(
            name="Owner Admin",
            store_name="Owner Store",
            role="owner",
            phone="01075000000",
            business_number=build_valid_business_number("567890123"),
            password_hash="hashed",
        )
        outsider = AdminAccount.objects.create(
            name="Outsider Admin",
            store_name="Outsider Store",
            role="owner",
            phone="01076000000",
            business_number=build_valid_business_number("678901234"),
            password_hash="hashed",
        )
        client = Client.objects.create(name="Scoped Client", phone="01077000000", gender="F")
        consultation = ConsultationRequest.objects.create(
            client=client,
            admin=admin_owner,
            source="current_recommendations",
            status="PENDING",
            is_active=True,
            is_read=False,
        )

        client_list_response = self.client.get(
            "/api/v1/admin/clients/",
            HTTP_AUTHORIZATION=f"Bearer {build_admin_token(admin=outsider)}",
        )
        self.assertEqual(client_list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(client_list_response.data["items"], [])

        close_response = self.client.post(
            "/api/v1/admin/consultations/close/",
            {"consultation_id": consultation.id},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {build_admin_token(admin=outsider)}",
        )
        self.assertEqual(close_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("outside the current admin scope", close_response.data["detail"])
