"""PyMongo model for customer-requested profile risk reviews."""

from datetime import datetime, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from config.field_encryption import decrypt_fields, encrypt_fields

RISK_REVIEW_REASONS = (
    "incorrect_profile_data",
    "unexpected_score",
    "missing_context",
    "other",
)
RISK_REVIEW_STATUSES = ("pending", "in_review", "resolved", "rejected")
RISK_REVIEW_TERMINAL_STATUSES = {"resolved", "rejected"}


class RiskReviewAlreadyExists(ValueError):
    """Raised when a scoring revision already has a review request."""


class RiskReviewConflict(RuntimeError):
    """Raised when a stale review revision or invalid transition is submitted."""


def get_db():
    return settings.MONGODB


class RiskReviewRequest:
    collection_name = "profile_risk_reviews"
    encrypted_fields = ("description", "resolution_note")

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = str(kwargs.get("customer_id") or "")
        self.risk_input_revision = int(kwargs.get("risk_input_revision", 0) or 0)
        self.risk_calculated_revision = int(
            kwargs.get("risk_calculated_revision", 0) or 0
        )
        self.risk_policy_version = kwargs.get("risk_policy_version")
        self.reason = kwargs.get("reason")
        self.description = kwargs.get("description", "")
        self.status = kwargs.get("status", "pending")
        self.review_revision = int(kwargs.get("review_revision", 0) or 0)
        self.assigned_officer_id = kwargs.get("assigned_officer_id")
        self.resolution_note = kwargs.get("resolution_note", "")
        self.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", self.created_at)
        self.resolved_at = kwargs.get("resolved_at")

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "risk_input_revision": self.risk_input_revision,
            "risk_calculated_revision": self.risk_calculated_revision,
            "risk_policy_version": self.risk_policy_version,
            "reason": self.reason,
            "description": self.description,
            "status": self.status,
            "review_revision": self.review_revision,
            "assigned_officer_id": self.assigned_officer_id,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    def to_customer_dict(self):
        return {
            "id": self.id,
            "risk_input_revision": self.risk_input_revision,
            "risk_calculated_revision": self.risk_calculated_revision,
            "risk_policy_version": self.risk_policy_version,
            "reason": self.reason,
            "description": self.description,
            "status": self.status,
            "review_revision": self.review_revision,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def to_officer_dict(self):
        return {"customer_id": self.customer_id, **self.to_customer_dict()}

    @classmethod
    def from_dict(cls, document):
        return cls(**decrypt_fields(document, cls.encrypted_fields)) if document else None

    @classmethod
    def create_for_score(cls, alternative, *, reason, description):
        if (
            alternative.risk_score_status != "complete"
            or alternative.risk_calculated_revision is None
            or alternative.risk_calculated_revision
            != alternative.risk_input_revision
        ):
            raise ValueError("A completed current risk score is required for review")
        now = datetime.now(timezone.utc)
        request = cls(
            customer_id=alternative.customer_id,
            risk_input_revision=alternative.risk_input_revision,
            risk_calculated_revision=alternative.risk_calculated_revision,
            risk_policy_version=alternative.risk_score_policy_version,
            reason=reason,
            description=description,
            created_at=now,
            updated_at=now,
        )
        try:
            result = get_db()[cls.collection_name].insert_one(request.to_dict())
        except DuplicateKeyError as exc:
            raise RiskReviewAlreadyExists(
                "A review already exists for this scoring revision"
            ) from exc
        request._id = result.inserted_id
        return request

    @classmethod
    def find_by_id(cls, review_id):
        if not ObjectId.is_valid(str(review_id)):
            return None
        return cls.from_dict(
            get_db()[cls.collection_name].find_one({"_id": ObjectId(str(review_id))})
        )

    @classmethod
    def find_by_customer(cls, customer_id, *, skip=0, limit=20):
        cursor = (
            get_db()[cls.collection_name]
            .find({"customer_id": str(customer_id)})
            .sort([("created_at", -1)])
            .skip(skip)
            .limit(limit)
        )
        return [cls.from_dict(document) for document in cursor]

    @classmethod
    def count_by_customer(cls, customer_id):
        return get_db()[cls.collection_name].count_documents(
            {"customer_id": str(customer_id)}
        )

    def transition(self, *, officer_id, status, resolution_note, expected_revision):
        if status not in RISK_REVIEW_STATUSES or status == "pending":
            raise ValueError("Unsupported review status")
        if self.status in RISK_REVIEW_TERMINAL_STATUSES:
            raise RiskReviewConflict("A completed review cannot be changed")
        if status in RISK_REVIEW_TERMINAL_STATUSES and not resolution_note.strip():
            raise ValueError("A resolution note is required for a terminal status")

        now = datetime.now(timezone.utc)
        updates = {
            "status": status,
            "assigned_officer_id": str(officer_id),
            "resolution_note": resolution_note.strip(),
            "updated_at": now,
            "resolved_at": now if status in RISK_REVIEW_TERMINAL_STATUSES else None,
        }
        updates = encrypt_fields(updates, self.encrypted_fields)
        document = get_db()[self.collection_name].find_one_and_update(
            {
                "_id": self._id,
                "review_revision": int(expected_revision),
                "status": {"$nin": list(RISK_REVIEW_TERMINAL_STATUSES)},
            },
            {"$set": updates, "$inc": {"review_revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise RiskReviewConflict("Review was changed; reload and retry")
        return type(self).from_dict(document)

    @classmethod
    def create_indexes(cls):
        collection = get_db()[cls.collection_name]
        collection.create_index(
            [("customer_id", 1), ("risk_calculated_revision", 1)],
            unique=True,
            name="unique_customer_scoring_review",
        )
        collection.create_index([("status", 1), ("created_at", -1)])
        collection.create_index([("customer_id", 1), ("created_at", -1)])
