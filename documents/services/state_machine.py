"""Canonical lifecycle policy for customer documents.

Stage 1 centralized the contract. Stage 3 made these transitions atomic at the
MongoDB write boundary with revision guards.
"""

from datetime import datetime, timedelta, timezone

from django.conf import settings


class DocumentTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not allowed."""


DOCUMENT_ALLOWED_TRANSITIONS = {
    "pending": frozenset({"needs_review", "approved", "rejected"}),
    "needs_review": frozenset({"needs_review", "approved", "rejected"}),
    "approved": frozenset(),
    "rejected": frozenset({"needs_review"}),
    "expired": frozenset(),
}

DOCUMENT_DELETABLE_STATUSES = frozenset({"pending", "needs_review", "rejected"})


def require_transition(current_status, target_status):
    """Validate one transition against the canonical state policy."""

    allowed_targets = DOCUMENT_ALLOWED_TRANSITIONS.get(current_status)
    if allowed_targets is None:
        raise DocumentTransitionError(
            f"Document has unsupported status: {current_status or 'unknown'}"
        )
    if target_status not in allowed_targets:
        raise DocumentTransitionError(
            f"Document cannot transition from {current_status} to {target_status}"
        )


def apply_review_decision(
    document,
    *,
    action,
    reviewer_id,
    rejection_reason="",
    notes=None,
    now=None,
):
    """Apply a validated review decision and normalize compatibility fields."""

    target_status = "approved" if action == "approve" else "rejected"
    require_transition(document.status, target_status)
    decision_time = now or datetime.now(timezone.utc)

    document.status = target_status
    document.reupload_requested = False
    document.reupload_reason = ""
    document.reupload_requested_by = None
    document.reupload_requested_at = None

    if action == "approve":
        document.verified = True
        document.verified_by = reviewer_id
        document.verified_at = decision_time
        document.rejection_reason = ""
    else:
        document.verified = False
        document.verified_by = None
        document.verified_at = None
        document.rejection_reason = rejection_reason
        document.retention_expires_at = decision_time + timedelta(
            days=int(getattr(settings, "DOCUMENT_REJECTED_RETENTION_DAYS", 90))
        )
        document.retention_policy_version = getattr(
            settings, "DOCUMENT_RETENTION_POLICY_VERSION", "unversioned"
        )

    if notes is not None:
        document.notes = notes
    return document


def apply_reupload_request(document, *, reviewer_id, reason, now=None):
    """Move an eligible document into the explicit re-upload review state."""

    require_transition(document.status, "needs_review")
    document.status = "needs_review"
    document.verified = False
    document.verified_by = None
    document.verified_at = None
    document.rejection_reason = ""
    document.reupload_requested = True
    document.reupload_reason = reason
    document.reupload_requested_by = reviewer_id
    document.reupload_requested_at = now or datetime.now(timezone.utc)
    return document


def can_customer_delete(document):
    """Return whether the current lifecycle state permits customer deletion."""

    return (
        document.status in DOCUMENT_DELETABLE_STATUSES
        and not bool(document.verified)
    )
