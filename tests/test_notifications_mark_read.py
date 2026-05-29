import mongomock
from types import SimpleNamespace
from rest_framework.test import APIRequestFactory
from django.conf import settings
from bson import ObjectId

from notifications.models.notification import Notification
from accounts.models.customer import Customer
from notifications.views.notification_views import NotificationMarkReadView, NotificationMarkAllReadView


def test_mark_read_and_mark_all_read_with_real_customer(monkeypatch):
    # Setup mongomock DB and patch settings.MONGODB
    client = mongomock.MongoClient()
    db = client['testdb']
    monkeypatch.setattr(settings, 'MONGODB', db)

    # Create a customer in DB so AccessControlMixin._load_actor can find it
    customer = Customer(first_name='Test', last_name='User', email='user@example.com')
    customer.save()

    # Create two notifications for this customer
    notif1 = Notification(user_id=str(customer.id), recipient_email=customer.email, recipient_name=customer.full_name, notification_type='loan_submitted', subject='Test1')
    notif1.save()
    notif2 = Notification(user_id=str(customer.id), recipient_email=customer.email, recipient_name=customer.full_name, notification_type='loan_submitted', subject='Test2')
    notif2.save()

    # Build DRF request for single mark-read
    factory = APIRequestFactory()
    django_req = factory.post(f'/api/notifications/{notif1.id}/read/')
    from rest_framework.request import Request as DRFRequest
    request = DRFRequest(django_req)
    request.user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

    view = NotificationMarkReadView()
    response = view.post(request, notification_id=notif1.id)
    assert response.status_code == 200
    data = response.data.get('data')
    assert data and data.get('status') == 'read'

    # Now mark all unread - should affect remaining notification
    django_req2 = factory.post('/api/notifications/mark-all-read/')
    request2 = DRFRequest(django_req2)
    request2.user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

    view2 = NotificationMarkAllReadView()
    response2 = view2.post(request2)
    assert response2.status_code == 200
    payload = response2.data.get('data')
    assert payload and payload.get('marked_count', 0) >= 1
