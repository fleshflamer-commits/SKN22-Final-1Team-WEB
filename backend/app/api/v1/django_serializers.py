from rest_framework import serializers

from app.models_django import ConsultationRequest, Customer, FaceAnalysis, FormerRecommendation, Style, StyleSelection, Survey


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"


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
            "customer",
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
    reasoning = serializers.CharField(source="llm_explanation", read_only=True)

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
            "match_score",
            "rank",
            "is_chosen",
            "created_at",
        ]


class RecommendationCardSerializer(serializers.Serializer):
    recommendation_id = serializers.IntegerField(required=False)
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.CharField()
    style_id = serializers.IntegerField()
    style_name = serializers.CharField()
    style_description = serializers.CharField(required=False, allow_blank=True)
    keywords = serializers.ListField(child=serializers.CharField(), required=False)
    sample_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    simulation_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    synthetic_image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    llm_explanation = serializers.CharField(required=False, allow_blank=True)
    reasoning = serializers.CharField(required=False, allow_blank=True)
    match_score = serializers.FloatField(required=False)
    rank = serializers.IntegerField(required=False)
    is_chosen = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField(required=False)


class RecommendationListResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    source = serializers.CharField(required=False)
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    days = serializers.IntegerField(required=False)
    message = serializers.CharField(required=False)
    next_action = serializers.CharField(required=False)
    next_actions = serializers.ListField(child=serializers.CharField(), required=False)
    items = RecommendationCardSerializer(many=True)


class ConsultationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationRequest
        fields = "__all__"


class CustomerCheckSerializer(serializers.Serializer):
    phone = serializers.CharField()


class CustomerRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["name", "gender", "phone"]
