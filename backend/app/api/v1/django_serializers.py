from rest_framework import serializers

from app.models_django import ConsultationRequest, Client, FaceAnalysis, FormerRecommendation, Style, StyleSelection, Survey
from app.services.age_profile import build_client_age_profile, estimate_birth_year_from_age, normalize_age_input


class ClientSerializer(serializers.ModelSerializer):
    current_age = serializers.SerializerMethodField()
    age_decade = serializers.SerializerMethodField()
    age_segment = serializers.SerializerMethodField()
    age_group = serializers.SerializerMethodField()

    def _profile(self, obj):
        return build_client_age_profile(obj) or {}

    def get_current_age(self, obj):
        return self._profile(obj).get("current_age")

    def get_age_decade(self, obj):
        return self._profile(obj).get("age_decade")

    def get_age_segment(self, obj):
        return self._profile(obj).get("age_segment")

    def get_age_group(self, obj):
        return self._profile(obj).get("age_group")

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "gender",
            "phone",
            "age_input",
            "birth_year_estimate",
            "image_storage_consent",
            "image_storage_consented_at",
            "current_age",
            "age_decade",
            "age_segment",
            "age_group",
            "created_at",
        ]


class StyleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Style
        fields = "__all__"


class SurveySerializer(serializers.ModelSerializer):
    target_length = serializers.CharField()
    target_vibe = serializers.CharField()
    scalp_type = serializers.CharField()
    hair_colour = serializers.CharField()
    budget_range = serializers.CharField()

    class Meta:
        model = Survey
        fields = [
            "id",
            "client",
            "target_length",
            "target_vibe",
            "scalp_type",
            "hair_colour",
            "budget_range",
            "preference_vector",
            "created_at",
        ]
        read_only_fields = ["id", "preference_vector", "created_at"]


class FaceAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaceAnalysis
        fields = "__all__"


class StyleSelectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StyleSelection
        fields = "__all__"


class FormerRecommendationSerializer(serializers.ModelSerializer):
    recommendation_id = serializers.IntegerField(source="id", read_only=True)
    style_id = serializers.IntegerField(source="style_id_snapshot", read_only=True)
    style_name = serializers.CharField(source="style_name_snapshot", read_only=True)
    style_description = serializers.CharField(source="style_description_snapshot", read_only=True)
    synthetic_image_url = serializers.CharField(source="simulation_image_url", read_only=True)
    reasoning = serializers.SerializerMethodField()
    reasoning_snapshot = serializers.JSONField(read_only=True)
    image_policy = serializers.SerializerMethodField()
    can_regenerate_simulation = serializers.SerializerMethodField()

    def get_reasoning(self, obj):
        snapshot = obj.reasoning_snapshot or {}
        return snapshot.get("summary") or obj.llm_explanation or ""

    def get_image_policy(self, obj):
        return "vector_only" if obj.regeneration_snapshot else "legacy_asset_store"

    def get_can_regenerate_simulation(self, obj):
        return bool(obj.regeneration_snapshot)

    class Meta:
        model = FormerRecommendation
        fields = [
            "recommendation_id",
            "batch_id",
            "source",
            "style_id",
            "style_name",
            "style_description",
            "keywords",
            "sample_image_url",
            "simulation_image_url",
            "synthetic_image_url",
            "llm_explanation",
            "reasoning",
            "reasoning_snapshot",
            "image_policy",
            "can_regenerate_simulation",
            "match_score",
            "rank",
            "is_chosen",
            "created_at",
        ]


class RecommendationCardSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    recommendation_id = serializers.IntegerField(required=False)
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.CharField()
    style_id = serializers.IntegerField()
    style_name = serializers.CharField()
    name = serializers.CharField(required=False)
    name_en = serializers.CharField(required=False, allow_blank=True)
    style_description = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    keywords = serializers.ListField(child=serializers.CharField(), required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    sample_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    imageUrl = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    simulation_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    synthetic_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    llm_explanation = serializers.CharField(required=False, allow_blank=True)
    reasoning = serializers.CharField(required=False, allow_blank=True)
    reasoning_snapshot = serializers.JSONField(required=False)
    image_policy = serializers.CharField(required=False)
    can_regenerate_simulation = serializers.BooleanField(required=False)
    match_score = serializers.FloatField(required=False)
    match = serializers.IntegerField(required=False)
    rank = serializers.IntegerField(required=False)
    is_chosen = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField(required=False)


class RecommendationListResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    source = serializers.CharField(required=False)
    recommendation_mode = serializers.CharField(required=False)
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    days = serializers.IntegerField(required=False)
    trend_scope = serializers.CharField(required=False)
    age_profile = serializers.JSONField(required=False)
    message = serializers.CharField(required=False)
    next_action = serializers.CharField(required=False)
    next_actions = serializers.ListField(child=serializers.CharField(), required=False)
    capture_required_for_full_result = serializers.BooleanField(required=False)
    items = RecommendationCardSerializer(many=True)


class ConsultationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationRequest
        fields = "__all__"


class ClientCheckSerializer(serializers.Serializer):
    phone = serializers.CharField()


class ClientRegisterSerializer(serializers.Serializer):
    name = serializers.CharField()
    gender = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField()
    age = serializers.IntegerField(required=False)
    ages = serializers.IntegerField(required=False)
    agree_image_storage = serializers.BooleanField(required=False, default=False)
    image_storage_consent = serializers.BooleanField(required=False)

    def validate(self, attrs):
        raw_age = attrs.pop("age", None)
        if raw_age is None:
            raw_age = attrs.pop("ages", None)
        explicit_image_storage_consent = attrs.pop("image_storage_consent", None)
        agree_image_storage = attrs.pop("agree_image_storage", False)
        if explicit_image_storage_consent is None:
            explicit_image_storage_consent = agree_image_storage
        try:
            age = normalize_age_input(raw_age)
        except ValueError as exc:
            raise serializers.ValidationError({"age": str(exc)}) from exc

        attrs["age_input"] = age
        attrs["birth_year_estimate"] = estimate_birth_year_from_age(age)
        attrs["image_storage_consent"] = bool(explicit_image_storage_consent)
        return attrs

    def create(self, validated_data):
        if validated_data.get("image_storage_consent"):
            from django.utils import timezone

            validated_data["image_storage_consented_at"] = timezone.now()
        return Client.objects.create(**validated_data)

