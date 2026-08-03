from rest_framework import serializers

from accounts.utils.email_utils import EmailUtils

from .base_serializers import OTPValidationMixin


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate_new_email(self, value):
        return EmailUtils.normalize_email(value)


class EmailChangeConfirmSerializer(OTPValidationMixin, serializers.Serializer):
    otp = serializers.CharField(max_length=6, min_length=6)


class AccountDeletionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TwoFactorRecoveryRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)

    def validate_email(self, value):
        return EmailUtils.normalize_email(value)


class TwoFactorRecoveryVerifySerializer(OTPValidationMixin, serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_email(self, value):
        return EmailUtils.normalize_email(value)


class CustomerStateUpdateSerializer(serializers.Serializer):
    account_state = serializers.ChoiceField(
        choices=("active", "suspended", "deactivated"),
        required=True,
    )
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TwoFactorRecoveryDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField(required=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
