import io
import shutil
import tempfile
from unittest.mock import patch

from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from app.api.v1.admin_auth import build_admin_token
from app.api.v1.services_django import persist_generated_batch, run_mirrai_analysis_pipeline
from app.models_django import AdminAccount, CaptureRecord, ClientSessionNote, ConsultationRequest, Client, FaceAnalysis, StyleSelection, Survey


def build_valid_business_number(prefix: str = "123456789") -> str:
    digits = [int(char) for char in prefix]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    checksum = sum(digit * weight for digit, weight in zip(digits, weights))
    checksum += (digits[8] * 5) // 10
    check_digit = (10 - (checksum % 10)) % 10
    return prefix + str(check_digit)


@override_settings(SUPABASE_USE_REMOTE_STORAGE=False)
class BackendIssueProgressTests(APITestCase):
    def setUp(self):
        self.temp_media_root = tempfile.mkdtemp(prefix="mirrai-test-media-")
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media_root)
        self.media_override.enable()

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.temp_media_root, ignore_errors=True)

    def test_admin_register_rejects_invalid_business_number(self):
        response = self.client.post(
            "/api/v1/admin/auth/register/",
            {
                "name": "Owner Kim",
                "store_name": "MirrAI Salon",
                "role": "owner",
                "phone": "01011112222",
                "business_number": "123-45-67890",
                "password": "pw1234!!",
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_admin_register_requires_required_consents(self):
        valid_business_number = build_valid_business_number("123456780")
        response = self.client.post(
            "/api/v1/admin/auth/register/",
            {
                "name": "Owner Park",
                "store_name": "MirrAI Branch",
                "role": "owner",
                "phone": "01066667777",
                "business_number": valid_business_number,
                "password": "pw1234!!",
                "agree_terms": True,
                "agree_privacy": False,
                "agree_third_party_sharing": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("agree_privacy", response.data)

    def test_admin_register_accepts_valid_business_number_and_normalizes_it(self):
        valid_business_number = build_valid_business_number()
        response = self.client.post(
            "/api/v1/admin/auth/register/",
            {
                "name": "Owner Lee",
                "store_name": "MirrAI Lab",
                "role": "owner",
                "phone": "01022223333",
                "business_number": f"{valid_business_number[:3]}-{valid_business_number[3:5]}-{valid_business_number[5:]}",
                "password": "pw1234!!",
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
                "agree_marketing": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        admin = AdminAccount.objects.get(id=response.data["admin_id"])
        self.assertEqual(admin.business_number, valid_business_number)
        self.assertEqual(admin.business_verification_status, "checksum_only")
        self.assertEqual(admin.business_verification_snapshot["source"], "local_checksum")
        self.assertTrue(admin.consent_snapshot["agree_terms"])
        self.assertIsNotNone(admin.consented_at)
        self.assertIn("access_token", response.data)

    def test_admin_login_returns_token_and_protected_endpoint_accepts_it(self):
        valid_business_number = build_valid_business_number("234567890")
        register_response = self.client.post(
            "/api/v1/admin/auth/register/",
            {
                "name": "Owner Choi",
                "store_name": "MirrAI Auth",
                "role": "owner",
                "phone": "01077778888",
                "business_number": valid_business_number,
                "password": "pw1234!!",
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
            format="json",
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)

        unauthorized_response = self.client.get("/api/v1/admin/auth/me/")
        self.assertIn(unauthorized_response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

        login_response = self.client.post(
            "/api/v1/admin/auth/login/",
            {
                "phone": "01077778888",
                "password": "pw1234!!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        token = login_response.data["access_token"]
        self.assertGreater(login_response.data["expires_in"], 0)

        me_response = self.client.get(
            "/api/v1/admin/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["admin"]["store_name"], "MirrAI Auth")
        self.assertTrue(me_response.data["admin"]["consent_snapshot"]["agree_privacy"])

    def test_capture_upload_blank_image_requests_retake_and_status_endpoint_matches(self):
        client = Client.objects.create(name="Capture Tester", phone="01012340000", gender="F")
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), "white").save(buffer, format="PNG")
        upload = SimpleUploadedFile("blank.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            "/api/v1/capture/upload/",
            {
                "client_id": str(client.id),
                "file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "needs_retake")

        record = CaptureRecord.objects.get(id=response.data["record_id"])
        self.assertEqual(record.status, "NEEDS_RETAKE")
        self.assertIsNotNone(record.error_note)
        self.assertIsNone(record.original_path)
        self.assertEqual(record.privacy_snapshot["storage_policy"], "vector_only")

        status_response = self.client.get(f"/api/v1/capture/status/?record_id={record.id}")
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["status"], "needs_retake")
        self.assertEqual(status_response.data["next_action"], "capture")
        self.assertEqual(status_response.data["image_storage_policy"], "vector_only")

    @override_settings(MIRRAI_PERSIST_CAPTURE_IMAGES=True)
    def test_capture_upload_persists_landmarks_and_deidentified_asset(self):
        client = Client.objects.create(
            name="Face Tester",
            phone="01055556666",
            gender="F",
            image_storage_consent=True,
            image_storage_consented_at=timezone.now(),
        )
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), "gray").save(buffer, format="PNG")
        upload = SimpleUploadedFile("face.png", buffer.getvalue(), content_type="image/png")

        landmark_snapshot = {
            "version": "coarse-v1",
            "face_count": 1,
            "image_size": {"width": 640, "height": 640},
            "face_bbox": {"x": 120, "y": 100, "width": 320, "height": 360},
            "landmarks": {
                "left_eye": {"point": {"x": 220.0, "y": 230.0}},
                "right_eye": {"point": {"x": 340.0, "y": 232.0}},
                "nose_tip": {"point": {"x": 280.0, "y": 320.0}},
                "mouth_center": {"point": {"x": 280.0, "y": 380.0}},
                "chin_center": {"point": {"x": 280.0, "y": 430.0}},
            },
            "quality": {"coverage": "coarse", "detected_feature_count": 5},
        }
        privacy_snapshot = {
            "metadata_removed": True,
            "deidentification_applied": True,
            "method": "pixelate_face_region",
        }

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
            patch("app.api.v1.django_views.extract_landmark_snapshot", return_value=landmark_snapshot),
            patch("app.api.v1.django_views.build_deidentified_capture", return_value=(b"fake-blurred-jpeg", privacy_snapshot)),
            patch("app.api.v1.django_views.threading.Thread", DummyThread),
        ):
            response = self.client.post(
                "/api/v1/capture/upload/",
                {
                    "client_id": str(client.id),
                    "file": upload,
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["privacy_snapshot"]["method"], "pixelate_face_region")

        record = CaptureRecord.objects.get(id=response.data["record_id"])
        self.assertEqual(record.landmark_snapshot["quality"]["detected_feature_count"], 5)
        self.assertEqual(record.privacy_snapshot["method"], "pixelate_face_region")
        self.assertEqual(record.privacy_snapshot["storage_policy"], "asset_store")
        self.assertIsNotNone(record.deidentified_path)

        status_response = self.client.get(f"/api/v1/capture/status/?record_id={record.id}")
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertIn("deidentified_image_url", status_response.data)
        self.assertEqual(status_response.data["landmark_snapshot"]["version"], "coarse-v1")
        self.assertEqual(status_response.data["image_storage_policy"], "asset_store")

    def test_capture_upload_vector_only_policy_skips_image_persistence(self):
        client = Client.objects.create(name="Vector Policy Tester", phone="01011110000", gender="F")
        buffer = io.BytesIO()
        Image.new("RGB", (640, 640), "gray").save(buffer, format="PNG")
        upload = SimpleUploadedFile("vector.png", buffer.getvalue(), content_type="image/png")

        landmark_snapshot = {
            "version": "coarse-v1",
            "face_count": 1,
            "image_size": {"width": 640, "height": 640},
            "face_bbox": {"x": 120, "y": 100, "width": 320, "height": 360},
            "landmarks": {
                "left_eye": {"point": {"x": 220.0, "y": 230.0}},
                "right_eye": {"point": {"x": 340.0, "y": 232.0}},
            },
            "quality": {"coverage": "coarse", "detected_feature_count": 2},
        }

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
            patch("app.api.v1.django_views.extract_landmark_snapshot", return_value=landmark_snapshot),
            patch("app.api.v1.django_views.threading.Thread", DummyThread),
        ):
            response = self.client.post(
                "/api/v1/capture/upload/",
                {
                    "client_id": str(client.id),
                    "file": upload,
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record = CaptureRecord.objects.get(id=response.data["record_id"])
        self.assertIsNone(record.original_path)
        self.assertIsNone(record.processed_path)
        self.assertIsNone(record.deidentified_path)
        self.assertEqual(record.privacy_snapshot["storage_policy"], "vector_only")
        self.assertEqual(response.data["privacy_snapshot"]["storage_policy"], "vector_only")

    def test_analysis_pipeline_copies_landmark_snapshot_to_face_analysis(self):
        client = Client.objects.create(name="Pipeline Tester", phone="01033334444", gender="F")
        Survey.objects.create(
            client=client,
            target_length="short",
            target_vibe="soft",
            scalp_type="normal",
            hair_colour="black",
            budget_range="10-15",
            preference_vector=[0.2] * 20,
        )
        jpeg_buffer = io.BytesIO()
        Image.new("RGB", (320, 320), "gray").save(jpeg_buffer, format="JPEG")

        record = CaptureRecord.objects.create(
            client=client,
            original_path=None,
            processed_path=None,
            filename=None,
            status="PENDING",
            face_count=1,
            landmark_snapshot={
                "version": "coarse-v1",
                "landmarks": {
                    "left_eye": {"point": {"x": 120.0, "y": 140.0}},
                    "right_eye": {"point": {"x": 220.0, "y": 142.0}},
                },
            },
            privacy_snapshot={"deidentification_applied": False, "storage_policy": "vector_only"},
        )

        run_mirrai_analysis_pipeline(record.id, processed_bytes=jpeg_buffer.getvalue())

        record.refresh_from_db()
        self.assertEqual(record.status, "DONE")
        analysis = FaceAnalysis.objects.get(client=client)
        self.assertEqual(analysis.landmark_snapshot["version"], "coarse-v1")
        self.assertIsNone(analysis.image_url)

    def test_recommendations_and_admin_detail_include_reasoning_and_history(self):
        client = Client.objects.create(name="History Tester", phone="01098765432", gender="F")
        admin = AdminAccount.objects.create(
            name="Manager Han",
            store_name="MirrAI Admin",
            role="owner",
            phone="01044445555",
            business_number=build_valid_business_number("345678901"),
            password_hash="hashed",
            consent_snapshot={
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
        )
        admin_token = build_admin_token(admin=admin)
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="chic",
            scalp_type="normal",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[1.0] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            original_path=None,
            processed_path=None,
            filename=None,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Oval",
            golden_ratio_score=0.92,
            image_url=None,
            landmark_snapshot={
                "version": "coarse-v1",
                "landmarks": {
                    "left_eye": {"point": {"x": 120.0, "y": 140.0}},
                    "right_eye": {"point": {"x": 220.0, "y": 142.0}},
                },
            },
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )
        selected_row = rows[0]
        self.assertIsNone(selected_row.sample_image_url)
        self.assertIsNone(selected_row.simulation_image_url)
        self.assertEqual(selected_row.regeneration_snapshot["version"], "vector-only-v1")
        selected_row.is_chosen = True
        selected_row.chosen_at = timezone.now()
        selected_row.save(update_fields=["is_chosen", "chosen_at"])
        StyleSelection.objects.create(
            client=client,
            selected_recommendation=selected_row,
            style_id=selected_row.style_id_snapshot,
            source="current_recommendations",
            match_score=selected_row.match_score,
            is_sent_to_admin=True,
        )
        ConsultationRequest.objects.create(
            client=client,
            admin=admin,
            selected_style=selected_row.style,
            selected_recommendation=selected_row,
            source="current_recommendations",
            status="PENDING",
            is_active=True,
            is_read=False,
        )

        recommendation_response = self.client.get(f"/api/v1/analysis/recommendations/?client_id={client.id}")
        self.assertEqual(recommendation_response.status_code, status.HTTP_200_OK)
        self.assertEqual(recommendation_response.data["status"], "ready")
        first_card = recommendation_response.data["items"][0]
        self.assertIn("reasoning_snapshot", first_card)
        self.assertIn("summary", first_card["reasoning_snapshot"])
        self.assertIn("face_score", first_card["reasoning_snapshot"])
        self.assertEqual(first_card["image_policy"], "vector_only")
        self.assertTrue(first_card["can_regenerate_simulation"])
        self.assertIsNotNone(first_card["sample_image_url"])
        self.assertIsNone(first_card["simulation_image_url"])

        detail_response = self.client.get(
            f"/api/v1/admin/clients/detail/?client_id={client.id}",
            HTTP_AUTHORIZATION=f"Bearer {admin_token}",
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(detail_response.data["capture_history"]), 1)
        self.assertEqual(len(detail_response.data["analysis_history"]), 1)
        self.assertEqual(len(detail_response.data["style_selection_history"]), 1)
        self.assertEqual(len(detail_response.data["chosen_recommendation_history"]), 1)
        self.assertIn("landmark_snapshot", detail_response.data["capture_history"][0])
        self.assertEqual(detail_response.data["capture_history"][0]["image_storage_policy"], "vector_only")
        self.assertIsNone(detail_response.data["capture_history"][0]["processed_image_url"])
        self.assertEqual(detail_response.data["analysis_history"][0]["landmark_snapshot"]["version"], "coarse-v1")
        self.assertEqual(detail_response.data["chosen_recommendation_history"][0]["image_policy"], "vector_only")

    def test_confirm_style_selection_binds_admin_scope_when_admin_id_is_provided(self):
        client = Client.objects.create(name="Scope Tester", phone="01022224444", gender="F")
        admin = AdminAccount.objects.create(
            name="Manager Scope",
            store_name="MirrAI Scope",
            role="owner",
            phone="01099990000",
            business_number=build_valid_business_number("456789012"),
            password_hash="hashed",
            consent_snapshot={
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
        )
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
            original_path=None,
            processed_path=None,
            filename=None,
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

        response = self.client.post(
            "/api/v1/analysis/confirm/",
            {
                "client_id": client.id,
                "recommendation_id": rows[0].id,
                "admin_id": admin.id,
                "source": "current_recommendations",
                "direct_consultation": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        consultation = ConsultationRequest.objects.get(id=response.data["consultation_id"])
        self.assertEqual(consultation.admin_id, admin.id)

        admin_response = self.client.get(
            "/api/v1/admin/dashboard/",
            HTTP_AUTHORIZATION=f"Bearer {build_admin_token(admin=admin)}",
        )
        self.assertEqual(admin_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(admin_response.data["today_metrics"]["active_clients"], 1)

    def test_admin_contract_endpoints_include_frontend_friendly_aliases(self):
        client = Client.objects.create(
            name="Admin Contract Tester",
            phone="01010101234",
            gender="F",
            birth_year_estimate=1998,
        )
        admin = AdminAccount.objects.create(
            name="Manager Contract",
            store_name="MirrAI Contract",
            role="owner",
            phone="01056565656",
            business_number=build_valid_business_number("567890123"),
            password_hash="hashed",
            consent_snapshot={
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
        )
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="chic",
            scalp_type="normal",
            hair_colour="brown",
            budget_range="10-15",
            preference_vector=[0.5] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            original_path=None,
            processed_path=None,
            filename=None,
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
        selected_row = rows[0]
        survey_snapshot = {
            "target_length": "medium",
            "target_vibe": "chic",
            "budget_range": "10-15",
            "occasion": "daily",
            "preferences": ["시크", "볼륨"],
        }
        StyleSelection.objects.create(
            client=client,
            selected_recommendation=selected_row,
            style_id=selected_row.style_id_snapshot,
            source="current_recommendations",
            survey_snapshot=survey_snapshot,
            match_score=selected_row.match_score,
            is_sent_to_admin=True,
        )
        consultation = ConsultationRequest.objects.create(
            client=client,
            admin=admin,
            selected_style=selected_row.style,
            selected_recommendation=selected_row,
            source="current_recommendations",
            survey_snapshot=survey_snapshot,
            status="IN_PROGRESS",
            is_active=True,
            is_read=False,
        )
        ClientSessionNote.objects.create(
            consultation=consultation,
            client=client,
            admin=admin,
            content="모발 건조 구간 집중 케어 필요",
        )
        token = build_admin_token(admin=admin)

        profile_response = self.client.get(
            "/api/v1/admin/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)
        self.assertTrue(profile_response.data["is_authenticated"])
        self.assertEqual(profile_response.data["next_action"], "admin_dashboard")
        self.assertEqual(profile_response.data["admin"]["storeName"], "MirrAI Contract")
        self.assertEqual(profile_response.data["admin"]["displayName"], "Manager Contract")

        dashboard_response = self.client.get(
            "/api/v1/admin/dashboard/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(dashboard_response.status_code, status.HTTP_200_OK)
        self.assertIn("todaySummary", dashboard_response.data)
        self.assertIn("summaryCards", dashboard_response.data)
        self.assertIn("topStylesToday", dashboard_response.data)
        self.assertGreaterEqual(dashboard_response.data["todaySummary"]["recommendations_completed"], 1)

        clients_response = self.client.get(
            "/api/v1/admin/clients/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(clients_response.status_code, status.HTTP_200_OK)
        self.assertEqual(clients_response.data["total_count"], 1)
        list_item = clients_response.data["items"][0]
        self.assertEqual(list_item["id"], client.id)
        self.assertTrue(list_item["isNew"])
        self.assertEqual(list_item["todayRecommendationId"], selected_row.style_id_snapshot)
        self.assertEqual(list_item["surveyResults"]["length"], "medium")
        self.assertEqual(list_item["designerNote"], "모발 건조 구간 집중 케어 필요")

        detail_response = self.client.get(
            f"/api/v1/admin/clients/detail/?client_id={client.id}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertIn("clientSummary", detail_response.data)
        self.assertIn("recommendationHistory", detail_response.data)
        self.assertEqual(detail_response.data["clientSummary"]["todayRecommendationName"], selected_row.style_name_snapshot)
        self.assertEqual(detail_response.data["clientSummary"]["surveyResults"]["occasion"], "daily")
        self.assertEqual(detail_response.data["designerNote"], "모발 건조 구간 집중 케어 필요")
        self.assertGreaterEqual(detail_response.data["clientSummary"]["totalSessions"], 1)

        trend_response = self.client.get(
            "/api/v1/admin/trend-report/?days=7",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(trend_response.status_code, status.HTTP_200_OK)
        self.assertIn("trendReport", trend_response.data)
        self.assertIn("hairstyles", trend_response.data)
        self.assertIn("chartData", trend_response.data)
        self.assertEqual(trend_response.data["trendReport"][0]["hairstyleId"], selected_row.style_id_snapshot)

    def test_admin_recommendation_and_style_reports_match_frontend_mock_structure(self):
        client = Client.objects.create(
            name="Recommendation Contract Tester",
            phone="01056561234",
            gender="F",
            birth_year_estimate=1996,
        )
        admin = AdminAccount.objects.create(
            name="Manager Recommendation",
            store_name="MirrAI Recommendation",
            role="owner",
            phone="01057575757",
            business_number=build_valid_business_number("678901234"),
            password_hash="hashed",
            consent_snapshot={
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
        )
        survey = Survey.objects.create(
            client=client,
            target_length="medium",
            target_vibe="natural",
            scalp_type="straight",
            hair_colour="brown",
            budget_range="mid",
            preference_vector=[0.4] * 20,
        )
        capture = CaptureRecord.objects.create(
            client=client,
            original_path=None,
            processed_path=None,
            filename=None,
            status="DONE",
            face_count=1,
            privacy_snapshot={"storage_policy": "vector_only"},
        )
        analysis = FaceAnalysis.objects.create(
            client=client,
            face_shape="Round",
            golden_ratio_score=0.86,
            image_url=None,
            landmark_snapshot={"version": "coarse-v1"},
        )
        _, rows = persist_generated_batch(
            client=client,
            capture_record=capture,
            survey=survey,
            analysis=analysis,
        )
        selected_row = rows[0]
        consultation = ConsultationRequest.objects.create(
            client=client,
            admin=admin,
            selected_style=selected_row.style,
            selected_recommendation=selected_row,
            source="current_recommendations",
            survey_snapshot={
                "target_length": "medium",
                "target_vibe": "natural",
                "budget_range": "mid",
                "occasion": "daily",
                "preferences": ["내추럴", "볼륨"],
            },
            status="PENDING",
            is_active=True,
            is_read=False,
        )
        ClientSessionNote.objects.create(
            consultation=consultation,
            client=client,
            admin=admin,
            content="추천 페이지 확인 후 상담 연결 예정",
        )
        token = build_admin_token(admin=admin)

        recommendation_response = self.client.get(
            f"/api/v1/admin/clients/recommendations/?client_id={client.id}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(recommendation_response.status_code, status.HTTP_200_OK)
        self.assertEqual(recommendation_response.data["status"], "ready")
        self.assertIn("clientSummary", recommendation_response.data)
        self.assertIn("aiProfile", recommendation_response.data)
        self.assertIn("todayStyle", recommendation_response.data)
        self.assertIn("recommendedStyles", recommendation_response.data)
        self.assertIn("items", recommendation_response.data)
        self.assertEqual(recommendation_response.data["clientSummary"]["todayRecommendationId"], selected_row.style_id_snapshot)
        self.assertEqual(recommendation_response.data["todayStyle"]["id"], selected_row.style_id_snapshot)
        self.assertEqual(recommendation_response.data["recommendedStyles"][0]["id"], selected_row.style_id_snapshot)
        self.assertEqual(recommendation_response.data["recommendedStyles"][0]["matchRate"], int(round(selected_row.match_score)))
        self.assertEqual(recommendation_response.data["aiProfile"]["faceShape"], "Round")

        style_response = self.client.get(
            f"/api/v1/admin/style-report/?style_id={selected_row.style_id_snapshot}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(style_response.status_code, status.HTTP_200_OK)
        self.assertIn("hairstyle", style_response.data)
        self.assertIn("relatedHairstyles", style_response.data)
        self.assertEqual(style_response.data["hairstyle"]["id"], selected_row.style_id_snapshot)
        self.assertIn("faceRatioData", style_response.data["hairstyle"])

    def test_admin_dashboard_and_reports_keep_empty_state_contract(self):
        admin = AdminAccount.objects.create(
            name="Manager Empty",
            store_name="MirrAI Empty",
            role="owner",
            phone="01058585858",
            business_number=build_valid_business_number("789012345"),
            password_hash="hashed",
            consent_snapshot={
                "agree_terms": True,
                "agree_privacy": True,
                "agree_third_party_sharing": True,
            },
        )
        token = build_admin_token(admin=admin)

        dashboard_response = self.client.get(
            "/api/v1/admin/dashboard/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(dashboard_response.status_code, status.HTTP_200_OK)
        self.assertEqual(dashboard_response.data["todaySummary"]["total_visits"], 0)
        self.assertEqual(dashboard_response.data["summaryCards"][0]["value"], 0)
        self.assertEqual(dashboard_response.data["topStylesToday"], [])
        self.assertEqual(dashboard_response.data["activeClientsPreview"], [])

        trend_response = self.client.get(
            "/api/v1/admin/trend-report/?days=7",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(trend_response.status_code, status.HTTP_200_OK)
        self.assertEqual(trend_response.data["trendReport"], [])
        self.assertEqual(trend_response.data["hairstyles"], [])
        self.assertEqual(trend_response.data["chartData"], [])

