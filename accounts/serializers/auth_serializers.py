from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from accounts.utils.email_utils import EmailUtils
import re

class PasswordValidationMixin:
    def validate_password(self, value):
        try:
            validate_password(value)
        except ValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value


class SignUpSerializer(PasswordValidationMixin, serializers.Serializer):
    
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate_first_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('First name cannot be blank')
        return value.strip()
    
    def validate_last_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Last name cannot be blank')
        return value.strip()
    
    def validate_email(self, value):
        """Validate and normalize email using centralized method"""
        return EmailUtils.normalize_email(value)

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(default=False)

    def validate_email(self, value):
        return EmailUtils.normalize_email(value)