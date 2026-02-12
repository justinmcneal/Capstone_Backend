from rest_framework import serializers
from documents.models import DOCUMENT_TYPES, ALLOWED_MIME_TYPES, MAX_FILE_SIZE
from accounts.utils.input_sanitizer import sanitize_text_input


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
        request = self.context.get('request') if hasattr(self, 'context') else None
        sanitize_text_input(
            value=value,
            field_name='document_type',
            request=request,
            max_length=100
        )
        if value not in DOCUMENT_TYPES:
            raise serializers.ValidationError(
                f"Invalid document type. Must be one of: {', '.join(DOCUMENT_TYPES)}"
            )
        return value

    def validate_description(self, value):
        request = self.context.get('request') if hasattr(self, 'context') else None
        return sanitize_text_input(
            value=value,
            field_name='description',
            request=request,
            allow_blank=True,
            max_length=500
        )


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
        choices=['approve', 'reject', 'approved', 'rejected'],  # Accept both forms
        required=False  # Make it optional to check for 'status' field
    )
    status = serializers.ChoiceField(
        choices=['approve', 'reject', 'approved', 'rejected'],
        required=False  # Accept 'status' as alternative to 'action'
    )
    rejection_reason = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=False,  # Don't allow blank strings
        help_text="Required when rejecting a document"
    )
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        help_text="Optional notes for the document"
    )
    
    def validate(self, data):
        # Get action from either 'action' or 'status' field
        action = data.get('action') or data.get('status')
        
        if not action:
            raise serializers.ValidationError({
                'action': 'Either "action" or "status" field is required with value "approve" or "reject"'
            })
        
        # Normalize the action value
        if action in ['approved', 'approve']:
            data['action'] = 'approve'
        elif action in ['rejected', 'reject']:
            data['action'] = 'reject'
        else:
            raise serializers.ValidationError({
                'action': f'Invalid action: {action}. Must be "approve" or "reject"'
            })
        
        # Remove 'status' field if it was provided
        data.pop('status', None)
        
        # Validate rejection reason - must be present and not just whitespace
        if data['action'] == 'reject':
            rejection_reason = data.get('rejection_reason', '').strip()
            if not rejection_reason:
                raise serializers.ValidationError({
                    'rejection_reason': 'Rejection reason is required when rejecting a document. It cannot be empty or whitespace.'
                })
            # Store the trimmed value
            data['rejection_reason'] = rejection_reason
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
