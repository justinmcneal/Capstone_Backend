from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from accounts.utils.validation_utils import sanitize_text


class PasswordValidationMixin:
    """Shared mixin for password validation across all serializers"""

    def validate_password(self, value):
        try:
            validate_password(value)
        except ValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value


class OTPValidationMixin:
    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be a 6-digit number")
        if len(value) != 6:
            raise serializers.ValidationError("OTP must be exactly 6 digits")
        return value


class PasswordConfirmationMixin:
    def validate(self, attrs):
        password_field = "new_password" if "new_password" in attrs else "password"
        confirm_field = "confirm_password"

        if password_field in attrs and confirm_field in attrs:
            if attrs.get(password_field) != attrs.get(confirm_field):
                raise serializers.ValidationError(
                    {confirm_field: "Passwords do not match"}
                )

        if "old_password" in attrs and "new_password" in attrs:
            if attrs.get("old_password") == attrs.get("new_password"):
                raise serializers.ValidationError(
                    {"new_password": "New password must be different from old password"}
                )

        return super().validate(attrs) if hasattr(super(), "validate") else attrs


class InputSanitizationMixin:
    """
    Sanitize serializer input for text fields.

    By default, all CharField values are sanitized except security-sensitive
    fields like passwords and OTP.
    """

    sanitize_excluded_fields = {
        "password",
        "password_confirm",
        "new_password",
        "confirm_password",
        "old_password",
        "otp",
    }

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        for field_name, value in list(attrs.items()):
            field = self.fields.get(field_name)
            if not field or field_name in self.sanitize_excluded_fields:
                continue

            if isinstance(field, serializers.CharField) and isinstance(value, str):
                attrs[field_name] = sanitize_text(value)
                continue

            if (
                isinstance(field, serializers.ListField)
                and isinstance(field.child, serializers.CharField)
                and isinstance(value, list)
            ):
                attrs[field_name] = [
                    sanitize_text(item) if isinstance(item, str) else item
                    for item in value
                ]

        return attrs
