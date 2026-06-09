"""
Unit tests for loans.blockchain.tasks (Celery tasks).

All service calls and model queries are mocked. Tests verify:
- Tasks skip when BLOCKCHAIN_ENABLED=False
- Tasks call the correct service functions
- Successful results update BlockchainTransaction and Django model
- Failures trigger retries and eventually mark tx as failed
- Rate conversion and enum mapping helpers work correctly
"""

from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from loans.blockchain.tasks import (
    _is_enabled,
    _monthly_rate_to_annual_bps,
    _risk_category_to_int,
    sync_application_to_chain,
    sync_approval_to_chain,
    sync_disbursement_to_chain,
    sync_schedule_to_chain,
    sync_payment_to_chain,
)


# ============================================================================
# Helper function tests
# ============================================================================

class TestHelpers:
    def test_is_enabled_true(self, settings):
        settings.BLOCKCHAIN_ENABLED = True
        assert _is_enabled() is True

    def test_is_enabled_false(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        assert _is_enabled() is False

    def test_is_enabled_missing_attr(self, settings):
        if hasattr(settings, 'BLOCKCHAIN_ENABLED'):
            delattr(settings, 'BLOCKCHAIN_ENABLED')
        assert _is_enabled() is False

    def test_monthly_rate_to_annual_bps(self):
        # 0.015 monthly = 18% annual = 1800 bps
        assert _monthly_rate_to_annual_bps(0.015) == 1800
        # 0.01 monthly = 12% annual = 1200 bps
        assert _monthly_rate_to_annual_bps(0.01) == 1200
        # 0 monthly = 0 bps
        assert _monthly_rate_to_annual_bps(0) == 0
        # 0.025 monthly = 30% annual = 3000 bps
        assert _monthly_rate_to_annual_bps(0.025) == 3000

    def test_risk_category_to_int(self):
        assert _risk_category_to_int("low") == 0
        assert _risk_category_to_int("medium") == 1
        assert _risk_category_to_int("high") == 2
        assert _risk_category_to_int("Low") == 0
        assert _risk_category_to_int("HIGH") == 2
        assert _risk_category_to_int(None) == 0
        assert _risk_category_to_int("unknown") == 0


# ============================================================================
# sync_application_to_chain
# ============================================================================

class TestSyncApplicationToChain:
    def test_skips_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        result = sync_application_to_chain("loan_id_1")
        assert result["skipped"] is True

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.application_service.submit_application_onchain")
    @patch("loans.blockchain.services.application_service.create_application_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_success(self, mock_create_pending, mock_find, mock_create, mock_submit, mock_update_tx, blockchain_settings):
        # Setup mock application
        mock_app = MagicMock()
        mock_app.product_id = "prod1"
        mock_app.requested_amount = 50000
        mock_app.term_months = 12
        mock_app.ai_recommendation = {"interest_rate": 0.015}
        mock_app.eligibility_score = 85
        mock_app.risk_category = "medium"
        mock_find.return_value = mock_app

        # Setup mock tx record
        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        # Setup mock service results
        mock_create.return_value = {"tx_hash": "0xcreate", "gas_used": 100000, "block_number": 1, "status": 1}
        mock_submit.return_value = {"tx_hash": "0xsubmit", "gas_used": 80000, "block_number": 2, "status": 1}

        result = sync_application_to_chain("loan_id_1")

        assert result["tx_hash"] == "0xsubmit"
        assert result["status"] == "confirmed"
        mock_tx.mark_confirmed.assert_called_once_with(
            tx_hash="0xsubmit",
            gas_used=180000,  # 100000 + 80000
            block_number=2,
        )
        mock_update_tx.assert_called_once_with("loan_id_1", "submit", "0xsubmit")

    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_app_not_found_retries(self, mock_create_pending, mock_find, blockchain_settings):
        mock_find.return_value = None
        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        # Celery self.retry(exc=exc) re-raises the original exception
        with pytest.raises(ValueError, match="not found"):
            sync_application_to_chain("nonexistent")

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.application_service.submit_application_onchain")
    @patch("loans.blockchain.services.application_service.create_application_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_handles_non_dict_ai_recommendation(self, mock_create_pending, mock_find, mock_create, mock_submit, mock_update_tx, blockchain_settings):
        mock_app = MagicMock()
        mock_app.product_id = "prod1"
        mock_app.requested_amount = 50000
        mock_app.term_months = 12
        mock_app.ai_recommendation = None  # Not a dict
        mock_app.eligibility_score = 0
        mock_app.risk_category = None
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_create.return_value = {"tx_hash": "0x1", "gas_used": 1, "block_number": 1, "status": 1}
        mock_submit.return_value = {"tx_hash": "0x2", "gas_used": 1, "block_number": 1, "status": 1}

        result = sync_application_to_chain("loan_id_2")
        assert result["status"] == "confirmed"


# ============================================================================
# sync_approval_to_chain
# ============================================================================

class TestSyncApprovalToChain:
    def test_skips_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        result = sync_approval_to_chain("loan_id_1")
        assert result["skipped"] is True

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.approval_service.approve_loan_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_success(self, mock_create_pending, mock_find, mock_approve, mock_update_tx, blockchain_settings):
        mock_app = MagicMock()
        mock_app.approved_amount = 45000
        mock_app.requested_amount = 50000
        mock_app.officer_notes = "Looks good"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_approve.return_value = {"tx_hash": "0xapprove", "gas_used": 90000, "block_number": 5, "status": 1}

        result = sync_approval_to_chain("loan_id_1")

        assert result["tx_hash"] == "0xapprove"
        mock_approve.assert_called_once_with(
            loan_id="loan_id_1",
            approved_amount=45000,
            notes_hash="Looks good",
        )

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.approval_service.approve_loan_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_uses_requested_amount_as_fallback(self, mock_create_pending, mock_find, mock_approve, mock_update_tx, blockchain_settings):
        mock_app = MagicMock()
        mock_app.approved_amount = None
        mock_app.requested_amount = 50000
        mock_app.officer_notes = None
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_approve.return_value = {"tx_hash": "0x1", "gas_used": 1, "block_number": 1, "status": 1}

        sync_approval_to_chain("loan_id_2")

        mock_approve.assert_called_once_with(
            loan_id="loan_id_2",
            approved_amount=50000,
            notes_hash="approved",  # Fallback
        )


# ============================================================================
# sync_disbursement_to_chain
# ============================================================================

class TestSyncDisbursementToChain:
    def test_skips_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        result = sync_disbursement_to_chain("loan_id_1")
        assert result["skipped"] is True

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.disbursement_service.complete_disbursement_onchain")
    @patch("loans.blockchain.services.disbursement_service.set_method_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_success(self, mock_create_pending, mock_find, mock_set, mock_complete, mock_update_tx, blockchain_settings):
        mock_app = MagicMock()
        mock_app.disbursement_method = "gcash"
        mock_app.preferred_disbursement_method = None
        mock_app.disbursed_amount = 50000
        mock_app.approved_amount = 50000
        mock_app.requested_amount = 50000
        mock_app.disbursement_reference = "REF_001"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_set.return_value = {"tx_hash": "0xset", "gas_used": 50000, "block_number": 1, "status": 1}
        mock_complete.return_value = {
            "initiate_tx": {"tx_hash": "0xinit", "gas_used": 100000, "block_number": 2, "status": 1},
            "complete_tx": {"tx_hash": "0xcomplete", "gas_used": 120000, "block_number": 3, "status": 1},
        }

        result = sync_disbursement_to_chain("loan_id_1")

        assert result["tx_hash"] == "0xcomplete"
        mock_set.assert_called_once_with(loan_id="loan_id_1", method="gcash")

    @patch("loans.blockchain.tasks._update_application_tx")
    @patch("loans.blockchain.services.disbursement_service.complete_disbursement_onchain")
    @patch("loans.blockchain.services.disbursement_service.set_method_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_fallback_method_and_amount(self, mock_create_pending, mock_find, mock_set, mock_complete, mock_update_tx, blockchain_settings):
        mock_app = MagicMock()
        mock_app.disbursement_method = None
        mock_app.preferred_disbursement_method = "bank_transfer"
        mock_app.disbursed_amount = None
        mock_app.approved_amount = 40000
        mock_app.requested_amount = 50000
        mock_app.disbursement_reference = None
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_set.return_value = {"tx_hash": "0x1", "gas_used": 1, "block_number": 1, "status": 1}
        mock_complete.return_value = {
            "initiate_tx": {"tx_hash": "0x2", "gas_used": 1, "block_number": 1, "status": 1},
            "complete_tx": {"tx_hash": "0x3", "gas_used": 1, "block_number": 1, "status": 1},
        }

        sync_disbursement_to_chain("loan_id_2")

        mock_set.assert_called_once_with(loan_id="loan_id_2", method="bank_transfer")
        mock_complete.assert_called_once_with(
            loan_id="loan_id_2",
            amount=40000,
            reference_hash="DISB_loan_id_2",
        )


# ============================================================================
# sync_schedule_to_chain
# ============================================================================

class TestSyncScheduleToChain:
    def test_skips_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        result = sync_schedule_to_chain("loan_id_1")
        assert result["skipped"] is True

    @patch("loans.blockchain.services.repayment_service.create_schedule_onchain")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_success(self, mock_create_pending, mock_find, mock_create_sched, blockchain_settings, _mock_mongodb):
        # Insert schedule doc into mongomock
        from datetime import datetime, timezone

        schedule_doc = {
            "loan_id": "loan_sched_1",
            "customer_id": "cust_1",
            "principal": 50000,
            "interest_rate": 0.015,
            "term_months": 12,
            "monthly_payment": 4583,
            "total_amount": 55000,
            "total_interest": 5000,
            "installments": [],
            "start_date": datetime(2025, 1, 1),
            "created_at": datetime.now(timezone.utc),
            "blockchain_schedule_tx": "",
        }
        _mock_mongodb["repayment_schedules"].insert_one(schedule_doc)

        mock_find.return_value = MagicMock()
        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_create_sched.return_value = {"tx_hash": "0xsched", "gas_used": 200000, "block_number": 10, "status": 1}

        result = sync_schedule_to_chain("loan_sched_1")

        assert result["tx_hash"] == "0xsched"
        mock_tx.mark_confirmed.assert_called_once()

        # Verify the schedule doc was updated with tx hash
        updated = _mock_mongodb["repayment_schedules"].find_one({"loan_id": "loan_sched_1"})
        assert updated["blockchain_schedule_tx"] == "0xsched"

    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_schedule_not_found_retries(self, mock_create_pending, mock_find, blockchain_settings, _mock_mongodb):
        mock_find.return_value = MagicMock()
        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        with pytest.raises(ValueError, match="not found"):
            sync_schedule_to_chain("nonexistent_loan")


# ============================================================================
# sync_payment_to_chain
# ============================================================================

class TestSyncPaymentToChain:
    def test_skips_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        result = sync_payment_to_chain("loan_id_1", "pay_id_1")
        assert result["skipped"] is True

    @patch("loans.blockchain.services.repayment_service.record_payment_onchain")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_success(self, mock_create_pending, mock_record, blockchain_settings, _mock_mongodb):
        from bson import ObjectId

        # Insert payment doc
        payment_id = ObjectId()
        from datetime import datetime, timezone

        payment_doc = {
            "_id": payment_id,
            "loan_id": "loan_pay_1",
            "schedule_id": "sched_1",
            "customer_id": "cust_1",
            "installment_number": 3,
            "amount": 5000,
            "payment_method": "gcash",
            "reference": "PAY_REF_001",
            "notes": "",
            "recorded_by": "officer_1",
            "recorded_at": datetime.now(timezone.utc),
            "blockchain_tx_hash": "",
        }
        _mock_mongodb["loan_payments"].insert_one(payment_doc)

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        mock_record.return_value = {"tx_hash": "0xpayment", "gas_used": 80000, "block_number": 15, "status": 1}

        result = sync_payment_to_chain("loan_pay_1", str(payment_id))

        assert result["tx_hash"] == "0xpayment"
        mock_record.assert_called_once_with(
            loan_id="loan_pay_1",
            installment_number=3,
            amount=5000,
            payment_method="gcash",
            reference_hash="PAY_REF_001",
        )

        # Verify payment doc updated
        updated = _mock_mongodb["loan_payments"].find_one({"_id": payment_id})
        assert updated["blockchain_tx_hash"] == "0xpayment"

    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_payment_not_found_retries(self, mock_create_pending, blockchain_settings, _mock_mongodb):
        from bson import ObjectId

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        with pytest.raises(ValueError, match="not found"):
            sync_payment_to_chain("loan_pay_2", str(ObjectId()))


# ============================================================================
# Retry behavior
# ============================================================================

class TestRetryBehavior:
    def test_application_task_has_correct_retry_config(self):
        assert sync_application_to_chain.max_retries == 3
        assert sync_application_to_chain.default_retry_delay == 10

    def test_approval_task_has_correct_retry_config(self):
        assert sync_approval_to_chain.max_retries == 3

    def test_disbursement_task_has_correct_retry_config(self):
        assert sync_disbursement_to_chain.max_retries == 3

    def test_schedule_task_has_correct_retry_config(self):
        assert sync_schedule_to_chain.max_retries == 3

    def test_payment_task_has_correct_retry_config(self):
        assert sync_payment_to_chain.max_retries == 3

    @patch("loans.blockchain.services.application_service.create_application_onchain", side_effect=Exception("chain error"))
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_marks_failed_on_max_retries(self, mock_create_pending, mock_find, mock_create, blockchain_settings):
        mock_app = MagicMock()
        mock_app.product_id = "prod1"
        mock_app.requested_amount = 50000
        mock_app.term_months = 12
        mock_app.ai_recommendation = {}
        mock_app.eligibility_score = 0
        mock_app.risk_category = "low"
        mock_find.return_value = mock_app

        mock_tx = MagicMock()
        mock_create_pending.return_value = mock_tx

        # Simulate being on the last retry
        sync_application_to_chain.request.retries = 3

        with pytest.raises(Exception, match="chain error"):
            sync_application_to_chain("loan_fail")

        mock_tx.mark_failed.assert_called_once()
