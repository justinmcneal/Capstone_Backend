from datetime import datetime, timedelta, timezone

from notifications.models.notification import Notification, serialize_utc_datetime
from notifications.services.websocket_service import serialize_notification_for_ws


def test_serialize_utc_datetime_marks_naive_mongodb_values_as_utc():
    assert serialize_utc_datetime(datetime(2026, 7, 23, 2, 15)) == '2026-07-23T02:15:00Z'


def test_serialize_utc_datetime_converts_aware_values_to_utc():
    philippines = timezone(timedelta(hours=8))

    assert (
        serialize_utc_datetime(datetime(2026, 7, 23, 10, 15, tzinfo=philippines))
        == '2026-07-23T02:15:00Z'
    )


def test_websocket_notifications_include_an_explicit_utc_designator():
    notification = Notification(
        user_id='123',
        notification_type='application_unassigned',
        created_at=datetime(2026, 7, 23, 2, 15),
    )

    assert serialize_notification_for_ws(notification)['created_at'] == '2026-07-23T02:15:00Z'
