"""Loan retention, legal hold, customer export, and account cleanup."""

import hashlib
from datetime import datetime, timezone

from bson import ObjectId
from django.conf import settings

from config.field_encryption import encrypt_value
from loans.models import LoanApplication, LoanPayment, RepaymentSchedule

TERMINAL_RETENTION_STATUSES = {"rejected", "cancelled", "completed", "written_off"}


def _customer_candidates(customer_id):
    value = str(customer_id or "").strip()
    if not value:
        raise ValueError("customer_id is required")
    candidates = [value]
    if ObjectId.is_valid(value):
        candidates.insert(0, ObjectId(value))
    return candidates


def _customer_filter(customer_id):
    candidates = _customer_candidates(customer_id)
    return candidates[0] if len(candidates) == 1 else {"$in": candidates}


def _bounded_rows(collection, query, *, sort, limit):
    total = collection.count_documents(query)
    bounded = max(1, min(int(limit), 10_000))
    rows = list(collection.find(query).sort(sort).limit(bounded))
    return rows, total


def export_customer_loan_data(db, customer_id, *, limit=None):
    """Return a bounded, customer-readable export without operational secrets."""
    limit = limit or getattr(settings, "LOAN_ACCOUNT_EXPORT_MAX_ROWS", 5000)
    owner = {"customer_id": _customer_filter(customer_id)}
    app_rows, app_total = _bounded_rows(
        db[LoanApplication.collection_name],
        owner,
        sort=[("created_at", 1), ("_id", 1)],
        limit=limit,
    )
    schedule_rows, schedule_total = _bounded_rows(
        db[RepaymentSchedule.collection_name],
        owner,
        sort=[("created_at", 1), ("_id", 1)],
        limit=limit,
    )
    payment_rows, payment_total = _bounded_rows(
        db[LoanPayment.collection_name],
        owner,
        sort=[("recorded_at", 1), ("_id", 1)],
        limit=limit,
    )

    applications = []
    for raw in app_rows:
        item = LoanApplication.from_dict(raw)
        applications.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "requested_amount": item.requested_amount,
                "recommended_amount": item.recommended_amount,
                "approved_amount": item.approved_amount,
                "term_months": item.term_months,
                "purpose": item.purpose,
                "eligibility_score": item.eligibility_score,
                "ai_recommendation": item.ai_recommendation,
                "risk_category": item.risk_category,
                "status": item.status,
                "rejection_reason": item.rejection_reason,
                "missing_documents_requested": item.missing_documents_requested,
                "missing_documents_reason": item.missing_documents_reason,
                "disbursed_amount": item.disbursed_amount,
                "disbursed_at": item.disbursed_at,
                "disbursement_method": item.disbursement_method,
                "repayment_status": item.repayment_status,
                "paid_off_at": item.paid_off_at,
                "submitted_at": item.submitted_at,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "retention_expires_at": item.retention_expires_at,
                "retention_policy_version": item.retention_policy_version,
                "legal_hold": item.legal_hold,
            }
        )

    schedules = []
    for raw in schedule_rows:
        item = RepaymentSchedule.from_dict(raw)
        schedules.append(
            {
                "id": item.id,
                "loan_id": item.loan_id,
                "principal": item.principal,
                "interest_rate": item.interest_rate,
                "term_months": item.term_months,
                "monthly_payment": item.monthly_payment,
                "total_amount": item.total_amount,
                "total_interest": item.total_interest,
                "status": item.status,
                "paid_off_at": item.paid_off_at,
                "installments": item.installments,
                "start_date": item.start_date,
                "created_at": item.created_at,
            }
        )

    payments = []
    for raw in payment_rows:
        item = LoanPayment.from_dict(raw)
        payments.append(
            {
                "id": item.id,
                "loan_id": item.loan_id,
                "installment_number": item.installment_number,
                "amount": item.amount,
                "payment_method": item.payment_method,
                "reference": item.reference,
                "payment_status": item.payment_status,
                "verified_at": item.verified_at,
                "timing_status": item.timing_status,
                "recorded_at": item.recorded_at,
            }
        )

    return {
        "applications": {
            "items": applications,
            "total": app_total,
            "truncated": app_total > len(applications),
        },
        "repayment_schedules": {
            "items": schedules,
            "total": schedule_total,
            "truncated": schedule_total > len(schedules),
        },
        "payments": {
            "items": payments,
            "total": payment_total,
            "truncated": payment_total > len(payments),
        },
    }


def pseudonymize_customer_loan_data(db, customer_id):
    """Detach retained lending records from a deleted customer, idempotently."""
    owner = _customer_filter(customer_id)
    pseudonym = (
        "deleted:" + hashlib.sha256(str(customer_id).encode("utf-8")).hexdigest()[:24]
    )
    now = datetime.now(timezone.utc)
    counts = {}
    for collection_name in (
        LoanApplication.collection_name,
        RepaymentSchedule.collection_name,
        LoanPayment.collection_name,
    ):
        result = db[collection_name].update_many(
            {"customer_id": owner},
            {"$set": {"customer_id": pseudonym, "pseudonymized_at": now}},
        )
        counts[collection_name] = int(result.modified_count)
    if "loan_notification_deliveries" in db.list_collection_names():
        delivery_result = db["loan_notification_deliveries"].update_many(
            {"recipient_user_id": str(customer_id)},
            {
                "$set": {
                    "recipient_user_id": pseudonym,
                    "recipient_email": encrypt_value("deleted@deleted.local"),
                    "recipient_name": encrypt_value("Deleted Customer"),
                    "pseudonymized_at": now,
                }
            },
        )
        counts["loan_notification_deliveries"] = int(delivery_result.modified_count)
    remaining = sum(
        db[name].count_documents({"customer_id": owner})
        for name in (
            LoanApplication.collection_name,
            RepaymentSchedule.collection_name,
            LoanPayment.collection_name,
        )
    )
    return {**counts, "remaining": int(remaining), "pseudonym": pseudonym}


def enforce_loan_retention(limit=100):
    """Delete one bounded batch whose approved retention period has elapsed."""
    now = datetime.now(timezone.utc)
    applications = settings.MONGODB[LoanApplication.collection_name]
    ids = [
        row["_id"]
        for row in applications.find(
            {
                "status": {"$in": sorted(TERMINAL_RETENTION_STATUSES)},
                "retention_expires_at": {"$lte": now},
                "legal_hold": {"$ne": True},
            },
            {"_id": 1},
        )
        .sort([("retention_expires_at", 1), ("_id", 1)])
        .limit(max(1, min(int(limit), 1000)))
    ]
    loan_ids = [str(value) for value in ids]
    if not loan_ids:
        return {
            "applications_deleted": 0,
            "schedules_deleted": 0,
            "payments_deleted": 0,
            "transactions_deleted": 0,
            "notifications_deleted": 0,
        }
    db = settings.MONGODB
    counts = {
        "schedules_deleted": int(
            db[RepaymentSchedule.collection_name]
            .delete_many({"loan_id": {"$in": loan_ids}})
            .deleted_count
        ),
        "payments_deleted": int(
            db[LoanPayment.collection_name]
            .delete_many({"loan_id": {"$in": loan_ids}})
            .deleted_count
        ),
        "transactions_deleted": int(
            db["blockchain_transactions"]
            .delete_many({"loan_id": {"$in": loan_ids}})
            .deleted_count
        ),
        "notifications_deleted": int(
            db["loan_notification_deliveries"]
            .delete_many({"loan_id": {"$in": loan_ids}})
            .deleted_count
        ),
    }
    counts["applications_deleted"] = int(
        applications.delete_many(
            {"_id": {"$in": ids}, "legal_hold": {"$ne": True}}
        ).deleted_count
    )
    return counts


def set_loan_legal_hold(application_id, *, reason, set_by):
    if not str(reason or "").strip():
        raise ValueError("A legal-hold reason is required")
    object_id = ObjectId(str(application_id))
    now = datetime.now(timezone.utc)
    return (
        settings.MONGODB[LoanApplication.collection_name]
        .update_one(
            {"_id": object_id, "legal_hold": {"$ne": True}},
            {
                "$set": {
                    "legal_hold": True,
                    "legal_hold_reason": encrypt_value(str(reason).strip()),
                    "legal_hold_set_at": now,
                    "legal_hold_set_by": str(set_by),
                    "updated_at": now,
                }
            },
        )
        .modified_count
        == 1
    )


def release_loan_legal_hold(application_id, *, released_by):
    object_id = ObjectId(str(application_id))
    now = datetime.now(timezone.utc)
    return (
        settings.MONGODB[LoanApplication.collection_name]
        .update_one(
            {"_id": object_id, "legal_hold": True},
            {
                "$set": {
                    "legal_hold": False,
                    "legal_hold_reason": "",
                    "legal_hold_released_at": now,
                    "legal_hold_released_by": str(released_by),
                    "updated_at": now,
                }
            },
        )
        .modified_count
        == 1
    )
