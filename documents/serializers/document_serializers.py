from rest_framework import serializers
from documents.models import DOCUMENT_TYPES, ALLOWED_MIME_TYPES, MAX_FILE_SIZE


class DocumentUploadSerializer(serializers.Serializer):
    """Serializer for document upload validation"""
    
    document_type = serializers.ChoiceField(
        choices=DOCUMENT_TYPES,
        required=True,
        help_text="Type of document being uploaded"
    )
    description = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Optional description of the document"
    )
    # File is handled separately via request.FILES
    
    def validate_document_type(self, value):
        if value not in DOCUMENT_TYPES:
            raise serializers.ValidationError(
                f"Invalid document type. Must be one of: {', '.join(DOCUMENT_TYPES)}"
            )
        return value


class DocumentResponseSerializer(serializers.Serializer):
    """Serializer for document response data"""
    id = serializers.CharField()
    customer_id = serializers.CharField()
    document_type = serializers.CharField()
    original_filename = serializers.CharField()
    file_size = serializers.IntegerField()
    file_size_display = serializers.CharField()
    mime_type = serializers.CharField()
    status = serializers.CharField()
    verified = serializers.BooleanField()
    verification = serializers.SerializerMethodField()
    description = serializers.CharField()
    uploaded_at = serializers.DateTimeField()
    file_url = serializers.CharField()
    
    def get_verification(self, obj):
        if obj.verified:
            return {
                'verified': True,
                'verified_at': obj.verified_at.isoformat() if obj.verified_at else None
            }
        elif obj.status == 'rejected':
            return {
                'verified': False,
                'rejection_reason': obj.rejection_reason
            }
        return {'verified': False, 'status': obj.status}


class DocumentVerifySerializer(serializers.Serializer):
    """Serializer for loan officer document verification"""
    
    action = serializers.ChoiceField(
        choices=['approve', 'reject'],
        required=True
    )
    rejection_reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Required when rejecting a document"
    )
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        help_text="Optional notes for the document"
    )
    
    def validate(self, data):
        if data['action'] == 'reject' and not data.get('rejection_reason'):
            raise serializers.ValidationError({
                'rejection_reason': 'Rejection reason is required when rejecting a document'
            })
        return data


def validate_uploaded_file(file):
    """
    Validate uploaded file type and size.
    
    Args:
        file: Django UploadedFile object
    
    Returns:
        tuple: (is_valid, error_message)
    """
    # Check file size
    if file.size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        return False, f"File size exceeds maximum allowed ({max_mb:.0f}MB)"
    
    # Check MIME type
    content_type = file.content_type
    if content_type not in ALLOWED_MIME_TYPES:
        return False, f"Invalid file type. Allowed types: JPEG, PNG, PDF"
    
    return True, None
