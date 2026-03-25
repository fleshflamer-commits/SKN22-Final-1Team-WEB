from django.db import models

from app.services.age_profile import build_age_profile


class Client(models.Model):
    name = models.CharField(max_length=50)
    gender = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    age_input = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_year_estimate = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    image_storage_consent = models.BooleanField(default=False)
    image_storage_consented_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clients"

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def age_profile(self) -> dict | None:
        return build_age_profile(birth_year_estimate=self.birth_year_estimate)


class AdminAccount(models.Model):
    name = models.CharField(max_length=50)
    store_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, default="owner")
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    business_number = models.CharField(max_length=30, unique=True, db_index=True)
    password_hash = models.CharField(max_length=255)
    business_verification_status = models.CharField(max_length=30, default="checksum_only")
    business_verification_snapshot = models.JSONField(default=dict, blank=True)
    consent_snapshot = models.JSONField(default=dict, blank=True)
    consented_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_accounts"

    def __str__(self):
        return f"{self.store_name} - {self.name}"


class Style(models.Model):
    name = models.CharField(max_length=100)
    vibe = models.CharField(max_length=50)
    description = models.TextField(null=True, blank=True)
    image_url = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "styles"

    def __str__(self):
        return self.name


class Survey(models.Model):
    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name="survey",
        db_index=True,
    )
    target_length = models.CharField(max_length=50)
    target_vibe = models.CharField(max_length=50)
    scalp_type = models.CharField(max_length=50)
    hair_colour = models.CharField(max_length=50)
    budget_range = models.CharField(max_length=50)
    preference_vector = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "surveys"


class CaptureRecord(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="captures",
        db_index=True,
    )
    original_path = models.CharField(max_length=500, null=True, blank=True)
    processed_path = models.CharField(max_length=500, null=True, blank=True)
    filename = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=50, default="PENDING", db_index=True)
    face_count = models.IntegerField(null=True, blank=True)
    landmark_snapshot = models.JSONField(null=True, blank=True)
    deidentified_path = models.CharField(max_length=500, null=True, blank=True)
    privacy_snapshot = models.JSONField(null=True, blank=True)
    error_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "capture_records"


class FaceAnalysis(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="face_analyses",
        db_index=True,
    )
    face_shape = models.CharField(max_length=50, null=True, blank=True)
    golden_ratio_score = models.FloatField(null=True, blank=True)
    image_url = models.CharField(max_length=500, null=True, blank=True)
    landmark_snapshot = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "face_analyses"


class FormerRecommendation(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="former_recommendations",
        db_index=True,
    )
    capture_record = models.ForeignKey(
        CaptureRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="former_recommendations",
    )
    style = models.ForeignKey(
        Style,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="former_recommendations",
    )
    batch_id = models.UUIDField(db_index=True)
    source = models.CharField(max_length=20, default="generated", db_index=True)
    style_id_snapshot = models.IntegerField(db_index=True)
    style_name_snapshot = models.CharField(max_length=100)
    style_description_snapshot = models.TextField(null=True, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    sample_image_url = models.CharField(max_length=500, null=True, blank=True)
    simulation_image_url = models.CharField(max_length=500, null=True, blank=True)
    regeneration_snapshot = models.JSONField(null=True, blank=True)
    llm_explanation = models.TextField(null=True, blank=True)
    reasoning_snapshot = models.JSONField(null=True, blank=True)
    match_score = models.FloatField(null=True, blank=True)
    rank = models.PositiveSmallIntegerField(default=1)
    is_chosen = models.BooleanField(default=False, db_index=True)
    chosen_at = models.DateTimeField(null=True, blank=True)
    is_sent_to_admin = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "former_recommendations"
        ordering = ["rank", "-created_at"]


class StyleSelection(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="style_selections",
        db_index=True,
    )
    selected_recommendation = models.ForeignKey(
        FormerRecommendation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="style_selections",
    )
    style_id = models.IntegerField()
    source = models.CharField(max_length=30, default="current_recommendations")
    survey_snapshot = models.JSONField(null=True, blank=True)
    match_score = models.FloatField(null=True, blank=True)
    is_sent_to_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "style_selections"


class ConsultationRequest(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="consultations",
        db_index=True,
    )
    admin = models.ForeignKey(
        AdminAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultations",
    )
    selected_style = models.ForeignKey(Style, on_delete=models.SET_NULL, null=True, blank=True)
    selected_recommendation = models.ForeignKey(
        FormerRecommendation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultations",
    )
    source = models.CharField(max_length=30, default="current_recommendations")
    survey_snapshot = models.JSONField(null=True, blank=True)
    analysis_data_snapshot = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, default="PENDING")
    is_active = models.BooleanField(default=True, db_index=True)
    is_read = models.BooleanField(default=False, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "consultation_requests"


class ClientSessionNote(models.Model):
    consultation = models.ForeignKey(
        ConsultationRequest,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="session_notes",
        db_index=True,
    )
    admin = models.ForeignKey(
        AdminAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_notes",
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "client_session_notes"

