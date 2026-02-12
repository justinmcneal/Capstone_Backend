from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import HttpResponse
from bson import ObjectId
from datetime import datetime
import os
import tempfile

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.response_helpers import success_response, error_response
from documents.models import Document
from documents.serializers import (
    DocumentUploadSerializer,
    DocumentVerifySerializer,
    validate_uploaded_file
)
from documents.storage import get_storage_backend
from documents.services.encryption_service import DocumentEncryptionError
from analytics.models import AuditLog
from config.security_events import log_security_event
import logging

logger = logging.getLogger('documents')


def serialize_value(value):
    """Convert MongoDB types to JSON-serializable types"""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


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
            customer_id = getattr(user, 'customer_id', '')
            user_role = getattr(user, 'role', '')

            log_security_event(
                event='document_upload_request_received',
                outcome='success',
                request=request,
                user_id=customer_id,
                user_role=user_role,
            )
            
            # Only customers can upload documents
            if hasattr(user, 'role') and user.role != 'customer':
                log_security_event(
                    event='document_authorization_check',
                    outcome='blocked',
                    request=request,
                    user_id=customer_id,
                    user_role=user_role,
                    details={'resource': 'document_upload', 'reason': 'non_customer_role'},
                )
                return error_response(
                    message="Only customers can upload documents",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            customer_id = user.customer_id
            log_security_event(
                event='document_authorization_check',
                outcome='allowed',
                request=request,
                user_id=customer_id,
                user_role='customer',
                details={'resource': 'document_upload'},
            )
            
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
            serializer = DocumentUploadSerializer(data=request.data, context={'request': request})
            if not serializer.is_valid():
                return error_response(
                    message="Invalid document data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            data = serializer.validated_data
            document_type = data['document_type']
            
            # Run AI analysis on the document
            ai_analysis = None
            try:
                from documents.services import analyze_document

                suffix = os.path.splitext(file.name)[1] or '.tmp'
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                    for chunk in file.chunks():
                        temp_file.write(chunk)
                    temp_path = temp_file.name

                if hasattr(file, 'seek'):
                    file.seek(0)

                ai_analysis = analyze_document(temp_path, expected_type=document_type)
                
                logger.info(f"AI analysis complete: quality={ai_analysis.get('quality_score', 0):.2f}")
            except Exception as e:
                logger.warning(f"AI analysis failed (continuing anyway): {e}")
                ai_analysis = {'error': str(e), 'is_valid': True}
            finally:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    os.remove(temp_path)

            # Save file using storage backend (encrypted at rest)
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
                encrypted_file_size=file_info.get('encrypted_size', 0),
                mime_type=file.content_type,
                description=data.get('description', ''),
                storage_filename=file_info.get('filename', ''),
                is_encrypted=file_info.get('is_encrypted', False),
                encryption_algorithm=file_info.get('encryption_algorithm', ''),
                encryption_version=file_info.get('encryption_version', '')
            )
            
            # Add AI analysis results if available
            if ai_analysis:
                document.confidence_score = ai_analysis.get('quality_score', 0)
                document.ai_analysis = ai_analysis
                
                # Auto-flag low quality for review
                if ai_analysis.get('quality_score', 1) < 0.5:
                    document.status = 'needs_review'
            
            document.save()
            
            logger.info(f"Document uploaded: {document.id} by customer {customer_id}")
            log_security_event(
                event='document_upload_completed',
                outcome='success',
                request=request,
                user_id=customer_id,
                user_role='customer',
                details={
                    'document_id': document.id,
                    'document_type': document_type,
                    'is_encrypted': document.is_encrypted,
                    'encryption_algorithm': document.encryption_algorithm,
                }
            )
            
            # Audit log
            AuditLog.log_action(
                action='document_uploaded',
                user_id=customer_id,
                user_type='customer',
                description=f'Document uploaded: {document_type} - {file.name}',
                resource_type='document',
                resource_id=document.id,
                details={'document_type': document_type, 'filename': file.name, 'size': document.file_size},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            response_data = {
                'id': document.id,
                'document_type': document.document_type,
                'original_filename': document.original_filename,
                'file_size': document.file_size,
                'encrypted_file_size': document.encrypted_file_size,
                'file_size_display': document.file_size_display,
                'status': document.status,
                'uploaded_at': document.uploaded_at.isoformat()
            }
            
            # Include AI analysis in response
            if ai_analysis and 'error' not in ai_analysis:
                response_data['ai_analysis'] = {
                    'quality_score': ai_analysis.get('quality_score'),
                    'is_valid': ai_analysis.get('is_valid', True),
                    'quality_issues': ai_analysis.get('quality_issues', []),
                    'analysis_mode': ai_analysis.get('analysis_mode', 'quality_check'),
                    'predicted_type': ai_analysis.get('predicted_type'),
                    'type_confidence': ai_analysis.get('type_confidence'),
                    'model_available': ai_analysis.get('model_available', False)
                }
            
            return success_response(
                data=response_data,
                message="Document uploaded successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Document upload error: {str(e)}")
            log_security_event(
                event='document_upload_failed',
                outcome='error',
                request=request,
                user_id=getattr(request.user, 'customer_id', ''),
                user_role=getattr(request.user, 'role', ''),
                details={'reason': str(e)}
            )
            return error_response(
                message="Failed to upload document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class DocumentListView(APIView):
    """
    List documents based on user role.
    - Customers: Only their own documents
    - Loan Officers/Admins: All documents
    
    GET /api/documents/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """List documents based on user role"""
        import re
        
        try:
            user = request.user
            
            # Pagination parameters
            page = int(request.query_params.get('page', 1))
            page_size = min(int(request.query_params.get('page_size', 20)), 200)
            
            # Optional filter by document type
            document_type = request.query_params.get('type')
            
            # Optional filter by customer_id (for officers/admins)
            customer_id_filter = request.query_params.get('customer_id')
            
            # Optional search term
            search = request.query_params.get('search', '').strip()
            
            # Determine which documents to show based on role
            if hasattr(user, 'role') and user.role in ['loan_officer', 'admin', 'super_admin']:
                # Loan officers and admins can see all documents
                query = {}
                if document_type:
                    query['document_type'] = document_type
                if customer_id_filter:
                    query['customer_id'] = customer_id_filter
                documents = Document.find(query, sort=[('uploaded_at', -1)])
            else:
                # Customers can only see their own documents
                customer_id = user.customer_id
                documents = Document.find_by_customer(customer_id, document_type)
            
            # Filter by search term (filename or document type)
            if search:
                search_regex = re.compile(re.escape(search), re.IGNORECASE)
                documents = [
                    doc for doc in documents
                    if search_regex.search(doc.original_filename or '') or
                       search_regex.search(doc.document_type or '')
                ]
            
            # Get total before pagination
            total = len(documents)
            
            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_documents = documents[start_idx:end_idx]
            
            docs_data = [{
                'id': doc.id,
                'customer_id': serialize_value(doc.customer_id),
                'document_type': doc.document_type,
                'filename': doc.original_filename,
                'original_filename': doc.original_filename,
                'file_size': doc.file_size,
                'file_size_display': doc.file_size_display,
                'mime_type': doc.mime_type,
                'status': doc.status,
                'verification_status': 'verified' if doc.verified else ('rejected' if doc.status == 'rejected' else 'unverified'),
                'verified': doc.verified,
                'verified_by': serialize_value(doc.verified_by),
                'verified_at': doc.verified_at.isoformat() if doc.verified_at else None,
                'verification_notes': doc.notes,
                'ai_analysis': serialize_value(doc.ai_analysis) if doc.ai_analysis else None,
                'reupload_requested': doc.reupload_requested,
                'reupload_reason': doc.reupload_reason,
                'reupload_requested_by': serialize_value(doc.reupload_requested_by) if doc.reupload_requested_by else None,
                'file_url': f"/api/documents/{doc.id}/preview/",
                'preview_url': f"/api/documents/{doc.id}/preview/",
                'download_url': f"/api/documents/{doc.id}/preview/?download=true",
                'is_encrypted': doc.is_encrypted,
                'encryption_algorithm': doc.encryption_algorithm,
                'created_at': doc.uploaded_at.isoformat(),
                'uploaded_at': doc.uploaded_at.isoformat()
            } for doc in paginated_documents]
            
            return success_response(
                data={
                    'documents': docs_data,
                    'total': total,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': (total + page_size - 1) // page_size if total > 0 else 1
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
                    log_security_event(
                        event='document_access_blocked',
                        outcome='blocked',
                        request=request,
                        user_id=customer_id,
                        user_role='customer',
                        details={'document_id': document_id, 'reason': 'ownership_mismatch'}
                    )
                    return error_response(
                        message="Document not found",
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            
            return success_response(
                data={
                    'id': document.id,
                    'customer_id': serialize_value(document.customer_id),
                    'document_type': document.document_type,
                    'original_filename': document.original_filename,
                    'file_size': document.file_size,
                    'file_size_display': document.file_size_display,
                    'mime_type': document.mime_type,
                    'status': document.status,
                    'verified': document.verified,
                    'verified_by': serialize_value(document.verified_by),
                    'verified_at': document.verified_at.isoformat() if document.verified_at else None,
                    'rejection_reason': document.rejection_reason,
                    'description': document.description,
                    'ai_analysis': serialize_value(document.ai_analysis) if document.ai_analysis else None,
                    'file_url': f"/api/documents/{document.id}/preview/",
                    'preview_url': f"/api/documents/{document.id}/preview/",
                    'download_url': f"/api/documents/{document.id}/preview/?download=true",
                    'is_encrypted': document.is_encrypted,
                    'encryption_algorithm': document.encryption_algorithm,
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
                log_security_event(
                    event='document_access_blocked',
                    outcome='blocked',
                    request=request,
                    user_id=customer_id,
                    user_role='customer',
                    details={'document_id': document_id, 'reason': 'delete_ownership_mismatch'}
                )
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


class DocumentPreviewView(APIView):
    """
    Preview a document with authorization checks and decrypt-on-access.

    GET /api/documents/<id>/preview/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        try:
            user = request.user
            user_id = getattr(user, 'customer_id', '')
            user_role = getattr(user, 'role', '')
            force_download = (
                str(request.query_params.get('download', '')).lower() in ('1', 'true', 'yes')
                or request.path.endswith('/download/')
            )

            log_security_event(
                event='document_view_request_received',
                outcome='success',
                request=request,
                user_id=user_id,
                user_role=user_role,
                details={'document_id': document_id, 'force_download': force_download},
            )

            document = Document.find_one({'_id': ObjectId(document_id)})

            if not document:
                return error_response(
                    message="Document not found",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            if hasattr(user, 'role') and user.role == 'customer':
                if document.customer_id != user.customer_id:
                    log_security_event(
                        event='document_authorization_check',
                        outcome='blocked',
                        request=request,
                        user_id=user.customer_id,
                        user_role='customer',
                        details={'document_id': document_id, 'reason': 'preview_ownership_mismatch'},
                    )
                    log_security_event(
                        event='document_access_blocked',
                        outcome='blocked',
                        request=request,
                        user_id=user.customer_id,
                        user_role='customer',
                        details={'document_id': document_id, 'reason': 'preview_ownership_mismatch'}
                    )
                    return error_response(
                        message="Document not found",
                        status_code=status.HTTP_404_NOT_FOUND
                    )
            elif not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin', 'super_admin']:
                log_security_event(
                    event='document_authorization_check',
                    outcome='blocked',
                    request=request,
                    user_id=getattr(user, 'customer_id', ''),
                    user_role=getattr(user, 'role', ''),
                    details={'document_id': document_id, 'reason': 'insufficient_role'},
                )
                log_security_event(
                    event='document_access_blocked',
                    outcome='blocked',
                    request=request,
                    user_id=getattr(user, 'customer_id', ''),
                    user_role=getattr(user, 'role', ''),
                    details={'document_id': document_id, 'reason': 'insufficient_role'}
                )
                return error_response(
                    message="Forbidden",
                    status_code=status.HTTP_403_FORBIDDEN
                )

            log_security_event(
                event='document_authorization_check',
                outcome='allowed',
                request=request,
                user_id=user_id,
                user_role=user_role,
                details={'document_id': document_id, 'resource': 'document_preview'},
            )

            storage = get_storage_backend()
            if document.is_encrypted:
                file_bytes = storage.read_decrypted(
                    document.file_path,
                    encryption_algorithm=document.encryption_algorithm,
                    event_details={
                        'storage_path': document.file_path,
                        'document_id': document.id,
                        'access_mode': 'preview',
                    }
                )
            else:
                full_path = storage.get_full_path(document.file_path)
                with open(full_path, 'rb') as source:
                    file_bytes = source.read()

            log_security_event(
                event='document_preview_streamed',
                outcome='success',
                request=request,
                user_id=getattr(user, 'customer_id', ''),
                user_role=getattr(user, 'role', ''),
                details={
                    'document_id': document.id,
                    'document_type': document.document_type,
                    'is_encrypted': document.is_encrypted,
                    'force_download': force_download,
                }
            )

            response = HttpResponse(
                file_bytes,
                content_type=document.mime_type or 'application/octet-stream'
            )
            disposition = 'attachment' if force_download else 'inline'
            response['Content-Disposition'] = f'{disposition}; filename="{document.original_filename}"'
            return response

        except DocumentEncryptionError as exc:
            logger.error(f"Encrypted document preview error for {document_id}: {str(exc)}")
            log_security_event(
                event='document_decryption_triggered',
                outcome='error',
                request=request,
                user_id=getattr(request.user, 'customer_id', ''),
                user_role=getattr(request.user, 'role', ''),
                details={'document_id': document_id, 'reason': str(exc)}
            )
            return error_response(
                message="Unable to decrypt document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"Document preview error for {document_id}: {str(e)}")
            return error_response(
                message="Failed to preview document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentDownloadView(DocumentPreviewView):
    """
    Legacy alias for document retrieval path.
    Use /preview/ with ?download=true for explicit download behavior.
    """


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
            
            # Debug logging
            logger.info(f"Document verify request from {user.email if hasattr(user, 'email') else 'Unknown'}")
            logger.info(f"Request data: {request.data}")
            logger.info(f"User role: {user.role if hasattr(user, 'role') else 'No role'}")
            
            # Only loan officers, admins, and super admins can verify
            if not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin', 'super_admin']:
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
                logger.error(f"Serializer validation failed: {serializer.errors}")
                return error_response(
                    message="Invalid verification data. Expected: {'action': 'approve' or 'reject', 'rejection_reason': 'required if rejecting', 'notes': 'optional'}",
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
            
            # Audit log
            AuditLog.log_action(
                action='document_verified' if action == 'approve' else 'document_rejected',
                user_id=user.customer_id,
                user_type=user.role if hasattr(user, 'role') else 'loan_officer',
                description=f'Document {action}d: {document.document_type}',
                resource_type='document',
                resource_id=document.id,
                details={'action': action, 'document_type': document.document_type, 'customer_id': document.customer_id},
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
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


class RequestReuploadView(APIView):
    """
    Officer requests customer to re-upload a document.
    
    POST /api/documents/<id>/request-reupload/
    """
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, document_id):
        user = request.user
        
        # Only officers/admins/super admins can request re-upload
        if not hasattr(user, 'role') or user.role not in ['loan_officer', 'admin', 'super_admin']:
            return error_response(
                message="Only officers can request document re-upload",
                status_code=status.HTTP_403_FORBIDDEN
            )
        
        doc = Document.find_by_id(document_id)
        if not doc:
            return error_response(
                message="Document not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
        
        reason = request.data.get('reason', '')
        if not reason:
            return error_response(
                message="reason is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )
        
        doc.request_reupload(
            officer_id=user.customer_id if hasattr(user, 'customer_id') else str(user._id),
            reason=reason
        )
        
        logger.info(f"Re-upload requested for document {doc.id}")
        
        # Send email notification to customer
        try:
            from accounts.models import Customer
            from notifications.services import get_email_sender
            
            customer = Customer.find_one({'customer_id': doc.customer_id})
            if customer and customer.email:
                sender = get_email_sender()
                sender.send_document_flagged(
                    customer_email=customer.email,
                    customer_name=f"{customer.first_name} {customer.last_name}",
                    document_type=doc.document_type,
                    issues=[reason]  # Pass reason as list of issues
                )
        except Exception as e:
            logger.warning(f"Failed to send re-upload email: {e}")
        
        return success_response(
            data={
                'document_id': doc.id,
                'status': doc.status,
                'reupload_requested': doc.reupload_requested
            },
            message="Re-upload request sent"
        )
