from rest_framework import serializers


class PartnerRegisterSerializer(serializers.Serializer):
    name = serializers.CharField()
    store_name = serializers.CharField()
    role = serializers.CharField(required=False, default="owner")
    phone = serializers.CharField()
    business_number = serializers.CharField()
    password = serializers.CharField(write_only=True)


class PartnerLoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)


class AdminCustomerSearchSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)


class ConsultationNoteCreateSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    consultation_id = serializers.IntegerField()
    content = serializers.CharField()
    partner_id = serializers.IntegerField(required=False)


class ConsultationCloseSerializer(serializers.Serializer):
    consultation_id = serializers.IntegerField()


class AdminTrendFilterSerializer(serializers.Serializer):
    days = serializers.IntegerField(required=False, default=7)
    target_length = serializers.CharField(required=False, allow_blank=True)
    target_vibe = serializers.CharField(required=False, allow_blank=True)
    scalp_type = serializers.CharField(required=False, allow_blank=True)
    hair_colour = serializers.CharField(required=False, allow_blank=True)
    budget_range = serializers.CharField(required=False, allow_blank=True)
