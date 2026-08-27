import logging
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import ClassVar

from bson import ObjectId
from django.conf import settings
from django.core.cache import cache
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from accounts.models.consent import Consent, ConsentEvent

logger = logging.getLogger("consent")


class ConsentPolicyError(ValueError):
    """Raised when a consent grant does not identify the deployed policy."""


class ConsentRoleError(ValueError):
    """Raised when a non-customer attempts to own customer consent."""


class ConsentMutationBusyError(RuntimeError):
    """Raised when another consent decision is being recorded for the user."""


class ConsentService:
    """Manage authoritative consent events and the current-state projection."""

    SUPPORTED_USER_TYPES: ClassVar[set[str]] = {"customer"}

    @staticmethod
    def current_policy():
        return {
            "policy_id": str(
                getattr(settings, "CONSENT_POLICY_ID", "privacy-and-ai-consent")
            ),
            "consent_version": str(
                getattr(settings, "CONSENT_POLICY_VERSION", "2026-08-01")
            ),
            "effective_at": str(
                getattr(
                    settings,
                    "CONSENT_POLICY_EFFECTIVE_AT",
                    "2026-08-01T00:00:00Z",
                )
            ),
            "document_uri": str(
                getattr(
                    settings,
                    "CONSENT_POLICY_DOCUMENT_URI",
                    "docs/feats/PRIVACY_POLICY.md",
                )
            ),
            "content_sha256": str(
                getattr(settings, "CONSENT_POLICY_CONTENT_SHA256", "")
            ),
        }

    @classmethod
    def _normalize_identity(cls, user_id, user_type):
        normalized_type = str(user_type or "").strip().lower()
        if normalized_type not in cls.SUPPORTED_USER_TYPES:
            raise ConsentRoleError("Consent preferences are customer-only")
        if isinstance(user_id, ObjectId):
            return user_id, normalized_type
        if not ObjectId.is_valid(str(user_id)):
            raise ValueError("Invalid consent user identifier")
        return ObjectId(str(user_id)), normalized_type

    @staticmethod
    @contextmanager
    def _mutation_guard(user_id, user_type):
        collection = settings.MONGODB["account_security_guards"]
        guard_id = f"consent:{user_type}:{user_id}"
        owner = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        try:
            guard = collection.find_one_and_update(
                {
                    "_id": guard_id,
                    "$or": [
                        {"lease_until": {"$lte": now}},
                        {"lease_until": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "lease_owner": owner,
                        "lease_until": now + timedelta(seconds=15),
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise ConsentMutationBusyError from exc
        if not guard or guard.get("lease_owner") != owner:
            raise ConsentMutationBusyError
        try:
            yield
        finally:
            collection.update_one(
                {"_id": guard_id, "lease_owner": owner},
                {"$unset": {"lease_owner": ""}, "$set": {"lease_until": now}},
            )

    @classmethod
    def _authoritative_state(cls, user_id, user_type):
        event = ConsentEvent.latest_for_user(user_id, user_type)
        if event:
            return {
                "data_consent": bool(event.data_consent),
                "ai_consent": bool(event.ai_consent),
                "consent_version": event.consent_version,
                "revision": int(event.revision),
                "recorded_at": event.recorded_at,
                "event_id": event.event_id,
            }

        legacy = Consent.find_by_user(user_id, user_type)
        if legacy:
            return {
                "data_consent": bool(legacy.data_consent),
                "ai_consent": bool(legacy.ai_consent),
                "consent_version": legacy.consent_version,
                "revision": int(getattr(legacy, "revision", 0)),
                "recorded_at": legacy.updated_at,
                "event_id": None,
            }
        return {
            "data_consent": False,
            "ai_consent": False,
            "consent_version": None,
            "revision": 0,
            "recorded_at": None,
            "event_id": None,
        }

    @classmethod
    def _validate_policy_grant(cls, updates, consent_version):
        if not any(value is True for value in updates.values()):
            return
        current_version = cls.current_policy()["consent_version"]
        if not consent_version:
            raise ConsentPolicyError(
                "consent_version is required when granting consent"
            )
        if str(consent_version) != current_version:
            raise ConsentPolicyError(
                "Consent policy has changed. Review and accept the current version."
            )

    @classmethod
    def _record_decision(
        cls,
        *,
        user_id,
        user_type,
        updates,
        consent_version=None,
        ip_address="",
        require_existing=False,
    ):
        user_id, user_type = cls._normalize_identity(user_id, user_type)
        updates = {
            key: bool(value)
            for key, value in updates.items()
            if key in {"data_consent", "ai_consent"}
        }
        if not updates:
            raise ValueError("At least one consent field must be provided")
        cls._validate_policy_grant(updates, consent_version)
        policy = cls.current_policy()

        with cls._mutation_guard(user_id, user_type):
            before = cls._authoritative_state(user_id, user_type)
            if (
                require_existing
                and before["revision"] == 0
                and before["event_id"] is None
                and not Consent.find_by_user(user_id, user_type)
            ):
                raise ValueError("No consent record found for user")

            after = {
                "data_consent": updates.get("data_consent", before["data_consent"]),
                "ai_consent": updates.get("ai_consent", before["ai_consent"]),
            }
            if after["ai_consent"] and not after["data_consent"]:
                raise ConsentPolicyError("AI consent requires data consent")

            changed_fields = [field for field in after if after[field] != before[field]]
            accepted_version = (
                policy["consent_version"]
                if any(value is True for value in updates.values())
                else before["consent_version"] or policy["consent_version"]
            )
            revision = int(before["revision"]) + 1
            if before["consent_version"] != accepted_version and not changed_fields:
                action = "consent_reconfirmed"
            elif any(before[field] and not after[field] for field in after):
                action = "consent_revoked"
            elif any(not before[field] and after[field] for field in after):
                action = "consent_granted"
            else:
                action = "consent_updated"

            recorded_at = datetime.now(timezone.utc)
            event_id = f"{user_type}:{user_id}:{revision}"
            event = ConsentEvent(
                event_id=event_id,
                user_id=user_id,
                user_type=user_type,
                revision=revision,
                action=action,
                data_consent=after["data_consent"],
                ai_consent=after["ai_consent"],
                consent_version=accepted_version,
                policy_id=policy["policy_id"],
                policy_effective_at=policy["effective_at"],
                policy_document_uri=policy["document_uri"],
                policy_content_sha256=policy["content_sha256"],
                previous_state={
                    "data_consent": before["data_consent"],
                    "ai_consent": before["ai_consent"],
                    "consent_version": before["consent_version"],
                    "revision": before["revision"],
                },
                changed_fields=changed_fields,
                ip_address=ip_address or "",
                recorded_at=recorded_at,
            ).save()

            consent_date = recorded_at if any(after.values()) else None
            document = settings.MONGODB[Consent.collection_name].find_one_and_update(
                {"user_id": user_id, "user_type": user_type},
                {
                    "$set": {
                        **after,
                        "consent_version": accepted_version,
                        "revision": revision,
                        "consent_date": consent_date,
                        "updated_at": recorded_at,
                        "ip_address": ip_address or "",
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )

        if before["ai_consent"] and not after["ai_consent"]:
            try:
                cache.delete(f"ai_consent:{user_id}")
            except (
                Exception
            ) as exc:
                logger.warning(
                    "Consent cache invalidation failed for %s: %s", user_id, exc
                )

        consent = Consent.from_dict(document)
        consent.previous_state = event.previous_state
        consent.event_id = event.event_id
        consent.event = event
        return consent

    @classmethod
    def get_or_create_consent(cls, user_id, user_type="customer"):
        user_id, user_type = cls._normalize_identity(user_id, user_type)
        consent = Consent.find_by_user(user_id, user_type)
        if consent:
            return consent
        return cls._record_decision(
            user_id=user_id,
            user_type=user_type,
            updates={"data_consent": False, "ai_consent": False},
        )

    @classmethod
    def record_consent(
        cls,
        user_id,
        user_type,
        data_consent,
        ai_consent,
        ip_address="",
        consent_version=None,
    ):
        return cls._record_decision(
            user_id=user_id,
            user_type=user_type,
            updates={
                "data_consent": data_consent,
                "ai_consent": ai_consent,
            },
            consent_version=consent_version,
            ip_address=ip_address,
        )

    @classmethod
    def update_consent(
        cls,
        user_id,
        user_type,
        updates,
        ip_address="",
        consent_version=None,
    ):
        return cls._record_decision(
            user_id=user_id,
            user_type=user_type,
            updates=updates,
            consent_version=consent_version,
            ip_address=ip_address,
            require_existing=True,
        )

    @classmethod
    def check_ai_consent(cls, user_id, user_type="customer"):
        """Fail closed unless both current-version data and AI consent exist."""
        try:
            user_id, user_type = cls._normalize_identity(user_id, user_type)
            state = cls._authoritative_state(user_id, user_type)
            return bool(
                state["data_consent"]
                and state["ai_consent"]
                and state["consent_version"] == cls.current_policy()["consent_version"]
            )
        except Exception:
            logger.exception("AI consent check failed closed for user %s", user_id)
            return False

    @classmethod
    def check_data_consent(cls, user_id, user_type="customer"):
        try:
            user_id, user_type = cls._normalize_identity(user_id, user_type)
            state = cls._authoritative_state(user_id, user_type)
            return bool(
                state["data_consent"]
                and state["consent_version"] == cls.current_policy()["consent_version"]
            )
        except Exception:
            logger.exception("Data consent check failed closed for user %s", user_id)
            return False

    @classmethod
    def get_consent_status(cls, user_id, user_type="customer"):
        user_id, user_type = cls._normalize_identity(user_id, user_type)
        state = cls._authoritative_state(user_id, user_type)
        current_policy = cls.current_policy()
        version_current = state["consent_version"] == current_policy["consent_version"]
        has_record = (
            state["event_id"] is not None
            or Consent.find_by_user(user_id, user_type) is not None
        )
        return {
            "data_consent": state["data_consent"],
            "ai_consent": state["ai_consent"],
            "consent_date": state["recorded_at"],
            "updated_at": state["recorded_at"],
            "consent_version": state["consent_version"],
            "current_policy": current_policy,
            "requires_reconsent": bool(
                has_record
                and any((state["data_consent"], state["ai_consent"]))
                and not version_current
            ),
            "can_access_ai": bool(
                state["data_consent"] and state["ai_consent"] and version_current
            ),
            "has_consent_record": has_record,
            "revision": state["revision"],
        }

    @classmethod
    def get_consent_statuses(cls, user_ids, user_type="customer"):
        """Resolve consent status for many customers with set-based reads."""
        normalized_type = str(user_type or "").strip().lower()
        if normalized_type not in cls.SUPPORTED_USER_TYPES:
            raise ConsentRoleError("Consent preferences are customer-only")

        normalized_ids = [
            cls._normalize_identity(user_id, normalized_type)[0]
            for user_id in user_ids
        ]
        events = ConsentEvent.latest_by_users(normalized_ids, normalized_type)
        ids_without_events = [
            user_id for user_id in normalized_ids if str(user_id) not in events
        ]
        legacy_records = Consent.find_by_users(
            ids_without_events, normalized_type
        )
        current_policy = cls.current_policy()
        current_version = current_policy["consent_version"]
        statuses = {}

        for user_id in normalized_ids:
            key = str(user_id)
            event = events.get(key)
            legacy = legacy_records.get(key)
            record = event or legacy
            data_consent = bool(record.data_consent) if record else False
            ai_consent = bool(record.ai_consent) if record else False
            consent_version = record.consent_version if record else None
            recorded_at = (
                event.recorded_at
                if event
                else legacy.updated_at
                if legacy
                else None
            )
            has_record = record is not None
            version_current = consent_version == current_version
            statuses[key] = {
                "data_consent": data_consent,
                "ai_consent": ai_consent,
                "consent_date": recorded_at,
                "updated_at": recorded_at,
                "consent_version": consent_version,
                "current_policy": current_policy,
                "requires_reconsent": bool(
                    has_record
                    and any((data_consent, ai_consent))
                    and not version_current
                ),
                "can_access_ai": bool(
                    data_consent and ai_consent and version_current
                ),
                "has_consent_record": has_record,
                "revision": int(record.revision) if record else 0,
            }
        return statuses

    @classmethod
    def get_consent_history(cls, user_id, user_type="customer", limit=100):
        user_id, user_type = cls._normalize_identity(user_id, user_type)
        return ConsentEvent.find_by_user(user_id, user_type, limit=limit)
