from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


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
            raise serializers.ValidationError('OTP must be a 6-digit number')
        if len(value) != 6:
            raise serializers.ValidationError('OTP must be exactly 6 digits')
        return value


class PasswordConfirmationMixin:
    def validate(self, attrs):
        password_field = 'new_password' if 'new_password' in attrs else 'password'
        confirm_field = 'confirm_password'
        
        if password_field in attrs and confirm_field in attrs:
            if attrs.get(password_field) != attrs.get(confirm_field):
                raise serializers.ValidationError(
                    {confirm_field: 'Passwords do not match'}
                )
        
        if 'old_password' in attrs and 'new_password' in attrs:
            if attrs.get('old_password') == attrs.get('new_password'):
                raise serializers.ValidationError(
                    {'new_password': 'New password must be different from old password'}
                )
        
        return super().validate(attrs) if hasattr(super(), 'validate') else attrs
