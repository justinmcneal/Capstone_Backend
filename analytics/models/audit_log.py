"""
AuditLog Model - Track all important actions in the system.
"""

from datetime import datetime, timezone

from django.conf import settings


def get_db():
    return settings.MONGODB


# Versioned action contract. New producers must register their action and stable
# category here before writing it. Legacy records are still readable, but new
# unknown actions fail closed instead of silently drifting out of filters.
AUDIT_EVENT_SCHEMA_VERSION = 1
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
            "timestamp": self.timestamp,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**data)

    def save(self):
        if self.action not in AUDIT_ACTION_REGISTRY:
            raise ValueError(f"Unregistered audit action: {self.action}")
        if self.user_type not in AUDIT_USER_TYPES:
            raise ValueError(f"Unregistered audit user type: {self.user_type}")
        self.event_schema_version = AUDIT_EVENT_SCHEMA_VERSION
        self.action_group = AUDIT_ACTION_REGISTRY[self.action]
        db = get_db()
        collection = db[self.collection_name]
        data = self.to_dict()
        result = collection.insert_one(data)
        self._id = result.inserted_id
        return self

    @classmethod
    def find(cls, query, sort=None, limit=100):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
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
        query = cls._build_filter_query(
            action, action_group, user_id, user_type, date_from, date_to, search
        )
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
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
        query = cls._build_filter_query(
            action, action_group, user_id, user_type, date_from, date_to, search
        )
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents(query)

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
            group_filter = {"action": {"$in": ACTION_GROUPS[group]}}
            if group == "delete":
                group_filter = {
                    "$or": [
                        group_filter,
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
            search_regex = {"$regex": re.escape(str(search).strip()), "$options": "i"}
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
        collection.create_index("user_id")
        collection.create_index("action")
        collection.create_index("timestamp")
        collection.create_index("resource_type")
        collection.create_index([("timestamp", -1), ("_id", -1)])

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
        )
        return log.save()
