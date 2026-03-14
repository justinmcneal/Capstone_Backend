"""
Unit tests for loans.blockchain.models (BlockchainTransaction).

Uses mongomock via the _mock_mongodb fixture from conftest.
"""

import pytest
from datetime import datetime

from loans.blockchain.models import BlockchainTransaction


class TestBlockchainTransaction:
    """Tests for the BlockchainTransaction MongoDB model."""

    def test_create_pending(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_001",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )

        assert tx._id is not None
        assert tx.loan_id == "loan_001"
        assert tx.action == "submit"
        assert tx.status == BlockchainTransaction.STATUS_PENDING
        assert tx.tx_hash == ""
        assert tx.gas_used == 0

    def test_create_pending_with_details(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_002",
            action="payment",
            contract_name="PaymentRecording",
            method="recordPayment",
            details={"payment_id": "pay_123"},
        )

        assert tx.details == {"payment_id": "pay_123"}

    def test_mark_confirmed(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_003",
            action="approve",
            contract_name="LoanApproval",
            method="approveLoan",
        )

        tx.mark_confirmed(
            tx_hash="0xabc123",
            gas_used=150000,
            block_number=42,
        )

        assert tx.status == BlockchainTransaction.STATUS_CONFIRMED
        assert tx.tx_hash == "0xabc123"
        assert tx.gas_used == 150000
        assert tx.block_number == 42
        assert tx.completed_at is not None

    def test_mark_failed(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_004",
            action="disburse",
            contract_name="DisbursementExecution",
            method="completeDisbursement",
        )

        tx.mark_failed("Transaction reverted: out of gas")

        assert tx.status == BlockchainTransaction.STATUS_FAILED
        assert "out of gas" in tx.error
        assert tx.completed_at is not None

    def test_mark_failed_truncates_long_error(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_005",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )

        long_error = "x" * 3000
        tx.mark_failed(long_error)

        assert len(tx.error) == 2000

    def test_find_by_loan(self, _mock_mongodb):
        # Create multiple transactions for the same loan
        BlockchainTransaction.create_pending(
            loan_id="loan_010",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )
        BlockchainTransaction.create_pending(
            loan_id="loan_010",
            action="approve",
            contract_name="LoanApproval",
            method="approveLoan",
        )
        # Different loan
        BlockchainTransaction.create_pending(
            loan_id="loan_999",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )

        results = BlockchainTransaction.find_by_loan("loan_010")

        assert len(results) == 2
        actions = {r.action for r in results}
        assert actions == {"submit", "approve"}

    def test_find_by_loan_empty(self, _mock_mongodb):
        results = BlockchainTransaction.find_by_loan("nonexistent")
        assert results == []

    def test_find_by_loan_and_action(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_020",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )
        tx.mark_confirmed(tx_hash="0xfound", gas_used=100, block_number=1)

        # Also create a pending one — should not be found
        BlockchainTransaction.create_pending(
            loan_id="loan_020",
            action="approve",
            contract_name="LoanApproval",
            method="approveLoan",
        )

        found = BlockchainTransaction.find_by_loan_and_action("loan_020", "submit")
        assert found is not None
        assert found.tx_hash == "0xfound"

    def test_find_by_loan_and_action_not_found(self, _mock_mongodb):
        found = BlockchainTransaction.find_by_loan_and_action("nonexistent", "submit")
        assert found is None

    def test_to_dict(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_030",
            action="schedule",
            contract_name="RepaymentSchedule",
            method="createSchedule",
        )

        d = tx.to_dict()

        assert d["loan_id"] == "loan_030"
        assert d["action"] == "schedule"
        assert d["status"] == "pending"
        assert "_id" in d

    def test_to_dict_without_id(self):
        tx = BlockchainTransaction(loan_id="loan_040", action="test")
        d = tx.to_dict()
        assert "_id" not in d

    def test_id_property(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_050",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )

        assert tx.id is not None
        assert isinstance(tx.id, str)

    def test_id_property_none_when_no_id(self):
        tx = BlockchainTransaction()
        assert tx.id is None

    def test_save_updates_existing(self, _mock_mongodb):
        tx = BlockchainTransaction.create_pending(
            loan_id="loan_060",
            action="submit",
            contract_name="LoanApplication",
            method="createApplication",
        )
        original_id = tx._id

        tx.status = "confirmed"
        tx.tx_hash = "0xupdated"
        tx.save()

        # Re-fetch from DB
        results = BlockchainTransaction.find_by_loan("loan_060")
        assert len(results) == 1
        assert results[0].tx_hash == "0xupdated"
        assert results[0]._id == original_id

    def test_collection_returns_none_when_no_db(self):
        """When MONGODB is None, operations should be graceful."""
        from loans.blockchain import models as m
        original_fn = m._get_collection

        def mock_none():
            return None

        m._get_collection = mock_none
        try:
            tx = BlockchainTransaction(loan_id="test")
            result = tx.save()
            assert result is tx  # Should return self without error

            results = BlockchainTransaction.find_by_loan("test")
            assert results == []

            found = BlockchainTransaction.find_by_loan_and_action("test", "submit")
            assert found is None
        finally:
            m._get_collection = original_fn
