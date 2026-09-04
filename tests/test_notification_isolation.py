import asyncio
from types import SimpleNamespace

import mongomock
from asgiref.sync import async_to_sync
from channels.layers import InMemoryChannelLayer
from django.conf import settings

from accounts.utils.access_control import AccessControlMixin
from notifications.consumer import NotificationConsumer
from notifications.models.notification import Notification
from notifications.ownership import notification_group_name
from notifications.services import assignment_events
from notifications.views.notification_views import (
    NotificationClearAllView,
    NotificationDeleteView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)


def _request(user_id, role, email):
    return SimpleNamespace(
        user=SimpleNamespace(customer_id=user_id, role=role, email=email),
        query_params={},
    )


def _notification(user_id, user_type, subject):
    return Notification(
        user_id=user_id,
        user_type=user_type,
        recipient_email=f"{user_type}@example.com",
        recipient_name=subject,
        notification_type="application_assigned",
        subject=subject,
        message=subject,
        channel="in_app",
        status="sent",
    ).save()


def _allow_authenticated_role(monkeypatch):
    monkeypatch.setattr(
        AccessControlMixin,
        "require_roles",
        lambda self, request, roles, *args, **kwargs: (True, request.user),
    )


def test_http_operations_are_isolated_for_cross_role_id_collision(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    _allow_authenticated_role(monkeypatch)

    shared_id = "shared-account-id"
    admin_notification = _notification(shared_id, "admin", "Admin only")
    officer_notification = _notification(shared_id, "loan_officer", "Officer only")
    admin_request = _request(shared_id, "admin", "admin@example.com")
    officer_request = _request(shared_id, "loan_officer", "officer@example.com")

    admin_list = NotificationListView().get(admin_request)
    officer_list = NotificationListView().get(officer_request)

    assert [item["subject"] for item in admin_list.data["data"]["notifications"]] == [
        "Admin only"
    ]
    assert [item["subject"] for item in officer_list.data["data"]["notifications"]] == [
        "Officer only"
    ]
    assert (
        NotificationUnreadCountView().get(admin_request).data["data"]["unread_count"]
        == 1
    )
    assert (
        NotificationUnreadCountView().get(officer_request).data["data"]["unread_count"]
        == 1
    )

    cross_role_mark = NotificationMarkReadView().post(
        officer_request, admin_notification.id
    )
    assert cross_role_mark.status_code == 404
    assert (
        database[Notification.collection_name].find_one(
            {"_id": admin_notification._id}
        )["status"]
        == "sent"
    )

    own_mark = NotificationMarkReadView().post(officer_request, officer_notification.id)
    assert own_mark.status_code == 200

    database[Notification.collection_name].update_one(
        {"_id": officer_notification._id},
        {"$set": {"status": "sent", "is_read": False}, "$unset": {"read_at": ""}},
    )
    mark_all = NotificationMarkAllReadView().post(officer_request)
    assert mark_all.data["data"]["marked_count"] == 1
    assert (
        database[Notification.collection_name].find_one(
            {"_id": admin_notification._id}
        )["status"]
        == "sent"
    )

    cross_role_delete = NotificationDeleteView().delete(
        officer_request, admin_notification.id
    )
    assert cross_role_delete.status_code == 404

    clear_officer = NotificationClearAllView().delete(officer_request)
    assert clear_officer.data["data"]["deleted_count"] == 1
    assert (
        database[Notification.collection_name].find_one({"_id": admin_notification._id})
        is not None
    )


def test_websocket_groups_and_mark_read_are_role_isolated(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    shared_id = "shared-account-id"
    admin_notification = _notification(shared_id, "admin", "Admin only")

    admin_group = notification_group_name(shared_id, "admin")
    officer_group = notification_group_name(shared_id, "loan_officer")
    assert admin_group != officer_group

    async def exercise_groups():
        layer = InMemoryChannelLayer()
        await layer.group_add(admin_group, "admin-channel")
        await layer.group_add(officer_group, "officer-channel")
        await layer.group_send(
            admin_group,
            {"type": "notification_message", "data": {"subject": "Admin only"}},
        )

        admin_event = await layer.receive("admin-channel")
        assert admin_event["data"]["subject"] == "Admin only"
        try:
            await asyncio.wait_for(layer.receive("officer-channel"), timeout=0.05)
        except asyncio.TimeoutError:
            return
        raise AssertionError("Officer channel received the Admin event")

    async_to_sync(exercise_groups)()

    officer_consumer = NotificationConsumer()
    officer_consumer.user_id = shared_id
    officer_consumer.user_type = "loan_officer"
    marked = async_to_sync(officer_consumer.mark_notification_read)(
        admin_notification.id
    )
    assert marked == {"success": False, "replayed": False}
    assert (
        database[Notification.collection_name].find_one(
            {"_id": admin_notification._id}
        )["status"]
        == "sent"
    )


def test_assignment_events_remain_isolated_through_inbox_api(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    _allow_authenticated_role(monkeypatch)
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda *args: None,
    )

    admin = {
        "id": "admin-1",
        "user_type": "admin",
        "name": "Avery Admin",
        "email": "admin@example.com",
    }
    previous = {
        "id": "officer-1",
        "user_type": "loan_officer",
        "name": "Casey Old",
        "email": "old@example.com",
    }
    assigned = {
        "id": "officer-2",
        "user_type": "loan_officer",
        "name": "Josh New",
        "email": "new@example.com",
    }

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=admin,
        assigned_to=assigned,
        previous_assignee=previous,
        related_type="loan",
        related_id="loan-1",
    )

    expected_messages = {
        "admin-1": "You reassigned Gab Soriano's loan application from Casey Old to Josh New.",
        "officer-1": "Gab Soriano's loan application was reassigned from you to Josh New by Avery Admin.",
        "officer-2": "Gab Soriano's loan application was assigned to you by Avery Admin.",
    }
    roles = {
        "admin-1": "admin",
        "officer-1": "loan_officer",
        "officer-2": "loan_officer",
    }

    for user_id, expected_message in expected_messages.items():
        response = NotificationListView().get(
            _request(user_id, roles[user_id], f"{user_id}@example.com")
        )
        notifications = response.data["data"]["notifications"]
        assert len(notifications) == 1
        assert notifications[0]["message"] == expected_message


def test_initial_assignment_remains_isolated_through_inbox_api(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    _allow_authenticated_role(monkeypatch)
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda *args: None,
    )

    admin = {
        "id": "admin-1",
        "user_type": "admin",
        "name": "Avery Admin",
        "email": "admin@example.com",
    }
    assigned = {
        "id": "officer-1",
        "user_type": "loan_officer",
        "name": "Josh Officer",
        "email": "officer@example.com",
    }

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=admin,
        assigned_to=assigned,
        related_type="loan",
        related_id="loan-1",
    )

    expected_messages = {
        ("admin-1", "admin"): (
            "You assigned Gab Soriano's loan application to Josh Officer."
        ),
        ("officer-1", "loan_officer"): (
            "Gab Soriano's loan application was assigned to you by Avery Admin."
        ),
    }
    for (user_id, role), expected_message in expected_messages.items():
        response = NotificationListView().get(
            _request(user_id, role, f"{user_id}@example.com")
        )
        notifications = response.data["data"]["notifications"]
        assert len(notifications) == 1
        assert notifications[0]["message"] == expected_message


def test_unassignment_remains_isolated_through_inbox_api(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    _allow_authenticated_role(monkeypatch)
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda *args: None,
    )

    admin = {
        "id": "admin-1",
        "user_type": "admin",
        "name": "Avery Admin",
        "email": "admin@example.com",
    }
    previous = {
        "id": "officer-1",
        "user_type": "loan_officer",
        "name": "Josh Officer",
        "email": "officer@example.com",
    }

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=admin,
        previous_assignee=previous,
        related_type="loan",
        related_id="loan-1",
    )

    expected_messages = {
        ("admin-1", "admin"): (
            "You unassigned Gab Soriano's loan application from Josh Officer."
        ),
        ("officer-1", "loan_officer"): (
            "Gab Soriano's loan application was unassigned from you by Avery Admin."
        ),
    }
    for (user_id, role), expected_message in expected_messages.items():
        response = NotificationListView().get(
            _request(user_id, role, f"{user_id}@example.com")
        )
        notifications = response.data["data"]["notifications"]
        assert len(notifications) == 1
        assert notifications[0]["message"] == expected_message
