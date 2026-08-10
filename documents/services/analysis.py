"""Durable, consent-aware orchestration for document image analysis."""

import logging

from django.conf import settings

from accounts.services.consent_service import ConsentService
from documents.models import Document

logger = logging.getLogger("documents")


def _analysis_settings():
    return {
        "max_attempts": max(1, int(getattr(settings, "DOCUMENT_AI_MAX_ATTEMPTS", 3))),
        "backoff_seconds": max(
            1, int(getattr(settings, "DOCUMENT_AI_RETRY_BACKOFF_SECONDS", 60))
        ),
        "lease_seconds": max(
            30, int(getattr(settings, "DOCUMENT_AI_LEASE_SECONDS", 300))
        ),
    }


def queue_document_analysis(document):
    """Persist work before publishing it so broker failures remain recoverable."""
    if not getattr(settings, "DOCUMENT_UPLOAD_AI_ANALYSIS", True):
        return False
    if not str(document.mime_type or "").lower().startswith("image/"):
        return False
    if not document.schedule_ai_analysis():
        return False

    try:
        from documents.tasks import analyze_document_task

        analyze_document_task.delay(document.id)
        return True
    except Exception:
        logger.exception(
            "Document analysis remains pending after enqueue failure for %s",
            document.id,
        )
        return False


def process_document_analysis(document_id):
    """Claim and execute one analysis attempt, returning a stable outcome code."""
    options = _analysis_settings()
    document = Document.claim_ai_analysis(
        document_id, lease_seconds=options["lease_seconds"]
    )
    if not document:
        return "not_due"

    try:
        consented = ConsentService.check_ai_consent(document.customer_id)
    except Exception:
        document.skip_ai_analysis("consent_unavailable")
        return "skipped_no_consent"
    if not consented:
        document.skip_ai_analysis("consent_not_granted")
        return "skipped_no_consent"

    try:
        from documents.services import analyze_document
        from documents.storage import get_storage_backend

        contents = get_storage_backend().get_file_bytes(document.file_path)
        analysis = analyze_document(contents, expected_type=document.document_type)
        if analysis.get("analysis_status") == "failed":
            raise RuntimeError("analysis_failed")
        if not {"is_valid", "quality_score"}.issubset(analysis):
            raise ValueError("analysis_contract_invalid")
        if not document.complete_ai_analysis(analysis):
            return "stale"
        return "completed"
    except Exception as exc:  # noqa: BLE001 - normalized to a safe operational code
        error_code = (
            "analysis_contract_invalid"
            if isinstance(exc, (TypeError, ValueError))
            else "analysis_execution_failed"
        )
        logger.exception("Document analysis attempt failed for %s", document.id)
        document.defer_ai_analysis(
            error_code,
            max_attempts=options["max_attempts"],
            backoff_seconds=options["backoff_seconds"],
        )
        return (
            "failed"
            if document.ai_analysis_attempts >= options["max_attempts"]
            else "retry_wait"
        )


def reconcile_due_document_analyses(limit=100):
    """Republish bounded due work; claims keep duplicate tasks idempotent."""
    from documents.tasks import analyze_document_task

    queued = 0
    for document_id in Document.find_due_ai_analyses(limit=limit):
        try:
            analyze_document_task.delay(document_id)
            queued += 1
        except Exception:
            logger.exception("Failed to republish document analysis %s", document_id)
    return queued
