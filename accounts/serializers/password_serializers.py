from rest_framework import serializers

from .base_serializers import (
    OTPValidationMixin,
    PasswordConfirmationMixin,
    PasswordValidationMixin,
)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=("customer", "loan_officer", "admin"), required=False
    )


class VerifyResetOTPSerializer(OTPValidationMixin, serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    role = serializers.ChoiceField(
        choices=("customer", "loan_officer", "admin"), required=False
    )


class ResetPasswordSerializer(
    PasswordValidationMixin,
    OTPValidationMixin,
    PasswordConfirmationMixin,
    serializers.Serializer,
):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    role = serializers.ChoiceField(
        choices=("customer", "loan_officer", "admin"), required=False
    )
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
