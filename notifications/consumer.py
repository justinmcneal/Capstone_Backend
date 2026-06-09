import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from datetime import datetime, timezone

logger = logging.getLogger("notifications")


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")

        if not user or isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
            await self.close(code=4001)
            return

        self.user_id = str(getattr(user, "customer_id", "") or getattr(user, "officer_id", ""))
        if not self.user_id:
            await self.close(code=4001)
            return

        self.user_group = f"notifications_{self.user_id}"

        await self.channel_layer.group_add(
            self.user_group,
            self.channel_name
        )

        await self.accept()
        logger.info(f"WebSocket connected: user={self.user_id}")

        unread_count = await self.get_unread_count(user)
        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "data": {"unread_count": unread_count}
        }))

    async def disconnect(self, close_code):
        if hasattr(self, "user_group"):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )
            logger.info(f"WebSocket disconnected: user={self.user_id}, code={close_code}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get("action")

            if action == "ping":
                await self.send(text_data=json.dumps({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
            elif action == "mark_read":
                notification_id = data.get("notification_id")
                success = await self.mark_notification_read(notification_id)
                await self.send(text_data=json.dumps({
                    "type": "mark_read_response",
                    "success": success,
                    "notification_id": notification_id
                }))
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Invalid JSON"
            }))

    async def notification_message(self, event):
        notification_data = event.get("data", {})
        await self.send(text_data=json.dumps({
            "type": "notification",
            "data": notification_data
        }))

    @database_sync_to_async
    def get_unread_count(self, user):
        from notifications.models.notification import get_db, Notification
        from notifications.views.notification_views import _build_notification_owner_query

        db = get_db()
        collection = db[Notification.collection_name]
        unread_query = _build_notification_owner_query(user)
        unread_query["status"] = {"$nin": ["read"]}
        return collection.count_documents(unread_query)

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from bson import ObjectId
        from notifications.models.notification import get_db, Notification

        try:
            db = get_db()
            collection = db[Notification.collection_name]
            result = collection.update_one(
                {"_id": ObjectId(notification_id), "user_id": self.user_id},
                {"$set": {"status": "read", "read_at": datetime.now(timezone.utc)}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error marking notification read: {e}")
            return False