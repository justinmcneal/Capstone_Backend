from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from bson import ObjectId
from datetime import datetime

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from accounts.models import Admin
from documents.models import Document, DOCUMENT_TYPES
from documents.serializers import (
    DocumentUploadSerializer,
    DocumentVerifySerializer,
    validate_uploaded_file
)
from documents.storage import get_storage_backend
import logging

logger = logging.getLogger('documents')


class DocumentUploadView(APIView):
    """
    Upload documents for customers.
    
    POST /api/documents/upload/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """Upload a document"""
        try:
            user = request.user
            
            # Only customers can upload documents
            if hasattr(user, 'role') and user.role != 'customer':
                return error_response(
                    message="Only customers can upload documents",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            customer_id = user.customer_id
            
            # Check for file in request
            if 'file' not in request.FILES:
                return error_response(
                    message="No file provided",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            file = request.FILES['file']
            
            # Validate file
            is_valid, error_msg = validate_uploaded_file(file)
            if not is_valid:
                return error_response(
                    message=error_msg,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate document type
            serializer = DocumentUploadSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid document data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            document_type = data['document_type']
            
            # Save file using storage backend
            storage = get_storage_backend()
            file_info = storage.save(
                file=file,
                customer_id=customer_id,
                document_type=document_type,
                original_filename=file.name
            )
            
            # Create document record
            document = Document(
                customer_id=customer_id,
                document_type=document_type,
                original_filename=file.name,
                file_path=file_info['file_path'],
                file_size=file_info['size'],
                mime_type=file.content_type,
                description=data.get('description', '')
            )
            document.save()
            
            logger.info(f"Document uploaded: {document.id} by customer {customer_id}")
            
            return success_response(
                data={
                    'id': document.id,
                    'document_type': document.document_type,
                    'original_filename': document.original_filename,
                    'file_size': document.file_size,
                    'file_size_display': document.file_size_display,
                    'status': document.status,
                    'uploaded_at': document.uploaded_at.isoformat()
                },
                message="Document uploaded successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Document upload error: {str(e)}")
            return error_response(
                message="Failed to upload document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentListView(APIView):
    """
    List documents for the authenticated customer.
    
    GET /api/documents/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List all documents for the customer"""
        try:
            user = request.user
            customer_id = user.customer_id
            
            # Optional filter by document type
            document_type = request.query_params.get('type')
            
            documents = Document.find_by_customer(customer_id, document_type)
            storage = get_storage_backend()
            
            docs_data = [{
                'id': doc.id,
                'document_type': doc.document_type,
                'original_filename': doc.original_filename,
                'file_size': doc.file_size,
                'file_size_display': doc.file_size_display,
                'mime_type': doc.mime_type,
                'status': doc.status,
                'verified': doc.verified,
                'file_url': storage.get_url(doc.file_path),
                'uploaded_at': doc.uploaded_at.isoformat()
            } for doc in documents]
            
            return success_response(
                data={
                    'documents': docs_data,
                    'total': len(docs_data)
                },
                message="Documents retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"List documents error: {str(e)}")
            return error_response(
                message="Failed to retrieve documents",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentDetailView(APIView):
    """
    Get, delete a specific document.
    
    GET /api/documents/<id>/
    DELETE /api/documents/<id>/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request, document_id):
        """Get document details"""
        try:
            user = request.user
            customer_id = user.customer_id
            
            document = Document.find_one({'_id': ObjectId(document_id)})
            
            if not document:
                return error_response(
                    message="Document not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Check ownership (customers can only see their own)
            if hasattr(user, 'role') and user.role == 'customer':
                if document.customer_id != customer_id:
                    return error_response(
                        message="Document not found",
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            
            storage = get_storage_backend()
            
            return success_response(
                data={
                    'id': document.id,
                    'customer_id': document.customer_id,
                    'document_type': document.document_type,
                    'original_filename': document.original_filename,
                    'file_size': document.file_size,
                    'file_size_display': document.file_size_display,
                    'mime_type': document.mime_type,
                    'status': document.status,
                    'verified': document.verified,
                    'verified_at': document.verified_at.isoformat() if document.verified_at else None,
                    'rejection_reason': document.rejection_reason,
                    'description': document.description,
                    'file_url': storage.get_url(document.file_path),
                    'uploaded_at': document.uploaded_at.isoformat()
                },
                message="Document retrieved successfully"
            )
            
        except Exception as e:
            logger.error(f"Get document error: {str(e)}")
            return error_response(
                message="Failed to retrieve document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, document_id):
        """Delete a document"""
        try:
            user = request.user
            customer_id = user.customer_id
            
            document = Document.find_one({'_id': ObjectId(document_id)})
            
            if not document:
                return error_response(
                    message="Document not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Only owner can delete
            if document.customer_id != customer_id:
                return error_response(
                    message="Document not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            # Cannot delete verified documents
            if document.verified:
                return error_response(
                    message="Cannot delete verified documents",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Delete file from storage
            storage = get_storage_backend()
            storage.delete(document.file_path)
            
            # Delete document record
            document.delete()
            
            logger.info(f"Document deleted: {document_id} by customer {customer_id}")
            
            return success_response(message="Document deleted successfully")
            
        except Exception as e:
            logger.error(f"Delete document error: {str(e)}")
            return error_response(
                message="Failed to delete document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentVerifyView(APIView):
    """
    Loan officer endpoint to verify documents.
    
    PUT /api/documents/<id>/verify/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def put(self, request, document_id):
        """Approve or reject a document"""
        try:
            user = request.user
            
            # Only loan officers and admins can verify
            if not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin']:
                return error_response(
                    message="Only loan officers can verify documents",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            document = Document.find_one({'_id': ObjectId(document_id)})
            
            if not document:
                return error_response(
                    message="Document not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )
            
            serializer = DocumentVerifySerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid verification data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            action = data['action']
            
            if action == 'approve':
                document.status = 'approved'
                document.verified = True
                document.verified_by = user.customer_id
                document.verified_at = datetime.utcnow()
            else:  # reject
                document.status = 'rejected'
                document.verified = False
                document.rejection_reason = data.get('rejection_reason', '')
            
            if data.get('notes'):
                document.notes = data['notes']
            
            document.save()
            
            logger.info(f"Document {action}d: {document_id} by {user.customer_id}")
            
            return success_response(
                data={
                    'id': document.id,
                    'status': document.status,
                    'verified': document.verified
                },
                message=f"Document {action}d successfully"
            )
            
        except Exception as e:
            logger.error(f"Verify document error: {str(e)}")
            return error_response(
                message="Failed to verify document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentTypesView(APIView):
    """
    Get list of available document types.
    
    GET /api/documents/types/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get available document types with descriptions"""
        types_info = [
            {'value': 'valid_id', 'label': 'Valid Government ID', 'required': True},
            {'value': 'selfie_with_id', 'label': 'Selfie with ID', 'required': False},
            {'value': 'proof_of_address', 'label': 'Proof of Address', 'required': False},
            {'value': 'business_permit', 'label': 'Business Permit', 'required': False},
            {'value': 'business_photo', 'label': 'Business Photo', 'required': False},
            {'value': 'income_proof', 'label': 'Proof of Income (Optional)', 'required': False},
            {'value': 'other', 'label': 'Other Documents', 'required': False},
        ]
        
        return success_response(
            data={'document_types': types_info},
            message="Document types retrieved successfully"
        )
