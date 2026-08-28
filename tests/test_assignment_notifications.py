from types import SimpleNamespace

import mongomock
from django.conf import settings

from loans.models import LoanApplication
from loans.services import assignment
from loans.views.admin_views import AssignApplicationView, ReassignApplicationView
from notifications.models.notification import Notification
from notifications.services import assignment_events


def _party(user_id, user_type, name):
    return {
        "id": user_id,
        "user_type": user_type,
        "name": name,
        "email": f"{user_id}@example.com",
    }


def test_reassignment_creates_distinct_notifications(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)

    broadcasts = []
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda user_id, user_type, payload: broadcasts.append(
            (str(user_id), user_type, payload)
        ),
    )

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=_party("admin-1", "admin", "Avery Admin"),
        assigned_to=_party("officer-2", "loan_officer", "Josh New"),
        previous_assignee=_party("officer-1", "loan_officer", "Casey Old"),
        related_type="loan",
        related_id="loan-1",
    )

    documents = list(database[Notification.collection_name].find())
    assert len(documents) == 3
    assert {document["user_id"] for document in documents} == {
        "admin-1",
        "officer-1",
        "officer-2",
    }

    by_user = {document["user_id"]: document for document in documents}
    assert by_user["admin-1"]["message"] == (
        "You reassigned Gab Soriano's loan application from Casey Old to Josh New."
    )
    assert by_user["officer-2"]["message"] == (
        "Gab Soriano's loan application was assigned to you by Avery Admin."
    )
    assert by_user["officer-1"]["message"] == (
        "Gab Soriano's loan application was reassigned from you to Josh New "
        "by Avery Admin."
    )
    assert by_user["officer-1"]["notification_type"] == "application_unassigned"
    assert by_user["admin-1"]["metadata"]["event_type"] == ("application_reassigned")
    assert by_user["admin-1"]["metadata"]["assigned_by"]["id"] == "admin-1"
    assert by_user["admin-1"]["metadata"]["assigned_to"]["id"] == "officer-2"
    assert by_user["admin-1"]["metadata"]["previous_assignee"]["id"] == ("officer-1")
    assert len(broadcasts) == 3
    assert all(payload["metadata"] for _, _, payload in broadcasts)


def test_initial_assignment_does_not_create_previous_assignee_notification(
    monkeypatch,
):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda *args: None,
    )

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=_party("admin-1", "admin", "Avery Admin"),
        assigned_to=_party("officer-1", "loan_officer", "Josh Officer"),
        related_type="loan",
        related_id="loan-1",
    )

    documents = list(database[Notification.collection_name].find())
    assert len(documents) == 2
    assert {document["notification_type"] for document in documents} == {
        "application_assigned"
    }
    assert {document["metadata"]["audience"] for document in documents} == {
        "assigner",
        "new_assignee",
    }


def test_unassignment_template_notifies_admin_and_previous_officer(monkeypatch):
    database = mongomock.MongoClient()["testdb"]
    monkeypatch.setattr(settings, "MONGODB", database)
    monkeypatch.setattr(
        "notifications.services.delivery.broadcast_notification_to_user",
        lambda *args: None,
    )

    assignment_events.publish_assignment_notifications(
        entity_name="Gab Soriano's loan application",
        assigned_by=_party("admin-1", "admin", "Avery Admin"),
        previous_assignee=_party("officer-1", "loan_officer", "Josh Officer"),
        related_type="loan",
        related_id="loan-1",
    )

    documents = list(database[Notification.collection_name].find())
    assert len(documents) == 2
    assert {document["notification_type"] for document in documents} == {
        "application_unassigned"
    }
    by_user = {document["user_id"]: document for document in documents}
    assert by_user["admin-1"]["message"] == (
        "You unassigned Gab Soriano's loan application from Josh Officer."
    )
    assert by_user["officer-1"]["message"] == (
        "Gab Soriano's loan application was unassigned from you by Avery Admin."
    )


def test_manual_assignment_passes_admin_and_customer_context(monkeypatch):
    officer = SimpleNamespace(
        id="officer-1",
        role="loan_officer",
        full_name="Josh Officer",
        email="josh@example.com",
        active=True,
    )
    admin = SimpleNamespace(
        id="admin-1",
        role="admin",
        full_name="Avery Admin",
        email="avery@example.com",
    )
    customer = SimpleNamespace(full_name="Gab Soriano")

    class Application:
        id = "loan-1"
        customer_id = "customer-1"
        assigned_officer = None

        def assign_officer(self, officer_id, actor_id=None, actor_type="system"):
            self.assigned_officer = officer_id
            self.assignment_actor = (actor_id, actor_type)

    application = Application()
    captured = {}

    monkeypatch.setattr(
        assignment,
        "_find_officer",
        lambda officer_id: officer if officer_id == officer.id else None,
    )
    monkeypatch.setattr(assignment, "_find_by_id", lambda model, value: customer)
    monkeypatch.setattr(
        "notifications.services.publish_assignment_notifications",
        lambda **kwargs: captured.update(kwargs),
    )

    result = assignment.manual_assign_application(
        application, officer.id, assigned_by=admin
    )

    assert result is officer
    assert application.assigned_officer == officer.id
    assert application.assignment_actor == (admin.id, "admin")
    assert captured["entity_name"] == "Gab Soriano's loan application"
    assert captured["assigned_by"]["id"] == admin.id
    assert captured["assigned_to"]["id"] == officer.id
    assert captured["previous_assignee"] is None


def test_same_officer_assignment_is_a_noop(monkeypatch):
    officer = SimpleNamespace(
        id="officer-1",
        role="loan_officer",
        full_name="Josh Officer",
        email="josh@example.com",
        active=True,
    )
    application = SimpleNamespace(assigned_officer=officer.id)
    monkeypatch.setattr(assignment, "_find_officer", lambda officer_id: officer)
    monkeypatch.setattr(
        assignment,
        "_notify_assignment_change",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("No notification should be sent")
        ),
    )

    assert assignment.manual_assign_application(application, officer.id) is officer


def test_assignment_views_pass_authenticated_admin_to_services(monkeypatch):
    admin = SimpleNamespace(id="admin-1")
    application = SimpleNamespace(id="loan-1", status="submitted")
    officer = SimpleNamespace(id="507f1f77bcf86cd799439011", full_name="Josh Officer")

    monkeypatch.setattr(
        LoanApplication, "find_by_id", lambda application_id: application
    )
    monkeypatch.setattr(
        AssignApplicationView,
        "check_admin_permission",
        lambda self, request: (True, admin),
    )
    monkeypatch.setattr(
        ReassignApplicationView,
        "check_admin_permission",
        lambda self, request: (True, admin),
    )

    captured = []
    monkeypatch.setattr(
        "loans.services.manual_assign_application",
        lambda app, officer_id, assigned_by=None: (
            captured.append(("assign", assigned_by)),
            officer,
        )[1],
    )
    monkeypatch.setattr(
        "loans.services.reassign_application",
        lambda app, officer_id, assigned_by=None: (
            captured.append(("reassign", assigned_by)),
            officer,
        )[1],
    )

    assign_request = SimpleNamespace(data={"officer_id": officer.id})
    reassign_request = SimpleNamespace(data={"officer_id": officer.id})

    assign_response = AssignApplicationView().post(assign_request, application.id)
    reassign_response = ReassignApplicationView().post(reassign_request, application.id)

    assert assign_response.status_code == 200
    assert reassign_response.status_code == 200
    assert captured == [("assign", admin), ("reassign", admin)]
