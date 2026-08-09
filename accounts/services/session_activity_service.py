"""Consistent login activity and active-session metadata handling."""

import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models.activity import ActiveSession, LoginActivity
from accounts.services.security_event_service import SecurityEventService
from accounts.utils.request_utils import get_client_ip

logger = logging.getLogger("authentication")


class SessionActivityService:
    """Record authentication activity without making telemetry an auth dependency."""

    DEFAULT_HEARTBEAT_SECONDS = 300

    @staticmethod
    def _request_metadata(request):
        return (
            get_client_ip(request),
            request.META.get("HTTP_USER_AGENT", ""),
        )

    @classmethod
    def record_login_activity(
        cls,
        *,
        role,
        status,
        request,
        user=None,
        email="",
        failure_reason="",
    ):
        """Persist a normalized success/failure activity row for every role."""
        try:
            ip_address, device_info = cls._request_metadata(request)
            LoginActivity(
                user_id=str(user.id) if user and getattr(user, "id", None) else None,
                email=getattr(user, "email", "") if user else str(email or ""),
                role=role,
                status=status,
                ip_address=ip_address,
                device_info=device_info,
                failure_reason=failure_reason,
            ).save()
            return True
        except Exception:
            logger.exception("Failed to record %s login activity for role %s", status, role)
            return False

    @classmethod
    def complete_successful_login(cls, *, user, role, tokens, request):
        """Attach request metadata to the token-created session and record activity."""
        try:
            session_id = str(RefreshToken(tokens["refresh"]).get("session_id") or "")
            if not session_id:
                return False
            now = datetime.now(timezone.utc)
            ip_address, device_info = cls._request_metadata(request)
            ActiveSession.update_many(
                {
                    "user_id": str(user.id),
                    "role": role,
                    "session_id": session_id,
                    "is_active": True,
                },
                {
                    "$set": {
                        "ip_address": ip_address,
                        "device_info": device_info,
                        "last_active": now,
                    }
                },
            )
            cls.record_login_activity(
                role=role,
                status="SUCCESS",
                request=request,
                user=user,
            )
            SecurityEventService.record_new_device_login_if_first(
                user=user,
                user_type=role,
                session_id=session_id,
                ip_address=ip_address,
                device_info=device_info,
            )
            return True
        except Exception:
            logger.exception("Failed to complete successful login activity for %s", role)
            return False

    @classmethod
    def touch_active_session(cls, *, user_id, role, session_id, request=None):
        """Update last_active at a bounded frequency to avoid per-request DB writes."""
        if not user_id or not role or not session_id:
            return False
        interval = int(
            getattr(
                settings,
                "SESSION_ACTIVITY_HEARTBEAT_SECONDS",
                cls.DEFAULT_HEARTBEAT_SECONDS,
            )
        )
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=max(interval, 0))
        updates = {"last_active": now}
        if request is not None:
            ip_address, device_info = cls._request_metadata(request)
            updates.update({"ip_address": ip_address, "device_info": device_info})
        try:
            result = settings.MONGODB[ActiveSession.collection_name].update_one(
                {
                    "user_id": str(user_id),
                    "role": role,
                    "session_id": str(session_id),
                    "is_active": True,
                    "$or": [
                        {"last_active": {"$exists": False}},
                        {"last_active": None},
                        {"last_active": {"$lte": cutoff}},
                    ],
                },
                {"$set": updates},
            )
            return result.modified_count == 1
        except Exception:
            logger.exception("Failed to update session activity heartbeat")
            return False
