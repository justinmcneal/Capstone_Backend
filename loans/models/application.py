"""
LoanApplication Model - Customer loan applications.
"""

from bson import ObjectId
from django.conf import settings
from config.field_encryption import decrypt_fields, encrypt_fields

from loans.utils.time import utcnow


def get_db():
    return settings.MONGODB


# Application status flow
APPLICATION_STATUSES = [
    "draft",  # Started but not submitted
    "submitted",  # Submitted, waiting for review
    "under_review",  # Assigned to loan officer
    "approved",  # Approved by loan officer
    "rejected",  # Rejected by loan officer
    "disbursed",  # Loan amount transferred
    "cancelled",  # Cancelled by customer
]


class LoanApplication:
    """
    Loan Application Model.
    Customer loan application.
    """

    collection_name = "loan_applications"
    encrypted_fields = (
        "internal_notes",
        "officer_notes",
        "rejection_reason",
        "missing_documents_reason",
        "disbursement_reference",
        "eth_disbursement_raw_transaction",
    )

    def __init__(self, **kwargs):
        self._id = kwargs.get("_id")
        self.customer_id = kwargs.get("customer_id")
        self.product_id = kwargs.get("product_id")

        # Loan details
        self.requested_amount = kwargs.get("requested_amount", 0)
        self.recommended_amount = kwargs.get("recommended_amount")  # AI recommendation
        self.approved_amount = kwargs.get("approved_amount")  # Final approved
        self.term_months = kwargs.get("term_months", 12)
        self.purpose = kwargs.get("purpose", "")

        # AI Scoring
        self.eligibility_score = kwargs.get("eligibility_score")  # 0-100
        self.ai_recommendation = kwargs.get("ai_recommendation", {})  # AI analysis
        self.risk_category = kwargs.get("risk_category")  # low/medium/high

        # Status
        self.status = kwargs.get("status", "draft")

        # Loan officer review
        self.assigned_officer = kwargs.get("assigned_officer")  # Loan officer ID
        self.officer_notes = kwargs.get("officer_notes", "")
        self.rejection_reason = kwargs.get("rejection_reason", "")
        self.decision_date = kwargs.get("decision_date")
        self.internal_notes = kwargs.get("internal_notes", [])

        # Missing document requests (for documents never uploaded)
        self.missing_documents_requested = kwargs.get("missing_documents_requested", [])
        self.missing_documents_reason = kwargs.get("missing_documents_reason", "")
        self.missing_documents_requested_by = kwargs.get(
            "missing_documents_requested_by"
        )
        self.missing_documents_requested_at = kwargs.get(
            "missing_documents_requested_at"
        )
        self.document_request_history = kwargs.get("document_request_history", [])

        # Disbursement tracking
        self.preferred_disbursement_method = kwargs.get(
            "preferred_disbursement_method"
        )  # Borrower-selected: gcash, bank_transfer
        self.disbursed_amount = kwargs.get("disbursed_amount")
        self.disbursed_at = kwargs.get("disbursed_at")
        self.disbursement_method = kwargs.get(
            "disbursement_method"
        )  # bank_transfer, cash, etc.
        self.disbursement_reference = kwargs.get("disbursement_reference", "")
        self.disbursed_by = kwargs.get("disbursed_by")  # Officer/Admin who processed
        self.disbursement_status = kwargs.get(
            "disbursement_status",
            "executed" if self.status == "disbursed" else "not_started",
        )
        self.disbursement_idempotency_key = kwargs.get(
            "disbursement_idempotency_key", ""
        )
        self.disbursement_requested_at = kwargs.get("disbursement_requested_at")
        self.disbursement_completed_at = kwargs.get("disbursement_completed_at")
        self.disbursement_failed_at = kwargs.get("disbursement_failed_at")
        self.disbursement_error = kwargs.get("disbursement_error", "")

        # ETH wallet disbursement details
        self.eth_disbursement_tx_hash = kwargs.get("eth_disbursement_tx_hash")
        self.eth_disbursement_amount = kwargs.get("eth_disbursement_amount")
        self.eth_disbursement_amount_wei = kwargs.get("eth_disbursement_amount_wei")
        self.eth_disbursement_rate = kwargs.get("eth_disbursement_rate")
        self.eth_disbursement_rate_source = kwargs.get("eth_disbursement_rate_source", "")
        self.eth_disbursement_recipient = kwargs.get("eth_disbursement_recipient")
        self.eth_disbursement_nonce = kwargs.get("eth_disbursement_nonce")
        self.eth_disbursement_broadcast_at = kwargs.get(
            "eth_disbursement_broadcast_at"
        )
        self.eth_disbursement_block_number = kwargs.get(
            "eth_disbursement_block_number"
        )
        self.eth_disbursement_raw_transaction = kwargs.get(
            "eth_disbursement_raw_transaction", ""
        )
        self.eth_disbursement_prepared_at = kwargs.get(
            "eth_disbursement_prepared_at"
        )
        self.eth_disbursement_last_checked_at = kwargs.get(
            "eth_disbursement_last_checked_at"
        )
        self.eth_disbursement_tx_status = kwargs.get(
            "eth_disbursement_tx_status", ""
        )
        self.eth_disbursement_rebroadcast_count = kwargs.get(
            "eth_disbursement_rebroadcast_count", 0
        )
        self.eth_disbursement_recovery_history = kwargs.get(
            "eth_disbursement_recovery_history", []
        )
        self.disbursement_worker_owner = kwargs.get("disbursement_worker_owner", "")
        self.disbursement_worker_lease_expires_at = kwargs.get(
            "disbursement_worker_lease_expires_at"
        )

        # Timestamps
        self.submitted_at = kwargs.get("submitted_at")
        self.created_at = kwargs.get("created_at", utcnow())
        self.updated_at = kwargs.get("updated_at", utcnow())

        # Blockchain sync tracking
        self.blockchain_tx_hashes = kwargs.get("blockchain_tx_hashes", {})

    @property
    def id(self):
        return str(self._id) if self._id else None

    def to_dict(self):
        data = {
            "customer_id": self.customer_id,
            "product_id": self.product_id,
            "requested_amount": self.requested_amount,
            "recommended_amount": self.recommended_amount,
            "approved_amount": self.approved_amount,
            "term_months": self.term_months,
            "purpose": self.purpose,
            "eligibility_score": self.eligibility_score,
            "ai_recommendation": self.ai_recommendation,
            "risk_category": self.risk_category,
            "status": self.status,
            "assigned_officer": self.assigned_officer,
            "officer_notes": self.officer_notes,
            "rejection_reason": self.rejection_reason,
            "decision_date": self.decision_date,
            "internal_notes": self.internal_notes,
            "missing_documents_requested": self.missing_documents_requested,
            "missing_documents_reason": self.missing_documents_reason,
            "missing_documents_requested_by": self.missing_documents_requested_by,
            "missing_documents_requested_at": self.missing_documents_requested_at,
            "document_request_history": self.document_request_history,
            "preferred_disbursement_method": self.preferred_disbursement_method,
            "disbursed_amount": self.disbursed_amount,
            "disbursed_at": self.disbursed_at,
            "disbursement_method": self.disbursement_method,
            "disbursement_reference": self.disbursement_reference,
            "disbursed_by": self.disbursed_by,
            "disbursement_status": self.disbursement_status,
            "disbursement_idempotency_key": self.disbursement_idempotency_key,
            "disbursement_requested_at": self.disbursement_requested_at,
            "disbursement_completed_at": self.disbursement_completed_at,
            "disbursement_failed_at": self.disbursement_failed_at,
            "disbursement_error": self.disbursement_error,
            "eth_disbursement_tx_hash": self.eth_disbursement_tx_hash,
            "eth_disbursement_amount": self.eth_disbursement_amount,
            "eth_disbursement_amount_wei": self.eth_disbursement_amount_wei,
            "eth_disbursement_rate": self.eth_disbursement_rate,
            "eth_disbursement_rate_source": self.eth_disbursement_rate_source,
            "eth_disbursement_recipient": self.eth_disbursement_recipient,
            "eth_disbursement_nonce": self.eth_disbursement_nonce,
            "eth_disbursement_broadcast_at": self.eth_disbursement_broadcast_at,
            "eth_disbursement_block_number": self.eth_disbursement_block_number,
            "eth_disbursement_raw_transaction": self.eth_disbursement_raw_transaction,
            "eth_disbursement_prepared_at": self.eth_disbursement_prepared_at,
            "eth_disbursement_last_checked_at": self.eth_disbursement_last_checked_at,
            "eth_disbursement_tx_status": self.eth_disbursement_tx_status,
            "eth_disbursement_rebroadcast_count": self.eth_disbursement_rebroadcast_count,
            "eth_disbursement_recovery_history": self.eth_disbursement_recovery_history,
            "disbursement_worker_owner": self.disbursement_worker_owner,
            "disbursement_worker_lease_expires_at": self.disbursement_worker_lease_expires_at,
            "submitted_at": self.submitted_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "blockchain_tx_hashes": self.blockchain_tx_hashes,
        }
        if self._id:
            data["_id"] = self._id
        return encrypt_fields(data, self.encrypted_fields)

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(**decrypt_fields(data, cls.encrypted_fields))

    def save(self):
        db = get_db()
        collection = db[self.collection_name]
        self.updated_at = utcnow()
        data = self.to_dict()

        if self._id:
            # MongoDB's _id field is immutable and cannot be included in $set,
            # even when the value is unchanged. Keep it only in the selector.
            data.pop("_id", None)
            collection.update_one({"_id": self._id}, {"$set": data})
        else:
            result = collection.insert_one(data)
            self._id = result.inserted_id
        return self

    def _log_status_transition(self, action, actor_id, actor_type, description, extra_details=None):
        """Log a status transition with structured metadata."""
        try:
            from analytics.models.audit_log import AuditLog
            AuditLog.log_action(
                action=action,
                user_id=str(actor_id) if actor_id else None,
                user_type=actor_type or "system",
                description=description,
                resource_type="loan",
                resource_id=self.id,
                details={
                    "loan_id": self.id,
                    "customer_id": self.customer_id,
                    "old_status": getattr(self, "_prev_status", None),
                    "new_status": self.status,
                    **(extra_details or {}),
                },
            )
        except Exception:
            pass

    def submit(self):
        """Submit the application for review"""
        self.status = "submitted"
        self.submitted_at = utcnow()
        return self.save()

    def assign_officer(self, officer_id):
        """Assign to a loan officer"""
        self._prev_status = self.status
        self.assigned_officer = officer_id
        self.status = "under_review"
        self.save()
        self._log_status_transition(
            action="loan_assigned",
            actor_id=str(officer_id),
            actor_type="loan_officer",
            description=f"Loan application assigned to officer {officer_id}",
        )
        return self

    def approve(self, officer_id, approved_amount, notes=""):
        """Approve the application"""
        self.status = "approved"
        self.approved_amount = approved_amount
        self.assigned_officer = officer_id
        self.officer_notes = notes
        self.decision_date = utcnow()
        return self.save()

    def reject(self, officer_id, reason, notes=""):
        """Reject the application"""
        self.status = "rejected"
        self.assigned_officer = officer_id
        self.rejection_reason = reason
        self.officer_notes = notes
        self.decision_date = utcnow()
        return self.save()

    def add_internal_note(self, author_id, author_role, content):
        """Add an internal note without changing approval/rejection state."""
        text = (content or "").strip()
        if not text:
            raise ValueError("Note content is required")

        entry = {
            "content": text,
            "author_id": str(author_id),
            "author_role": author_role or "loan_officer",
            "created_at": utcnow(),
        }

        notes = self.internal_notes or []
        notes.append(entry)
        # Keep history bounded
        self.internal_notes = notes[-100:]
        return self.save()

    def request_missing_documents(self, officer_id, missing_documents, reason=""):
        """
        Request missing documents that were never uploaded.

        - Keeps application in active review flow
        - Tracks latest request and request history
        """
        if self.status not in ["submitted", "under_review"]:
            raise ValueError(
                f"Cannot request missing documents for status: {self.status}"
            )

        # Keep stable order while removing duplicates
        unique_documents = []
        for document_type in missing_documents:
            if document_type not in unique_documents:
                unique_documents.append(document_type)

        now = utcnow()
        officer_id = str(officer_id)

        self.missing_documents_requested = unique_documents
        self.missing_documents_reason = reason
        self.missing_documents_requested_by = officer_id
        self.missing_documents_requested_at = now

        # Ensure application is actively tracked under review
        if self.status == "submitted":
            self.status = "under_review"
        if not self.assigned_officer:
            self.assigned_officer = officer_id

        history = self.document_request_history or []
        history.append(
            {
                "requested_documents": unique_documents,
                "reason": reason,
                "requested_by": officer_id,
                "requested_at": now,
            }
        )
        # Keep history bounded
        self.document_request_history = history[-20:]

        return self.save()

    def disburse(self, amount, method, reference, processed_by):
        """Compatibility helper for a synchronously confirmed disbursement."""
        self.begin_disbursement(
            amount=amount,
            method=method,
            reference=reference,
            processed_by=processed_by,
            idempotency_key=f"legacy:{self.id}:{reference}",
        )
        self.complete_disbursement(self.disbursement_idempotency_key)
        return self

    def begin_disbursement(
        self, amount, method, reference, processed_by, idempotency_key
    ):
        """Atomically reserve an approved loan for one disbursement attempt."""
        if self.approved_amount is None or float(self.approved_amount) <= 0:
            raise ValueError("Loan does not have a valid approved amount")
        if abs(float(amount) - float(self.approved_amount)) > 0.01:
            raise ValueError(
                f"Disbursement amount must equal approved amount of PHP{float(self.approved_amount):.2f}"
            )
        if method not in {"cash", "gcash", "bank_transfer", "check", "wallet"}:
            raise ValueError("Invalid disbursement method")
        if not idempotency_key:
            raise ValueError("Idempotency-Key is required")

        if self.disbursement_idempotency_key == idempotency_key:
            same_payload = (
                abs(float(self.disbursed_amount) - float(amount)) <= 0.01
                and self.disbursement_method == method
                and self.disbursement_reference == reference
            )
            if not same_payload:
                raise ValueError(
                    "Idempotency-Key was already used for a different disbursement"
                )
            return self, True
        if self.status != "approved":
            raise ValueError("Only approved loans can be disbursed")
        if not self._id:
            raise ValueError("Disbursement requires a persisted loan application")
        if self.disbursement_status in {"pending", "executed"}:
            raise ValueError("A disbursement is already pending or executed")

        now = utcnow()
        collection = get_db()[self.collection_name]
        result = collection.update_one(
            {
                "_id": self._id,
                "status": "approved",
                "disbursement_status": {"$in": [None, "not_started", "failed"]},
            },
            {
                "$set": {
                    "disbursed_amount": amount,
                    "disbursement_method": method,
                    "disbursement_reference": reference,
                    "disbursed_by": str(processed_by),
                    "disbursement_status": "pending",
                    "disbursement_idempotency_key": idempotency_key,
                    "disbursement_requested_at": now,
                    "disbursement_completed_at": None,
                    "disbursement_failed_at": None,
                    "disbursement_error": "",
                    "updated_at": now,
                }
            },
        )
        refreshed = self.find_by_id(self.id)
        if not result.modified_count:
            if refreshed and refreshed.disbursement_idempotency_key == idempotency_key:
                self.__dict__.update(refreshed.__dict__)
                return self, True
            raise ValueError("Disbursement could not be started due to a concurrent update")
        self.__dict__.update(refreshed.__dict__)
        return self, False

    def complete_disbursement(self, idempotency_key):
        """Mark a pending disbursement executed after its prerequisites succeed."""
        if (
            self.disbursement_status == "executed"
            and self.disbursement_idempotency_key == idempotency_key
        ):
            return self, True
        now = utcnow()
        collection = get_db()[self.collection_name]
        result = collection.update_one(
            {
                "_id": self._id,
                "status": "approved",
                "disbursement_status": "pending",
                "disbursement_idempotency_key": idempotency_key,
            },
            {
                "$set": {
                    "status": "disbursed",
                    "disbursement_status": "executed",
                    "disbursed_at": now,
                    "disbursement_completed_at": now,
                    "disbursement_error": "",
                    "updated_at": now,
                }
            },
        )
        refreshed = self.find_by_id(self.id)
        if not result.modified_count:
            if (
                refreshed
                and refreshed.disbursement_status == "executed"
                and refreshed.disbursement_idempotency_key == idempotency_key
            ):
                self.__dict__.update(refreshed.__dict__)
                return self, True
            raise ValueError("Disbursement is not pending for this Idempotency-Key")
        self.__dict__.update(refreshed.__dict__)
        return self, False

    def fail_disbursement(self, idempotency_key, error):
        """Keep the loan approved while recording a failed execution attempt."""
        now = utcnow()
        collection = get_db()[self.collection_name]
        collection.update_one(
            {
                "_id": self._id,
                "status": "approved",
                "disbursement_status": "pending",
                "disbursement_idempotency_key": idempotency_key,
            },
            {
                "$set": {
                    "disbursement_status": "failed",
                    "disbursement_failed_at": now,
                    "disbursement_error": str(error)[:500],
                    "updated_at": now,
                }
            },
        )
        refreshed = self.find_by_id(self.id)
        if refreshed:
            self.__dict__.update(refreshed.__dict__)
        return self

    def set_preferred_disbursement_method(self, method):
        """Set the borrower's preferred disbursement method."""
        allowed = {"cash", "gcash", "bank_transfer", "check", "wallet"}
        if method not in allowed:
            raise ValueError(
                f"Disbursement method must be one of: {', '.join(sorted(allowed))}"
            )
        allowed_statuses = {"pending", "submitted", "under_review", "approved"}
        if self.status not in allowed_statuses:
            raise ValueError(
                "Cannot change disbursement method for this application status"
            )
        self.preferred_disbursement_method = method
        self.updated_at = utcnow()
        return self.save()

    def can_resubmit(self):
        """Check if application can be resubmitted"""
        return self.status == "rejected"

    def resubmit(self, actor_id=None):
        """Resubmit a rejected application"""
        if not self.can_resubmit():
            raise ValueError("Only rejected applications can be resubmitted")

        self._prev_status = self.status
        self.status = "draft"
        self.rejection_reason = None
        self.officer_notes = None
        self.decision_date = None
        self.assigned_officer = None
        self.missing_documents_requested = []
        self.missing_documents_reason = ""
        self.missing_documents_requested_by = None
        self.missing_documents_requested_at = None
        self.updated_at = utcnow()
        self.save()
        self._log_status_transition(
            action="loan_resubmitted",
            actor_id=actor_id or self.customer_id,
            actor_type="customer",
            description="Loan application resubmitted after rejection",
        )
        return self

    @classmethod
    def find_one(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        doc = collection.find_one(query)
        return cls.from_dict(doc)

    @classmethod
    def find(cls, query, sort=None, skip=None, limit=None):
        db = get_db()
        collection = db[cls.collection_name]
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return [cls.from_dict(doc) for doc in cursor]

    @classmethod
    def count(cls, query):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents(query)

    @classmethod
    def find_by_id(cls, app_id):
        try:
            return cls.find_one({"_id": ObjectId(app_id)})
        except Exception:
            return None

    @classmethod
    def find_by_customer(cls, customer_id):
        return cls.find({"customer_id": str(customer_id)}, sort=[("created_at", -1)])

    @classmethod
    def find_pending(cls):
        """Get applications pending review"""
        return cls.find(
            {"status": {"$in": ["submitted", "under_review"]}},
            sort=[("submitted_at", 1)],
        )

    @classmethod
    def find_by_officer(cls, officer_id):
        """Get applications assigned to officer"""
        return cls.find(
            {"assigned_officer": str(officer_id)}, sort=[("updated_at", -1)]
        )

    @classmethod
    def count_by_product(cls, product_id):
        """
        Count active applications using this product.
        Active = submitted, under_review, approved, or disbursed status.
        """
        db = get_db()
        collection = db[cls.collection_name]

        # Convert product_id to string for comparison
        product_id_str = str(product_id)

        count = collection.count_documents(
            {
                "product_id": product_id_str,
                "status": {
                    "$in": ["submitted", "under_review", "approved", "disbursed"]
                },
            }
        )
        return count

    @classmethod
    def find_pending_paginated(cls, page=1, page_size=20, search=None):
        """
        Get paginated UNASSIGNED applications pending review with optional search.

        Args:
            page: Page number (default 1)
            page_size: Items per page (default 20)
            search: Optional search term for customer_id or application id

        Returns:
            dict with applications list and pagination info
        """
        import re
        from bson import ObjectId

        db = get_db()
        collection = db[cls.collection_name]

        # Base query: only truly unassigned applications pending review
        query = {
            "status": {"$in": ["submitted", "under_review"]},
            "$or": [
                {"assigned_officer": None},
                {"assigned_officer": {"$exists": False}},
                {"assigned_officer": ""},
            ],
        }

        # Apply search filter if provided
        if search:
            search_conditions = []
            try:
                # Try as exact ObjectId
                search_conditions.append({"_id": ObjectId(search)})
            except Exception:
                pass

            # Search in customer_id (case-insensitive)
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            search_conditions.append({"customer_id": search_regex})

            # Search by partial _id string match
            search_conditions.append(
                {
                    "$expr": {
                        "$regexMatch": {
                            "input": {"$toString": "$_id"},
                            "regex": re.escape(search),
                            "options": "i",
                        }
                    }
                }
            )

            if search_conditions:
                # Combine base query with search using $and
                query = {"$and": [query, {"$or": search_conditions}]}

        # Get total count
        total = collection.count_documents(query)

        # Apply pagination
        skip = (page - 1) * page_size
        cursor = (
            collection.find(query).sort("submitted_at", 1).skip(skip).limit(page_size)
        )

        applications = [cls.from_dict(doc) for doc in cursor]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        return {
            "applications": applications,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    @classmethod
    def find_assigned_paginated(
        cls, page=1, page_size=20, search=None, officer_id=None
    ):
        """
        Get paginated assigned applications with optional search and officer filter.

        Args:
            page: Page number (default 1)
            page_size: Items per page (default 20)
            search: Optional search term for customer_id or application id
            officer_id: Optional filter by specific officer

        Returns:
            dict with applications list and pagination info
        """
        import re
        from bson import ObjectId

        db = get_db()
        collection = db[cls.collection_name]

        # Base query for assigned applications
        query = {
            "assigned_officer": {"$nin": [None, "", False]},
        }

        # Filter by officer if provided
        if officer_id:
            query["assigned_officer"] = str(officer_id)

        # Apply search filter if provided
        if search:
            search_conditions = []
            try:
                # Try as exact ObjectId
                search_conditions.append({"_id": ObjectId(search)})
            except Exception:
                pass

            # Search in customer_id (case-insensitive)
            search_regex = re.compile(re.escape(search), re.IGNORECASE)
            search_conditions.append({"customer_id": search_regex})

            # Search by partial _id string match
            search_conditions.append(
                {
                    "$expr": {
                        "$regexMatch": {
                            "input": {"$toString": "$_id"},
                            "regex": re.escape(search),
                            "options": "i",
                        }
                    }
                }
            )

            if search_conditions:
                query = {"$and": [query, {"$or": search_conditions}]}

        # Get total count
        total = collection.count_documents(query)

        # Apply pagination
        skip = (page - 1) * page_size
        cursor = (
            collection.find(query).sort("updated_at", -1).skip(skip).limit(page_size)
        )

        applications = [cls.from_dict(doc) for doc in cursor]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        return {
            "applications": applications,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def reassign(self, new_officer_id):
        """
        Reassign application to a different officer.

        Args:
            new_officer_id: ID of the new officer

        Returns:
            self (saved instance)
        """
        if not self.assigned_officer:
            raise ValueError("Application is not currently assigned")

        if self.status not in ["under_review", "submitted"]:
            raise ValueError(f"Cannot reassign application with status: {self.status}")

        self.assigned_officer = str(new_officer_id)
        return self.save()

    @classmethod
    def count_by_status(cls, status):
        db = get_db()
        collection = db[cls.collection_name]
        return collection.count_documents({"status": status})

    @classmethod
    def create_indexes(cls):
        db = get_db()
        collection = db[cls.collection_name]
        collection.create_index("customer_id")
        collection.create_index("product_id")
        collection.create_index("status")
        collection.create_index("assigned_officer")
        collection.create_index("submitted_at")
        collection.create_index("disbursement_status")
        collection.create_index(
            "disbursement_idempotency_key",
            unique=True,
            partialFilterExpression={
                "disbursement_idempotency_key": {"$type": "string", "$gt": ""}
            },
        )

    @classmethod
    def update_blockchain_tx_hash(cls, application_id, action, tx_hash):
        db = get_db()
        collection = db[cls.collection_name]
        field = f"blockchain_tx_hashes.{action}"
        collection.update_one(
            {"_id": application_id},
            {"$set": {field: tx_hash}},
        )

    @classmethod
    def update_eth_disbursement(cls, application_id, **fields):
        db = get_db()
        collection = db[cls.collection_name]
        if "raw_transaction" in fields:
            encrypted = encrypt_fields(
                {"eth_disbursement_raw_transaction": fields.pop("raw_transaction")},
                ("eth_disbursement_raw_transaction",),
            )
            fields["raw_transaction"] = encrypted[
                "eth_disbursement_raw_transaction"
            ]
        collection.update_one(
            {"_id": application_id},
            {"$set": {f"eth_disbursement_{key}": value for key, value in fields.items()}},
        )

    @classmethod
    def clear_eth_disbursement_fields(cls, application_id, *field_names):
        if not field_names:
            return
        get_db()[cls.collection_name].update_one(
            {"_id": ObjectId(str(application_id))},
            {
                "$unset": {
                    f"eth_disbursement_{field_name}": ""
                    for field_name in field_names
                }
            },
        )

    @classmethod
    def record_eth_rebroadcast(cls, application_id):
        get_db()[cls.collection_name].update_one(
            {"_id": ObjectId(str(application_id))},
            {
                "$inc": {"eth_disbursement_rebroadcast_count": 1},
                "$set": {
                    "eth_disbursement_broadcast_at": utcnow(),
                    "eth_disbursement_tx_status": "broadcast",
                },
            },
        )

    @classmethod
    def reopen_wallet_disbursement(cls, application_id, actor_id):
        """Reopen an explicitly reviewed failed/cancelled wallet attempt."""
        now = utcnow()
        collection = get_db()[cls.collection_name]
        doc = collection.find_one_and_update(
            {
                "_id": ObjectId(str(application_id)),
                "status": "approved",
                "disbursement_method": "wallet",
                "disbursement_status": {"$in": ["failed", "cancelled"]},
            },
            {
                "$set": {
                    "disbursement_status": "pending",
                    "disbursement_error": "",
                    "disbursement_failed_at": None,
                    "updated_at": now,
                },
                "$push": {
                    "eth_disbursement_recovery_history": {
                        "action": "retry",
                        "actor_id": str(actor_id),
                        "at": now,
                    }
                },
            },
            return_document=__import__("pymongo").ReturnDocument.AFTER,
        )
        return cls.from_dict(doc)

    @classmethod
    def cancel_wallet_disbursement(cls, application_id, actor_id, reason=""):
        """Cancel only a wallet request that has no prepared transaction."""
        now = utcnow()
        doc = get_db()[cls.collection_name].find_one_and_update(
            {
                "_id": ObjectId(str(application_id)),
                "status": "approved",
                "disbursement_method": "wallet",
                "disbursement_status": "pending",
                "eth_disbursement_tx_hash": {"$in": [None, ""]},
                "eth_disbursement_raw_transaction": {"$in": [None, ""]},
                "disbursement_worker_owner": {"$in": [None, ""]},
            },
            {
                "$set": {
                    "disbursement_status": "cancelled",
                    "disbursement_error": str(reason or "Cancelled by operator")[:500],
                    "disbursement_failed_at": now,
                    "updated_at": now,
                },
                "$push": {
                    "eth_disbursement_recovery_history": {
                        "action": "cancel",
                        "actor_id": str(actor_id),
                        "reason": str(reason)[:500],
                        "at": now,
                    }
                },
            },
            return_document=__import__("pymongo").ReturnDocument.AFTER,
        )
        return cls.from_dict(doc)

    @classmethod
    def claim_wallet_disbursement(cls, application_id, owner, lease_expires_at, now):
        """Claim one pending wallet disbursement for a durable worker."""
        from pymongo import ReturnDocument

        doc = get_db()[cls.collection_name].find_one_and_update(
            {
                "_id": ObjectId(str(application_id)),
                "status": "approved",
                "disbursement_status": "pending",
                "disbursement_method": "wallet",
                "$or": [
                    {"disbursement_worker_owner": owner},
                    {"disbursement_worker_owner": {"$in": [None, ""]}},
                    {"disbursement_worker_lease_expires_at": {"$lte": now}},
                    {"disbursement_worker_lease_expires_at": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "disbursement_worker_owner": owner,
                    "disbursement_worker_lease_expires_at": lease_expires_at,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.from_dict(doc)

    @classmethod
    def release_wallet_disbursement(cls, application_id, owner):
        get_db()[cls.collection_name].update_one(
            {"_id": ObjectId(str(application_id)), "disbursement_worker_owner": owner},
            {
                "$unset": {
                    "disbursement_worker_owner": "",
                    "disbursement_worker_lease_expires_at": "",
                }
            },
        )
