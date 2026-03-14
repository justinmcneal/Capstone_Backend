"""
Tests for loans.blockchain.sync — synchronous blockchain sync (no Celery).
"""

import threading
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_is_enabled_true(self, blockchain_settings):
        from loans.blockchain.sync import _is_enabled
        assert _is_enabled() is True

    def test_is_enabled_false(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import _is_enabled
        assert _is_enabled() is False

    def test_monthly_rate_to_annual_bps(self):
        from loans.blockchain.sync import _monthly_rate_to_annual_bps
        assert _monthly_rate_to_annual_bps(0.015) == 1800
        assert _monthly_rate_to_annual_bps(0.01) == 1200
        assert _monthly_rate_to_annual_bps(0) == 0

    def test_risk_category_to_int(self):
        from loans.blockchain.sync import _risk_category_to_int
        assert _risk_category_to_int("low") == 0
        assert _risk_category_to_int("medium") == 1
        assert _risk_category_to_int("high") == 2
        assert _risk_category_to_int(None) == 0
        assert _risk_category_to_int("unknown") == 0


# ---------------------------------------------------------------------------
# sync_application
# ---------------------------------------------------------------------------

class TestSyncApplication:
    def test_skips_when_disabled(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import sync_application
        # Should return immediately without error
        sync_application("fake_id")

    @patch("loans.blockchain.sync._run_in_thread")
    def test_calls_thread_when_enabled(self, mock_thread, blockchain_settings):
        from loans.blockchain.sync import sync_application, _sync_application_impl
        sync_application("loan123")
        mock_thread.assert_called_once_with(_sync_application_impl, "loan123")

    @patch("loans.blockchain.services.application_service.submit_application_onchain")
    @patch("loans.blockchain.services.application_service.create_application_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    @patch("loans.models.application.LoanApplication.find_by_id")
    def test_impl_success(self, mock_find, mock_pending, mock_create, mock_submit, blockchain_settings):
        from loans.blockchain.sync import _sync_application_impl

        mock_app = MagicMock()
        mock_app.ai_recommendation = {"interest_rate": 0.015}
        mock_app.product_id = "prod1"
        mock_app.requested_amount = 50000
        mock_app.term_months = 12
        mock_app.eligibility_score = 85
        mock_app.risk_category = "low"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        mock_create.return_value = {"tx_hash": "0xaaa", "gas_used": 100000, "block_number": 1}
        mock_submit.return_value = {"tx_hash": "0xbbb", "gas_used": 80000, "block_number": 2}

        _sync_application_impl("loan123")

        mock_create.assert_called_once()
        mock_submit.assert_called_once()
        mock_tx.mark_confirmed.assert_called_once()

    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    @patch("loans.models.application.LoanApplication.find_by_id")
    def test_impl_marks_failed_on_error(self, mock_find, mock_pending, blockchain_settings):
        from loans.blockchain.sync import _sync_application_impl

        mock_find.return_value = None
        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        # Should not raise — errors are caught
        _sync_application_impl("loan123")
        mock_tx.mark_failed.assert_called_once()


# ---------------------------------------------------------------------------
# sync_approval
# ---------------------------------------------------------------------------

class TestSyncApproval:
    def test_skips_when_disabled(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import sync_approval
        sync_approval("fake_id")

    @patch("loans.blockchain.sync._run_in_thread")
    def test_calls_thread_when_enabled(self, mock_thread, blockchain_settings):
        from loans.blockchain.sync import sync_approval, _sync_approval_impl
        sync_approval("loan123")
        mock_thread.assert_called_once_with(_sync_approval_impl, "loan123")

    @patch("loans.blockchain.services.approval_service.approve_loan_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    @patch("loans.models.application.LoanApplication.find_by_id")
    def test_impl_success(self, mock_find, mock_pending, mock_approve, blockchain_settings):
        from loans.blockchain.sync import _sync_approval_impl

        mock_app = MagicMock()
        mock_app.approved_amount = 50000
        mock_app.officer_notes = "Good application"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        mock_approve.return_value = {"tx_hash": "0xccc", "gas_used": 90000, "block_number": 3}

        _sync_approval_impl("loan123")

        mock_approve.assert_called_once()
        mock_tx.mark_confirmed.assert_called_once()


# ---------------------------------------------------------------------------
# sync_disbursement
# ---------------------------------------------------------------------------

class TestSyncDisbursement:
    def test_skips_when_disabled(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import sync_disbursement
        sync_disbursement("fake_id")

    @patch("loans.blockchain.services.disbursement_service.complete_disbursement_onchain")
    @patch("loans.blockchain.services.disbursement_service.set_method_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    @patch("loans.models.application.LoanApplication.find_by_id")
    def test_impl_success(self, mock_find, mock_pending, mock_set_method, mock_complete, blockchain_settings):
        from loans.blockchain.sync import _sync_disbursement_impl

        mock_app = MagicMock()
        mock_app.disbursement_method = "gcash"
        mock_app.preferred_disbursement_method = "gcash"
        mock_app.disbursed_amount = 50000
        mock_app.disbursement_reference = "REF123"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        mock_complete.return_value = {
            "complete_tx": {"tx_hash": "0xddd", "gas_used": 120000, "block_number": 4}
        }

        _sync_disbursement_impl("loan123")

        mock_set_method.assert_called_once()
        mock_complete.assert_called_once()
        mock_tx.mark_confirmed.assert_called_once()


# ---------------------------------------------------------------------------
# sync_schedule
# ---------------------------------------------------------------------------

class TestSyncSchedule:
    def test_skips_when_disabled(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import sync_schedule
        sync_schedule("fake_id")

    @patch("loans.blockchain.services.repayment_service.create_schedule_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    @patch("loans.models.application.LoanApplication.find_by_id")
    def test_impl_success(self, mock_find, mock_pending, mock_create_sched, blockchain_settings):
        from datetime import datetime
        from loans.blockchain.sync import _sync_schedule_impl
        from loans.models.repayment import RepaymentSchedule

        mock_app = MagicMock()
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        schedule_doc = {
            "_id": "sched1",
            "loan_id": "loan123",
            "principal": 50000,
            "interest_rate": 0.015,
            "term_months": 12,
            "monthly_payment": 4583,
            "total_amount": 55000,
            "start_date": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "installments": [],
        }
        settings.MONGODB["repayment_schedules"].insert_one(schedule_doc)

        mock_create_sched.return_value = {"tx_hash": "0xeee", "gas_used": 200000, "block_number": 5}

        _sync_schedule_impl("loan123")

        mock_create_sched.assert_called_once()
        mock_tx.mark_confirmed.assert_called_once()


# ---------------------------------------------------------------------------
# sync_payment
# ---------------------------------------------------------------------------

class TestSyncPayment:
    def test_skips_when_disabled(self):
        settings.BLOCKCHAIN_ENABLED = False
        from loans.blockchain.sync import sync_payment
        sync_payment("fake_id", "pay_id")

    @patch("loans.blockchain.services.repayment_service.record_payment_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_impl_success(self, mock_pending, mock_record, blockchain_settings):
        from datetime import datetime
        from bson import ObjectId
        from loans.blockchain.sync import _sync_payment_impl

        mock_tx = MagicMock()
        mock_pending.return_value = mock_tx

        payment_id = ObjectId()
        payment_doc = {
            "_id": payment_id,
            "loan_id": "loan123",
            "installment_number": 1,
            "amount": 4583,
            "payment_method": "gcash",
            "reference": "PAY_REF_001",
            "recorded_at": datetime.utcnow(),
        }
        settings.MONGODB["loan_payments"].insert_one(payment_doc)

        mock_record.return_value = {"tx_hash": "0xfff", "gas_used": 90000, "block_number": 6}

        _sync_payment_impl("loan123", str(payment_id))

        mock_record.assert_called_once()
        mock_tx.mark_confirmed.assert_called_once()


# ---------------------------------------------------------------------------
# Thread behavior
# ---------------------------------------------------------------------------

class TestThreading:
    @patch("loans.blockchain.sync._sync_application_impl")
    def test_run_in_thread_fires(self, mock_impl, blockchain_settings):
        from loans.blockchain.sync import sync_application

        # Call sync_application which should spawn a thread
        sync_application("loan123")

        # Give the thread a moment to run
        import time
        time.sleep(0.1)

        mock_impl.assert_called_once_with("loan123")

    @patch("loans.blockchain.sync._sync_application_impl", side_effect=RuntimeError("boom"))
    def test_thread_error_does_not_propagate(self, mock_impl, blockchain_settings):
        from loans.blockchain.sync import sync_application

        # Should not raise even though the impl raises
        sync_application("loan123")

        import time
        time.sleep(0.1)
        # No exception = success
