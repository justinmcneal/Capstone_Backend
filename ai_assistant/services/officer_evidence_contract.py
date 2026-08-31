"""Canonical, officer-only normalization for domain evidence values."""

APPLICATION_STATUSES = frozenset(
    {
        "draft",
        "submitted",
        "under_review",
        "approved",
        "rejected",
        "disbursed",
        "completed",
        "written_off",
        "cancelled",
    }
)
RISK_SCORE_STATUSES = frozenset(
    {"not_calculated", "pending", "complete", "failed", "stale"}
)
DOCUMENT_STATUSES = frozenset(
    {"pending", "needs_review", "approved", "rejected", "expired"}
)
INSTALLMENT_STATUSES = frozenset(
    {"pending", "partial", "overdue", "partial_overdue", "paid"}
)
SCHEDULE_STATUSES = frozenset(
    {"active", "paid_off", "restructured", "written_off"}
)

_LEGACY_RISK_SCORE_STATUS_ALIASES = {"calculated": "complete"}


def normalize_status(value, allowed, *, fallback="unknown"):
    normalized = value.strip().lower() if isinstance(value, str) else ""
    return normalized if normalized in allowed else fallback


def normalize_risk_status(value):
    normalized = value.strip().lower() if isinstance(value, str) else ""
    normalized = _LEGACY_RISK_SCORE_STATUS_ALIASES.get(normalized, normalized)
    return normalized if normalized in RISK_SCORE_STATUSES else "unknown"
