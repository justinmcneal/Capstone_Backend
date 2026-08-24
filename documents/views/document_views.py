import logging
from datetime import datetime

from bson import ObjectId
from django.conf import settings
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.authentication import CustomJWTAuthentication
from accounts.services.consent_service import (  # noqa: F401 - test patch boundary
    ConsentService,
)
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.request_utils import get_client_ip
from accounts.utils.response_helpers import error_response, success_response
from accounts.utils.throttles import DocumentUploadRateThrottle
from accounts.utils.validation_utils import sanitize_filename, sanitize_text
from analytics.models import AuditLog  # noqa: F401 - test integration compatibility
from documents.metrics import DOCUMENT_OPERATIONS, increment
from documents.models import (
    DOCUMENT_STATUSES,
    DOCUMENT_TYPES,
    Document,
    DocumentRevisionConflict,
    DocumentUploadSession,
)
from documents.serializers import (
    DocumentPresignedFinalizeSerializer,
    DocumentPresignedUploadSerializer,
    DocumentUploadSerializer,
    DocumentVerifySerializer,
    validate_uploaded_file,
)
from documents.services.analysis import queue_document_analysis
from documents.services.audit import (
    DocumentAuditUnavailable,
    record_document_audit,
)
from documents.services.listing import (
    append_query_condition,
    bulk_customer_display_names,
    indexed_search_condition,
)
from documents.services.malware import MalwareScanUnavailable
from documents.services.notification import (
    get_customer_by_identifier,
    notify_reviewers_document_pending,
    queue_customer_document_notification,
    queue_reviewer_notifications,
)
from documents.services.presigned_upload import (
    PresignedUploadError,
    finalize_presigned_upload,
)
from documents.services.state_machine import (
    DocumentTransitionError,
    can_customer_delete,
)
from documents.services.storage_reconciliation import enqueue_storage_cleanup
from documents.storage import get_storage_backend

logger = logging.getLogger("documents")


def _audit_actor(request):
    user = request.user
    return {
        "user_id": getattr(user, "customer_id", None),
        "user_type": str(getattr(user, "role", "") or "unknown").lower(),
        "ip_address": get_client_ip(request),
    }


def _audit_denied(request, *, resource_id=None, reason_code="scope_denied"):
    record_document_audit(
        action="document_access_denied",
        description="Document access denied",
        resource_type="document",
        resource_id=resource_id,
        details={"reason_code": reason_code},
        **_audit_actor(request),
    )


def _require_document_reviewer(view, request):
    allowed, actor_or_response = view.require_officer_or_admin(request)
    if not allowed:
        return False, actor_or_response
    permission_check = getattr(actor_or_response, "has_permission", None)
    # A real privileged actor is always loaded by AccessControlMixin. The
    # fallback only supports isolated view tests that replace that loader.
    if permission_check is not None and not permission_check("review_documents"):
        return False, error_response(
            message="Document review permission required",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return True, actor_or_response


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


def parse_document_id(document_id):
    """Return a canonical ObjectId or ``None`` for malformed path input."""

    value = str(document_id or "").strip()
    if not ObjectId.is_valid(value):
        return None
    return ObjectId(value)


class DocumentUploadView(AccessControlMixin, APIView):
    """
    Upload documents for customers.

    POST /api/documents/upload/
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = (DocumentUploadRateThrottle,)

    def post(self, request):
        """Upload a document"""
        stored_file_path = None
        document_committed = False
        storage = None
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
            stored_file_path = file_info["file_path"]

            # Create document record
            replacement_lookup = getattr(Document, "find_reupload_candidate", None)
            replacement_for = (
                replacement_lookup(customer_id, document_type)
                if replacement_lookup
                else None
            )
            document = Document(
                customer_id=customer_id,
                document_type=document_type,
                original_filename=safe_original_filename,
                file_path=file_info["file_path"],
                file_size=file_info["size"],
                mime_type=file.content_type,
                description=data.get("description", ""),
                replaces_document_id=(replacement_for.id if replacement_for else None),
            )

            document.save()
            document_committed = True

            # Analysis is durable background work. Consent is checked again by
            # the worker immediately before it reads the document bytes.
            try:
                queue_document_analysis(document)
            except Exception:
                logger.exception(
                    "Failed to persist document analysis work for %s", document.id
                )

            if replacement_for:
                try:
                    replacement_for.mark_superseded(document.id)
                except DocumentRevisionConflict:
                    # The new document's forward link remains canonical and a
                    # concurrent replacement must not turn success into a 500.
                    logger.warning(
                        "Replacement backlink changed concurrently for document %s",
                        replacement_for.id,
                    )

            logger.info(f"Document uploaded: {document.id} by customer {customer_id}")

            # Audit log
            try:
                record_document_audit(
                    action="document_uploaded",
                    user_id=customer_id,
                    user_type="customer",
                    description=f"Document uploaded: {document_type}",
                    resource_type="document",
                    resource_id=document.id,
                    details={
                        "document_type": document_type,
                        "size": document.file_size,
                    },
                    ip_address=get_client_ip(request),
                )
            except Exception:
                logger.exception(
                    "Audit write failed after document upload %s", document.id
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
                        queue_reviewer_notifications(document)
                    else:
                        notify_reviewers_document_pending(document)
                except Exception as notify_error:
                    logger.warning(
                        f"Failed to notify reviewers for document {document.id}: {notify_error}"
                    )

            from documents.serializers import DocumentResponseSerializer

            response_data = DocumentResponseSerializer(document).data
            increment(DOCUMENT_OPERATIONS, operation="upload", outcome="completed")

            return success_response(
                data=response_data,
                message="Document uploaded successfully",
                status_code=status.HTTP_201_CREATED,
            )

        except MalwareScanUnavailable:
            increment(DOCUMENT_OPERATIONS, operation="upload", outcome="failed")
            return error_response(
                message="Document scanning is temporarily unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            increment(DOCUMENT_OPERATIONS, operation="upload", outcome="failed")
            if stored_file_path and not document_committed:
                try:
                    if not storage.delete(stored_file_path):
                        enqueue_storage_cleanup(
                            stored_file_path, reason="direct_upload_rollback"
                        )
                except Exception:
                    enqueue_storage_cleanup(
                        stored_file_path, reason="direct_upload_rollback"
                    )
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
                page_size = int(request.query_params.get("page_size", 20))
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
            if page_size < 1 or page_size > 200:
                return error_response(
                    message="Invalid page_size parameter",
                    errors={"page_size": "page_size must be between 1 and 200"},
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
            if len(search) > 100:
                return error_response(
                    message="Invalid search parameter",
                    errors={"search": "search must be at most 100 characters"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Determine which documents to show based on role
            query = {}
            if user_role in ["admin", "super_admin"]:
                if customer_id_filter:
                    query.update(Document._customer_query(customer_id_filter))
            elif user_role == "loan_officer":
                # ABAC scope: officers can only see documents belonging to customers
                # they are allowed to handle via application assignment scope.
                has_scope, scope_result = self.get_officer_scoped_customer_ids(
                    request,
                )
                if not has_scope:
                    return scope_result

                scoped_customer_ids = scope_result or set()
                if customer_id_filter:
                    if customer_id_filter not in scoped_customer_ids:
                        query["_id"] = {"$in": []}
                    else:
                        query.update(Document._customer_query(customer_id_filter))
                elif not scoped_customer_ids:
                    query["_id"] = {"$in": []}
                else:
                    scope_values = []
                    for customer_id in scoped_customer_ids:
                        scope_values.extend(self._id_variants(customer_id))
                    query["customer_id"] = {"$in": scope_values}
            else:
                # Customers can only see their own documents
                query.update(Document._customer_query(user.customer_id))

            if document_type:
                query["document_type"] = document_type
            if status_filter:
                query["status"] = status_filter
            query = Document.available_query(query)

            # Randomized field encryption makes filename search intentionally
            # unsupported. Only indexed exact document types and IDs are safe.
            if search:
                search_condition = indexed_search_condition(search)
                if search_condition is None:
                    return error_response(
                        message="Unsupported document search",
                        errors={
                            "search": (
                                "Use an exact document type, document ID, or "
                                "customer ID. Use the scoped profile directory "
                                "to find a customer by name."
                            )
                        },
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                append_query_condition(query, search_condition)

            paginated_documents, total = Document.paginate(
                query,
                page=page,
                page_size=page_size,
                sort=[("uploaded_at", -1), ("_id", -1)],
            )
            customer_names = bulk_customer_display_names(
                document.customer_id for document in paginated_documents
            )

            from documents.serializers import DocumentResponseSerializer

            docs_data = [
                DocumentResponseSerializer(
                    doc,
                    context={
                        "include_file_url": False,
                        "customer_names": customer_names,
                    },
                ).data
                for doc in paginated_documents
            ]

            if user_role in {"loan_officer", "admin", "super_admin"}:
                record_document_audit(
                    required=True,
                    action="document_list_viewed",
                    description="Document metadata list viewed",
                    resource_type="document",
                    details={
                        "filter_customer_id": customer_id_filter or None,
                        "filter_document_type": document_type or None,
                        "filter_status": status_filter or None,
                        "page": page,
                        "page_size": page_size,
                        "result_count": len(docs_data),
                        "search_applied": bool(search),
                    },
                    **_audit_actor(request),
                )

            return success_response(
                data={
                    "documents": docs_data,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (
                        (total + page_size - 1) // page_size if total > 0 else 0
                    ),
                },
                message="Documents retrieved successfully",
            )

        except DocumentAuditUnavailable:
            return error_response(
                message="Document audit service is temporarily unavailable",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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

            object_id = parse_document_id(document_id)
            if object_id is None:
                return error_response(
                    message="Invalid document_id format",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            document = Document.find_one({"_id": object_id})

            if not document or document.storage_state in {
                "delete_pending",
                "delete_failed",
            }:
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
                    _audit_denied(request, resource_id=document.id)
                    return owner_result
            elif user_role == "loan_officer":
                has_scope, scope_result = self.require_customer_scope_for_officer(
                    request,
                    document.customer_id,
                    conceal_existence=True,
                )
                if not has_scope:
                    _audit_denied(request, resource_id=document.id)
                    return scope_result

            if user_role in {"loan_officer", "admin", "super_admin"}:
                try:
                    record_document_audit(
                        required=True,
                        action="document_detail_viewed",
                        description="Document detail viewed",
                        resource_type="document",
                        resource_id=document.id,
                        details={"customer_id": str(document.customer_id)},
                        **_audit_actor(request),
                    )
                except DocumentAuditUnavailable:
                    return error_response(
                        message="Document audit service is temporarily unavailable",
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )

            from documents.serializers import DocumentResponseSerializer

            return success_response(
                data=DocumentResponseSerializer(document).data,
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

            object_id = parse_document_id(document_id)
            if object_id is None:
                return error_response(
                    message="Invalid document_id format",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            document = Document.find_one({"_id": object_id})

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
                _audit_denied(request, resource_id=document.id)
                return owner_result

            # Customers may delete only non-terminal review states.
            if not can_customer_delete(document):
                return error_response(
                    message="Cannot delete approved, verified, or expired documents",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            expected_revision = request.data.get("revision")
            if expected_revision is not None:
                try:
                    expected_revision = int(expected_revision)
                    if expected_revision < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return error_response(
                        message="Invalid revision",
                        errors={"revision": "revision must be a non-negative integer"},
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
            try:
                document.claim_deletion(expected_revision=expected_revision)
            except DocumentRevisionConflict as exc:
                return error_response(
                    message=str(exc), status_code=status.HTTP_409_CONFLICT
                )

            storage = get_storage_backend()
            try:
                storage_deleted = storage.delete(document.file_path)
            except Exception:
                storage_deleted = False
            if not storage_deleted:
                document.mark_deletion_failed("storage_delete_failed")
                record_document_audit(
                    action="document_delete_scheduled",
                    description="Document deletion scheduled for retry",
                    resource_type="document",
                    resource_id=document.id,
                    details={"status": "delete_failed"},
                    **_audit_actor(request),
                )
                return success_response(
                    data={"id": document.id, "storage_state": "delete_failed"},
                    message="Document deletion scheduled for retry",
                    status_code=status.HTTP_202_ACCEPTED,
                )

            if not document.complete_deletion():
                record_document_audit(
                    action="document_delete_scheduled",
                    description="Document deletion scheduled for completion",
                    resource_type="document",
                    resource_id=document.id,
                    details={"status": "delete_pending"},
                    **_audit_actor(request),
                )
                return success_response(
                    data={"id": document.id, "storage_state": "delete_pending"},
                    message="Document deletion scheduled for completion",
                    status_code=status.HTTP_202_ACCEPTED,
                )

            logger.info(f"Document deleted: {document_id} by customer {customer_id}")

            record_document_audit(
                action="document_deleted",
                description="Document deleted",
                resource_type="document",
                resource_id=document.id,
                details={"document_type": document.document_type},
                **_audit_actor(request),
            )

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
    Creates an owner-bound, short-lived upload session and restrictive S3 POST.
    """

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = (DocumentUploadRateThrottle,)

    def post(self, request):
        try:
            has_permission, result = self.require_customer(request)
            if not has_permission:
                return result

            if not getattr(settings, "DOCUMENT_PRESIGNED_UPLOAD_ENABLED", False):
                return error_response(
                    message="Presigned document uploads are not available",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            serializer = DocumentPresignedUploadSerializer(data=request.data)
            if not serializer.is_valid():
                return error_response(
                    message="Invalid presigned upload request",
                    errors=serializer.errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            data = serializer.validated_data
            storage = get_storage_backend()
            if not getattr(storage, "supports_presigned_uploads", False):
                return error_response(
                    message="Presigned uploads are not supported by the active storage backend",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            lifetime_seconds = getattr(
                settings, "DOCUMENT_PRESIGNED_UPLOAD_EXPIRY_SECONDS", 900
            )
            upload_session, finalize_token = DocumentUploadSession.issue(
                customer_id=request.user.customer_id,
                document_type=data["document_type"],
                original_filename=data["original_filename"],
                description=data.get("description", ""),
                expected_size=data["file_size"],
                expected_mime_type=data["mime_type"],
                expected_sha256=data["sha256"],
                lifetime_seconds=lifetime_seconds,
            )
            upload = storage.create_quarantined_presigned_upload(
                session_id=upload_session.id,
                original_filename=upload_session.original_filename,
                expected_size=upload_session.expected_size,
                expected_mime_type=upload_session.expected_mime_type,
                expected_sha256=upload_session.expected_sha256,
                expires_in=lifetime_seconds,
            )
            if not upload:
                upload_session.mark_failed("presign_failed")
                return error_response(
                    message="Failed to generate presigned upload data",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            upload_session.set_object_key(upload["object_key"])
            record_document_audit(
                action="document_upload_session_issued",
                description="Document upload session issued",
                resource_type="document_upload_session",
                resource_id=upload_session.id,
                details={
                    "document_type": upload_session.document_type,
                    "size": upload_session.expected_size,
                    "upload_session_id": upload_session.id,
                },
                **_audit_actor(request),
            )
            return success_response(
                data={
                    "upload_session_id": upload_session.id,
                    "finalize_token": finalize_token,
                    "expires_at": upload_session.expires_at.isoformat(),
                    "post": upload["post"],
                },
                message="Presigned upload session created",
                status_code=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.exception("Failed to generate presigned upload data: %s", e)
            return error_response(
                message="Failed to generate presigned upload data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentPresignedFinalizeView(AccessControlMixin, APIView):
    """Validate and finalize one quarantined direct upload exactly once."""

    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = (DocumentUploadRateThrottle,)

    def post(self, request, session_id):
        has_permission, result = self.require_customer(request)
        if not has_permission:
            return result
        if not getattr(settings, "DOCUMENT_PRESIGNED_UPLOAD_ENABLED", False):
            return error_response(
                message="Presigned document uploads are not available",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if not ObjectId.is_valid(str(session_id or "")):
            return error_response(
                message="Invalid upload_session_id format",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DocumentPresignedFinalizeSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Invalid upload finalization request",
                errors=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        storage = get_storage_backend()
        if not getattr(storage, "supports_presigned_uploads", False):
            return error_response(
                message="Presigned uploads are not supported by the active storage backend",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            document, replayed = finalize_presigned_upload(
                session_id=session_id,
                customer_id=request.user.customer_id,
                finalize_token=serializer.validated_data["finalize_token"],
                storage=storage,
                ip_address=get_client_ip(request),
            )
        except PresignedUploadError as exc:
            increment(DOCUMENT_OPERATIONS, operation="finalize", outcome="failed")
            record_document_audit(
                action="document_upload_finalized",
                description="Document upload finalization rejected",
                resource_type="document_upload_session",
                resource_id=session_id,
                details={"status": "failed", "reason_code": exc.failure_code},
                **_audit_actor(request),
            )
            return error_response(message=str(exc), status_code=exc.status_code)

        record_document_audit(
            action="document_upload_finalized",
            description="Document upload finalized",
            resource_type="document",
            resource_id=document.id,
            details={
                "status": "completed",
                "replayed": replayed,
                "upload_session_id": str(session_id),
            },
            **_audit_actor(request),
        )
        increment(
            DOCUMENT_OPERATIONS,
            operation="finalize",
            outcome="replayed" if replayed else "completed",
        )

        from documents.serializers import DocumentResponseSerializer

        return success_response(
            data={
                "document": DocumentResponseSerializer(document).data,
                "replayed": replayed,
            },
            message=(
                "Document upload already finalized"
                if replayed
                else "Document upload finalized successfully"
            ),
            status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
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

            has_permission, result = _require_document_reviewer(self, request)
            if not has_permission:
                return result

            object_id = parse_document_id(document_id)
            if object_id is None:
                return error_response(
                    message="Invalid document_id format",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            document = Document.find_one({"_id": object_id})

            if not document:
                return error_response(
                    message="Document not found", status_code=status.HTTP_404_NOT_FOUND
                )

            user_role = str(getattr(user, "role", "") or "").strip().lower()
            if user_role == "loan_officer":
                has_scope, scope_result = self.require_customer_scope_for_officer(
                    request,
                    document.customer_id,
                    conceal_existence=True,
                )
                if not has_scope:
                    _audit_denied(request, resource_id=document.id)
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

            try:
                document.review(
                    action=action,
                    reviewer_id=user.customer_id,
                    rejection_reason=data.get("rejection_reason", ""),
                    notes=data.get("notes"),
                    expected_revision=data.get("revision"),
                )
            except (DocumentTransitionError, DocumentRevisionConflict) as exc:
                return error_response(
                    message=str(exc),
                    status_code=status.HTTP_409_CONFLICT,
                )

            customer = get_customer_by_identifier(document.customer_id)

            # Notify customer for document status outcomes.
            if action in ["approve", "reject"]:
                try:
                    if customer and customer.email:
                        if action == "approve":
                            queue_customer_document_notification(
                                document,
                                customer,
                                delivery_type="approved",
                                notes=document.notes or "",
                            )
                        else:
                            queue_customer_document_notification(
                                document,
                                customer,
                                delivery_type="rejected",
                                issues=(
                                    [document.rejection_reason]
                                    if document.rejection_reason
                                    else ["Document was rejected during verification."]
                                ),
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
            record_document_audit(
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
                ip_address=get_client_ip(request),
            )

            return success_response(
                data={
                    "id": document.id,
                    "status": document.status,
                    "verified": document.verified,
                    "revision": document.revision,
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
        has_permission, result = _require_document_reviewer(self, request)
        if not has_permission:
            return result
        user = request.user

        object_id = parse_document_id(document_id)
        if object_id is None:
            return error_response(
                message="Invalid document_id format",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        doc = Document.find_one({"_id": object_id})
        if not doc:
            return error_response(
                message="Document not found", status_code=status.HTTP_404_NOT_FOUND
            )

        user_role = str(getattr(user, "role", "") or "").strip().lower()
        if user_role == "loan_officer":
            has_scope, scope_result = self.require_customer_scope_for_officer(
                request,
                doc.customer_id,
                conceal_existence=True,
            )
            if not has_scope:
                _audit_denied(request, resource_id=doc.id)
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

        expected_revision = request.data.get("revision")
        if expected_revision is not None:
            try:
                expected_revision = int(expected_revision)
                if expected_revision < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return error_response(
                    message="Invalid revision",
                    errors={"revision": "revision must be a non-negative integer"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        try:
            doc.request_reupload(
                officer_id=(
                    user.customer_id if hasattr(user, "customer_id") else str(user._id)
                ),
                reason=reason,
                expected_revision=expected_revision,
            )
        except (DocumentTransitionError, DocumentRevisionConflict) as exc:
            return error_response(
                message=str(exc),
                status_code=status.HTTP_409_CONFLICT,
            )

        logger.info(f"Re-upload requested for document {doc.id}")

        record_document_audit(
            action="document_reupload_requested",
            description="Document replacement requested",
            resource_type="document",
            resource_id=doc.id,
            details={
                "customer_id": str(doc.customer_id),
                "document_type": doc.document_type,
                "revision": doc.revision,
            },
            **_audit_actor(request),
        )

        # Send email notification to customer
        try:
            customer = get_customer_by_identifier(doc.customer_id)
            if customer and customer.email:
                queue_customer_document_notification(
                    doc,
                    customer,
                    delivery_type="reupload_requested",
                    issues=[reason],
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
                "revision": doc.revision,
            },
            message="Re-upload request sent",
        )
