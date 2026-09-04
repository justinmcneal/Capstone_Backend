"""
Document Model for MSME Pathways

Stores document metadata and references to uploaded files.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.conf import settings
from pymongo import ReturnDocument

from config.field_encryption import decrypt_fields, encrypt_fields


def get_db():
    """Helper function to get MongoDB database instance"""
    return settings.MONGODB


# Document Types - All optional except valid_id for loan applications
DOCUMENT_TYPES = [
    "valid_id",  # Government-issued ID (required for loan)
    "selfie_with_id",  # Selfie holding ID (identity verification)
    "proof_of_address",  # Utility bill, barangay cert
    "business_permit",  # DTI/SEC/Mayor's permit
    "business_photo",  # Photo of business premises
    "income_proof",  # Bank statement, sales records (OPTIONAL - informal economy)
    "other",  # Other supporting documents
]

# Document statuses
DOCUMENT_STATUSES = [
    "pending",  # Uploaded, awaiting review
    "needs_review",  # Flagged by AI for quality issues
    "approved",  # Verified by loan officer
    "rejected",  # Rejected by loan officer
    "expired",  # Document has expired
]

# Allowed file types
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/jpg", "application/pdf"]

# Max file size (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class DocumentRevisionConflict(RuntimeError):
    """Raised when a stale document snapshot loses an atomic write race."""


class Document:
    """
    Document model for storing uploaded files metadata.
    """

    collection_name = "documents"
    encrypted_fields = (
        "original_filename",
        "file_path",
        "rejection_reason",
        "notes",
        "description",
        "reupload_reason",
        "legal_hold_reason",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")

        # Document info
        self.document_type = kwargs.get("document_type")  # From DOCUMENT_TYPES
        self.original_filename = kwargs.get("original_filename", "")
        self.file_path = kwargs.get("file_path", "")  # Storage path
        self.file_size = kwargs.get("file_size", 0)  # Bytes
        self.mime_type = kwargs.get("mime_type", "")
        self.sha256 = kwargs.get("sha256", "")
        self.upload_session_id = kwargs.get("upload_session_id")
        self.revision = int(kwargs.get("revision", 0) or 0)
        self.storage_state = kwargs.get("storage_state", "available")
        self.deletion_requested_at = kwargs.get("deletion_requested_at")
        self.deletion_attempts = int(kwargs.get("deletion_attempts", 0) or 0)
        self.deletion_last_error = kwargs.get("deletion_last_error", "")
        self.replaces_document_id = kwargs.get("replaces_document_id")
        self.superseded_by_document_id = kwargs.get("superseded_by_document_id")
        self.superseded_at = kwargs.get("superseded_at")
        self.retention_policy_version = kwargs.get("retention_policy_version")
        self.retention_expires_at = kwargs.get("retention_expires_at")
        self.legal_hold = bool(kwargs.get("legal_hold", False))
        self.legal_hold_reason = kwargs.get("legal_hold_reason", "")
        self.legal_hold_set_at = kwargs.get("legal_hold_set_at")
        self.legal_hold_set_by = kwargs.get("legal_hold_set_by")
        self.deletion_reason_code = kwargs.get("deletion_reason_code", "")

        # Status and verification
        self.status = kwargs.get("status", "pending")
        self.verified = kwargs.get("verified", False)
        self.verified_by = kwargs.get("verified_by")  # Loan officer ID
        self.verified_at = kwargs.get("verified_at")
        self.rejection_reason = kwargs.get("rejection_reason", "")

        # AI Analysis (for future CNN integration)
        self.confidence_score = kwargs.get("confidence_score")  # 0.0 - 1.0
        self.ai_analysis = kwargs.get("ai_analysis", {})  # CNN results
        self.ai_analyzed_at = kwargs.get("ai_analyzed_at")
        self.ai_analysis_status = kwargs.get("ai_analysis_status", "not_requested")
        self.ai_analysis_attempts = int(kwargs.get("ai_analysis_attempts", 0) or 0)
        self.ai_analysis_next_attempt_at = kwargs.get("ai_analysis_next_attempt_at")
        self.ai_analysis_started_at = kwargs.get("ai_analysis_started_at")
        self.ai_analysis_last_error_code = kwargs.get("ai_analysis_last_error_code", "")

        # Notes
        self.notes = kwargs.get("notes", "")  # Officer notes
        self.description = kwargs.get("description", "")  # User description

        # Re-upload request
        self.reupload_requested = kwargs.get("reupload_requested", False)
        self.reupload_reason = kwargs.get("reupload_reason", "")
        self.reupload_requested_by = kwargs.get("reupload_requested_by")
        self.reupload_requested_at = kwargs.get("reupload_requested_at")

        # Timestamps
        self.uploaded_at = kwargs.get("uploaded_at", datetime.now(timezone.utc))
        self.updated_at = kwargs.get("updated_at", datetime.now(timezone.utc))

        if self._id is None and self.retention_expires_at is None:
            self.retention_policy_version = getattr(
                settings, "DOCUMENT_RETENTION_POLICY_VERSION", "unversioned"
            )
            self.retention_expires_at = self.uploaded_at + timedelta(
                days=int(getattr(settings, "DOCUMENT_RETENTION_DAYS", 2555))
            )

    @property
    def id(self):
        return str(self._id) if self._id else None

    @property
    def file_size_display(self):
        """Human-readable file size"""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "document_type": self.document_type,
            "original_filename": self.original_filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "revision": self.revision,
            "storage_state": self.storage_state,
            "deletion_requested_at": self.deletion_requested_at,
            "deletion_attempts": self.deletion_attempts,
            "deletion_last_error": self.deletion_last_error,
            "replaces_document_id": self.replaces_document_id,
            "superseded_by_document_id": self.superseded_by_document_id,
            "superseded_at": self.superseded_at,
            "retention_policy_version": self.retention_policy_version,
            "retention_expires_at": self.retention_expires_at,
            "legal_hold": self.legal_hold,
            "legal_hold_reason": self.legal_hold_reason,
            "legal_hold_set_at": self.legal_hold_set_at,
            "legal_hold_set_by": self.legal_hold_set_by,
            "deletion_reason_code": self.deletion_reason_code,
            "status": self.status,
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at,
            "rejection_reason": self.rejection_reason,
            "confidence_score": self.confidence_score,
            "ai_analysis": self.ai_analysis,
            "ai_analyzed_at": self.ai_analyzed_at,
            "ai_analysis_status": self.ai_analysis_status,
            "ai_analysis_attempts": self.ai_analysis_attempts,
            "ai_analysis_next_attempt_at": self.ai_analysis_next_attempt_at,
            "ai_analysis_started_at": self.ai_analysis_started_at,
            "ai_analysis_last_error_code": self.ai_analysis_last_error_code,
            "notes": self.notes,
            "description": self.description,
            "reupload_requested": self.reupload_requested,
            "reupload_reason": self.reupload_reason,
            "reupload_requested_by": self.reupload_requested_by,
            "reupload_requested_at": self.reupload_requested_at,
            "uploaded_at": self.uploaded_at,
            "updated_at": self.updated_at,
        }
        if self.upload_session_id:
            data["upload_session_id"] = self.upload_session_id
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    def request_reupload(self, officer_id, reason, *, expected_revision=None):
        """Officer requests customer to re-upload this document"""
        from documents.services.state_machine import apply_reupload_request

        apply_reupload_request(self, reviewer_id=officer_id, reason=reason)
        return self._atomic_transition(
            allowed_current_statuses={"pending", "needs_review", "rejected"},
            expected_revision=expected_revision,
        )

    @classmethod
    def _revision_query(cls, document_id, expected_revision):
        query = {"_id": document_id}
        revision = int(expected_revision or 0)
        if revision == 0:
            query["$or"] = [
                {"revision": 0},
                {"revision": {"$exists": False}},
            ]
        else:
            query["revision"] = revision
        return query

    def _atomic_transition(self, *, allowed_current_statuses, expected_revision=None):
        if not self._id:
            raise ValueError("Document must be saved before transition")
        if expected_revision is None:
            expected_revision = self.revision
        data = self.to_dict()
        data.pop("_id", None)
        data.pop("revision", None)
        query = self._revision_query(self._id, expected_revision)
        query.update(
            {
                "status": {"$in": list(allowed_current_statuses)},
            }
        )
        # Legacy records have no storage_state field.
        query["$and"] = [
            {
                "$or": [
                    {"storage_state": "available"},
                    {"storage_state": {"$exists": False}},
                ]
            }
        ]
        document = get_db()[self.collection_name].find_one_and_update(
            query,
            {"$set": data, "$inc": {"revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise DocumentRevisionConflict(
                "Document was changed by another request; reload and retry"
            )
        refreshed = type(self).from_dict(document)
        self.__dict__.update(refreshed.__dict__)
        return self

    def review(
        self,
        *,
        action,
        reviewer_id,
        rejection_reason="",
        notes=None,
        expected_revision=None,
    ):
        """Apply one review decision with status and revision compare-and-set."""
        from documents.services.state_machine import apply_review_decision

        current_status = self.status
        apply_review_decision(
            self,
            action=action,
            reviewer_id=reviewer_id,
            rejection_reason=rejection_reason,
            notes=notes,
        )
        return self._atomic_transition(
            allowed_current_statuses={current_status},
            expected_revision=expected_revision,
        )

    def claim_deletion(self, *, expected_revision=None):
        """Atomically prevent review writes while storage deletion is pending."""
        if not self._id:
            raise ValueError("Document must be saved before deletion")
        now = datetime.now(timezone.utc)
        if expected_revision is None:
            expected_revision = self.revision
        query = self._revision_query(self._id, expected_revision)
        query.update(
            {
                "status": {"$in": ["pending", "needs_review", "rejected"]},
                "verified": {"$ne": True},
                "$and": [
                    {
                        "$or": [
                            {"storage_state": "available"},
                            {"storage_state": {"$exists": False}},
                        ]
                    }
                ],
            }
        )
        document = get_db()[self.collection_name].find_one_and_update(
            query,
            {
                "$set": {
                    "storage_state": "delete_pending",
                    "deletion_requested_at": now,
                    "deletion_last_error": "",
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise DocumentRevisionConflict(
                "Document was changed by another request; reload and retry"
            )
        refreshed = type(self).from_dict(document)
        self.__dict__.update(refreshed.__dict__)
        return self

    def mark_superseded(self, replacement_document_id):
        """Record the replacement without reopening or rewriting review history."""
        if not self._id:
            raise ValueError("Document must be saved before supersession")
        now = datetime.now(timezone.utc)
        query = self._revision_query(self._id, self.revision)
        query["$and"] = [
            {
                "$or": [
                    {"superseded_by_document_id": None},
                    {"superseded_by_document_id": {"$exists": False}},
                ]
            }
        ]
        document = get_db()[self.collection_name].find_one_and_update(
            query,
            {
                "$set": {
                    "superseded_by_document_id": str(replacement_document_id),
                    "superseded_at": now,
                    "retention_expires_at": now
                    + timedelta(
                        days=int(
                            getattr(
                                settings,
                                "DOCUMENT_SUPERSEDED_RETENTION_DAYS",
                                90,
                            )
                        )
                    ),
                    "retention_policy_version": getattr(
                        settings, "DOCUMENT_RETENTION_POLICY_VERSION", "unversioned"
                    ),
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise DocumentRevisionConflict(
                "Document replacement was changed by another request"
            )
        refreshed = type(self).from_dict(document)
        self.__dict__.update(refreshed.__dict__)
        return self

    def set_legal_hold(self, *, reason, set_by):
        """Place a document on legal hold using an atomic metadata update."""
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("A legal-hold reason is required")
        now = datetime.now(timezone.utc)
        encrypted_reason = encrypt_fields(
            {"legal_hold_reason": reason}, ("legal_hold_reason",)
        )["legal_hold_reason"]
        result = get_db()[self.collection_name].update_one(
            {"_id": self._id, "storage_state": {"$nin": ["delete_pending", "delete_failed"]}},
            {
                "$set": {
                    "legal_hold": True,
                    "legal_hold_reason": encrypted_reason,
                    "legal_hold_set_at": now,
                    "legal_hold_set_by": str(set_by),
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        return result.modified_count == 1

    def release_legal_hold(self, *, released_by):
        """Release a legal hold while retaining a non-sensitive audit marker."""
        now = datetime.now(timezone.utc)
        result = get_db()[self.collection_name].update_one(
            {"_id": self._id, "legal_hold": True},
            {
                "$set": {
                    "legal_hold": False,
                    "legal_hold_reason": "",
                    "legal_hold_set_at": None,
                    "legal_hold_set_by": None,
                    "legal_hold_released_at": now,
                    "legal_hold_released_by": str(released_by),
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        return result.modified_count == 1

    @classmethod
    def claim_retention_deletion(cls, document_id):
        """Atomically route one due, non-held record through storage cleanup."""
        if isinstance(document_id, ObjectId):
            object_id = document_id
        elif ObjectId.is_valid(str(document_id)):
            object_id = ObjectId(str(document_id))
        else:
            return None
        now = datetime.now(timezone.utc)
        row = get_db()[cls.collection_name].find_one_and_update(
            {
                "_id": object_id,
                "retention_expires_at": {"$lte": now},
                "legal_hold": {"$ne": True},
                "$or": [
                    {"storage_state": "available"},
                    {"storage_state": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "storage_state": "delete_pending",
                    "deletion_requested_at": now,
                    "deletion_reason_code": "retention_expired",
                    "deletion_last_error": "",
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(row)

    @classmethod
    def find_due_retention_ids(cls, limit=100):
        now = datetime.now(timezone.utc)
        cursor = (
            get_db()[cls.collection_name]
            .find(
                {
                    "retention_expires_at": {"$lte": now},
                    "legal_hold": {"$ne": True},
                    "$or": [
                        {"storage_state": "available"},
                        {"storage_state": {"$exists": False}},
                    ],
                },
                {"_id": 1},
            )
            .sort("retention_expires_at", 1)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [str(row["_id"]) for row in cursor]

    def mark_deletion_failed(self, error_code):
        get_db()[self.collection_name].update_one(
            {
                "_id": self._id,
                "storage_state": {"$in": ["delete_pending", "delete_failed"]},
            },
            {
                "$set": {
                    "storage_state": "delete_failed",
                    "deletion_last_error": str(error_code)[:100],
                    "updated_at": datetime.now(timezone.utc),
                },
                "$inc": {"deletion_attempts": 1},
            },
        )
        self.storage_state = "delete_failed"

    def schedule_ai_analysis(self):
        """Durably mark an image for consent-aware background analysis."""
        if not self._id:
            raise ValueError("Document must be saved before analysis is scheduled")
        now = datetime.now(timezone.utc)
        result = get_db()[self.collection_name].update_one(
            {
                "_id": self._id,
                "mime_type": {"$regex": "^image/", "$options": "i"},
                "$and": [
                    {
                        "$or": [
                            {"storage_state": "available"},
                            {"storage_state": {"$exists": False}},
                        ]
                    },
                    {
                        "$or": [
                            {"ai_analysis_status": {"$exists": False}},
                            {
                                "ai_analysis_status": {
                                    "$in": [
                                        "not_requested",
                                        "failed",
                                        "skipped_no_consent",
                                    ]
                                }
                            },
                        ]
                    },
                ],
            },
            {
                "$set": {
                    "ai_analysis_status": "pending",
                    "ai_analysis_attempts": 0,
                    "ai_analysis_next_attempt_at": now,
                    "ai_analysis_started_at": None,
                    "ai_analysis_last_error_code": "",
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count:
            self.ai_analysis_status = "pending"
            self.ai_analysis_next_attempt_at = now
            self.revision += 1
        return result.modified_count == 1

    @classmethod
    def claim_ai_analysis(cls, document_id, *, lease_seconds=300):
        """Claim one due analysis job, including an abandoned processing lease."""
        try:
            object_id = (
                document_id
                if isinstance(document_id, ObjectId)
                else ObjectId(str(document_id))
            )
        except Exception:
            return None
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=max(30, int(lease_seconds)))
        claimed = get_db()[cls.collection_name].find_one_and_update(
            {
                "_id": object_id,
                "$or": [
                    {
                        "ai_analysis_status": {"$in": ["pending", "retry_wait"]},
                        "ai_analysis_next_attempt_at": {"$lte": now},
                    },
                    {
                        "ai_analysis_status": "processing",
                        "ai_analysis_started_at": {"$lte": stale_before},
                    },
                ],
            },
            {
                "$set": {
                    "ai_analysis_status": "processing",
                    "ai_analysis_started_at": now,
                    "ai_analysis_next_attempt_at": None,
                    "updated_at": now,
                },
                "$inc": {"ai_analysis_attempts": 1, "revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(claimed)

    def complete_ai_analysis(self, analysis):
        """Persist a traceable result without overriding a human review decision."""
        now = datetime.now(timezone.utc)
        result = get_db()[self.collection_name].update_one(
            {"_id": self._id, "ai_analysis_status": "processing"},
            {
                "$set": {
                    "ai_analysis": dict(analysis),
                    "confidence_score": analysis.get("quality_score"),
                    "ai_analyzed_at": now,
                    "ai_analysis_status": "completed",
                    "ai_analysis_started_at": None,
                    "ai_analysis_next_attempt_at": None,
                    "ai_analysis_last_error_code": "",
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count and not analysis.get("is_valid", False):
            get_db()[self.collection_name].update_one(
                {"_id": self._id, "status": "pending"},
                {
                    "$set": {"status": "needs_review", "updated_at": now},
                    "$inc": {"revision": 1},
                },
            )
        return result.modified_count == 1

    def defer_ai_analysis(self, error_code, *, max_attempts=3, backoff_seconds=60):
        """Record a bounded retry or terminal failure using a non-sensitive code."""
        now = datetime.now(timezone.utc)
        exhausted = self.ai_analysis_attempts >= max(1, int(max_attempts))
        next_attempt = None
        if not exhausted:
            next_attempt = now + timedelta(
                seconds=max(1, int(backoff_seconds))
                * (2 ** max(0, self.ai_analysis_attempts - 1))
            )
        result = get_db()[self.collection_name].update_one(
            {"_id": self._id, "ai_analysis_status": "processing"},
            {
                "$set": {
                    "ai_analysis_status": "failed" if exhausted else "retry_wait",
                    "ai_analysis_started_at": None,
                    "ai_analysis_next_attempt_at": next_attempt,
                    "ai_analysis_last_error_code": str(error_code)[:64],
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        return result.modified_count == 1

    def skip_ai_analysis(self, reason="consent_unavailable"):
        """Fail closed when current AI consent cannot be established."""
        now = datetime.now(timezone.utc)
        result = get_db()[self.collection_name].update_one(
            {"_id": self._id, "ai_analysis_status": "processing"},
            {
                "$set": {
                    "ai_analysis_status": "skipped_no_consent",
                    "ai_analysis_started_at": None,
                    "ai_analysis_next_attempt_at": None,
                    "ai_analysis_last_error_code": str(reason)[:64],
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
        )
        return result.modified_count == 1

    @classmethod
    def find_due_ai_analyses(cls, limit=100):
        now = datetime.now(timezone.utc)
        lease_seconds = max(
            30, int(getattr(settings, "DOCUMENT_AI_LEASE_SECONDS", 300))
        )
        stale_before = now - timedelta(seconds=lease_seconds)
        cursor = (
            get_db()[cls.collection_name]
            .find(
                {
                    "$or": [
                        {
                            "ai_analysis_status": {"$in": ["pending", "retry_wait"]},
                            "ai_analysis_next_attempt_at": {"$lte": now},
                        },
                        {
                            "ai_analysis_status": "processing",
                            "ai_analysis_started_at": {"$lte": stale_before},
                        },
                    ]
                },
                {"_id": 1},
            )
            .sort("ai_analysis_next_attempt_at", 1)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [str(item["_id"]) for item in cursor]

    @classmethod
    def find_deletion_candidates(cls, limit=100):
        cursor = (
            get_db()[cls.collection_name]
            .find({"storage_state": {"$in": ["delete_pending", "delete_failed"]}})
            .sort("updated_at", 1)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [cls.from_dict(item) for item in cursor]

    def complete_deletion(self):
        result = get_db()[self.collection_name].delete_one(
            {
                "_id": self._id,
                "storage_state": {"$in": ["delete_pending", "delete_failed"]},
            }
        )
        return result.deleted_count == 1

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def save(self):
        db = get_db()
        collection = db[self.collection_name]

        self.updated_at = datetime.now(timezone.utc)
        data = self.to_dict()

        if self._id:
            data.pop("_id", None)
            data.pop("revision", None)
            document = collection.find_one_and_update(
                self._revision_query(self._id, self.revision),
                {"$set": data, "$inc": {"revision": 1}},
                return_document=ReturnDocument.AFTER,
            )
            if not document:
                raise DocumentRevisionConflict(
                    "Document was changed by another request; reload and retry"
                )
            refreshed = type(self).from_dict(document)
            self.__dict__.update(refreshed.__dict__)
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id

        return self

    def delete(self):
        """Complete an already-claimed deletion without bypassing storage state."""
        if not self._id:
            return False
        return self.complete_deletion()

    @classmethod
    def _customer_id_candidates(cls, customer_id):
        """Return customer_id candidates covering both ObjectId and string storage."""
        if customer_id is None:
            return []

        candidates = []

        if isinstance(customer_id, ObjectId):
            candidates.append(customer_id)
            candidates.append(str(customer_id))
        else:
            customer_id_str = str(customer_id)
            candidates.append(customer_id_str)
            try:
                candidates.insert(0, ObjectId(customer_id_str))
            except Exception:
                pass

        deduped = []
        seen = set()
        for value in candidates:
            marker = (type(value).__name__, str(value))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(value)
        return deduped

    @classmethod
    def _customer_query(cls, customer_id):
        """Build a Mongo query that matches both legacy and current ID shapes."""
        candidates = cls._customer_id_candidates(customer_id)
        if not candidates:
            return {"customer_id": customer_id}
        if len(candidates) == 1:
            return {"customer_id": candidates[0]}
        return {"customer_id": {"$in": candidates}}

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find_by_id(cls, document_id):
        """Find a document using either its ObjectId or canonical string form."""
        try:
            object_id = (
                document_id
                if isinstance(document_id, ObjectId)
                else ObjectId(str(document_id))
            )
        except Exception:
            return None
        return cls.find_one({"_id": object_id})

    @classmethod
    def find_reupload_candidate(cls, customer_id, document_type):
        query = cls._customer_query(customer_id)
        query.update(
            {
                "document_type": document_type,
                "reupload_requested": True,
                "$or": [
                    {"superseded_by_document_id": None},
                    {"superseded_by_document_id": {"$exists": False}},
                ],
            }
        )
        document = get_db()[cls.collection_name].find_one(
            query, sort=[("reupload_requested_at", -1), ("uploaded_at", -1)]
        )
        return cls.from_dict(document)

    @classmethod
    def find(cls, query, sort=None, limit=None, projection=None):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query, projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(max(1, int(limit)))
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def available_query(cls, query=None):
        """Add the visible-storage condition while retaining existing clauses."""
        visible_query = dict(query or {})
        conditions = list(visible_query.pop("$and", []))
        conditions.append(
            {
                "$or": [
                    {"storage_state": "available"},
                    {"storage_state": {"$exists": False}},
                ]
            }
        )
        visible_query["$and"] = conditions
        return visible_query

    @classmethod
    def paginate(
        cls,
        query,
        *,
        page,
        page_size,
        sort=None,
    ):
        """Count and load only one deterministic MongoDB result page."""
        page = int(page)
        page_size = int(page_size)
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")

        collection = get_db()[cls.collection_name]
        query = dict(query or {})
        ordering = sort or [("uploaded_at", -1), ("_id", -1)]
        total = collection.count_documents(query)
        cursor = (
            collection.find(query)
            .sort(ordering)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [cls.from_dict(document) for document in cursor], total

    @classmethod
    def find_by_customer(
        cls, customer_id, document_type=None, limit=None, projection=None
    ):
        """Find all documents for a customer, optionally filtered by type"""
        query = cls.available_query(cls._customer_query(customer_id))
        if document_type:
            query["document_type"] = document_type
        return cls.find(
            query,
            sort=[("uploaded_at", -1)],
            limit=limit,
            projection=projection,
        )

    @classmethod
    def count_by_customer(cls, customer_id, document_type=None):
        """Count documents for a customer"""
        db = get_db()
        collection = db[cls.collection_name]
        query = cls.available_query(cls._customer_query(customer_id))
        if document_type:
            query["document_type"] = document_type
        return collection.count_documents(query)

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id")
        collection.create_index("document_type")
        collection.create_index([("customer_id", 1), ("document_type", 1)])
        collection.create_index("status")
        collection.create_index("uploaded_at")
        collection.create_index("upload_session_id", unique=True, sparse=True)
        collection.create_index([("storage_state", 1), ("updated_at", 1)])
        collection.create_index(
            [("legal_hold", 1), ("retention_expires_at", 1), ("storage_state", 1)],
            name="document_retention_cleanup",
        )
        collection.create_index(
            [("ai_analysis_status", 1), ("ai_analysis_next_attempt_at", 1)],
            name="document_ai_analysis_reconciliation",
        )
        collection.create_index(
            [("ai_analysis_status", 1), ("ai_analysis_started_at", 1)],
            name="document_ai_analysis_stale_lease",
        )
        collection.create_index(
            [("storage_state", 1), ("uploaded_at", -1), ("_id", -1)]
        )
        collection.create_index(
            [
                ("customer_id", 1),
                ("storage_state", 1),
                ("uploaded_at", -1),
                ("_id", -1),
            ]
        )
        collection.create_index(
            [
                ("customer_id", 1),
                ("document_type", 1),
                ("status", 1),
                ("storage_state", 1),
                ("uploaded_at", -1),
                ("_id", -1),
            ]
        )
        collection.create_index(
            [
                ("document_type", 1),
                ("status", 1),
                ("storage_state", 1),
                ("uploaded_at", -1),
                ("_id", -1),
            ]
        )
