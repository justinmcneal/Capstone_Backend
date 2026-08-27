"""Stage 1 routed auth, owner, state, bound, and throttle evidence."""

from bson import ObjectId
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.token_utils import TokenUtils
from notifications.models.notification import Notification
from notifications.throttles import (
    NotificationDeviceTokenRateThrottle,
    NotificationReadRateThrottle,
    NotificationWriteRateThrottle,
)
from notifications.views.notification_views import (
    NotificationClearAllView,
    NotificationDeleteView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
    RegisterDeviceTokenView,
)


def _customer():
    return Customer(
        first_name="Notify",
        last_name="Customer",
        email=f"notify-{ObjectId()}@example.test",
        password="hashed",
        verified=True,
        active=True,
        account_state="active",
    ).save()


def _officer():
    return LoanOfficer(
        employee_id=f"NOTIFY-{ObjectId()}",
        first_name="Notify",
        last_name="Officer",
        email=f"notify-officer-{ObjectId()}@example.test",
        password="hashed",
        active=True,
        verified=True,
        must_change_password=False,
    ).save()


def _admin():
    return Admin(
        username=f"notify-admin-{ObjectId()}",
        email=f"notify-admin-{ObjectId()}@example.test",
        password="hashed",
        first_name="Notify",
        last_name="Admin",
        active=True,
    ).save()


def _client(account, role):
    if role == "customer":
        tokens = TokenUtils.generate_jwt_tokens(account)
    else:
        tokens = TokenUtils.generate_tokens(
            user_id=account.id,
            email=account.email,
            verified=True,
            role=role,
            security_version=account.security_version,
        )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


def _notification(account, role, subject="Stage 1", status="sent"):
    return Notification(
        user_id=account.id,
        user_type=role,
        notification_type="loan_submitted",
        subject=subject,
        message="Owner-scoped notification",
        channel="in_app",
        status=status,
    ).save()


def test_all_rest_routes_reject_missing_jwt():
    client = APIClient()
    notification_id = str(ObjectId())
    requests = (
        ("get", reverse("notifications:notification-list"), None),
        ("get", reverse("notifications:notification-unread-count"), None),
        ("post", reverse("notifications:notification-mark-all-read"), {}),
        (
            "post",
            reverse(
                "notifications:notification-mark-read",
                kwargs={"notification_id": notification_id},
            ),
            {},
        ),
        (
            "delete",
            reverse(
                "notifications:notification-delete",
                kwargs={"notification_id": notification_id},
            ),
            None,
        ),
        ("delete", reverse("notifications:notification-clear-all"), None),
        ("post", reverse("notifications:notification-register-token"), {"token": "x"}),
    )
    for method, url, data in requests:
        response = getattr(client, method)(url, data=data, format="json")
        assert response.status_code in {401, 403}


def test_all_roles_receive_only_their_role_qualified_inbox():
    actors = (
        (_customer(), "customer"),
        (_officer(), "loan_officer"),
        (_admin(), "admin"),
    )
    for index, (account, role) in enumerate(actors):
        _notification(account, role, subject=f"owner-{index}")

    for index, (account, role) in enumerate(actors):
        response = _client(account, role).get(
            reverse("notifications:notification-list")
        )
        assert response.status_code == 200
        items = response.json()["data"]["notifications"]
        assert [item["subject"] for item in items] == [f"owner-{index}"]


def test_routed_customer_exercises_all_seven_operations():
    customer = _customer()
    client = _client(customer, "customer")
    first = _notification(customer, "customer", "first", status="failed")
    second = _notification(customer, "customer", "second")

    listed = client.get(reverse("notifications:notification-list"))
    assert listed.status_code == 200
    assert listed.json()["data"]["unread_count"] == 2

    unread = client.get(reverse("notifications:notification-unread-count"))
    assert unread.status_code == 200
    assert unread.json()["data"]["unread_count"] == 2

    mark_url = reverse(
        "notifications:notification-mark-read",
        kwargs={"notification_id": first.id},
    )
    marked = client.post(mark_url, {}, format="json")
    assert marked.status_code == 200
    assert marked.json()["data"] == {
        "notification_id": first.id,
        "is_read": True,
        "read_at": marked.json()["data"]["read_at"],
        "delivery_status": "failed",
        "replayed": False,
    }
    replay = client.post(mark_url, {}, format="json")
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True

    stored = Notification.find_by_user(customer.id, limit=2, user_type="customer")
    by_id = {item.id: item for item in stored}
    assert by_id[first.id].is_read is True
    assert by_id[first.id].delivery_status == "failed"

    mark_all = client.post(
        reverse("notifications:notification-mark-all-read"), {}, format="json"
    )
    assert mark_all.status_code == 200
    assert mark_all.json()["data"]["marked_count"] == 1

    registered = client.post(
        reverse("notifications:notification-register-token"),
        {"token": "stage1-device-token-1234567890", "platform": "android"},
        format="json",
    )
    assert registered.status_code == 200

    deleted = client.delete(
        reverse(
            "notifications:notification-delete",
            kwargs={"notification_id": second.id},
        )
    )
    assert deleted.status_code == 200

    cleared = client.delete(reverse("notifications:notification-clear-all"))
    assert cleared.status_code == 200
    assert cleared.json()["data"]["deleted_count"] == 1


def test_cross_owner_mark_and_delete_are_concealed():
    owner = _customer()
    other = _customer()
    notification = _notification(owner, "customer")
    client = _client(other, "customer")

    mark = client.post(
        reverse(
            "notifications:notification-mark-read",
            kwargs={"notification_id": notification.id},
        ),
        {},
        format="json",
    )
    delete = client.delete(
        reverse(
            "notifications:notification-delete",
            kwargs={"notification_id": notification.id},
        )
    )
    assert mark.status_code == 404
    assert delete.status_code == 404


def test_list_rejects_unknown_parameters_page_size_and_deep_offset(settings):
    customer = _customer()
    client = _client(customer, "customer")
    url = reverse("notifications:notification-list")

    assert client.get(url, {"unexpected": "1"}).status_code == 400
    assert client.get(url, {"page_size": 101}).status_code == 400
    settings.NOTIFICATIONS_MAX_OFFSET = 10
    response = client.get(url, {"page": 3, "page_size": 10})
    assert response.status_code == 400
    assert response.json()["code"] == "NOTIFICATION_OFFSET_LIMIT_EXCEEDED"


def test_bulk_operations_fail_before_exceeding_the_synchronous_bound(settings):
    settings.NOTIFICATIONS_BULK_MUTATION_LIMIT = 1
    customer = _customer()
    client = _client(customer, "customer")
    _notification(customer, "customer", "one")
    _notification(customer, "customer", "two")

    marked = client.post(
        reverse("notifications:notification-mark-all-read"), {}, format="json"
    )
    cleared = client.delete(reverse("notifications:notification-clear-all"))
    assert marked.status_code == 409
    assert cleared.status_code == 409
    assert marked.json()["code"] == "NOTIFICATION_BULK_LIMIT_EXCEEDED"
    assert cleared.json()["code"] == "NOTIFICATION_BULK_LIMIT_EXCEEDED"


def test_notification_views_declare_dedicated_throttles():
    assert NotificationListView.throttle_classes == [NotificationReadRateThrottle]
    assert NotificationUnreadCountView.throttle_classes == [
        NotificationReadRateThrottle
    ]
    for view in (
        NotificationMarkReadView,
        NotificationMarkAllReadView,
        NotificationDeleteView,
        NotificationClearAllView,
    ):
        assert view.throttle_classes == [NotificationWriteRateThrottle]
    assert RegisterDeviceTokenView.throttle_classes == [
        NotificationDeviceTokenRateThrottle
    ]


def test_routed_read_throttle_uses_authenticated_identity(settings):
    cache.clear()
    settings.NOTIFICATIONS_READ_RATE = "1/hour"
    customer = _customer()
    client = _client(customer, "customer")
    url = reverse("notifications:notification-unread-count")

    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 429


def test_revoked_session_is_rejected_by_routed_inbox():
    customer = _customer()
    client = _client(customer, "customer")
    url = reverse("notifications:notification-list")
    assert client.get(url).status_code == 200

    TokenUtils.revoke_all_sessions(customer.id, "customer")
    assert client.get(url).status_code == 401
