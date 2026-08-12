"""Allowlisted customer export and metadata-only profile history."""

from datetime import date, datetime, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128
from django.conf import settings

from profiles.models import (
    AlternativeData,
    BusinessProfile,
    CustomerProfile,
    RiskReviewRequest,
)
from profiles.services.notification_preferences import get_preferences

PROFILE_EXPORT_SCHEMA_VERSION = "2026-08-09-v1"
PROFILE_HISTORY_ACTIONS = (
    "profile_created",
    "profile_updated",
    "notification_preferences_updated",
    "risk_score_calculated",
    "risk_score_failed",
    "risk_score_stale",
    "risk_review_requested",
    "risk_review_status_changed",
)

PERSONAL_EXPORT_FIELDS = (
    "date_of_birth",
    "gender",
    "civil_status",
    "nationality",
    "mobile_number",
    "address_line1",
    "address_line2",
    "barangay",
    "city_municipality",
    "province",
    "zip_code",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
    "wallet_address",
)
BUSINESS_EXPORT_FIELDS = (
    "business_name",
    "business_type",
    "business_type_other",
    "business_description",
    "business_address",
    "business_barangay",
    "business_city",
    "business_province",
    "business_age_months",
    "is_registered",
    "registration_type",
    "registration_number",
    "estimated_monthly_income",
    "income_range",
    "estimated_monthly_expenses",
    "number_of_employees",
)
ALTERNATIVE_EXPORT_FIELDS = (
    "education_level",
    "employment_status",
    "years_of_experience",
    "housing_status",
    "years_at_current_address",
    "monthly_rent",
    "number_of_dependents",
    "household_income",
    "has_existing_loans",
    "existing_loan_amount",
    "existing_loan_source",
    "loan_payment_history",
    "has_bank_account",
    "bank_account_duration",
    "has_ewallet",
    "ewallet_usage",
    "pays_utilities",
    "utility_payment_history",
    "is_coop_member",
    "community_involvement",
    "risk_score",
    "risk_category",
    "score_calculated_at",
    "risk_score_status",
    "risk_score_policy_version",
    "risk_score_use",
    "risk_score_manual_review_required",
    "risk_input_revision",
    "risk_calculated_revision",
    "risk_score_breakdown",
    "risk_score_reason_codes",
)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _section(profile, fields):
    if profile is None:
        return {"present": False, "data": None}
    profile.calculate_completion()
    return {
        "present": bool(profile.id),
        "data": {
            **{field: _json_value(getattr(profile, field, None)) for field in fields},
            "profile_revision": profile.profile_revision,
            "profile_completed": profile.profile_completed,
            "completion_percentage": profile.completion_percentage,
            "profile_completion_policy_version": (
                profile.profile_completion_policy_version
            ),
            "profile_missing_fields": list(profile.profile_missing_fields),
            "created_at": _json_value(profile.created_at) if profile.id else None,
            "updated_at": _json_value(profile.updated_at) if profile.id else None,
        },
    }


def build_profile_export(customer):
    customer_id = str(customer.id)
    review_total = RiskReviewRequest.count_by_customer(customer_id)
    reviews = RiskReviewRequest.find_by_customer(customer_id, limit=100)
    return {
        "schema_version": PROFILE_EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "customer_id": customer_id,
        "scope": "profiles_only",
        "personal_profile": _section(
            CustomerProfile.find_by_customer(customer_id), PERSONAL_EXPORT_FIELDS
        ),
        "business_profile": _section(
            BusinessProfile.find_by_customer(customer_id), BUSINESS_EXPORT_FIELDS
        ),
        "alternative_data": _section(
            AlternativeData.find_by_customer(customer_id), ALTERNATIVE_EXPORT_FIELDS
        ),
        "notification_preferences": get_preferences(customer),
        "risk_reviews": {
            "items": [review.to_customer_dict() for review in reviews],
            "total": review_total,
            "truncated": review_total > len(reviews),
        },
        "retention": {
            "server_copy_created": False,
            "note": "Generated in memory; the API does not retain an export file.",
        },
    }


def get_profile_history(customer_id, *, page=1, page_size=20):
    from analytics.models import AuditLog

    query = {
        "$and": [
            {"action": {"$in": list(PROFILE_HISTORY_ACTIONS)}},
            {
                "$or": [
                    {"subject_index": AuditLog.blind_index(str(customer_id))},
                    {"user_id": str(customer_id)},
                    {"details.customer_id": str(customer_id)},
                ]
            },
        ]
    }
    collection = settings.MONGODB["audit_logs"]
    total = collection.count_documents(query)
    cursor = (
        collection.find(query)
        .sort([("timestamp", -1), ("_id", -1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    history = []
    for raw_event in cursor:
        event = AuditLog.from_dict(raw_event)
        details = event.details or {}
        history.append(
            {
                "event_id": event.id,
                "action": event.action,
                "section": event.resource_type,
                "resource_id": event.resource_id,
                "changed_fields": sorted(details.get("changed_fields") or []),
                "profile_revision": details.get("profile_revision"),
                "risk_revision": details.get("revision"),
                "status": details.get("status"),
                "timestamp": _json_value(event.timestamp),
            }
        )
    return {
        "history": history,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }
