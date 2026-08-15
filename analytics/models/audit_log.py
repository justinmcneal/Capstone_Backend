"""Versioned, encrypted, idempotent audit events."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128
from django.conf import settings
from pymongo.errors import DuplicateKeyError

from config.field_encryption import decrypt_fields, encrypt_fields


def get_db():
    return settings.MONGODB


# Versioned action contract. New producers must register their action and stable
# category here before writing it. Legacy records are still readable, but new
# unknown actions fail closed instead of silently drifting out of filters.
AUDIT_EVENT_SCHEMA_VERSION = 2
AUDIT_SCOPE_POLICY_VERSIONS = frozenset({"event-time-assignment-v1"})
AUDIT_ACTION_REGISTRY = {
    # Authentication
    "user_login": "login",
    "user_login_failed": "login",
    "user_logout": "login",
    "user_registered": "create",
    "two_factor_setup_started": "update",
    "two_factor_enabled": "update",
    "two_factor_disabled": "update",
    "two_factor_backup_codes_regenerated": "update",
    "two_factor_backup_code_used": "update",
    "password_changed": "update",
    "password_reset_requested": "update",
    "password_reset_completed": "update",
    "sessions_terminated": "update",
    "email_change_requested": "update",
    "email_changed": "update",
    "account_suspended": "update",
    "account_deactivated": "update",
    "account_deletion_requested": "update",
    "account_deletion_cancelled": "update",
    "account_deleted": "delete",
    "two_factor_recovery_requested": "update",
    "two_factor_recovery_approved": "update",
    "two_factor_recovery_rejected": "update",
    "admin_customer_unlock": "update",
    "new_device_login": "update",
    "admin_created": "create",
    "admin_updated": "update",
    "admin_deactivated": "delete",
    "admin_permissions_changed": "update",
    "loan_officer_updated": "update",
    "loan_officer_deactivated": "delete",
    # Analytics privileged reads
    "analytics_privileged_read": "read",
    # Profile
    "profile_created": "create",
    "profile_updated": "update",
    "notification_preferences_updated": "update",
    "profile_exported": "read",
    "profile_history_viewed": "read",
    "profile_directory_viewed": "read",
    "profile_sensitive_read": "read",
    "profile_access_denied": "read",
    "risk_score_calculated": "update",
    "risk_score_failed": "update",
    "risk_score_stale": "update",
    "risk_review_requested": "create",
    "risk_review_queue_viewed": "read",
    "risk_review_status_changed": "update",
    # Documents
    "document_uploaded": "create",
    "document_verified": "update",
    "document_rejected": "update",
    "document_deleted": "delete",
    "document_delete_scheduled": "delete",
    "document_reupload_requested": "update",
    "document_list_viewed": "read",
    "document_detail_viewed": "read",
    "document_access_denied": "read",
    "document_upload_session_issued": "create",
    "document_upload_finalized": "create",
    "document_legal_hold_set": "update",
    "document_legal_hold_release": "update",
    # Loans
    "loan_submitted": "create",
    "loan_draft_updated_and_submitted": "update",
    "loan_assigned": "update",
    "loan_reassigned": "update",
    "loan_resubmitted": "update",
    "loan_approved": "update",
    "loan_rejected": "update",
    "loan_disbursement_pending": "update",
    "loan_disbursement_failed": "update",
    "loan_disbursed": "update",
    "loan_paid_off": "update",
    "loan_internal_note_added": "update",
    "loan_missing_documents_requested": "update",
    "loan_legal_hold_set": "update",
    "loan_legal_hold_release": "update",
    "disbursement_method_set": "update",
    "wallet_disbursement_reconcile": "update",
    "wallet_disbursement_retry": "update",
    "wallet_disbursement_cancel": "update",
    # Payments
    "payment_recorded": "create",
    "customer_payment_submitted": "create",
    "customer_payment_recorded": "create",
    "wallet_payment_verified": "update",
    "repayment_schedule_exported": "read",
    # Penalties / Consent
    "penalty_applied": "update",
    "penalty_waived": "update",
    "consent_recorded": "create",
    "consent_granted": "update",
    "consent_reconfirmed": "update",
    "consent_revoked": "update",
    "consent_updated": "update",
    # Admin
    "admin_action": "update",
}

AUDIT_ACTIONS = tuple(AUDIT_ACTION_REGISTRY)
AUDIT_USER_TYPES = frozenset(
    {"customer", "loan_officer", "admin", "super_admin", "system"}
)

# Producer-controlled metadata is limited to known operational fields. Nested
# objects may use domain keys, but credential-shaped keys are rejected at every
# depth and the whole object is encrypted before persistence.
AUDIT_ALLOWED_DETAIL_KEYS = frozenset(
    {
        "action",
        "after",
        "amount",
        "approved",
        "approved_amount",
        "assigned_officer",
        "attempted_revision",
        "automated",
        "before",
        "category",
        "changed_by",
        "changed_fields",
        "changed_keys",
        "completion_percentage",
        "current_revision",
        "customer_id",
        "delivery",
        "device_info",
        "disbursement_method",
        "disbursement_new_status",
        "disbursement_old_status",
        "document_type",
        "employee_id",
        "error_code",
        "error_type",
        "eth_amount",
        "eth_rate",
        "filter_customer_id",
        "filter_document_type",
        "filter_status",
        "filters",
        "format",
        "installment",
        "installment_number",
        "loan_id",
        "method",
        "missing_documents",
        "new_email",
        "new_state",
        "new_status",
        "note_preview",
        "officer_email",
        "old_email",
        "old_status",
        "page",
        "page_size",
        "paid_off_at",
        "payment_status",
        "pending_email",
        "performed_by_admin",
        "php_amount",
        "policy_version",
        "previous_state",
        "previous_officer",
        "product",
        "profile_completed",
        "profile_completion_policy_version",
        "profile_missing_fields",
        "profile_revision",
        "profile_type",
        "reason",
        "reason_code",
        "reason_codes",
        "replayed",
        "requested_email",
        "result_count",
        "retention_period_elapsed",
        "review_revision",
        "revision",
        "risk_input_revision",
        "risk_score_status",
        "row_count",
        "scheduled_for",
        "schema_version",
        "scope",
        "scope_enforced",
        "search_applied",
        "server_copy_created",
        "session_id",
        "sessions_revoked",
        "size",
        "status",
        "status_filter",
        "source",
        "transition_id",
        "target_email",
        "term",
        "tx_hash",
        "tx_status",
        "upload_method",
        "upload_session_id",
        "verified",
    }
)
AUDIT_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "backup_code",
    "cookie",
    "credential",
    "file_path",
    "mnemonic",
    "object_key",
    "otp",
    "password",
    "private_key",
    "secret",
    "seed_phrase",
    "token",
)

_ACCOUNT_STATE_KEYS = frozenset(
    {"previous_state", "new_state", "reason", "sessions_revoked"}
)
_ADMIN_CHANGE_KEYS = frozenset(
    {"target_email", "before", "after", "changed_fields"}
)
_PROFILE_MUTATION_KEYS = frozenset(
    {
        "changed_fields",
        "completion_percentage",
        "profile_completed",
        "profile_completion_policy_version",
        "profile_missing_fields",
        "profile_revision",
        "profile_type",
        "risk_input_revision",
        "risk_score_status",
    }
)
_LOAN_TRANSITION_KEYS = frozenset(
    {
        "amount",
        "assigned_officer",
        "customer_id",
        "disbursement_new_status",
        "disbursement_old_status",
        "error_type",
        "loan_id",
        "method",
        "new_status",
        "old_status",
        "paid_off_at",
        "previous_officer",
        "source",
        "transition_id",
    }
)

# Every registered action has an explicit top-level metadata contract. Empty
# means that the producer must not attach details for that event.
AUDIT_ACTION_DETAIL_KEYS = {
    action: frozenset() for action in AUDIT_ACTION_REGISTRY
}
AUDIT_ACTION_DETAIL_KEYS.update(
    {
        "user_login_failed": frozenset({"email", "identifier", "reason"}),
        "password_changed": frozenset({"sessions_revoked"}),
        "password_reset_requested": frozenset({"delivery"}),
        "password_reset_completed": frozenset({"sessions_revoked"}),
        "sessions_terminated": frozenset({"scope", "session_id"}),
        "email_change_requested": frozenset({"pending_email"}),
        "email_changed": frozenset(
            {"new_email", "old_email", "requested_email", "sessions_revoked"}
        ),
        "account_suspended": _ACCOUNT_STATE_KEYS,
        "account_deactivated": _ACCOUNT_STATE_KEYS,
        "account_deletion_requested": frozenset({"scheduled_for"}),
        "account_deletion_cancelled": frozenset({"sessions_revoked"}),
        "account_deleted": frozenset(
            {"automated", "performed_by_admin", "reason", "retention_period_elapsed"}
        ),
        "two_factor_recovery_requested": frozenset({"verified"}),
        "two_factor_recovery_approved": frozenset(
            {"approved", "reason", "sessions_revoked"}
        ),
        "two_factor_recovery_rejected": frozenset(
            {"approved", "reason", "sessions_revoked"}
        ),
        "admin_customer_unlock": _ACCOUNT_STATE_KEYS
        | frozenset({"customer_email"}),
        "new_device_login": frozenset({"device_info", "session_id"}),
        "admin_created": _ADMIN_CHANGE_KEYS,
        "admin_updated": _ADMIN_CHANGE_KEYS,
        "admin_deactivated": _ADMIN_CHANGE_KEYS,
        "admin_permissions_changed": _ADMIN_CHANGE_KEYS | frozenset({"changed_by"}),
        "loan_officer_updated": _ADMIN_CHANGE_KEYS,
        "loan_officer_deactivated": _ADMIN_CHANGE_KEYS,
        "admin_action": frozenset({"employee_id", "officer_email"}),
        "profile_created": _PROFILE_MUTATION_KEYS,
        "profile_updated": _PROFILE_MUTATION_KEYS,
        "notification_preferences_updated": frozenset({"changed_keys"}),
        "profile_exported": frozenset({"schema_version", "server_copy_created"}),
        "profile_history_viewed": frozenset({"page", "page_size"}),
        "profile_directory_viewed": frozenset(
            {"page", "page_size", "result_count", "search_applied"}
        ),
        "profile_sensitive_read": frozenset({"scope_enforced"}),
        "profile_access_denied": frozenset({"reason"}),
        "risk_score_calculated": frozenset(
            {"category", "policy_version", "reason_codes", "revision"}
        ),
        "risk_score_failed": frozenset({"error_code", "policy_version", "revision"}),
        "risk_score_stale": frozenset(
            {"attempted_revision", "current_revision", "policy_version"}
        ),
        "risk_review_requested": frozenset(
            {"policy_version", "reason", "revision", "status"}
        ),
        "risk_review_queue_viewed": frozenset(
            {"page", "page_size", "result_count", "status_filter"}
        ),
        "risk_review_status_changed": frozenset(
            {"customer_id", "review_revision", "revision", "status"}
        ),
        "document_uploaded": frozenset(
            {"document_type", "size", "upload_method", "upload_session_id"}
        ),
        "document_verified": frozenset(
            {"action", "customer_id", "document_type", "revision", "status"}
        ),
        "document_rejected": frozenset(
            {"action", "customer_id", "document_type", "reason", "revision", "status"}
        ),
        "document_deleted": frozenset({"document_type"}),
        "document_delete_scheduled": frozenset({"status"}),
        "document_reupload_requested": frozenset(
            {"customer_id", "document_type", "revision"}
        ),
        "document_list_viewed": frozenset(
            {
                "filter_customer_id",
                "filter_document_type",
                "filter_status",
                "page",
                "page_size",
                "result_count",
                "search_applied",
            }
        ),
        "document_detail_viewed": frozenset({"customer_id"}),
        "document_access_denied": frozenset({"reason_code"}),
        "document_upload_session_issued": frozenset(
            {"document_type", "size", "upload_session_id"}
        ),
        "document_upload_finalized": frozenset(
            {
                "document_type",
                "reason_code",
                "replayed",
                "size",
                "status",
                "upload_method",
                "upload_session_id",
            }
        ),
        "document_legal_hold_set": frozenset({"reason", "revision"}),
        "document_legal_hold_release": frozenset({"revision"}),
        "loan_submitted": frozenset(
            {"amount", "product", "term", "transition_id"}
        ),
        "loan_draft_updated_and_submitted": frozenset(
            {"amount", "product", "term", "transition_id"}
        ),
        "loan_assigned": _LOAN_TRANSITION_KEYS,
        "loan_reassigned": _LOAN_TRANSITION_KEYS,
        "loan_resubmitted": _LOAN_TRANSITION_KEYS,
        "loan_approved": _LOAN_TRANSITION_KEYS | frozenset({"approved_amount"}),
        "loan_rejected": _LOAN_TRANSITION_KEYS | frozenset({"reason"}),
        "loan_disbursement_pending": _LOAN_TRANSITION_KEYS,
        "loan_disbursement_failed": _LOAN_TRANSITION_KEYS,
        "loan_disbursed": _LOAN_TRANSITION_KEYS,
        "loan_paid_off": _LOAN_TRANSITION_KEYS,
        "loan_internal_note_added": frozenset(
            {"customer_id", "note_preview", "transition_id"}
        ),
        "loan_missing_documents_requested": frozenset(
            {"customer_id", "missing_documents", "reason", "transition_id"}
        ),
        "loan_legal_hold_set": frozenset({"legal_hold_action"}),
        "loan_legal_hold_release": frozenset({"legal_hold_action"}),
        "disbursement_method_set": frozenset({"disbursement_method"}),
        "wallet_disbursement_reconcile": frozenset({"tx_hash", "tx_status"}),
        "wallet_disbursement_retry": frozenset({"tx_hash", "tx_status"}),
        "wallet_disbursement_cancel": frozenset({"tx_hash", "tx_status"}),
        "payment_recorded": frozenset({"amount", "installment", "loan_id", "method"}),
        "customer_payment_submitted": frozenset(
            {"amount", "installment", "loan_id", "method", "payment_status"}
        ),
        "customer_payment_recorded": frozenset(
            {"amount", "installment", "loan_id", "method", "payment_status"}
        ),
        "wallet_payment_verified": frozenset(
            {
                "eth_amount",
                "eth_rate",
                "installment_number",
                "loan_id",
                "php_amount",
                "tx_hash",
            }
        ),
        "repayment_schedule_exported": frozenset({"filters", "format", "row_count"}),
        "penalty_applied": frozenset(
            {"amount", "installment_number", "loan_id", "reason", "policy_version"}
        ),
        "penalty_waived": frozenset(
            {"amount", "installment_number", "loan_id", "reason", "policy_version"}
        ),
        "analytics_privileged_read": frozenset(),
    }
)
AUDIT_ALLOWED_DETAIL_KEYS = frozenset().union(*AUDIT_ACTION_DETAIL_KEYS.values())

# High-level groups are generated from the same registry used to validate writes.
ACTION_GROUPS = {
    category: tuple(
        action
        for action, registered_category in AUDIT_ACTION_REGISTRY.items()
        if registered_category == category
    )
    for category in ("login", "read", "create", "update", "delete")
}


class AuditLog:
    """
    Audit log for tracking system actions.
    """

    collection_name = "audit_logs"
    encrypted_fields = (
        "user_email",
        "description",
        "details",
        "ip_address",
        "legal_hold_reason",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")

        # Who performed the action
        self.user_id = kwargs.get("user_id")
        self.user_type = kwargs.get(
            "user_type", "customer"
        )  # customer/loan_officer/admin
        self.user_email = kwargs.get("user_email", "")

        # What action was performed
        self.action = kwargs.get("action")  # From AUDIT_ACTIONS
        self.event_schema_version = kwargs.get(
            "event_schema_version", AUDIT_EVENT_SCHEMA_VERSION
        )
        self.action_group = kwargs.get("action_group") or AUDIT_ACTION_REGISTRY.get(
            self.action
        )
        self.description = kwargs.get("description", "")

        # Related resource
        self.resource_type = kwargs.get("resource_type")  # loan, document, user
        self.resource_id = kwargs.get("resource_id")

        # Additional details
        self.details = kwargs.get("details", {})
        self.ip_address = kwargs.get("ip_address", "")

        self.event_id = kwargs.get("event_id") or f"evt_{uuid.uuid4().hex}"
        self.payload_digest = kwargs.get("payload_digest", "")
        self.subject_index = kwargs.get("subject_index")
        self.scope_officer_index = kwargs.get("scope_officer_index") or self.blind_index(
            kwargs.get("scope_officer_id")
        )
        self.scope_policy_version = kwargs.get("scope_policy_version")
        self.integrity_algorithm = kwargs.get("integrity_algorithm", "hmac-sha256-v1")
        self.integrity_hash = kwargs.get("integrity_hash", "")

        self.retention_policy_version = kwargs.get("retention_policy_version") or getattr(
            settings, "ANALYTICS_AUDIT_RETENTION_POLICY_VERSION", "2026-08-12-v1"
        )
        self.retention_expires_at = kwargs.get("retention_expires_at")
        self.legal_hold = bool(kwargs.get("legal_hold", False))
        self.legal_hold_reason = kwargs.get("legal_hold_reason", "")
        self.legal_hold_set_at = kwargs.get("legal_hold_set_at")
        self.legal_hold_set_by = kwargs.get("legal_hold_set_by")
        self.pseudonymized_at = kwargs.get("pseudonymized_at")

        # Timestamp
        self.timestamp = kwargs.get("timestamp", datetime.now(timezone.utc))

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "user_id": self.user_id,
            "user_type": self.user_type,
            "user_email": self.user_email,
            "action": self.action,
            "event_schema_version": self.event_schema_version,
            "action_group": self.action_group,
            "description": self.description,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "event_id": self.event_id,
            "payload_digest": self.payload_digest,
            "subject_index": self.subject_index,
            "scope_officer_index": self.scope_officer_index,
            "scope_policy_version": self.scope_policy_version,
            "integrity_algorithm": self.integrity_algorithm,
            "integrity_hash": self.integrity_hash,
            "retention_policy_version": self.retention_policy_version,
            "retention_expires_at": self.retention_expires_at,
            "legal_hold": self.legal_hold,
            "legal_hold_reason": self.legal_hold_reason,
            "legal_hold_set_at": self.legal_hold_set_at,
            "legal_hold_set_by": self.legal_hold_set_by,
            "pseudonymized_at": self.pseudonymized_at,
            "timestamp": self.timestamp,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    @staticmethod
    def _integrity_keys():
        configured = [
            str(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or "").strip(),
            *[
                str(key or "").strip()
                for key in getattr(settings, "FIELD_ENCRYPTION_PREVIOUS_KEYS", ())
            ],
        ]
        keys = []
        for value in configured:
            encoded = value.encode("utf-8") if value else None
            if encoded and encoded not in keys:
                keys.append(encoded)
        return keys or [str(settings.SECRET_KEY).encode("utf-8")]

    @classmethod
    def _integrity_key(cls):
        return cls._integrity_keys()[0]

    @staticmethod
    def _canonical_json(data):
        def default(value):
            if isinstance(value, datetime):
                normalized = value
                if normalized.tzinfo is None:
                    normalized = normalized.replace(tzinfo=timezone.utc)
                else:
                    normalized = normalized.astimezone(timezone.utc)
                normalized = normalized.replace(
                    microsecond=(normalized.microsecond // 1000) * 1000
                )
                return normalized.isoformat()
            if isinstance(value, (ObjectId, Decimal, Decimal128)):
                return str(value)
            return repr(value)

        return json.dumps(
            data, default=default, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @classmethod
    def blind_index(cls, value):
        text = str(value or "").strip()
        if not text:
            return None
        return hmac.new(
            cls._integrity_key(), text.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @classmethod
    def blind_index_candidates(cls, value):
        """Return current and previous-key indexes during controlled rotation."""
        text = str(value or "").strip()
        if not text:
            return []
        return [
            hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()
            for key in cls._integrity_keys()
        ]

    @classmethod
    def _hash_document(cls, data, *, key=None):
        signed = {
            key: value
            for key, value in data.items()
            if key not in {"_id", "integrity_hash"}
        }
        return hmac.new(
            key or cls._integrity_key(), cls._canonical_json(signed), hashlib.sha256
        ).hexdigest()

    @classmethod
    def verify_integrity_document(cls, raw_document):
        expected = str((raw_document or {}).get("integrity_hash") or "")
        if not expected:
            return False
        return any(
            hmac.compare_digest(expected, cls._hash_document(raw_document, key=key))
            for key in cls._integrity_keys()
        )

    @classmethod
    def _validate_nested_value(cls, value, *, depth=0):
        max_depth = int(getattr(settings, "ANALYTICS_AUDIT_MAX_DETAILS_DEPTH", 4))
        if depth > max_depth:
            raise ValueError("Audit details exceed the maximum nesting depth")
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower()
                if any(part in normalized for part in AUDIT_FORBIDDEN_KEY_PARTS):
                    raise ValueError(f"Forbidden audit detail key: {key}")
                cls._validate_nested_value(nested, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            if len(value) > 100:
                raise ValueError("Audit detail lists may contain at most 100 items")
            for nested in value:
                cls._validate_nested_value(nested, depth=depth + 1)
        elif isinstance(value, str) and len(value) > 2000:
            raise ValueError("Audit detail strings may contain at most 2000 characters")

    def _validate(self):
        if self.action not in AUDIT_ACTION_REGISTRY:
            raise ValueError(f"Unregistered audit action: {self.action}")
        if self.user_type not in AUDIT_USER_TYPES:
            raise ValueError(f"Unregistered audit user type: {self.user_type}")
        if bool(self.scope_officer_index) != bool(self.scope_policy_version):
            raise ValueError("Audit officer scope and policy must be stored together")
        if (
            self.scope_policy_version
            and self.scope_policy_version not in AUDIT_SCOPE_POLICY_VERSIONS
        ):
            raise ValueError("Unregistered audit officer scope policy")
        if not isinstance(self.details, dict):
            raise TypeError("Audit details must be an object")
        allowed_keys = AUDIT_ACTION_DETAIL_KEYS[self.action]
        unknown_keys = sorted(set(self.details) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"Unsupported audit detail keys: {', '.join(unknown_keys)}")
        self._validate_nested_value(self.details)
        max_bytes = int(getattr(settings, "ANALYTICS_AUDIT_MAX_DETAILS_BYTES", 16384))
        if len(self._canonical_json(self.details)) > max_bytes:
            raise ValueError("Audit details exceed the maximum encoded size")
        if len(str(self.description or "")) > 1000:
            raise ValueError("Audit description may contain at most 1000 characters")
        for name, value in (
            ("event_id", self.event_id),
            ("user_id", self.user_id),
            ("resource_type", self.resource_type),
            ("resource_id", self.resource_id),
        ):
            if value is not None and len(str(value)) > 200:
                raise ValueError(f"Audit {name} may contain at most 200 characters")

    def _payload_for_digest(self):
        return {
            "action": self.action,
            "user_id": self.user_id,
            "user_type": self.user_type,
            "user_email": self.user_email,
            "description": self.description,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "scope_officer_index": self.scope_officer_index,
            "scope_policy_version": self.scope_policy_version,
        }

    def to_storage_dict(self):
        data = encrypt_fields(self.to_dict(), self.encrypted_fields)
        data["integrity_hash"] = self._hash_document(data)
        self.integrity_hash = data["integrity_hash"]
        return data

    def save(self):
        self._validate()
        self.event_schema_version = AUDIT_EVENT_SCHEMA_VERSION
        self.action_group = AUDIT_ACTION_REGISTRY[self.action]
        if self.action == "admin_action" and any(
            word in str(self.description or "").lower()
            for word in (
                "delete",
                "deleted",
                "deactivate",
                "deactivated",
                "remove",
                "removed",
            )
        ):
            self.action_group = "delete"
        if not self.retention_expires_at:
            retention_days = int(
                getattr(settings, "ANALYTICS_AUDIT_RETENTION_DAYS", 2555)
            )
            self.retention_expires_at = self.timestamp + timedelta(days=retention_days)
        if not self.subject_index:
            subject_id = self.details.get("customer_id")
            if not subject_id and self.user_type == "customer":
                subject_id = self.user_id
            if not subject_id and self.resource_type in {
                "customer",
                "customer_profile",
                "account_security",
            }:
                subject_id = self.resource_id
            self.subject_index = self.blind_index(subject_id)
        if self.action == "account_deleted" and self.subject_index:
            subject_pseudonym = f"deleted:{self.subject_index[:24]}"
            if self.user_type in {"customer", "system"}:
                self.user_id = subject_pseudonym
            self.resource_id = subject_pseudonym
            self.user_email = ""
            self.ip_address = ""
            self.description = "Customer account deletion recorded"
        if not self.payload_digest:
            self.payload_digest = hashlib.sha256(
                self._canonical_json(self._payload_for_digest())
            ).hexdigest()
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_storage_dict()
        try:
            result = collection.insert_one(data)
        except DuplicateKeyError as exc:
            existing = collection.find_one({"event_id": self.event_id})
            if existing and hmac.compare_digest(
                str(existing.get("payload_digest") or ""), self.payload_digest
            ):
                return self.from_dict(existing)
            raise ValueError("Audit event ID was reused with a different payload") from exc
        self._id = result.inserted_id
        return self

    @classmethod
    def find(cls, query, sort=None, limit=100):
        from analytics.services.operations import bounded_cursor

        db = get_db()
        collection = db[cls.collection_name]
        cursor = bounded_cursor(collection.find(query))
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.limit(limit)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def find_by_user(cls, user_id, limit=50):
        return cls.find(
            {"user_id": str(user_id)}, sort=[("timestamp", -1)], limit=limit
        )

    @classmethod
    def find_recent(cls, limit=100):
        return cls.find({}, sort=[("timestamp", -1)], limit=limit)

    @classmethod
    def find_by_action(cls, action, limit=100):
        return cls.find({"action": action}, sort=[("timestamp", -1)], limit=limit)

    @classmethod
    def find_with_filters(
        cls,
        action=None,
        action_group=None,
        user_id=None,
        user_type=None,
        date_from=None,
        date_to=None,
        search=None,
        skip=0,
        limit=100,
    ):
        from analytics.services.operations import bounded_cursor

        query = cls._build_filter_query(
            action, action_group, user_id, user_type, date_from, date_to, search
        )
        db = get_db()
        collection = db[cls.collection_name]
        cursor = bounded_cursor(collection.find(query))
        cursor = cursor.sort([("timestamp", -1), ("_id", -1)])
        if skip:
            cursor = cursor.skip(skip)
        cursor = cursor.limit(limit)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def count_with_filters(
        cls,
        action=None,
        action_group=None,
        user_id=None,
        user_type=None,
        date_from=None,
        date_to=None,
        search=None,
    ):
        from analytics.services.operations import bounded_count

        query = cls._build_filter_query(
            action, action_group, user_id, user_type, date_from, date_to, search
        )
        db = get_db()
        collection = db[cls.collection_name]
        return bounded_count(collection, query)

    @classmethod
    def _build_filter_query(
        cls,
        action,
        action_group,
        user_id,
        user_type,
        date_from,
        date_to,
        search=None,
    ):
        import re

        and_conditions = []

        if action:
            and_conditions.append({"action": action})

        if action_group:
            group = str(action_group).strip().lower()
            if group not in ACTION_GROUPS:
                raise ValueError(f"Unregistered audit action group: {group}")
            group_filter = {
                "$or": [
                    {"action_group": group},
                    {"action": {"$in": ACTION_GROUPS[group]}},
                ]
            }
            if group == "delete":
                group_filter = {
                    "$or": [
                        {"action_group": "delete"},
                        {"action": {"$in": ACTION_GROUPS[group]}},
                        {
                            "action": "admin_action",
                            "description": {
                                "$regex": "(delete|deleted|deactivate|deactivated|remove|removed)",
                                "$options": "i",
                            },
                        },
                    ]
                }
            and_conditions.append(group_filter)

        if user_id:
            and_conditions.append({"user_id": str(user_id).strip()})

        if user_type:
            and_conditions.append({"user_type": str(user_type).strip()})

        if date_from or date_to:
            ts_cond = {}
            if date_from:
                ts_cond["$gte"] = date_from
            if date_to:
                ts_cond["$lte"] = date_to
            if ts_cond:
                and_conditions.append({"timestamp": ts_cond})

        if search and str(search).strip():
            search_regex = {
                "$regex": f"^{re.escape(str(search).strip())}",
                "$options": "i",
            }
            and_conditions.append(
                {
                    "$or": [
                        {"action": search_regex},
                        {"user_id": search_regex},
                        {"user_type": search_regex},
                        {"resource_id": search_regex},
                        {"resource_type": search_regex},
                    ]
                }
            )

        if not and_conditions:
            return {}
        if len(and_conditions) == 1:
            return and_conditions[0]
        return {"$and": and_conditions}

    @classmethod
    def count_by_action(cls, action, start_date=None, end_date=None):
        db = get_db()
        collection = db[cls.collection_name]
        query = {"action": action}
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date
        return collection.count_documents(query)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("event_id", unique=True, sparse=True)
        collection.create_index("user_id")
        collection.create_index("subject_index")
        collection.create_index(
            [("scope_officer_index", 1), ("timestamp", -1), ("_id", -1)],
            name="audit_officer_event_scope",
        )
        collection.create_index("action")
        collection.create_index("timestamp")
        collection.create_index("resource_type")
        collection.create_index([("timestamp", -1), ("_id", -1)])
        collection.create_index(
            [("user_id", 1), ("user_type", 1), ("timestamp", -1), ("_id", -1)],
            name="audit_actor_filter_sort",
        )
        collection.create_index(
            [("action", 1), ("timestamp", -1), ("_id", -1)],
            name="audit_action_filter_sort",
        )
        collection.create_index(
            [("resource_type", 1), ("resource_id", 1), ("timestamp", -1), ("_id", -1)],
            name="audit_resource_filter_sort",
        )
        collection.create_index(
            [("legal_hold", 1), ("retention_expires_at", 1)],
            name="audit_retention_cleanup",
        )

    @classmethod
    def create_validator(cls):
        """Install the production MongoDB shape validator for protected events."""
        validator = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "event_id",
                    "event_schema_version",
                    "action",
                    "action_group",
                    "user_type",
                    "timestamp",
                    "retention_policy_version",
                    "retention_expires_at",
                    "integrity_hash",
                ],
                "properties": {
                    "event_id": {"bsonType": "string"},
                    "event_schema_version": {"bsonType": "int"},
                    "action": {"enum": list(AUDIT_ACTION_REGISTRY)},
                    "action_group": {
                        "enum": ["login", "read", "create", "update", "delete"]
                    },
                    "user_type": {"enum": sorted(AUDIT_USER_TYPES)},
                    "timestamp": {"bsonType": "date"},
                    "retention_expires_at": {"bsonType": "date"},
                    "legal_hold": {"bsonType": "bool"},
                    "scope_officer_index": {"bsonType": ["string", "null"]},
                    "scope_policy_version": {
                        "enum": [None, *sorted(AUDIT_SCOPE_POLICY_VERSIONS)]
                    },
                    "integrity_hash": {"bsonType": "string"},
                },
            }
        }
        get_db().command(
            "collMod",
            cls.collection_name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )

    @classmethod
    def log_action(
        cls,
        action,
        user_id=None,
        user_type="customer",
        user_email="",
        description="",
        resource_type=None,
        resource_id=None,
        details=None,
        ip_address="",
        event_id=None,
        idempotency_key=None,
        scope_officer_id=None,
        scope_policy_version=None,
    ):
        """
        Convenience method to create and save an audit log entry.

        Usage:
            AuditLog.log_action(
                action='user_login',
                user_id=user.id,
                user_type='customer',
                user_email=user.email,
                description='User logged in successfully',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
        """
        if event_id and idempotency_key:
            raise ValueError("Use either event_id or idempotency_key, not both")
        stable_event_id = event_id
        if idempotency_key:
            key = str(idempotency_key).strip()
            if not key or len(key) > 200:
                raise ValueError("Audit idempotency_key must contain 1 to 200 characters")
            stable_event_id = f"evt_{cls.blind_index(key)}"
        log = cls(
            user_id=str(user_id) if user_id else None,
            user_type=user_type,
            user_email=user_email,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details=details or {},
            ip_address=ip_address,
            event_id=stable_event_id,
            scope_officer_id=scope_officer_id,
            scope_policy_version=scope_policy_version,
        )
        return log.save()
