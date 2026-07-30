"""
Inbox API tests for /api/notifications/ endpoints.
"""
import mongomock
from datetime import datetime, timezone
from types import SimpleNamespace
from rest_framework.test import APIRequestFactory
from django.conf import settings
from bson import ObjectId

from accounts.models.customer import Customer
from accounts.models.loan_officer import LoanOfficer
from accounts.models.admin import Admin
from notifications.models.notification import Notification
from notifications.models.device_token import DeviceToken
from notifications.views.notification_views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationUnreadCountView,
    NotificationDeleteView,
    NotificationClearAllView,
    RegisterDeviceTokenView,
)


def _setup_db(monkeypatch):
    client = mongomock.MongoClient()
    db = client['testdb']
    monkeypatch.setattr(settings, 'MONGODB', db)
    return db


def _create_customer(db, customer_id='123'):
    customer = Customer(
        first_name='Test',
        last_name='User',
        email='user@example.com',
        password='hashed',
        verified=True,
    )
    customer.save()
    return customer


def _create_officer(db, officer_id='456'):
    officer = LoanOfficer(
        first_name='Officer',
        last_name='Test',
        email='officer@example.com',
        password='hashed',
        department='Operations',
    )
    officer.save()
    return officer


def _create_admin(db, admin_id='789'):
    admin = Admin(
        username='admin_test',
        email='admin@example.com',
        password='hashed',
        first_name='Admin',
        last_name='Test',
    )
    admin.save()
    return admin


def _make_request(user, method='get', path='/api/notifications/', data=None, query=None):
    factory = APIRequestFactory()
    if method == 'get':
        django_req = factory.get(path, query or {})
    elif method == 'post':
        django_req = factory.post(path, data or {}, format='json')
    elif method == 'delete':
        django_req = factory.delete(path, data or {}, format='json')
    else:
        raise ValueError(f"Unsupported method: {method}")

    from rest_framework.request import Request as DRFRequest
    request = DRFRequest(django_req)
    request.user = user

    if method == 'post' and data is not None:
        request._full_data = data

    return request


def _bypass_rbac(view_cls):
    original = getattr(view_cls, 'require_roles', None)
    return original


class TestNotificationListView:
    def test_returns_empty_for_user_with_no_notifications(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='101')
        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

        request = _make_request(user, path='/api/notifications/')
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert response.data['data']['notifications'] == []
        assert response.data['data']['pagination']['total_items'] == 0

    def test_lists_notifications_owned_by_customer(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='201')
        notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/')
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert len(response.data['data']['notifications']) == 1
        assert response.data['data']['notifications'][0]['notification_type'] == 'loan_submitted'

    def test_excludes_notifications_owned_by_other_role(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='301')
        notif = Notification(
            user_id=str(customer.id),
            user_type='customer',
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        other_customer_id = ObjectId()
        fake_other = SimpleNamespace(
            customer_id=str(other_customer_id),
            email='other@example.com',
            role='customer',
        )
        request = _make_request(fake_other, path='/api/notifications/')
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, fake_other)

        response = view.get(request)
        assert response.status_code == 200
        assert response.data['data']['notifications'] == []

    def test_pagination_returns_correct_page_and_size(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='401')
        for i in range(5):
            Notification(
                user_id=str(customer.id),
                recipient_email=customer.email,
                recipient_name=customer.full_name,
                notification_type='loan_submitted',
                subject=f'Test {i}',
                message='hello',
            ).save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/', query={'page': 2, 'page_size': 2})
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert len(response.data['data']['notifications']) == 2
        assert response.data['data']['pagination']['page'] == 2
        assert response.data['data']['pagination']['page_size'] == 2
        assert response.data['data']['pagination']['total_items'] == 5
        assert response.data['data']['pagination']['total_pages'] == 3

    def test_unread_filter_returns_only_unread(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='501')

        read_notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Read',
            message='hello',
            status='read',
        )
        read_notif.save()

        unread_notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Unread',
            message='hello',
            status='sent',
        )
        unread_notif.save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/', query={'unread': 'true'})
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        subjects = [n['subject'] for n in response.data['data']['notifications']]
        assert 'Unread' in subjects
        assert 'Read' not in subjects

    def test_channel_filter_returns_matching_channel(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='601')

        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Email',
            message='hello',
            channel='email',
        ).save()

        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='InApp',
            message='hello',
            channel='in_app',
        ).save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/', query={'channel': 'in_app'})
        view = NotificationListView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert len(response.data['data']['notifications']) == 1
        assert response.data['data']['notifications'][0]['channel'] == 'in_app'


class TestNotificationUnreadCountView:
    def test_returns_zero_when_no_notifications(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='701')
        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

        request = _make_request(user, path='/api/notifications/unread-count/')
        view = NotificationUnreadCountView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert response.data['data']['unread_count'] == 0

    def test_returns_unread_count(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='801')
        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
            status='sent',
        ).save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/unread-count/')
        view = NotificationUnreadCountView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.get(request)
        assert response.status_code == 200
        assert response.data['data']['unread_count'] == 1


class TestNotificationMarkReadView:
    def test_marks_notification_as_read(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='901')
        notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path=f'/api/notifications/{notif.id}/read/', method='post')
        view = NotificationMarkReadView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.post(request, notification_id=notif.id)
        assert response.status_code == 200
        assert response.data['data']['status'] == 'read'

        updated = Notification.find_by_user(customer.id, limit=1)[0]
        assert updated.status == 'read'

    def test_returns_404_for_notification_owned_by_other_user(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1001')
        notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        other_id = ObjectId()
        other_user = SimpleNamespace(customer_id=str(other_id), email='other@example.com', role='customer')
        request = _make_request(other_user, path=f'/api/notifications/{notif.id}/read/', method='post')
        view = NotificationMarkReadView()
        view.require_roles = lambda *a, **k: (True, other_user)

        response = view.post(request, notification_id=notif.id)
        assert response.status_code == 404

    def test_returns_400_for_invalid_notification_id(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1101')
        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

        request = _make_request(user, path='/api/notifications/invalid-id/read/', method='post')
        view = NotificationMarkReadView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.post(request, notification_id='invalid-id')
        assert response.status_code == 400


class TestNotificationMarkAllReadView:
    def test_marks_all_unread_as_read(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1201')
        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test1',
            message='hello',
            status='sent',
        ).save()
        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test2',
            message='hello',
            status='pending',
        ).save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/mark-all-read/', method='post')
        view = NotificationMarkAllReadView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.post(request)
        assert response.status_code == 200
        assert response.data['data']['marked_count'] == 2

        unread_count = db['notifications'].count_documents({'user_id': str(customer.id), 'status': {'$nin': ['read']}})
        assert unread_count == 0


class TestNotificationDeleteView:
    def test_deletes_owned_notification(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1301')
        notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path=f'/api/notifications/{notif.id}/', method='delete')
        view = NotificationDeleteView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.delete(request, notification_id=notif.id)
        assert response.status_code == 200
        assert response.data['data']['status'] == 'deleted'

        assert db['notifications'].find_one({'_id': notif._id}) is None

    def test_returns_404_for_other_users_notification(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1401')
        notif = Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
        )
        notif.save()

        other_id = ObjectId()
        other_user = SimpleNamespace(customer_id=str(other_id), email='other@example.com', role='customer')
        request = _make_request(other_user, path=f'/api/notifications/{notif.id}/', method='delete')
        view = NotificationDeleteView()
        view.require_roles = lambda *a, **k: (True, other_user)

        response = view.delete(request, notification_id=notif.id)
        assert response.status_code == 404


class TestNotificationClearAllView:
    def test_deletes_all_owned_notifications(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1501')
        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test',
            message='hello',
            status='read',
        ).save()
        Notification(
            user_id=str(customer.id),
            recipient_email=customer.email,
            recipient_name=customer.full_name,
            notification_type='loan_submitted',
            subject='Test2',
            message='hello',
            status='sent',
        ).save()

        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')
        request = _make_request(user, path='/api/notifications/clear-all/', method='delete')
        view = NotificationClearAllView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.delete(request)
        assert response.status_code == 200
        assert response.data['data']['deleted_count'] == 2

        assert db['notifications'].count_documents({'user_id': str(customer.id)}) == 0


class TestRegisterDeviceTokenView:
    def test_registers_device_token(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1601')
        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

        request = _make_request(
            user,
            path='/api/notifications/register-token/',
            method='post',
            data={'token': 'fcm-token-123', 'platform': 'android'},
        )
        view = RegisterDeviceTokenView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.post(request)
        assert response.status_code == 200
        assert response.data['data']['status'] == 'registered'

        token_doc = db[DeviceToken.collection_name].find_one({'token': 'fcm-token-123'})
        assert token_doc is not None
        assert token_doc['user_id'] == str(customer.id)
        assert token_doc['platform'] == 'android'

    def test_returns_400_for_missing_token(self, monkeypatch):
        db = _setup_db(monkeypatch)
        customer = _create_customer(db, customer_id='1701')
        user = SimpleNamespace(customer_id=str(customer.id), email=customer.email, role='customer')

        request = _make_request(
            user,
            path='/api/notifications/register-token/',
            method='post',
            data={'platform': 'ios'},
        )
        view = RegisterDeviceTokenView()
        view.require_roles = lambda *a, **k: (True, user)

        response = view.post(request)
        assert response.status_code == 400
