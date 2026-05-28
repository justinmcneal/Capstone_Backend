from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.conf import settings
from bson import ObjectId
from datetime import datetime
import threading

from accounts.authentication import CustomJWTAuthentication
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.validation_utils import sanitize_text, sanitize_filename
from accounts.models import Admin, Customer, LoanOfficer
from documents.models import Document, DOCUMENT_TYPES, DOCUMENT_STATUSES

from documents.serializers import (
    DocumentUploadSerializer,
    DocumentVerifySerializer,
    validate_uploaded_file,
)
from documents.storage import get_storage_backend
from analytics.models import AuditLog
import logging

logger = logging.getLogger("documents")


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


def get_customer_by_identifier(customer_id):
    """Resolve customer record from ObjectId/string IDs across legacy data shapes."""
    if not customer_id:
        return None

    candidate_queries = []
    if isinstance(customer_id, ObjectId):
        candidate_queries.append({"_id": customer_id})
        customer_id = str(customer_id)
    else:
        try:
            candidate_queries.append({"_id": ObjectId(customer_id)})
        except Exception:
            pass

    candidate_queries.append({"_id": customer_id})
    candidate_queries.append({"customer_id": customer_id})

    for query in candidate_queries:
        customer = Customer.find_one(query)
        if customer:
            return customer
    return None


def get_display_name(user, fallback="User"):
    """Build a readable display name from common account model fields."""
    if not user:
        return fallback

    first_name = (getattr(user, "first_name", "") or "").strip()
    last_name = (getattr(user, "last_name", "") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    username = (getattr(user, "username", "") or "").strip()
    if username:
        return username

    email = (getattr(user, "email", "") or "").strip()
    if email:
        return email
    return fallback


def notify_reviewers_document_pending(document):
    """Notify active officers/admins that a document needs review."""
    from notifications.services import get_email_sender

    sender = get_email_sender()
    customer = get_customer_by_identifier(document.customer_id)
    customer_name = get_display_name(customer, fallback="Customer")

    recipients = []
    seen_emails = set()

    for officer in LoanOfficer.find({"active": True}):
        email = (officer.email or "").strip()
        if not email:
            continue
        email_key = email.lower()
        if email_key in seen_emails:
            continue
        seen_emails.add(email_key)
        recipients.append(
            {
                "email": email,
                "name": get_display_name(officer, fallback="Loan Officer"),
                "user_id": officer.id,
                "user_type": "loan_officer",
            }
        )

    for admin in Admin.find({"active": True}):
        email = (admin.email or "").strip()
        if not email:
            continue
        email_key = email.lower()
        if email_key in seen_emails:
            continue
        seen_emails.add(email_key)
        recipients.append(
            {
                "email": email,
                "name": get_display_name(admin, fallback="Admin"),
                "user_id": admin.id,
                "user_type": "admin",
            }
        )

    if not recipients:
        logger.warning(
            f"No active reviewers found to notify for pending document {document.id}"
        )
        return

    for recipient in recipients:
        try:
            sender.send_document_pending_review(
                reviewer_email=recipient["email"],
                reviewer_name=recipient["name"],
                customer_name=customer_name,
                document_type=document.document_type,
                document_id=document.id,
                reviewer_user_id=recipient["user_id"],
                reviewer_user_type=recipient["user_type"],
            )
        except Exception as e:
            logger.warning(
                f"Failed pending-review email to {recipient['email']} for document {document.id}: {e}"
            )


def notify_reviewers_document_pending_async(document):
    """Dispatch reviewer notifications in the background to avoid blocking upload responses."""
    document_id = document.id or "unknown"

    def _send():
        try:
            notify_reviewers_document_pending(document)
        except Exception as e:
            logger.warning(
                f"Background reviewer notification failed for document {document_id}: {e}"
            )

    thread = threading.Thread(
        target=_send,
        name=f"document-review-notify-{document_id}",
        daemon=True,
    )
    thread.start()


class DocumentUploadView(AccessControlMixin, APIView):
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
            has_permission, result = self.require_customer(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = str(user.customer_id)

            # Check for file in request
            if "file" not in request.FILES:
                return error_response(
                    message="No file provided", status_code=status.HTTP_400_BAD_REQUEST
                )

            file = request.FILES["file"]
            safe_original_filename = sanitize_filename(file.name)

            # Validate file
            is_valid, error_msg = validate_uploaded_file(file)
            if not is_valid:
                return error_response(
                    message=error_msg, status_code=status.HTTP_400_BAD_REQUEST
                )

            # Validate document type
            serializer = DocumentUploadSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid document data",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            data = serializer.validated_data
            document_type = data["document_type"]

            # Save file using storage backend
            storage = get_storage_backend()
            file_info = storage.save(
                file=file,
                customer_id=customer_id,
                document_type=document_type,
                original_filename=safe_original_filename,
            )

            ai_analysis = None
            run_ai_analysis = getattr(settings, "DOCUMENT_UPLOAD_AI_ANALYSIS", True)
            file_content_type = (file.content_type or "").lower()
            is_image_upload = file_content_type.startswith("image/")
            if run_ai_analysis and is_image_upload:
                # Run AI analysis on the document
                try:
                    from documents.services import analyze_document

                    # Read storage-agnostic bytes so S3 and local backends both work.
                    document_bytes = storage.get_file_bytes(file_info["file_path"])
                    ai_analysis = analyze_document(
                        document_bytes, expected_type=document_type
                    )

                    logger.info(
                        f"AI analysis complete: quality={ai_analysis.get('quality_score', 0):.2f}"
                    )
                except Exception as e:
                    logger.warning(f"AI analysis failed (continuing anyway): {e}")
                    ai_analysis = {"error": str(e), "is_valid": True}
            elif run_ai_analysis:
                logger.info(
                    f"Skipping AI analysis for non-image upload: content_type={file_content_type or 'unknown'}"
                )

            # Create document record
            document = Document(
                customer_id=customer_id,
                document_type=document_type,
                original_filename=safe_original_filename,
                file_path=file_info["file_path"],
                file_size=file_info["size"],
                mime_type=file.content_type,
                description=data.get("description", ""),
            )

            # Add AI analysis results if available
            if ai_analysis:
                document.confidence_score = ai_analysis.get("quality_score", 0)
                document.ai_analysis = ai_analysis

                # Auto-flag for review when image quality/type validation fails.
                if (not ai_analysis.get("is_valid", True)) or ai_analysis.get(
                    "quality_score", 1
                ) < 0.5:
                    document.status = "needs_review"

            document.save()

            logger.info(f"Document uploaded: {document.id} by customer {customer_id}")

            # Audit log
            AuditLog.log_action(
                action="document_uploaded",
                user_id=customer_id,
                user_type="customer",
                description=f"Document uploaded: {document_type} - {safe_original_filename}",
                resource_type="document",
                resource_id=document.id,
                details={
                    "document_type": document_type,
                    "filename": safe_original_filename,
                    "size": document.file_size,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            # Optional reviewer notification for newly pending documents.
            should_notify_reviewers = getattr(
                settings, "DOCUMENT_UPLOAD_NOTIFY_REVIEWERS", True
            )
            notify_async = getattr(settings, "DOCUMENT_UPLOAD_NOTIFY_ASYNC", True)
            if should_notify_reviewers and document.status in [
                "pending",
                "needs_review",
            ]:
                try:
                    if notify_async:
                        notify_reviewers_document_pending_async(document)
                    else:
                        notify_reviewers_document_pending(document)
                except Exception as notify_error:
                    logger.warning(
                        f"Failed to notify reviewers for document {document.id}: {notify_error}"
                    )

            response_data = {
                "id": document.id,
                "document_type": document.document_type,
                "original_filename": document.original_filename,
                "file_size": document.file_size,
                "file_size_display": document.file_size_display,
                "status": document.status,
                "uploaded_at": document.uploaded_at.isoformat(),
            }

            # Include AI analysis in response
            if ai_analysis and "error" not in ai_analysis:
                response_data["ai_analysis"] = {
                    "quality_score": ai_analysis.get("quality_score"),
                    "is_valid": ai_analysis.get("is_valid", True),
                    "quality_issues": ai_analysis.get("quality_issues", []),
                    "analysis_mode": ai_analysis.get("analysis_mode", "quality_check"),
                    "expected_type": ai_analysis.get("expected_type"),
                    "predicted_type": ai_analysis.get("predicted_type"),
                    "type_confidence": ai_analysis.get("type_confidence"),
                    "type_matches_expected": ai_analysis.get("type_matches_expected"),
                    "type_validation_passed": ai_analysis.get("type_validation_passed"),
                    "type_confidence_threshold": ai_analysis.get(
                        "type_confidence_threshold"
                    ),
                    "model_available": ai_analysis.get("model_available", False),
                }

            return success_response(
                data=response_data,
                message="Document uploaded successfully",
                status_code=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.error(f"Document upload error: {str(e)}")
            return error_response(
                message="Failed to upload document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentListView(AccessControlMixin, APIView):
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
            has_permission, result = self.require_roles(
                request,
                {"customer", "loan_officer", "admin", "super_admin"},
            )
            if not has_permission:
                return result

            user = request.user
            user_role = str(getattr(user, "role", "") or "").strip().lower()

            # Pagination parameters
            try:
                page = int(request.query_params.get("page", 1))
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page parameter",
                    errors={"page": "page must be an integer"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            try:
                page_size = min(int(request.query_params.get("page_size", 20)), 200)
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid page_size parameter",
                    errors={"page_size": "page_size must be an integer"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if page < 1:
                return error_response(
                    message="Invalid page parameter",
                    errors={"page": "page must be at least 1"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if page_size < 1:
                return error_response(
                    message="Invalid page_size parameter",
                    errors={"page_size": "page_size must be at least 1"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Optional filter by document type
            document_type = sanitize_text(request.query_params.get("type", "")).lower()
            status_filter = sanitize_text(
                request.query_params.get("status", "")
            ).lower()
            allowed_status_filters = set(DOCUMENT_STATUSES)
            if document_type and document_type not in DOCUMENT_TYPES:
                return error_response(
                    message="Invalid document type filter",
                    errors={
                        "type": f"type must be one of: {', '.join(DOCUMENT_TYPES)}"
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if status_filter and status_filter not in allowed_status_filters:
                return error_response(
                    message="Invalid status filter",
                    errors={
                        "status": f"status must be one of: {', '.join(sorted(allowed_status_filters))}"
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Optional filter by customer_id (for officers/admins)
            customer_id_filter = sanitize_text(
                request.query_params.get("customer_id", "")
            )

            # Optional search term
            search = sanitize_text(request.query_params.get("search", ""))

            # Determine which documents to show based on role
            if user_role in ["admin", "super_admin"]:
                # Admin and super admin can see all documents.
                query = {}
                if document_type:
                    query["document_type"] = document_type
                if status_filter in allowed_status_filters:
                    query["status"] = status_filter
                if customer_id_filter:
                    query.update(Document._customer_query(customer_id_filter))
                documents = Document.find(query, sort=[("uploaded_at", -1)])
            elif user_role == "loan_officer":
                # ABAC scope: officers can only see documents belonging to customers
                # they are allowed to handle via application assignment scope.
                has_scope, scope_result = self.get_officer_scoped_customer_ids(
                    request,
                    include_unassigned=True,
                )
                if not has_scope:
                    return scope_result

                scoped_customer_ids = scope_result or set()
                if customer_id_filter:
                    if customer_id_filter not in scoped_customer_ids:
                        documents = []
                    else:
                        query = Document._customer_query(customer_id_filter)
                        if document_type:
                            query["document_type"] = document_type
                        if status_filter in allowed_status_filters:
                            query["status"] = status_filter
                        documents = Document.find(query, sort=[("uploaded_at", -1)])
                elif not scoped_customer_ids:
                    documents = []
                else:
                    scope_values = []
                    for customer_id in scoped_customer_ids:
                        scope_values.extend(self._id_variants(customer_id))
                    query = {
                        "customer_id": {"$in": scope_values},
                    }
                    if document_type:
                        query["document_type"] = document_type
                    if status_filter in allowed_status_filters:
                        query["status"] = status_filter
                    documents = Document.find(query, sort=[("uploaded_at", -1)])
            else:
                # Customers can only see their own documents
                customer_id = user.customer_id
                documents = Document.find_by_customer(
                    customer_id, document_type or None
                )
                if status_filter in allowed_status_filters:
                    documents = [
                        doc for doc in documents if doc.status == status_filter
                    ]

            # Filter by search term (filename or document type)
            if search:
                search_regex = re.compile(re.escape(search), re.IGNORECASE)
                documents = [
                    doc
                    for doc in documents
                    if search_regex.search(doc.original_filename or "")
                    or search_regex.search(doc.document_type or "")
                ]

            # Get total before pagination
            total = len(documents)

            # Paginate
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_documents = documents[start_idx:end_idx]

            storage = get_storage_backend()

            docs_data = [
                {
                    "id": doc.id,
                    "customer_id": serialize_value(doc.customer_id),
                    "document_type": doc.document_type,
                    "filename": doc.original_filename,
                    "original_filename": doc.original_filename,
                    "file_size": doc.file_size,
                    "file_size_display": doc.file_size_display,
                    "mime_type": doc.mime_type,
                    "status": doc.status,
                    "verification_status": (
                        "verified"
                        if doc.verified
                        else ("rejected" if doc.status == "rejected" else "unverified")
                    ),
                    "verified": doc.verified,
                    "verified_by": serialize_value(doc.verified_by),
                    "verified_at": (
                        doc.verified_at.isoformat() if doc.verified_at else None
                    ),
                    "verification_notes": doc.notes,
                    "ai_analysis": (
                        serialize_value(doc.ai_analysis) if doc.ai_analysis else None
                    ),
                    "reupload_requested": doc.reupload_requested,
                    "reupload_reason": doc.reupload_reason,
                    "reupload_requested_by": (
                        serialize_value(doc.reupload_requested_by)
                        if doc.reupload_requested_by
                        else None
                    ),
                    "file_url": storage.get_url(doc.file_path),
                    "created_at": doc.uploaded_at.isoformat(),
                    "uploaded_at": doc.uploaded_at.isoformat(),
                }
                for doc in paginated_documents
            ]

            return success_response(
                data={
                    "documents": docs_data,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (
                        (total + page_size - 1) // page_size if total > 0 else 1
                    ),
                },
                message="Documents retrieved successfully",
            )

        except Exception as e:
            logger.error(f"List documents error: {str(e)}")
            return error_response(
                message="Failed to retrieve documents",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentDetailView(AccessControlMixin, APIView):
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
            has_permission, result = self.require_roles(
                request,
                {"customer", "loan_officer", "admin", "super_admin"},
            )
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            document = Document.find_one({"_id": ObjectId(document_id)})

            if not document:
                return error_response(
                    message="Document not found", status_code=status.HTTP_404_NOT_FOUND
                )

            user_role = str(getattr(user, "role", "") or "").strip().lower()

            # Check ownership (customers can only see their own)
            if user_role == "customer":
                has_owner, owner_result = self.require_owner(
                    request,
                    document.customer_id,
                    conceal_existence=True,
                )
                if not has_owner:
                    return owner_result
            elif user_role == "loan_officer":
                has_scope, scope_result = self.require_customer_scope_for_officer(
                    request,
                    document.customer_id,
                    include_unassigned=True,
                    conceal_existence=True,
                )
                if not has_scope:
                    return scope_result

            storage = get_storage_backend()

            return success_response(
                data={
                    "id": document.id,
                    "customer_id": serialize_value(document.customer_id),
                    "document_type": document.document_type,
                    "original_filename": document.original_filename,
                    "file_size": document.file_size,
                    "file_size_display": document.file_size_display,
                    "mime_type": document.mime_type,
                    "status": document.status,
                    "verified": document.verified,
                    "verified_by": serialize_value(document.verified_by),
                    "verified_at": (
                        document.verified_at.isoformat()
                        if document.verified_at
                        else None
                    ),
                    "rejection_reason": document.rejection_reason,
                    "description": document.description,
                    "ai_analysis": (
                        serialize_value(document.ai_analysis)
                        if document.ai_analysis
                        else None
                    ),
                    "file_url": storage.get_url(document.file_path),
                    "uploaded_at": document.uploaded_at.isoformat(),
                },
                message="Document retrieved successfully",
            )

        except Exception as e:
            logger.error(f"Get document error: {str(e)}")
            return error_response(
                message="Failed to retrieve document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, document_id):
        """Delete a document"""
        try:
            has_permission, result = self.require_customer(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = user.customer_id

            document = Document.find_one({"_id": ObjectId(document_id)})

            if not document:
                return error_response(
                    message="Document not found", status_code=status.HTTP_404_NOT_FOUND
                )

            # Only owner can delete
            has_owner, owner_result = self.require_owner(
                request,
                document.customer_id,
                conceal_existence=True,
            )
            if not has_owner:
                return owner_result

            # Cannot delete verified documents
            if document.verified:
                return error_response(
                    message="Cannot delete verified documents",
                    status_code=status.HTTP_400_BAD_REQUEST,
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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentPresignedUploadView(AccessControlMixin, APIView):
    """Provide presigned POST data for browser/client direct uploads to S3.

    POST /api/documents/presigned-upload/
    Body: { "document_type": "id_card", "original_filename": "photo.jpg" }
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            has_permission, result = self.require_customer(request)
            if not has_permission:
                return result

            user = request.user
            customer_id = str(user.customer_id)

            document_type = sanitize_text(request.data.get("document_type", "")).lower()
            original_filename = sanitize_filename(
                request.data.get("original_filename", "")
            )

            if not document_type or document_type not in DOCUMENT_TYPES:
                return error_response(
                    message="Invalid or missing document_type",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if not original_filename:
                return error_response(
                    message="original_filename is required",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            storage = get_storage_backend()

            # Only S3 backend supports presigned POST in this implementation
            if hasattr(storage, "get_presigned_upload_for_new_object"):
                post = storage.get_presigned_upload_for_new_object(
                    customer_id=customer_id,
                    document_type=document_type,
                    original_filename=original_filename,
                )
                if not post:
                    return error_response(
                        message="Failed to generate presigned upload data",
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                return success_response(
                    data=post, message="Presigned upload data generated"
                )

            return error_response(
                message="Presigned uploads are not supported by the active storage backend",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.exception("Failed to generate presigned upload data: %s", e)
            return error_response(
                message="Failed to generate presigned upload data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentVerifyView(AccessControlMixin, APIView):
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
            logger.info(
                f"Document verify request from {user.email if hasattr(user, 'email') else 'Unknown'}"
            )
            logger.info(f"Request data: {request.data}")
            logger.info(
                f"User role: {user.role if hasattr(user, 'role') else 'No role'}"
            )

            has_permission, result = self.require_officer_or_admin(request)
            if not has_permission:
                return result

            document = Document.find_one({"_id": ObjectId(document_id)})

            if not document:
                return error_response(
                    message="Document not found", status_code=status.HTTP_404_NOT_FOUND
                )

            user_role = str(getattr(user, "role", "") or "").strip().lower()
            if user_role == "loan_officer":
                has_scope, scope_result = self.require_customer_scope_for_officer(
                    request,
                    document.customer_id,
                    include_unassigned=True,
                    conceal_existence=True,
                )
                if not has_scope:
                    return scope_result

            serializer = DocumentVerifySerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"Serializer validation failed: {serializer.errors}")
                return error_response(
                    message="Invalid verification data. Expected: {'action': 'approve' or 'reject', 'rejection_reason': 'required if rejecting', 'notes': 'optional'}",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            data = serializer.validated_data
            action = data["action"]

            if action == "approve":
                document.status = "approved"
                document.verified = True
                document.verified_by = user.customer_id
                document.verified_at = datetime.utcnow()
            else:  # reject
                document.status = "rejected"
                document.verified = False
                document.rejection_reason = data.get("rejection_reason", "")

            if data.get("notes"):
                document.notes = data["notes"]

            document.save()
            customer = get_customer_by_identifier(document.customer_id)

            # Notify customer for document status outcomes.
            if action in ["approve", "reject"]:
                try:
                    from notifications.services import get_email_sender

                    if customer and customer.email:
                        sender = get_email_sender()
                        customer_name = get_display_name(customer, fallback="Customer")

                        if action == "approve":
                            sender.send_document_approved(
                                customer_email=customer.email,
                                customer_name=customer_name,
                                document_type=document.document_type,
                                document_id=document.id,
                                customer_id=customer.id,
                                notes=document.notes or "",
                            )
                        else:
                            sender.send_document_flagged(
                                customer_email=customer.email,
                                customer_name=customer_name,
                                document_type=document.document_type,
                                issues=(
                                    [document.rejection_reason]
                                    if document.rejection_reason
                                    else ["Document was rejected during verification."]
                                ),
                                document_id=document.id,
                                customer_id=customer.id,
                            )
                    else:
                        logger.warning(
                            f"Skip {action}-document email: customer/email not found for document {document.id}"
                        )
                except Exception as notify_error:
                    logger.warning(
                        f"Failed to send {action}-document email: {notify_error}"
                    )

            logger.info(f"Document {action}d: {document_id} by {user.customer_id}")

            # Audit log
            AuditLog.log_action(
                action=(
                    "document_verified" if action == "approve" else "document_rejected"
                ),
                user_id=user.customer_id,
                user_type=user.role if hasattr(user, "role") else "loan_officer",
                description=f"Document {action}d: {document.document_type}",
                resource_type="document",
                resource_id=document.id,
                details={
                    "action": action,
                    "document_type": document.document_type,
                    "customer_id": document.customer_id,
                },
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            return success_response(
                data={
                    "id": document.id,
                    "status": document.status,
                    "verified": document.verified,
                },
                message=f"Document {action}d successfully",
            )

        except Exception as e:
            logger.error(f"Verify document error: {str(e)}")
            return error_response(
                message="Failed to verify document",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentTypesView(AccessControlMixin, APIView):
    """
    Get list of available document types.

    GET /api/documents/types/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get available document types with descriptions"""
        from loans.services.qualification import resolve_required_document_types

        has_permission, result = self.require_roles(
            request,
            {"customer", "loan_officer", "admin", "super_admin"},
        )
        if not has_permission:
            return result

        product_id = sanitize_text(request.query_params.get("product_id", ""))
        requirement_source = "baseline"
        required_document_set = set(resolve_required_document_types(None, "baseline"))

        if product_id:
            from loans.models import LoanProduct

            if not ObjectId.is_valid(product_id):
                return error_response(
                    message="Invalid product_id format",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            product = LoanProduct.find_by_id(product_id)
            if not product or not product.active:
                return error_response(
                    message="Loan product not found",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            requirement_source = "product"
            required_document_set = set(
                resolve_required_document_types(product, "product")
            )

        types_info = []
        for doc_type in DOCUMENT_TYPES:
            label = doc_type.replace("_", " ").title()
            types_info.append(
                {
                    "value": doc_type,
                    "label": label,
                    "required": doc_type in required_document_set,
                }
            )

        return success_response(
            data={
                "document_types": types_info,
                "requirement_source": requirement_source,
            },
            message="Document types retrieved successfully",
        )


class RequestReuploadView(AccessControlMixin, APIView):
    """
    Officer requests customer to re-upload a document.

    POST /api/documents/<id>/request-reupload/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, document_id):
        has_permission, result = self.require_officer_or_admin(request)
        if not has_permission:
            return result
        user = request.user

        doc = None
        try:
            doc = Document.find_one({"_id": ObjectId(document_id)})
        except Exception:
            doc = None
        if not doc:
            return error_response(
                message="Document not found", status_code=status.HTTP_404_NOT_FOUND
            )

        user_role = str(getattr(user, "role", "") or "").strip().lower()
        if user_role == "loan_officer":
            has_scope, scope_result = self.require_customer_scope_for_officer(
                request,
                doc.customer_id,
                include_unassigned=True,
                conceal_existence=True,
            )
            if not has_scope:
                return scope_result

        reason = sanitize_text(request.data.get("reason", ""))
        if not reason:
            return error_response(
                message="reason is required", status_code=status.HTTP_400_BAD_REQUEST
            )
        if len(reason) > 1000:
            return error_response(
                message="reason must be at most 1000 characters",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        doc.request_reupload(
            officer_id=(
                user.customer_id if hasattr(user, "customer_id") else str(user._id)
            ),
            reason=reason,
        )

        logger.info(f"Re-upload requested for document {doc.id}")

        # Send email notification to customer
        try:
            from notifications.services import get_email_sender

            customer = get_customer_by_identifier(doc.customer_id)
            if customer and customer.email:
                sender = get_email_sender()
                sender.send_document_flagged(
                    customer_email=customer.email,
                    customer_name=get_display_name(customer, fallback="Customer"),
                    document_type=doc.document_type,
                    issues=[reason],  # Pass reason as list of issues
                    document_id=doc.id,
                    customer_id=customer.id,
                )
            else:
                logger.warning(
                    f"Skip reupload email: customer/email not found for document {doc.id}"
                )
        except Exception as e:
            logger.warning(f"Failed to send re-upload email: {e}")

        return success_response(
            data={
                "document_id": doc.id,
                "status": doc.status,
                "reupload_requested": doc.reupload_requested,
            },
            message="Re-upload request sent",
        )
