from rest_framework import serializers
from accounts.models import ADMIN_PERMISSIONS


class AdminCreateSerializer(serializers.Serializer):
    """Serializer for creating a new admin"""
    username = serializers.CharField(
        max_length=50,
        required=True,
        help_text="Unique username for the admin"
    )
    email = serializers.EmailField(
        required=True,
        help_text="Admin email address"
    )
    first_name = serializers.CharField(
        max_length=50,
        required=False,
        default='',
        allow_blank=True
    )
    last_name = serializers.CharField(
        max_length=50,
        required=False,
        default='',
        allow_blank=True
    )
    super_admin = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, grants all permissions"
    )
    permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=[],
        help_text="List of permission strings"
    )
    
    def validate_username(self, value):
        """Validate username format"""
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Username must be at least 3 characters")
        if not value.replace('_', '').replace('-', '').isalnum():
            raise serializers.ValidationError("Username can only contain letters, numbers, underscores, and hyphens")
        return value
    
    def validate_permissions(self, value):
        """Validate that all permissions are valid"""
        invalid = [p for p in value if p not in ADMIN_PERMISSIONS]
        if invalid:
            raise serializers.ValidationError(
                f"Invalid permissions: {', '.join(invalid)}. "
                f"Valid permissions are: {', '.join(ADMIN_PERMISSIONS)}"
            )
        return value


class AdminUpdateSerializer(serializers.Serializer):
    """Serializer for updating admin details"""
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    active = serializers.BooleanField(required=False)
    
    def validate(self, data):
        if not data:
            raise serializers.ValidationError("At least one field must be provided")
        return data


class AdminPermissionsSerializer(serializers.Serializer):
    """Serializer for updating admin permissions"""
    permissions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of permission strings. Pass empty list to clear permissions."
    )
    super_admin = serializers.BooleanField(
        required=False,
        help_text="Set to true to grant all permissions, false to use specific permissions list"
    )
    
    def validate_permissions(self, value):
        """Validate that all permissions are valid"""
        invalid = [p for p in value if p not in ADMIN_PERMISSIONS]
        if invalid:
            raise serializers.ValidationError(
                f"Invalid permissions: {', '.join(invalid)}. "
                f"Valid permissions are: {', '.join(ADMIN_PERMISSIONS)}"
            )
        return value
    
    def validate(self, data):
        if 'permissions' not in data and 'super_admin' not in data:
            raise serializers.ValidationError(
                "At least 'permissions' or 'super_admin' must be provided"
            )
        return data


class AdminResponseSerializer(serializers.Serializer):
    """Serializer for admin response data"""
    id = serializers.CharField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    role = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())
    super_admin = serializers.BooleanField()
    active = serializers.BooleanField()
    two_factor_enabled = serializers.BooleanField()
    created_at = serializers.DateTimeField()
