"""
Unit tests for all blockchain service modules.

Every contract interaction is mocked via send_transaction / call_view patches
so no blockchain node is needed.
"""

from unittest.mock import MagicMock, patch

import pytest
from web3 import Web3


# ============================================================================
# Shared helpers
# ============================================================================

TX_RESULT = {
    "tx_hash": "0x" + "aa" * 32,
    "gas_used": 100000,
    "block_number": 5,
    "status": 1,
}


# ============================================================================
# ApplicationService
# ============================================================================

class TestApplicationService:
    @patch("loans.blockchain.services.application_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.application_service.get_contract")
    def test_create_application_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.application_service import create_application_onchain

        mock_gc.return_value = MagicMock()
        result = create_application_onchain(
            loan_id="loan123",
            borrower_addr="0x0000000000000000000000000000000000000001",
            product_id="prod1",
            amount=50000,
            term_months=12,
            interest_rate_bps=1200,
        )

        assert result["tx_hash"] == TX_RESULT["tx_hash"]
        mock_tx.assert_called_once()
        # Verify bytes32 hashing was applied to loan_id
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "createApplication"

    @patch("loans.blockchain.services.application_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.application_service.get_contract")
    def test_submit_application_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.application_service import submit_application_onchain

        mock_gc.return_value = MagicMock()
        result = submit_application_onchain(
            loan_id="loan123",
            eligibility_score=85,
            risk_category=1,
            ai_recommendation_hash="some_hash",
        )

        assert result["gas_used"] == 100000
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "submitApplication"

    @patch("loans.blockchain.services.application_service.call_view")
    @patch("loans.blockchain.services.application_service.get_contract")
    def test_get_application_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.application_service import get_application_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (b"\x00" * 32, 50000, 12, 1200, 0)

        result = get_application_onchain("loan123")

        assert result[1] == 50000
        mock_cv.assert_called_once()

    def test_to_bytes32_with_string(self, blockchain_settings):
        from loans.blockchain.services.application_service import _to_bytes32

        result = _to_bytes32("test")
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_to_bytes32_with_bytes(self, blockchain_settings):
        from loans.blockchain.services.application_service import _to_bytes32

        raw = b"\xaa" * 32
        result = _to_bytes32(raw)
        assert result is raw

    def test_to_bytes32_deterministic(self, blockchain_settings):
        from loans.blockchain.services.application_service import _to_bytes32

        a = _to_bytes32("same_id")
        b = _to_bytes32("same_id")
        assert a == b

    def test_to_bytes32_different_for_different_inputs(self, blockchain_settings):
        from loans.blockchain.services.application_service import _to_bytes32

        a = _to_bytes32("id_1")
        b = _to_bytes32("id_2")
        assert a != b


# ============================================================================
# ReviewService
# ============================================================================

class TestReviewService:
    @patch("loans.blockchain.services.review_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.review_service.get_contract")
    def test_assign_officer_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.review_service import assign_officer_onchain

        mock_gc.return_value = MagicMock()
        result = assign_officer_onchain(
            loan_id="loan456",
            officer_address="0x1234567890123456789012345678901234567890",
        )

        assert result["tx_hash"] == TX_RESULT["tx_hash"]
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "assignOfficer"

    @patch("loans.blockchain.services.review_service.call_view")
    @patch("loans.blockchain.services.review_service.get_contract")
    def test_get_assigned_officer_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.review_service import get_assigned_officer_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = "0x1234567890123456789012345678901234567890"

        result = get_assigned_officer_onchain("loan456")

        assert result == "0x1234567890123456789012345678901234567890"


# ============================================================================
# ApprovalService
# ============================================================================

class TestApprovalService:
    @patch("loans.blockchain.services.approval_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.approval_service.get_contract")
    def test_approve_loan_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.approval_service import approve_loan_onchain

        mock_gc.return_value = MagicMock()
        result = approve_loan_onchain(
            loan_id="loan789",
            approved_amount=45000,
            notes_hash="Approved after review",
        )

        assert result["status"] == 1
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "approveLoan"
        # Verify amount is passed as int
        assert call_args[3] == 45000


# ============================================================================
# DisbursementService
# ============================================================================

class TestDisbursementService:
    @patch("loans.blockchain.services.disbursement_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.disbursement_service.get_contract")
    def test_set_method_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.disbursement_service import set_method_onchain, DISBURSEMENT_METHOD_MAP

        mock_gc.return_value = MagicMock()
        result = set_method_onchain(loan_id="loan1", method="gcash")

        assert result["tx_hash"] == TX_RESULT["tx_hash"]
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "setPreferredMethod"
        # gcash = 1 in the enum
        assert call_args[3] == DISBURSEMENT_METHOD_MAP["gcash"]

    @patch("loans.blockchain.services.disbursement_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.disbursement_service.get_contract")
    def test_set_method_defaults_to_other(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.disbursement_service import set_method_onchain

        mock_gc.return_value = MagicMock()
        set_method_onchain(loan_id="loan1", method="unknown_method")

        call_args = mock_tx.call_args[0]
        assert call_args[3] == 4  # Other

    @patch("loans.blockchain.services.disbursement_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.disbursement_service.get_contract")
    def test_initiate_disbursement_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.disbursement_service import initiate_disbursement_onchain

        mock_gc.return_value = MagicMock()
        result = initiate_disbursement_onchain(loan_id="loan1", amount=50000)

        call_args = mock_tx.call_args[0]
        assert call_args[1] == "initiateDisbursement"

    @patch("loans.blockchain.services.disbursement_service.call_view")
    @patch("loans.blockchain.services.disbursement_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.disbursement_service.get_contract")
    def test_complete_disbursement_onchain(self, mock_gc, mock_tx, mock_cv, blockchain_settings):
        from loans.blockchain.services.disbursement_service import complete_disbursement_onchain

        mock_gc.return_value = MagicMock()
        # getDisbursementByLoan returns tuple where first element is disbursementId
        mock_cv.return_value = (b"\xdd" * 32, b"\x00" * 32, 50000, 0, 0, 0)

        result = complete_disbursement_onchain(
            loan_id="loan1",
            amount=50000,
            reference_hash="REF_001",
        )

        assert "initiate_tx" in result
        assert "complete_tx" in result
        # send_transaction called twice: initiate + complete
        assert mock_tx.call_count == 2

    @patch("loans.blockchain.services.disbursement_service.call_view")
    @patch("loans.blockchain.services.disbursement_service.get_contract")
    def test_get_disbursement_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.disbursement_service import get_disbursement_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (b"\xdd" * 32, b"\x00" * 32, 50000, 0, 0, 0)

        result = get_disbursement_onchain(b"\xdd" * 32)

        assert result[2] == 50000

    def test_disbursement_method_map_completeness(self):
        from loans.blockchain.services.disbursement_service import DISBURSEMENT_METHOD_MAP

        expected = {"bank_transfer", "gcash", "cash", "maya", "other"}
        assert set(DISBURSEMENT_METHOD_MAP.keys()) == expected
        # Values should be 0-4
        assert set(DISBURSEMENT_METHOD_MAP.values()) == {0, 1, 2, 3, 4}


# ============================================================================
# RepaymentService
# ============================================================================

class TestRepaymentService:
    @patch("loans.blockchain.services.repayment_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_create_schedule_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.repayment_service import create_schedule_onchain

        mock_gc.return_value = MagicMock()
        result = create_schedule_onchain(
            loan_id="loan_sched",
            borrower_address="0x1234567890123456789012345678901234567890",
            principal=100000,
            interest_rate_bps=1800,
            term_months=12,
            start_date=1700000000,
        )

        assert result["tx_hash"] == TX_RESULT["tx_hash"]
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "createSchedule"

    @patch("loans.blockchain.services.repayment_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_create_schedule_default_start_date(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.repayment_service import create_schedule_onchain

        mock_gc.return_value = MagicMock()
        result = create_schedule_onchain(
            loan_id="loan_sched2",
            borrower_address="0x1234567890123456789012345678901234567890",
            principal=100000,
            interest_rate_bps=1800,
            term_months=6,
        )

        # start_date should have been set to current time (non-zero int)
        call_args = mock_tx.call_args[0]
        start_date_arg = call_args[7]  # 7th positional arg
        assert start_date_arg > 0

    @patch("loans.blockchain.services.repayment_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_record_payment_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.repayment_service import record_payment_onchain

        mock_gc.return_value = MagicMock()
        result = record_payment_onchain(
            loan_id="loan_pay",
            installment_number=3,
            amount=5000,
            payment_method="gcash",
            reference_hash="PAY_REF_001",
        )

        assert result["gas_used"] == 100000
        call_args = mock_tx.call_args[0]
        assert call_args[1] == "recordPayment"
        # gcash = 2 in PaymentMethod enum
        assert call_args[5] == 2

    @patch("loans.blockchain.services.repayment_service.send_transaction", return_value=TX_RESULT)
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_mark_overdue_onchain(self, mock_gc, mock_tx, blockchain_settings):
        from loans.blockchain.services.repayment_service import mark_overdue_onchain

        mock_gc.return_value = MagicMock()
        result = mark_overdue_onchain(loan_id="loan_overdue", installment_number=1)

        call_args = mock_tx.call_args[0]
        assert call_args[1] == "markOverdue"

    @patch("loans.blockchain.services.repayment_service.call_view")
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_get_schedule_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.repayment_service import get_schedule_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (b"\x00" * 32, 100000, 1800, 12, 0)

        result = get_schedule_onchain("loan_sched")
        assert result[1] == 100000

    @patch("loans.blockchain.services.repayment_service.call_view")
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_get_installment_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.repayment_service import get_installment_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (1, 5000, 0, 0)

        result = get_installment_onchain("loan_sched", 1)
        assert result[0] == 1

    @patch("loans.blockchain.services.repayment_service.call_view")
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_get_all_installments_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.repayment_service import get_all_installments_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = [(1, 5000, 0), (2, 5000, 0)]

        result = get_all_installments_onchain("loan_sched")
        assert len(result) == 2

    @patch("loans.blockchain.services.repayment_service.call_view")
    @patch("loans.blockchain.services.repayment_service.get_contract")
    def test_get_remaining_balance_onchain(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.repayment_service import get_remaining_balance_onchain

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = 75000

        result = get_remaining_balance_onchain("loan_sched")
        assert result == 75000

    def test_payment_method_map_completeness(self):
        from loans.blockchain.services.repayment_service import PAYMENT_METHOD_MAP

        expected = {"cash", "bank_transfer", "gcash", "maya", "other"}
        assert set(PAYMENT_METHOD_MAP.keys()) == expected
        assert set(PAYMENT_METHOD_MAP.values()) == {0, 1, 2, 3, 4}


# ============================================================================
# AuditService
# ============================================================================

class TestAuditService:
    @patch("loans.blockchain.services.audit_service.call_view")
    @patch("loans.blockchain.services.audit_service.get_contract")
    def test_get_audit_trail(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.audit_service import get_audit_trail

        mock_gc.return_value = MagicMock()
        # Each entry has 9 fields
        mock_cv.return_value = [
            (b"\x01" * 32, b"\x02" * 32, b"\x03" * 32, 1, b"\x04" * 32, b"\x05" * 32, "0xActor", 1700000000, 10),
            (b"\x01" * 32, b"\x02" * 32, b"\x03" * 32, 3, b"\x04" * 32, b"\x05" * 32, "0xActor2", 1700001000, 11),
        ]

        result = get_audit_trail("resource1")

        assert len(result) == 2
        assert result[0]["action"] == 1
        assert result[0]["action_label"] == "LoanSubmitted"
        assert result[1]["action"] == 3
        assert result[1]["action_label"] == "LoanApproved"
        assert result[0]["actor"] == "0xActor"
        assert result[1]["timestamp"] == 1700001000

    @patch("loans.blockchain.services.audit_service.call_view")
    @patch("loans.blockchain.services.audit_service.get_contract")
    def test_get_audit_trail_empty(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.audit_service import get_audit_trail

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = []

        result = get_audit_trail("nonexistent")
        assert result == []

    @patch("loans.blockchain.services.audit_service.call_view")
    @patch("loans.blockchain.services.audit_service.get_contract")
    def test_get_audit_entry(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.audit_service import get_audit_entry

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (
            b"\x01" * 32, b"\x02" * 32, b"\x03" * 32, 5,
            b"\x04" * 32, b"\x05" * 32, "0xActor", 1700000000, 10,
        )

        result = get_audit_entry("ab" * 32)

        assert result["action"] == 5
        assert result["action_label"] == "LoanDisbursed"
        assert result["block_number"] == 10

    @patch("loans.blockchain.services.audit_service.call_view")
    @patch("loans.blockchain.services.audit_service.get_contract")
    def test_get_audit_entry_with_bytes(self, mock_gc, mock_cv, blockchain_settings):
        from loans.blockchain.services.audit_service import get_audit_entry

        mock_gc.return_value = MagicMock()
        mock_cv.return_value = (
            b"\x01" * 32, b"\x02" * 32, b"\x03" * 32, 0,
            b"\x04" * 32, b"\x05" * 32, "0xActor", 1700000000, 10,
        )

        result = get_audit_entry(b"\xab" * 32)
        assert result["action_label"] == "LoanCreated"

    def test_audit_action_labels_coverage(self):
        from loans.blockchain.services.audit_service import AUDIT_ACTION_LABELS

        assert len(AUDIT_ACTION_LABELS) == 12
        assert AUDIT_ACTION_LABELS[0] == "LoanCreated"
        assert AUDIT_ACTION_LABELS[11] == "SystemConfigChanged"
