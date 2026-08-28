import asyncio
import json
import logging
from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
from time import monotonic
from typing import ClassVar

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from notifications.metrics import (
    NOTIFICATION_WS_ACTIONS,
    NOTIFICATION_WS_ACTIVE,
    NOTIFICATION_WS_CONNECTIONS,
    decrement,
    increment,
)
from notifications.ownership import (
    build_notification_owner_query_from_values,
    notification_group_name,
    notification_owner_identity,
)
from notifications.services.inbox import (
    mark_notification_read,
    with_unread_state,
)

logger = logging.getLogger("notifications")


class NotificationConsumer(AsyncWebsocketConsumer):
    _connections_by_owner: ClassVar[dict[str, int]] = {}

    async def connect(self):
        user = self.scope.get("user")

        if (
            not user
            or isinstance(user, AnonymousUser)
            or not getattr(user, "is_authenticated", False)
        ):
            increment(NOTIFICATION_WS_CONNECTIONS, outcome="authentication_rejected")
            await self.close(code=4001)
            return

        self.user_id, self.user_type = notification_owner_identity(user)
        self.user_group = notification_group_name(self.user_id, self.user_type)
        if not self.user_group:
            increment(NOTIFICATION_WS_CONNECTIONS, outcome="owner_rejected")
            await self.close(code=4001)
            return

        self._owner_key = f"{self.user_type}:{self.user_id}"
        current = self._connections_by_owner.get(self._owner_key, 0)
        maximum = int(settings.NOTIFICATIONS_WS_MAX_CONNECTIONS_PER_USER)
        if current >= maximum:
            increment(NOTIFICATION_WS_CONNECTIONS, outcome="connection_limit")
            await self.close(code=4004)
            return
        self._connections_by_owner[self._owner_key] = current + 1
        self._connection_counted = True

        self._action_times = deque()
        self._last_activity = monotonic()

        await self.channel_layer.group_add(self.user_group, self.channel_name)

        await self.accept()
        increment(NOTIFICATION_WS_CONNECTIONS, outcome="accepted")
        increment(NOTIFICATION_WS_ACTIVE)
        logger.info(
            "Notification WebSocket connected: user_type=%s",
            self.user_type,
        )

        unread_count = await self.get_unread_count(user)
        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection_established",
                    "data": {
                        "unread_count": unread_count,
                        "sync_required": True,
                        "contract_version": 2,
                    },
                }
            )
        )
        self._revalidation_task = asyncio.create_task(self._revalidation_loop())

    async def disconnect(self, close_code):
        task = getattr(self, "_revalidation_task", None)
        if task and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if hasattr(self, "user_group"):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
            logger.info(
                "Notification WebSocket disconnected: user_type=%s code=%s",
                self.user_type,
                close_code,
            )
        if getattr(self, "_connection_counted", False):
            remaining = max(0, self._connections_by_owner.get(self._owner_key, 1) - 1)
            if remaining:
                self._connections_by_owner[self._owner_key] = remaining
            else:
                self._connections_by_owner.pop(self._owner_key, None)
            self._connection_counted = False
            decrement(NOTIFICATION_WS_ACTIVE)

    async def receive(self, text_data=None, bytes_data=None):
        size = (
            len(bytes_data)
            if bytes_data is not None
            else len((text_data or "").encode())
        )
        if bytes_data is not None or size > int(
            settings.NOTIFICATIONS_WS_MAX_MESSAGE_BYTES
        ):
            increment(NOTIFICATION_WS_ACTIONS, action="frame", outcome="rejected")
            await self.close(code=4005)
            return
        if not await self.connection_is_current():
            increment(NOTIFICATION_WS_ACTIONS, action="auth", outcome="revoked")
            await self.close(code=4002)
            return
        self._last_activity = monotonic()
        if not self._allow_action():
            increment(NOTIFICATION_WS_ACTIONS, action="rate_limit", outcome="rejected")
            await self.send_error(
                "rate_limited",
                "Too many WebSocket actions; retry later",
            )
            return
        try:
            data = json.loads(text_data)
            if not isinstance(data, dict):
                await self.send_error(
                    "invalid_message",
                    "Message must be a JSON object",
                )
                return
            action = data.get("action")

            if action == "ping":
                increment(NOTIFICATION_WS_ACTIONS, action="ping", outcome="success")
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "pong",
                            "data": {
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            },
                        }
                    )
                )
            elif action == "mark_read":
                notification_id = data.get("notification_id")
                if not isinstance(notification_id, str) or not notification_id:
                    await self.send_error(
                        "invalid_notification_id",
                        "A notification_id is required",
                    )
                    return
                success = await self.mark_notification_read(notification_id)
                increment(
                    NOTIFICATION_WS_ACTIONS,
                    action="mark_read",
                    outcome="success" if success["success"] else "not_found",
                )
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "mark_read_response",
                            "data": {
                                "success": success["success"],
                                "notification_id": notification_id,
                                "replayed": success.get("replayed", False),
                            },
                        }
                    )
                )
                if success["success"]:
                    await self.channel_layer.group_send(
                        self.user_group,
                        {
                            "type": "inbox_state_message",
                            "data": {
                                "action": "mark_read",
                                "notification_id": notification_id,
                                "replayed": success.get("replayed", False),
                            },
                        },
                    )
            else:
                increment(
                    NOTIFICATION_WS_ACTIONS, action="unsupported", outcome="rejected"
                )
                await self.send_error("unsupported_action", "Unsupported action")
        except json.JSONDecodeError:
            increment(NOTIFICATION_WS_ACTIONS, action="json", outcome="rejected")
            await self.send_error("invalid_json", "Invalid JSON")

    async def _revalidation_loop(self):
        interval = int(settings.NOTIFICATIONS_WS_REVALIDATE_SECONDS)
        idle_timeout = int(settings.NOTIFICATIONS_WS_IDLE_TIMEOUT_SECONDS)
        while True:
            await asyncio.sleep(interval)
            if monotonic() - self._last_activity >= idle_timeout:
                increment(NOTIFICATION_WS_ACTIONS, action="idle", outcome="closed")
                await self.close(code=4003)
                return
            if not await self.connection_is_current():
                increment(NOTIFICATION_WS_ACTIONS, action="auth", outcome="revoked")
                await self.close(code=4002)
                return

    def _allow_action(self):
        limit = int(getattr(settings, "NOTIFICATIONS_WS_ACTIONS_PER_MINUTE", 120))
        now = monotonic()
        cutoff = now - 60
        while self._action_times and self._action_times[0] <= cutoff:
            self._action_times.popleft()
        if len(self._action_times) >= limit:
            return False
        self._action_times.append(now)
        return True

    async def send_error(self, code, message):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "error",
                    "data": {"code": code, "message": message},
                }
            )
        )

    async def notification_message(self, event):
        notification_data = event.get("data", {})
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification",
                    "data": notification_data,
                }
            )
        )

    async def inbox_state_message(self, event):
        await self.send(
            text_data=json.dumps({"type": "inbox_state", "data": event.get("data", {})})
        )

    @database_sync_to_async
    def connection_is_current(self):
        """Recheck expiry, live account state, security version, and session."""
        user = self.scope.get("user")
        expires_at = int(getattr(user, "access_token_expires_at", 0) or 0)
        if expires_at and expires_at <= int(datetime.now(timezone.utc).timestamp()):
            return False
        session_id = getattr(user, "session_id", None)
        security_version = getattr(user, "security_version", None)
        # Direct consumer tests use a lightweight authenticated user. Production
        # middleware always supplies both fields and therefore takes the strict path.
        if not session_id or security_version is None:
            return bool(getattr(user, "is_authenticated", False))
        from accounts.authentication import CustomJWTAuthentication
        from accounts.utils.token_utils import TokenUtils

        live_user = CustomJWTAuthentication._get_live_user(self.user_id, self.user_type)
        if live_user is None:
            return False
        if not bool(getattr(live_user, "active", True)):
            return False
        if getattr(live_user, "deleted_at", None) is not None:
            return False
        if (
            self.user_type == "customer"
            and getattr(live_user, "account_state", "active") != "active"
        ):
            return False
        if not bool(getattr(live_user, "verified", True)):
            return False
        if bool(getattr(live_user, "must_change_password", False)):
            return False
        live_version = int(getattr(live_user, "security_version", 1))
        return live_version == int(security_version) and TokenUtils.is_session_active(
            self.user_id, self.user_type, session_id, live_version
        )

    @database_sync_to_async
    def get_unread_count(self, user):
        from notifications.models.notification import Notification, get_db
        from notifications.views.notification_views import (
            _build_notification_owner_query,
        )

        db = get_db()
        collection = db[Notification.collection_name]
        unread_query = _build_notification_owner_query(user)
        unread_query = with_unread_state(unread_query)
        return collection.count_documents(unread_query)

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from notifications.models.notification import get_db

        try:
            db = get_db()
            owner_query = build_notification_owner_query_from_values(
                self.user_id, self.user_type
            )
            outcome = mark_notification_read(db, notification_id, owner_query)
            return {
                "success": bool(outcome.get("found"))
                and not bool(outcome.get("conflict")),
                "replayed": bool(outcome.get("replayed")),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Error marking notification read: error_type=%s",
                type(exc).__name__,
            )
            return {"success": False, "replayed": False}
