import json
import logging
from datetime import datetime, timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from notifications.ownership import (
    build_notification_owner_query_from_values,
    notification_group_name,
    notification_owner_identity,
)

logger = logging.getLogger("notifications")


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")

        if (
            not user
            or isinstance(user, AnonymousUser)
            or not getattr(user, "is_authenticated", False)
        ):
            await self.close(code=4001)
            return

        self.user_id, self.user_type = notification_owner_identity(user)
        self.user_group = notification_group_name(self.user_id, self.user_type)
        if not self.user_group:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.user_group, self.channel_name)

        await self.accept()
        logger.info(
            "WebSocket connected: user_type=%s user=%s",
            self.user_type,
            self.user_id,
        )

        unread_count = await self.get_unread_count(user)
        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection_established",
                    "data": {"unread_count": unread_count},
                }
            )
        )

    async def disconnect(self, close_code):
        if hasattr(self, "user_group"):
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
            logger.info(
                "WebSocket disconnected: user_type=%s user=%s code=%s",
                self.user_type,
                self.user_id,
                close_code,
            )

    async def receive(self, text_data):
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
                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "mark_read_response",
                            "data": {
                                "success": success,
                                "notification_id": notification_id,
                            },
                        }
                    )
                )
            else:
                await self.send_error("unsupported_action", "Unsupported action")
        except json.JSONDecodeError:
            await self.send_error("invalid_json", "Invalid JSON")

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

    @database_sync_to_async
    def get_unread_count(self, user):
        from notifications.models.notification import Notification, get_db
        from notifications.views.notification_views import (
            _build_notification_owner_query,
        )

        db = get_db()
        collection = db[Notification.collection_name]
        unread_query = _build_notification_owner_query(user)
        unread_query["status"] = {"$nin": ["read"]}
        return collection.count_documents(unread_query)

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from bson import ObjectId

        from notifications.models.notification import Notification, get_db

        try:
            db = get_db()
            collection = db[Notification.collection_name]
            owner_query = build_notification_owner_query_from_values(
                self.user_id, self.user_type
            )
            result = collection.update_one(
                {"_id": ObjectId(notification_id), **owner_query},
                {"$set": {"status": "read", "read_at": datetime.now(timezone.utc)}},
            )
            return result.modified_count > 0
        except Exception as exc:  # noqa: BLE001
            logger.error("Error marking notification read: %s", exc)
            return False
