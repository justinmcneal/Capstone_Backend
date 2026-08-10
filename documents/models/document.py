"""
Document Model for MSME Pathways

Stores document metadata and references to uploaded files.
"""

from datetime import datetime, timezone

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
            "status": self.status,
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at,
            "rejection_reason": self.rejection_reason,
            "confidence_score": self.confidence_score,
            "ai_analysis": self.ai_analysis,
            "ai_analyzed_at": self.ai_analyzed_at,
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
    def find(cls, query, sort=None):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def find_by_customer(cls, customer_id, document_type=None):
        """Find all documents for a customer, optionally filtered by type"""
        query = cls._customer_query(customer_id)
        query["$and"] = [
            {
                "$or": [
                    {"storage_state": "available"},
                    {"storage_state": {"$exists": False}},
                ]
            }
        ]
        if document_type:
            query["document_type"] = document_type
        return cls.find(query, sort=[("uploaded_at", -1)])

    @classmethod
    def count_by_customer(cls, customer_id, document_type=None):
        """Count documents for a customer"""
        db = get_db()
        collection = db[cls.collection_name]
        query = cls._customer_query(customer_id)
        query["$and"] = [
            {
                "$or": [
                    {"storage_state": "available"},
                    {"storage_state": {"$exists": False}},
                ]
            }
        ]
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
