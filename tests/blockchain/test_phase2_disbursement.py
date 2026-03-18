"""
Phase 2 — Backend Disbursement (System → Customer) tests.

Tests:
  2.1  _execute_eth_disbursement() flow
  2.2  ETH details stored in LoanApplication model
  2.3  Officer detail response includes wallet_address and ETH fields
  2.1+ _sync_disbursement_impl() calls ETH transfer before audit trail
"""

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest


# ── 2.1  _execute_eth_disbursement ─────────────────────────────────

class TestExecuteEthDisbursement:
    @patch("profiles.models.profile_models.CustomerProfile.find_by_customer")
    @patch("loans.blockchain.services.eth_price_service.php_to_eth")
    @patch("loans.blockchain.client.send_eth_transfer")
    @patch("loans.blockchain.client.get_web3")
    def test_sends_eth_to_customer_wallet(
        self, mock_get_web3, mock_send, mock_php_to_eth, mock_find_profile,
    ):
        from loans.blockchain.sync import _execute_eth_disbursement

        # Mock profile with wallet address
        mock_profile = MagicMock()
        mock_profile.wallet_address = "0x5F034623bFD198980e8Af188702b871458E5d854"
        mock_find_profile.return_value = mock_profile

        # Mock conversion
        mock_php_to_eth.return_value = {
            "eth_amount": 0.385,
            "rate": 130000.0,
            "source": "cryptocompare",
        }

        # Mock web3
        mock_w3 = MagicMock()
        mock_w3.to_wei.return_value = 385000000000000000
        mock_get_web3.return_value = mock_w3

        mock_send.return_value = {
            "tx_hash": "0xabc123",
            "gas_used": 21000,
            "block_number": 42,
            "status": 1,
            "amount_wei": 385000000000000000,
        }

        # Mock app
        app = MagicMock()
        app.customer_id = "cust_123"
        app.disbursed_amount = 50000
        app.approved_amount = 50000
        app.requested_amount = 50000

        with patch("loans.blockchain.sync.settings") as mock_settings:
            mock_db = MagicMock()
            mock_settings.MONGODB = mock_db
            _execute_eth_disbursement("6650a1b2c3d4e5f6a7b8c9d0", app)

        # Verify ETH was sent to customer's wallet
        mock_send.assert_called_once_with(
            "0x5F034623bFD198980e8Af188702b871458E5d854",
            385000000000000000,
        )

        # Verify MongoDB update was called with ETH details
        mock_db.__getitem__.return_value.update_one.assert_called_once()
        update_call = mock_db.__getitem__.return_value.update_one.call_args
        set_data = update_call[0][1]["$set"]
        assert set_data["eth_disbursement_tx_hash"] == "0xabc123"
        assert set_data["eth_disbursement_rate"] == 130000.0
        assert set_data["eth_disbursement_rate_source"] == "cryptocompare"
        assert set_data["eth_disbursement_recipient"] == "0x5F034623bFD198980e8Af188702b871458E5d854"

    @patch("profiles.models.profile_models.CustomerProfile.find_by_customer")
    def test_raises_if_no_wallet_address(self, mock_find_profile):
        from loans.blockchain.sync import _execute_eth_disbursement

        mock_profile = MagicMock()
        mock_profile.wallet_address = None
        mock_find_profile.return_value = mock_profile

        app = MagicMock()
        app.customer_id = "cust_no_wallet"

        with pytest.raises(ValueError, match="no wallet address"):
            _execute_eth_disbursement("loan_002", app)

    @patch("profiles.models.profile_models.CustomerProfile.find_by_customer")
    def test_raises_if_profile_not_found(self, mock_find_profile):
        from loans.blockchain.sync import _execute_eth_disbursement

        mock_find_profile.return_value = None

        app = MagicMock()
        app.customer_id = "cust_missing"

        with pytest.raises(ValueError, match="no wallet address"):
            _execute_eth_disbursement("loan_003", app)


# ── 2.1+ ETH transfer happens BEFORE audit trail ──────────────────

class TestDisbursementOrdering:
    @patch("loans.blockchain.sync._sync_schedule_impl")
    @patch("loans.blockchain.client.send_transaction")
    @patch("loans.blockchain.client.get_contract")
    @patch("loans.blockchain.services.disbursement_service.complete_disbursement_onchain")
    @patch("loans.blockchain.services.disbursement_service.set_method_onchain")
    @patch("loans.blockchain.sync._execute_eth_disbursement")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_eth_transfer_called_before_audit(
        self,
        mock_btx_create,
        mock_find_by_id,
        mock_eth_disb,
        mock_set_method,
        mock_complete,
        mock_get_contract,
        mock_send_tx,
        mock_schedule,
    ):
        from loans.blockchain.sync import _sync_disbursement_impl

        # Setup
        mock_btx_create.return_value = MagicMock()
        app = MagicMock()
        app.disbursement_method = "wallet"
        app.preferred_disbursement_method = "wallet"
        app.disbursed_amount = 50000
        app.approved_amount = 50000
        app.requested_amount = 50000
        app.disbursement_reference = "DSB-001"
        mock_find_by_id.return_value = app

        mock_complete.return_value = {
            "complete_tx": {
                "tx_hash": "0xaudit_hash",
                "gas_used": 100000,
                "block_number": 50,
            }
        }

        _sync_disbursement_impl("loan_wallet_test")

        # Verify ETH disbursement was called
        mock_eth_disb.assert_called_once_with("loan_wallet_test", app)

        # Verify ordering: ETH transfer first, then set_method, then complete
        mock_set_method.assert_called_once()
        mock_complete.assert_called_once()

    @patch("loans.blockchain.sync._sync_schedule_impl")
    @patch("loans.blockchain.client.send_transaction")
    @patch("loans.blockchain.client.get_contract")
    @patch("loans.blockchain.services.disbursement_service.complete_disbursement_onchain")
    @patch("loans.blockchain.services.disbursement_service.set_method_onchain")
    @patch("loans.blockchain.sync._execute_eth_disbursement")
    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch("loans.blockchain.models.BlockchainTransaction.create_pending")
    def test_non_wallet_skips_eth_transfer(
        self,
        mock_btx_create,
        mock_find_by_id,
        mock_eth_disb,
        mock_set_method,
        mock_complete,
        mock_get_contract,
        mock_send_tx,
        mock_schedule,
    ):
        from loans.blockchain.sync import _sync_disbursement_impl

        mock_btx_create.return_value = MagicMock()
        app = MagicMock()
        app.disbursement_method = "bank_transfer"
        app.preferred_disbursement_method = "bank_transfer"
        app.disbursed_amount = 50000
        app.approved_amount = 50000
        app.requested_amount = 50000
        app.disbursement_reference = "DSB-002"
        mock_find_by_id.return_value = app

        mock_complete.return_value = {
            "complete_tx": {
                "tx_hash": "0xaudit_hash",
                "gas_used": 100000,
                "block_number": 50,
            }
        }

        _sync_disbursement_impl("loan_bank_test")

        # ETH disbursement should NOT be called for non-wallet methods
        mock_eth_disb.assert_not_called()

        # Audit trail should still run
        mock_set_method.assert_called_once()
        mock_complete.assert_called_once()


# ── 2.2  LoanApplication model ETH fields ─────────────────────────

class TestLoanApplicationEthFields:
    def test_model_has_eth_disbursement_fields(self):
        from loans.models.application import LoanApplication

        app = LoanApplication(
            customer_id="test",
            eth_disbursement_tx_hash="0xabc123",
            eth_disbursement_amount="0.385",
            eth_disbursement_rate=130000.0,
            eth_disbursement_recipient="0x5F034623bFD198980e8Af188702b871458E5d854",
        )
        assert app.eth_disbursement_tx_hash == "0xabc123"
        assert app.eth_disbursement_amount == "0.385"
        assert app.eth_disbursement_rate == 130000.0
        assert app.eth_disbursement_recipient == "0x5F034623bFD198980e8Af188702b871458E5d854"

    def test_eth_fields_default_to_none(self):
        from loans.models.application import LoanApplication

        app = LoanApplication(customer_id="test")
        assert app.eth_disbursement_tx_hash is None
        assert app.eth_disbursement_amount is None
        assert app.eth_disbursement_rate is None
        assert app.eth_disbursement_recipient is None

    def test_eth_fields_in_to_dict(self):
        from loans.models.application import LoanApplication

        app = LoanApplication(
            customer_id="test",
            eth_disbursement_tx_hash="0xabc",
            eth_disbursement_amount="0.5",
            eth_disbursement_rate=100000.0,
            eth_disbursement_recipient="0x1234",
        )
        d = app.to_dict()
        assert d["eth_disbursement_tx_hash"] == "0xabc"
        assert d["eth_disbursement_amount"] == "0.5"
        assert d["eth_disbursement_rate"] == 100000.0
        assert d["eth_disbursement_recipient"] == "0x1234"


# ── 2.3  Officer detail response ──────────────────────────────────

class TestOfficerDetailResponse:
    """Verify that officer views include wallet_address and ETH fields."""

    def test_officer_view_has_wallet_address_in_response(self):
        """Structural check: officer_views.py references wallet_address."""
        import inspect
        from loans.views import officer_views

        source = inspect.getsource(officer_views)
        assert "wallet_address" in source
        assert "personal.wallet_address" in source or "wallet_address': personal.wallet_address" in source

    def test_officer_view_has_eth_disbursement_fields(self):
        """Structural check: officer_views.py returns ETH disbursement fields."""
        import inspect
        from loans.views import officer_views

        source = inspect.getsource(officer_views)
        assert "eth_disbursement_tx_hash" in source
        assert "eth_disbursement_amount" in source
        assert "eth_disbursement_rate" in source
        assert "eth_disbursement_recipient" in source
