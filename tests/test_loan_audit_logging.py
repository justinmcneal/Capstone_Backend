"""
Tests for explicit status-transition audit logging in LoanApplication.

Coverage:
- assign_officer logs with structured metadata
- resubmit logs with structured metadata
- approval/rejection/submission endpoint audits remain compatible
- disbursement sub-state transitions are audited at the model boundary
"""

from unittest.mock import patch

from bson import ObjectId

from loans.models.application import LoanApplication


def _make_application(**overrides):
    defaults = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 20000,
        "approved_amount": 20000,
        "disbursed_amount": 20000,
        "term_months": 12,
        "purpose": "Working capital",
        "status": "submitted",
    }
    defaults.update(overrides)
    return LoanApplication(**defaults)


class TestStatusTransitionAuditLogs:
    def test_assign_officer_creates_audit_log(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="submitted")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.assign_officer("officer_123")

        assert mock_log.called is True
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "loan_assigned"
        assert call_kwargs["user_id"] == "officer_123"
        assert call_kwargs["user_type"] == "loan_officer"
        assert call_kwargs["resource_type"] == "loan"
        assert call_kwargs["resource_id"] == app.id
        details = call_kwargs["details"]
        assert details["old_status"] == "submitted"
        assert details["new_status"] == "under_review"
        assert details["loan_id"] == app.id
        assert details["customer_id"] == app.customer_id

    def test_assign_officer_audit_log_when_already_under_review(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="under_review", assigned_officer="officer_999")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.assign_officer("officer_123")

        assert mock_log.called is True
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "loan_assigned"
        assert call_kwargs["details"]["old_status"] == "under_review"
        assert call_kwargs["details"]["new_status"] == "under_review"

    def test_resubmit_creates_audit_log(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(
            status="rejected",
            rejection_reason="Incomplete",
            officer_notes="Needs more info",
            decision_date="2025-01-01T00:00:00Z",
        )
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.resubmit(actor_id="customer_456")

        assert mock_log.called is True
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == "loan_resubmitted"
        assert call_kwargs["user_id"] == "customer_456"
        assert call_kwargs["user_type"] == "customer"
        assert call_kwargs["resource_type"] == "loan"
        assert call_kwargs["resource_id"] == app.id
        details = call_kwargs["details"]
        assert details["old_status"] == "rejected"
        assert details["new_status"] == "draft"
        assert details["loan_id"] == app.id
        assert details["customer_id"] == app.customer_id

    def test_resubmit_defaults_to_customer_id_when_actor_not_provided(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(
            status="rejected",
            rejection_reason="Incomplete",
        )
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.resubmit()

        assert mock_log.called is True
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["user_id"] == app.customer_id
        assert call_kwargs["user_type"] == "customer"

    def test_approve_does_not_create_duplicate_audit_log_in_model(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="under_review")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.approve(
                officer_id="officer_789",
                approved_amount=15000,
                notes="Approved",
            )

        assert mock_log.called is False

    def test_reject_does_not_create_duplicate_audit_log_in_model(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="under_review")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.reject(
                officer_id="officer_789",
                reason="Insufficient income",
                notes="Rejected",
            )

        assert mock_log.called is False

    def test_submit_does_not_create_duplicate_audit_log_in_model(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="draft")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.submit()

        assert mock_log.called is False

    def test_disburse_audits_pending_and_completed_transitions(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="approved")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action") as mock_log:
            app.disburse(
                amount=20000,
                method="cash",
                reference="DSB-001",
                processed_by="officer_001",
            )

        assert [call.kwargs["action"] for call in mock_log.call_args_list] == [
            "loan_disbursement_pending",
            "loan_disbursed",
        ]
        assert all(
            call.kwargs["user_id"] == "officer_001"
            for call in mock_log.call_args_list
        )

    def test_audit_log_survives_analytics_failure(self, monkeypatch):
        import mongomock
        from django.conf import settings

        client = mongomock.MongoClient()
        db = client["testdb"]
        monkeypatch.setattr(settings, "MONGODB", db, raising=False)

        app = _make_application(status="submitted")
        app.save()

        with patch("analytics.models.audit_log.AuditLog.log_action", side_effect=Exception("DB down")):
            app.assign_officer("officer_123")

        assert app.status == "under_review"
        assert app.assigned_officer == "officer_123"
