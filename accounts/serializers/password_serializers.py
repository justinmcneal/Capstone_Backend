from rest_framework import serializers
from .base_serializers import (
    PasswordValidationMixin,
    OTPValidationMixin,
    PasswordConfirmationMixin,
)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyResetOTPSerializer(OTPValidationMixin, serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)


class ResetPasswordSerializer(
    PasswordValidationMixin,
    OTPValidationMixin,
    PasswordConfirmationMixin,
    serializers.Serializer,
):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return self.validate_password(value)


class ChangePasswordSerializer(
    PasswordValidationMixin, PasswordConfirmationMixin, serializers.Serializer
):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return self.validate_password(value)
