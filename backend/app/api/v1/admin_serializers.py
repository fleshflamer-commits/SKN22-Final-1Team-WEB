from rest_framework import serializers


class AdminRegisterSerializer(serializers.Serializer):
    name = serializers.CharField()
    store_name = serializers.CharField()
    role = serializers.CharField(required=False, default="owner")
    phone = serializers.CharField()
    business_number = serializers.CharField()
    password = serializers.CharField(write_only=True)
    agree_terms = serializers.BooleanField()
    agree_privacy = serializers.BooleanField()
    agree_third_party_sharing = serializers.BooleanField()
    agree_marketing = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        required_flags = {
            "agree_terms": "terms of service agreement is required",
            "agree_privacy": "privacy policy agreement is required",
            "agree_third_party_sharing": "third-party sharing agreement is required",
        }
        for key, message in required_flags.items():
            if not attrs.get(key):
                raise serializers.ValidationError({key: message})
        return attrs


class AdminLoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)


class AdminClientSearchSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)


class ConsultationNoteCreateSerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    consultation_id = serializers.IntegerField()
    content = serializers.CharField()
    admin_id = serializers.IntegerField(required=False)


class ConsultationCloseSerializer(serializers.Serializer):
    consultation_id = serializers.IntegerField()


class AdminTrendFilterSerializer(serializers.Serializer):
    days = serializers.IntegerField(required=False, default=7)
    target_length = serializers.CharField(required=False, allow_blank=True)
    target_vibe = serializers.CharField(required=False, allow_blank=True)
    scalp_type = serializers.CharField(required=False, allow_blank=True)
    hair_colour = serializers.CharField(required=False, allow_blank=True)
    budget_range = serializers.CharField(required=False, allow_blank=True)
    age_decade = serializers.CharField(required=False, allow_blank=True)
    age_segment = serializers.CharField(required=False, allow_blank=True)
    age_group = serializers.CharField(required=False, allow_blank=True)

