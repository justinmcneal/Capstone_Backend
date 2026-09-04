"""Metadata-only, retention-bounded audit events for AI tool execution."""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from django.conf import settings
from pymongo import ASCENDING, DESCENDING


class AIActivityEvent:
    collection_name = "ai_activity_events"
    schema_version = 1
    allowed_outcomes: ClassVar[set[str]] = {
        "success",
        "execution_error",
        "validation_error",
        "rate_limited_minute",
        "rate_limited_hour",
    }
    allowed_tools: ClassVar[set[str]] = {
        "get_profile_status",
        "get_document_status",
        "get_loan_status",
        "get_repayment_schedule",
        "get_next_payment_due",
        "get_payment_history",
        "get_loan_products",
        "get_application_readiness",
        "get_customer_dashboard",
        "get_notification_status",
        "unknown",
    }

    @staticmethod
    def _subject_index(customer_id):
        key = str(getattr(settings, "FIELD_ENCRYPTION_KEY", "") or settings.SECRET_KEY)
        return hmac.new(
            key.encode("utf-8"),
            str(customer_id).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def record_tool_call(
        cls,
        *,
        customer_id,
        tool_name,
        success,
        outcome,
        duration_ms,
        cost,
        request_id=None,
    ):
        if outcome not in cls.allowed_outcomes:
            raise ValueError("Unsupported AI tool audit outcome")
        if tool_name not in cls.allowed_tools:
            raise ValueError("Unsupported AI tool audit name")
        now = datetime.now(timezone.utc)
        retention_days = int(
            getattr(settings, "AI_ASSISTANT_AUDIT_RETENTION_DAYS", 90)
        )
        document = {
            "event_id": str(uuid.uuid4()),
            "event_schema_version": cls.schema_version,
            "subject_index": cls._subject_index(customer_id),
            "request_id": str(request_id) if request_id else None,
            "tool": str(tool_name),
            "success": bool(success),
            "outcome": outcome,
            "duration_ms": max(0, int(duration_ms)),
            "cost": max(1, int(cost)),
            "created_at": now,
            "retention_expires_at": now + timedelta(days=retention_days),
        }
        settings.MONGODB[cls.collection_name].insert_one(document)
        return document

    @classmethod
    def recent_for_customer(cls, customer_id, limit=10):
        bounded_limit = min(max(int(limit), 1), 100)
        cursor = settings.MONGODB[cls.collection_name].find(
            {"subject_index": cls._subject_index(customer_id)},
            {
                "_id": 0,
                "event_id": 1,
                "request_id": 1,
                "tool": 1,
                "success": 1,
                "outcome": 1,
                "duration_ms": 1,
                "cost": 1,
                "created_at": 1,
            },
        ).sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(bounded_limit)
        return list(cursor)

    @classmethod
    def create_indexes(cls):
        collection = settings.MONGODB[cls.collection_name]
        collection.create_index("event_id", name="ai_activity_event_id", unique=True)
        collection.create_index(
            [("subject_index", ASCENDING), ("created_at", DESCENDING)],
            name="ai_activity_by_subject",
        )
        collection.create_index(
            "retention_expires_at",
            name="ai_activity_retention_ttl",
            expireAfterSeconds=0,
        )

    @classmethod
    def create_validator(cls):
        validator = {
            "$jsonSchema": {
                "bsonType": "object",
                "required": [
                    "event_id",
                    "event_schema_version",
                    "subject_index",
                    "tool",
                    "success",
                    "outcome",
                    "duration_ms",
                    "cost",
                    "created_at",
                    "retention_expires_at",
                ],
                "properties": {
                    "event_id": {"bsonType": "string"},
                    "event_schema_version": {"enum": [cls.schema_version]},
                    "subject_index": {
                        "bsonType": "string",
                        "pattern": "^[0-9a-f]{64}$",
                    },
                    "request_id": {"bsonType": ["string", "null"]},
                    "tool": {"enum": sorted(cls.allowed_tools)},
                    "success": {"bsonType": "bool"},
                    "outcome": {"enum": sorted(cls.allowed_outcomes)},
                    "duration_ms": {
                        "bsonType": ["int", "long"],
                        "minimum": 0,
                    },
                    "cost": {"bsonType": ["int", "long"], "minimum": 1},
                    "created_at": {"bsonType": "date"},
                    "retention_expires_at": {"bsonType": "date"},
                },
            }
        }
        settings.MONGODB.command(
            "collMod",
            cls.collection_name,
            validator=validator,
            validationLevel="strict",
            validationAction="error",
        )
