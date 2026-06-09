import mongomock
from types import SimpleNamespace
from rest_framework.test import APIRequestFactory
from django.conf import settings

from notifications.views.notification_views import NotificationListView
from notifications.models.notification import Notification


def test_notification_list_view_with_mongomock(monkeypatch):
    # Use an in-memory mongomock DB
    client = mongomock.MongoClient()
    monkeypatch.setattr(settings, 'MONGODB', client['testdb'])

    # Create a notification for user_id '123'
    notif = Notification(
        user_id='123',
        recipient_email='user@example.com',
        recipient_name='User',
        notification_type='loan_submitted',
        subject='Test',
        message='hello',
    )
    notif.save()

    # Build request with a fake user owning customer_id '123'
    factory = APIRequestFactory()
    django_req = factory.get('/api/notifications/')
    from rest_framework.request import Request as DRFRequest

    request = DRFRequest(django_req)
    request.user = SimpleNamespace(customer_id='123', email='user@example.com', role='customer')

    # Bypass RBAC for the unit test by stubbing require_roles
    monkeypatch = __import__('pytest').MonkeyPatch()
    try:
        monkeypatch.setattr(
            NotificationListView,
            'require_roles',
            lambda self, request, roles, *a, **k: (True, request.user),
        )
        view = NotificationListView()
        response = view.get(request)
    finally:
        monkeypatch.undo()

    assert response.status_code == 200
    assert 'data' in response.data
    payload = response.data['data']
    assert 'notifications' in payload
    data = payload['notifications']
    assert isinstance(data, list)
    assert any(n['notification_type'] == 'loan_submitted' for n in data)
