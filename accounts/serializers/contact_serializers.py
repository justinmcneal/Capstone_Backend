from rest_framework import serializers


class ContactSupportSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=100)
    contact_email = serializers.EmailField()
    concern_type = serializers.ChoiceField(
        choices=[
            "Account Access Issue",
            "Password Reset Problem",
            "Two-Factor Authentication",
            "Account Locked",
            "Other",
        ]
    )
    message = serializers.CharField(max_length=300)
