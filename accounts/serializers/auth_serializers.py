from rest_framework import serializers
from accounts.utils.email_utils import EmailUtils
from .base_serializers import PasswordValidationMixin
from accounts.utils.input_sanitizer import sanitize_text_input


class SignUpSerializer(PasswordValidationMixin, serializers.Serializer):
    
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=True, write_only=True)
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True, required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=[('en', 'English'), ('tl', 'Tagalog')], default='en', required=False)
    
    def validate_first_name(self, value):
        request = self.context.get('request') if hasattr(self, 'context') else None
        return sanitize_text_input(
            value=value,
            field_name='first_name',
            request=request,
            max_length=100
        )
    
    def validate_last_name(self, value):
        request = self.context.get('request') if hasattr(self, 'context') else None
        return sanitize_text_input(
            value=value,
            field_name='last_name',
            request=request,
            max_length=100
        )

    def validate_middle_name(self, value):
        request = self.context.get('request') if hasattr(self, 'context') else None
        return sanitize_text_input(
            value=value,
            field_name='middle_name',
            request=request,
            allow_blank=True,
            max_length=100
        )
    
    def validate_email(self, value):
        """Validate and normalize email using centralized method"""
        request = self.context.get('request') if hasattr(self, 'context') else None
        sanitize_text_input(
            value=value,
            field_name='email',
            request=request,
            max_length=254
        )
        return EmailUtils.normalize_email(value)
    
    def validate_phone(self, value):
        """Validate phone number format"""
        if value:
            request = self.context.get('request') if hasattr(self, 'context') else None
            cleaned_value = sanitize_text_input(
                value=value,
                field_name='phone',
                request=request,
                allow_blank=True,
                max_length=20
            )
            # Remove spaces and dashes
            cleaned = cleaned_value.replace(' ', '').replace('-', '')
            # Basic validation for Philippine phone numbers
            if not cleaned.startswith(('09', '+63', '63')):
                raise serializers.ValidationError('Please enter a valid Philippine phone number')
            return cleaned
        return value
    
    def validate(self, data):
        """Validate password confirmation if provided"""
        password = data.get('password')
        password_confirm = data.get('password_confirm')
        
        if password_confirm and password != password_confirm:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        
        return data

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    remember_me = serializers.BooleanField(default=False)

    def validate_email(self, value):
        request = self.context.get('request') if hasattr(self, 'context') else None
        sanitize_text_input(
            value=value,
            field_name='email',
            request=request,
            max_length=254
        )
        return EmailUtils.normalize_email(value)
