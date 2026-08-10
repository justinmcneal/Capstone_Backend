"""Validation and one-time finalization for quarantined direct uploads."""

import hashlib
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.services.consent_service import ConsentService
from analytics.models import AuditLog  # noqa: F401 - test integration compatibility
from documents.models import Document, DocumentRevisionConflict, DocumentUploadSession
from documents.serializers import validate_uploaded_file
from documents.services.audit import record_document_audit
from documents.services.notification import notify_reviewers_document_pending
from documents.services.storage_reconciliation import enqueue_storage_cleanup
from documents.tasks import notify_reviewers_document_pending_task

logger = logging.getLogger("documents")


class PresignedUploadError(Exception):
    """A safe client-facing finalization failure."""

    def __init__(self, message, *, status_code=400, failure_code="invalid_upload"):
        super().__init__(message)
        self.status_code = status_code
        self.failure_code = failure_code


def _find_finalized_document(session):
    return Document.find_one({"upload_session_id": session.id})


def _cleanup_failed_object(session, storage, failure_code):
    session.mark_failed(failure_code)
    if not session.object_key:
        return
    try:
        if storage.delete(session.object_key):
            session.mark_expired_and_cleaned()
    except Exception:
        logger.exception(
            "Failed to clean quarantined document upload session %s", session.id
        )


def _validate_object(session, storage):
    try:
        metadata = storage.get_object_metadata(session.object_key)
    except Exception as exc:
        raise PresignedUploadError(
            "Uploaded object was not found",
            status_code=409,
            failure_code="object_missing",
        ) from exc

    object_metadata = metadata.get("metadata") or {}
    if metadata.get("size") != session.expected_size:
        raise PresignedUploadError(
            "Uploaded object size does not match the upload session",
            failure_code="size_mismatch",
        )
    if metadata.get("mime_type") != session.expected_mime_type:
        raise PresignedUploadError(
            "Uploaded object type does not match the upload session",
            failure_code="mime_mismatch",
        )
    if object_metadata.get("upload-session") != session.id:
        raise PresignedUploadError(
            "Uploaded object is not bound to this upload session",
            failure_code="session_metadata_mismatch",
        )
    if object_metadata.get("sha256", "").lower() != session.expected_sha256:
        raise PresignedUploadError(
            "Uploaded object hash metadata does not match the upload session",
            failure_code="hash_metadata_mismatch",
        )

    try:
        contents = storage.get_file_bytes(session.object_key)
    except Exception as exc:
        raise PresignedUploadError(
            "Uploaded object could not be read",
            status_code=409,
            failure_code="object_read_failed",
        ) from exc

    if len(contents) != session.expected_size:
        raise PresignedUploadError(
            "Uploaded content size does not match the upload session",
            failure_code="content_size_mismatch",
        )
    actual_sha256 = hashlib.sha256(contents).hexdigest()
    if actual_sha256 != session.expected_sha256:
        raise PresignedUploadError(
            "Uploaded content hash does not match the upload session",
            failure_code="content_hash_mismatch",
        )

    uploaded_file = SimpleUploadedFile(
        session.original_filename,
        contents,
        content_type=session.expected_mime_type,
    )
    is_valid, validation_error = validate_uploaded_file(uploaded_file)
    if not is_valid:
        raise PresignedUploadError(
            validation_error or "Uploaded content failed validation",
            failure_code="content_validation_failed",
        )
    return contents


def _analyze_image(session, contents):
    if not getattr(settings, "DOCUMENT_UPLOAD_AI_ANALYSIS", True):
        return None
    if not session.expected_mime_type.startswith("image/"):
        return None
    try:
        if not ConsentService.check_ai_consent(session.customer_id):
            return None
    except Exception:  # noqa: BLE001 - consent-store failure must fail closed
        return None

    try:
        from documents.services import analyze_document

        return analyze_document(contents, expected_type=session.document_type)
    except Exception:
        logger.exception("Document AI analysis failed during presigned finalization")
        return {
            "is_valid": False,
            "quality_score": 0,
            "quality_issues": ["Document analysis was unavailable"],
            "analysis_mode": "failed",
        }


def _apply_analysis(document, analysis):
    if not analysis:
        return
    document.confidence_score = analysis.get("quality_score", 0)
    document.ai_analysis = analysis
    document.ai_analyzed_at = datetime.now(timezone.utc)
    quality_score = analysis.get("quality_score")
    try:
        quality_score = float(quality_score) if quality_score is not None else 1.0
    except (TypeError, ValueError):
        quality_score = 0.0
    if not analysis.get("is_valid", True) or quality_score < 0.5:
        document.status = "needs_review"


def _notify_reviewers(document):
    if not getattr(settings, "DOCUMENT_UPLOAD_NOTIFY_REVIEWERS", True):
        return
    if document.status not in {"pending", "needs_review"}:
        return
    try:
        if getattr(settings, "DOCUMENT_UPLOAD_NOTIFY_ASYNC", True):
            notify_reviewers_document_pending_task.delay(document.id)
        else:
            notify_reviewers_document_pending(document)
    except Exception:
        logger.exception(
            "Failed to enqueue reviewer notification for document %s", document.id
        )


def finalize_presigned_upload(
    *, session_id, customer_id, finalize_token, storage, ip_address=""
):
    """Validate, promote, persist, and return a document exactly once."""

    session = DocumentUploadSession.find_by_id(session_id)
    if (
        not session
        or str(session.customer_id) != str(customer_id)
        or not session.token_matches(finalize_token)
    ):
        raise PresignedUploadError(
            "Upload session not found", status_code=404, failure_code="not_found"
        )

    existing = _find_finalized_document(session)
    if existing:
        if session.status != "completed":
            session.mark_completed(existing.id)
        return existing, True

    now = datetime.now(timezone.utc)
    expires_at = session.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at <= now:
        _cleanup_failed_object(session, storage, "session_expired")
        raise PresignedUploadError(
            "Upload session has expired",
            status_code=410,
            failure_code="session_expired",
        )
    if session.status != "issued":
        raise PresignedUploadError(
            "Upload session is already being finalized",
            status_code=409,
            failure_code="already_finalizing",
        )

    claimed = DocumentUploadSession.claim_for_finalization(
        session_id=session.id,
        customer_id=customer_id,
        token=finalize_token,
    )
    if not claimed:
        refreshed = DocumentUploadSession.find_by_id(session.id)
        existing = _find_finalized_document(refreshed) if refreshed else None
        if existing:
            return existing, True
        raise PresignedUploadError(
            "Upload session is already being finalized",
            status_code=409,
            failure_code="claim_conflict",
        )
    session = claimed

    promoted = None
    document_committed = False
    try:
        contents = _validate_object(session, storage)
        analysis = _analyze_image(session, contents)
        promoted = storage.promote_quarantined_upload(
            session.object_key,
            session.customer_id,
            session.document_type,
            session.original_filename,
        )
        replacement_for = Document.find_reupload_candidate(
            session.customer_id, session.document_type
        )
        document = Document(
            customer_id=session.customer_id,
            document_type=session.document_type,
            original_filename=session.original_filename,
            file_path=promoted["file_path"],
            file_size=session.expected_size,
            mime_type=session.expected_mime_type,
            sha256=session.expected_sha256,
            upload_session_id=session.id,
            description=session.description,
            replaces_document_id=(replacement_for.id if replacement_for else None),
        )
        _apply_analysis(document, analysis)
        document.save()
        document_committed = True
        if replacement_for:
            try:
                replacement_for.mark_superseded(document.id)
            except DocumentRevisionConflict:
                logger.warning(
                    "Replacement backlink changed concurrently for document %s",
                    replacement_for.id,
                )
        try:
            session.mark_completed(document.id)
        except Exception:
            # The document and durable object already agree. A replay finds the
            # document by upload_session_id and repairs the session marker.
            logger.exception(
                "Failed to mark completed upload session %s", session.id
            )
    except PresignedUploadError as exc:
        _cleanup_failed_object(session, storage, exc.failure_code)
        raise
    except Exception as exc:
        if promoted and promoted.get("file_path") and not document_committed:
            try:
                if not storage.delete(promoted["file_path"]):
                    enqueue_storage_cleanup(
                        promoted["file_path"], reason="finalize_rollback"
                    )
            except Exception:
                logger.exception("Failed to roll back promoted document object")
                enqueue_storage_cleanup(
                    promoted["file_path"], reason="finalize_rollback"
                )
        if not document_committed:
            _cleanup_failed_object(session, storage, "finalization_failed")
        raise PresignedUploadError(
            "Document finalization failed",
            status_code=500,
            failure_code="finalization_failed",
        ) from exc

    try:
        record_document_audit(
            action="document_uploaded",
            user_id=str(customer_id),
            user_type="customer",
            description=f"Document uploaded: {document.document_type}",
            resource_type="document",
            resource_id=document.id,
            details={
                "document_type": document.document_type,
                "size": document.file_size,
                "upload_method": "presigned",
                "upload_session_id": session.id,
            },
            ip_address=ip_address,
        )
    except Exception:
        logger.exception("Audit write failed after presigned document finalization")
    _notify_reviewers(document)
    return document, False


def cleanup_expired_upload_sessions(*, storage, limit=100):
    """Delete expired quarantine objects before expiring their session records."""

    cleaned = 0
    failed = 0
    for session in DocumentUploadSession.find_cleanup_candidates(limit=limit):
        try:
            deleted = not session.object_key or storage.delete(session.object_key)
            if deleted and session.mark_expired_and_cleaned():
                cleaned += 1
            elif not deleted:
                failed += 1
        except Exception:
            failed += 1
            logger.exception("Failed to clean upload session %s", session.id)
    return {"cleaned": cleaned, "failed": failed}
