"""Loans MongoDB inventory, dry-run backfill, and validator definitions."""

from copy import deepcopy
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.field_encryption import (
    is_encrypted_value,
    is_primary_encrypted_value,
    reencrypt_value,
)
from loans.blockchain.models import BlockchainTransaction
from loans.models import LoanApplication, LoanPayment, LoanProduct, RepaymentSchedule
from loans.models.application import APPLICATION_STATUSES
from loans.models.payment import PAYMENT_METHODS, PAYMENT_STATUSES
from loans.models.repayment import SCHEDULE_STATUSES
from loans.utils.money import to_centavos

NUMBER_TYPES = ["int", "long", "double", "decimal"]
SETTLEMENT_METHODS = ["cash", "check", "wallet"]
ENCRYPTED_STRING = {
    "bsonType": "string",
    "pattern": "^enc::v2::[0-9a-f]{12}::",
}
ENCRYPTED_BSON = {
    "bsonType": "string",
    "pattern": "^encbson::v2::[0-9a-f]{12}::",
}

LOAN_VALIDATORS = {
    LoanProduct.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "name",
                "code",
                "min_amount",
                "max_amount",
                "interest_rate",
                "min_term_months",
                "max_term_months",
                "active",
                "created_at",
                "updated_at",
            ],
            "properties": {
                "name": {"bsonType": "string", "minLength": 1},
                "code": {"bsonType": "string", "minLength": 1},
                "description": {"oneOf": [{"enum": [""]}, ENCRYPTED_STRING]},
                "target_description": {"oneOf": [{"enum": [""]}, ENCRYPTED_STRING]},
                "min_amount": {"bsonType": NUMBER_TYPES, "minimum": 0},
                "max_amount": {"bsonType": NUMBER_TYPES, "minimum": 0},
                "interest_rate": {"bsonType": NUMBER_TYPES, "minimum": 0},
                "min_term_months": {"bsonType": ["int", "long"], "minimum": 1},
                "max_term_months": {"bsonType": ["int", "long"], "minimum": 1},
                "active": {"bsonType": "bool"},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
    LoanApplication.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "customer_id",
                "product_id",
                "requested_amount",
                "term_months",
                "status",
                "disbursement_status",
                "retention_policy_version",
                "retention_expires_at",
                "legal_hold",
                "created_at",
                "updated_at",
            ],
            "properties": {
                "customer_id": {"bsonType": "string", "minLength": 1},
                "product_id": {"bsonType": "string", "minLength": 1},
                "requested_amount": {"bsonType": NUMBER_TYPES, "minimum": 0},
                "term_months": {"bsonType": ["int", "long"], "minimum": 1},
                "status": {"enum": APPLICATION_STATUSES},
                "disbursement_status": {
                    "enum": ["not_started", "pending", "executed", "failed", "cancelled"]
                },
                "preferred_disbursement_method": {
                    "oneOf": [{"enum": [None]}, {"enum": SETTLEMENT_METHODS}]
                },
                "disbursement_method": {
                    "oneOf": [{"enum": [None]}, {"enum": SETTLEMENT_METHODS}]
                },
                "internal_notes": {"oneOf": [{"enum": ["", None]}, ENCRYPTED_BSON]},
                "purpose": {"oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]},
                "ai_recommendation": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_BSON]
                },
                "officer_notes": {"oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]},
                "rejection_reason": {"oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]},
                "missing_documents_reason": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]
                },
                "disbursement_reference": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]
                },
                "eth_disbursement_raw_transaction": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]
                },
                "disbursement_error": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]
                },
                "eth_disbursement_recovery_history": {
                    "bsonType": "array"
                },
                "legal_hold_reason": {
                    "oneOf": [{"enum": ["", None]}, ENCRYPTED_STRING]
                },
                "retention_policy_version": {"bsonType": "string", "minLength": 1},
                "retention_expires_at": {"bsonType": "date"},
                "legal_hold": {"bsonType": "bool"},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        }
    },
    RepaymentSchedule.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "loan_id",
                "customer_id",
                "principal_centavos",
                "total_amount_centavos",
                "status",
                "installments",
                "accounting_version",
                "created_at",
            ],
            "properties": {
                "loan_id": {"bsonType": "string", "minLength": 1},
                "customer_id": {"bsonType": "string", "minLength": 1},
                "principal_centavos": {"bsonType": ["int", "long"], "minimum": 0},
                "total_amount_centavos": {"bsonType": ["int", "long"], "minimum": 0},
                "status": {"enum": SCHEDULE_STATUSES},
                "installments": ENCRYPTED_BSON,
                "accounting_version": {"bsonType": ["int", "long"], "minimum": 0},
                "created_at": {"bsonType": "date"},
            },
        }
    },
    LoanPayment.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "loan_id",
                "customer_id",
                "installment_number",
                "amount_centavos",
                "payment_method",
                "payment_status",
                "reference_search_index",
                "timing_status",
                "scope_officer_id",
                "loan_disbursed",
                "recorded_at",
            ],
            "properties": {
                "loan_id": {"bsonType": "string", "minLength": 1},
                "customer_id": {"bsonType": "string", "minLength": 1},
                "installment_number": {"bsonType": ["int", "long"], "minimum": 0},
                "amount_centavos": {"bsonType": ["int", "long"], "minimum": 1},
                "payment_method": {"enum": PAYMENT_METHODS},
                "payment_status": {"enum": PAYMENT_STATUSES},
                "reference": {"oneOf": [{"enum": [""]}, ENCRYPTED_STRING]},
                "notes": {"oneOf": [{"enum": [""]}, ENCRYPTED_STRING]},
                "failure_reason": {
                    "oneOf": [{"enum": [""]}, ENCRYPTED_STRING]
                },
                "blockchain_sync_error": {
                    "oneOf": [{"enum": [""]}, ENCRYPTED_STRING]
                },
                "reference_search_index": {
                    "bsonType": "string",
                    "pattern": "^$|^[0-9a-f]{64}$",
                },
                "timing_status": {"enum": ["on_time", "late", "payoff", "unknown"]},
                "scope_officer_id": {"bsonType": "string"},
                "loan_disbursed": {"bsonType": "bool"},
                "recorded_at": {"bsonType": "date"},
            },
        }
    },
    BlockchainTransaction.collection_name: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "contract_name",
                "method",
                "loan_id",
                "action",
                "status",
                "idempotency_key",
                "created_at",
            ],
            "properties": {
                "contract_name": {"bsonType": "string"},
                "method": {"bsonType": "string"},
                "loan_id": {"bsonType": "string"},
                "action": {"bsonType": "string"},
                "status": {"enum": ["pending", "confirmed", "failed"]},
                "idempotency_key": {"bsonType": "string", "minLength": 1},
                "error": {"oneOf": [{"enum": [""]}, ENCRYPTED_STRING]},
                "details": {"bsonType": "object"},
                "created_at": {"bsonType": "date"},
            },
        }
    },
}

INVENTORY_CONFIG = {
    LoanProduct.collection_name: {
        "required": ["name", "code", "created_at", "updated_at"],
        "sensitive": LoanProduct.encrypted_fields,
        "unique": ["code"],
    },
    LoanApplication.collection_name: {
        "required": ["customer_id", "product_id", "status", "created_at", "updated_at"],
        "sensitive": LoanApplication.encrypted_fields,
        "unique": ["disbursement_idempotency_key"],
        "statuses": ("status", set(APPLICATION_STATUSES)),
        "metadata": ["retention_policy_version", "retention_expires_at", "legal_hold"],
        "enums": (
            ("preferred_disbursement_method", set(SETTLEMENT_METHODS), True),
            ("disbursement_method", set(SETTLEMENT_METHODS), True),
        ),
    },
    RepaymentSchedule.collection_name: {
        "required": ["loan_id", "customer_id", "installments", "created_at"],
        "sensitive": RepaymentSchedule.encrypted_fields,
        "unique": ["loan_id"],
        "statuses": ("status", set(SCHEDULE_STATUSES)),
        "metadata": ["principal_centavos", "total_amount_centavos", "accounting_version"],
    },
    LoanPayment.collection_name: {
        "required": ["loan_id", "customer_id", "payment_method", "recorded_at"],
        "sensitive": LoanPayment.encrypted_fields,
        "unique": ["idempotency_key", "reference_fingerprint", "eth_tx_hash"],
        "statuses": ("payment_status", set(PAYMENT_STATUSES)),
        "enums": (("payment_method", set(PAYMENT_METHODS), False),),
        "metadata": [
            "amount_centavos",
            "reference_search_index",
            "timing_status",
            "scope_officer_id",
            "loan_disbursed",
        ],
    },
    BlockchainTransaction.collection_name: {
        "required": ["loan_id", "action", "status", "idempotency_key", "created_at"],
        "sensitive": BlockchainTransaction.encrypted_fields,
        "unique": ["idempotency_key"],
        "statuses": ("status", {"pending", "confirmed", "failed"}),
    },
}


def install_loan_validators():
    """Install strict validators only after inventory/backfill is clean."""
    if not getattr(settings, "FIELD_ENCRYPTION_KEY", ""):
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is required before installing Loans validators"
        )
    for collection_name, validator in LOAN_VALIDATORS.items():
        settings.MONGODB.command(
            "collMod",
            collection_name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )


def loan_data_inventory(limit=10_000):
    """Return a bounded, count-only inventory without exposing record values."""
    limit = max(1, int(limit))
    result = {"limit": limit, "collections": {}, "complete": True}
    for collection_name, config in INVENTORY_CONFIG.items():
        collection = settings.MONGODB[collection_name]
        total = collection.count_documents({})
        rows = list(collection.find({}).sort("_id", 1).limit(limit))
        counts = {
            "total": total,
            "scanned": len(rows),
            "truncated": total > len(rows),
            "missing_required": 0,
            "missing_metadata": 0,
            "invalid_status": 0,
            "invalid_enum": 0,
            "plaintext_sensitive": 0,
            "non_primary_ciphertext": 0,
            "duplicate_unique_values": 0,
        }
        seen = {field: set() for field in config.get("unique", ())}
        duplicates = {field: set() for field in config.get("unique", ())}
        for raw in rows:
            if any(field not in raw or raw.get(field) is None for field in config["required"]):
                counts["missing_required"] += 1
            if any(field not in raw for field in config.get("metadata", ())):
                counts["missing_metadata"] += 1
            status_config = config.get("statuses")
            if status_config and raw.get(status_config[0]) not in status_config[1]:
                counts["invalid_status"] += 1
            for field, allowed, nullable in config.get("enums", ()):
                value = raw.get(field)
                if value in (None, "") and nullable:
                    continue
                if value not in allowed:
                    counts["invalid_enum"] += 1
            for field in config.get("sensitive", ()):
                value = raw.get(field)
                if value in (None, ""):
                    continue
                if not is_encrypted_value(value):
                    counts["plaintext_sensitive"] += 1
                elif not is_primary_encrypted_value(value):
                    counts["non_primary_ciphertext"] += 1
            for field in config.get("unique", ()):
                value = raw.get(field)
                if value in (None, ""):
                    continue
                if value in seen[field]:
                    duplicates[field].add(value)
                seen[field].add(value)
        counts["duplicate_unique_values"] = sum(
            len(values) for values in duplicates.values()
        )
        result["collections"][collection_name] = counts
        if counts["truncated"] or any(
            counts[key]
            for key in (
                "missing_required",
                "missing_metadata",
                "invalid_status",
                "invalid_enum",
                "plaintext_sensitive",
                "non_primary_ciphertext",
                "duplicate_unique_values",
            )
        ):
            result["complete"] = False
    return result


def _payment_timing(schedule, raw):
    number = int(raw.get("installment_number", 0) or 0)
    if number == 0:
        return "payoff"
    installment = schedule.get_installment(number) if schedule else None
    due_date = installment.get("due_date") if installment else None
    recorded_at = raw.get("recorded_at")
    if not due_date or not recorded_at:
        return "unknown"
    return "on_time" if recorded_at.date() <= due_date.date() else "late"


def prepare_loan_backfill(collection_name, raw):
    """Build a deterministic update for one legacy Loans document."""
    protected = {}
    config = INVENTORY_CONFIG[collection_name]
    for field in config.get("sensitive", ()):
        if field in raw and raw.get(field) not in (None, ""):
            protected[field] = reencrypt_value(raw[field])

    if collection_name == RepaymentSchedule.collection_name:
        schedule = RepaymentSchedule.from_dict(deepcopy(raw))
        protected.update(
            {
                "principal_centavos": schedule.principal_centavos,
                "monthly_payment_centavos": schedule.monthly_payment_centavos,
                "total_amount_centavos": schedule.total_amount_centavos,
                "total_interest_centavos": schedule.total_interest_centavos,
                "accounting_version": schedule.accounting_version,
            }
        )
    elif collection_name == LoanApplication.collection_name:
        created_at = raw.get("created_at")
        protected.update(
            {
                "retention_policy_version": raw.get("retention_policy_version")
                or getattr(settings, "LOAN_RETENTION_POLICY_VERSION", "2026-08-15-v1"),
                "retention_expires_at": raw.get("retention_expires_at")
                or created_at + timedelta(days=int(getattr(settings, "LOAN_RETENTION_DAYS", 2555))),
                "legal_hold": bool(raw.get("legal_hold", False)),
            }
        )
        history = []
        for entry in raw.get("eth_disbursement_recovery_history", []) or []:
            item = deepcopy(entry)
            if item.get("reason") not in (None, ""):
                item["reason"] = reencrypt_value(item["reason"])
            history.append(item)
        if history:
            protected["eth_disbursement_recovery_history"] = history
    elif collection_name == LoanPayment.collection_name:
        payment = LoanPayment.from_dict(deepcopy(raw))
        schedule = RepaymentSchedule.find_by_loan(payment.loan_id)
        application = LoanApplication.find_by_id(payment.loan_id)
        protected.update(
            {
                "amount_centavos": to_centavos(payment.amount, "amount"),
                "reference_search_index": LoanPayment.blind_index_reference(
                    payment.reference
                ),
                "timing_status": _payment_timing(schedule, raw),
                "scope_officer_id": str(application.assigned_officer or "")
                if application
                else "",
                "loan_disbursed": bool(
                    application
                    and application.status in {"disbursed", "completed", "written_off"}
                ),
            }
        )
    return protected
