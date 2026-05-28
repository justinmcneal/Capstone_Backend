from rest_framework import serializers


class ConsentSerializer(serializers.Serializer):
    """Serializer for consent data validation and response"""

    data_consent = serializers.BooleanField(required=False, default=False)
    ai_consent = serializers.BooleanField(required=False, default=False)


class ConsentResponseSerializer(serializers.Serializer):
    """Serializer for consent response data"""

    data_consent = serializers.BooleanField()
    ai_consent = serializers.BooleanField()
    consent_date = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField()
    can_access_ai = serializers.BooleanField()


class ConsentCreateSerializer(serializers.Serializer):
    """Serializer for creating consent record"""

    data_consent = serializers.BooleanField(required=True)
    ai_consent = serializers.BooleanField(required=True)

    def validate(self, data):
        """Validate that at least one consent is provided"""
        if not data.get("data_consent") and not data.get("ai_consent"):
            # Allow users to explicitly set both to false (withdrawal)
            pass
        return data


class ConsentUpdateSerializer(serializers.Serializer):
    """Serializer for updating consent preferences"""

    data_consent = serializers.BooleanField(required=False)
    ai_consent = serializers.BooleanField(required=False)

    def validate(self, data):
        """Ensure at least one field is provided for update"""
        if not data:
            raise serializers.ValidationError(
                "At least one consent field must be provided"
            )
        return data
