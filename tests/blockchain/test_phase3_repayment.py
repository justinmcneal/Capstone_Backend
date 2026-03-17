"""
Phase 3 — Backend Repayment (Customer → System) tests.

Tests:
  3.1  WalletPaymentView — verify and record ETH wallet payments
  3.2  SystemWalletInfoView — return system wallet address and rate
  3.x  URL routes for wallet-payment and system-wallet
"""

import inspect
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from loans.views.customer_views import WalletPaymentView, SystemWalletInfoView


# ── 3.x  URL routes ───────────────────────────────────────────────

class TestPhase3UrlRoutes:
    def test_wallet_payment_route_exists(self):
        from django.urls import reverse, resolve
        url = reverse("loans:wallet-payment", kwargs={"application_id": "6650a1b2c3d4e5f6a7b8c9d0"})
        assert "wallet-payment" in url
        view = resolve(url)
        assert view.func.view_class is WalletPaymentView

    def test_system_wallet_route_exists(self):
        from django.urls import reverse, resolve
        url = reverse("loans:system-wallet")
        assert "system-wallet" in url
        view = resolve(url)
        assert view.func.view_class is SystemWalletInfoView


# ── 3.1  WalletPaymentView ────────────────────────────────────────

class TestWalletPaymentViewValidation:
    """Input validation tests (no mocking of blockchain needed)."""

    def test_view_exists_and_has_post_method(self):
        assert hasattr(WalletPaymentView, 'post')
        sig = inspect.signature(WalletPaymentView.post)
        params = list(sig.parameters.keys())
        assert 'request' in params
        assert 'application_id' in params

    def test_view_requires_authentication(self):
        from rest_framework.authentication import BaseAuthentication
        assert len(WalletPaymentView.authentication_classes) > 0

    def test_view_verifies_tx_hash_format(self):
        """Structural: view code checks tx_hash starts with 0x and is 66 chars."""
        source = inspect.getsource(WalletPaymentView)
        assert "startswith('0x')" in source
        assert "len(tx_hash)" in source

    def test_view_verifies_receipt_status(self):
        """Structural: view checks receipt['status'] != 1."""
        source = inspect.getsource(WalletPaymentView)
        assert "receipt['status']" in source or 'receipt["status"]' in source

    def test_view_verifies_recipient_is_system_wallet(self):
        """Structural: view checks tx['to'] matches system wallet."""
        source = inspect.getsource(WalletPaymentView)
        assert "system_address" in source
        assert "tx['to']" in source or 'tx["to"]' in source

    def test_view_verifies_sender_is_customer_wallet(self):
        """Structural: view checks tx['from'] matches customer's wallet_address."""
        source = inspect.getsource(WalletPaymentView)
        assert "wallet_address" in source
        assert "tx['from']" in source or 'tx["from"]' in source

    def test_view_has_amount_tolerance(self):
        """Structural: view uses ±2% tolerance for exchange rate fluctuations."""
        source = inspect.getsource(WalletPaymentView)
        assert "tolerance" in source
        assert "0.02" in source

    def test_view_checks_duplicate_tx_hash(self):
        """Structural: view checks for existing payment with same tx_hash."""
        source = inspect.getsource(WalletPaymentView)
        assert "eth_tx_hash" in source
        assert "already been recorded" in source

    def test_view_records_payment_with_wallet_method(self):
        """Structural: payment_method is set to 'wallet'."""
        source = inspect.getsource(WalletPaymentView)
        assert "payment_method='wallet'" in source

    def test_view_triggers_blockchain_sync(self):
        """Structural: sync_payment is called after recording."""
        source = inspect.getsource(WalletPaymentView)
        assert "sync_payment" in source

    def test_view_stores_eth_details_on_payment(self):
        """Structural: ETH-specific fields are stored."""
        source = inspect.getsource(WalletPaymentView)
        assert "eth_tx_hash" in source
        assert "eth_amount" in source
        assert "eth_rate" in source
        assert "eth_rate_source" in source
        assert "eth_sender" in source
        assert "eth_block_number" in source

    def test_view_creates_audit_log(self):
        """Structural: AuditLog.log_action is called."""
        source = inspect.getsource(WalletPaymentView)
        assert "AuditLog" in source
        assert "wallet_payment_verified" in source

    def test_view_returns_correct_success_fields(self):
        """Structural: response includes required fields."""
        source = inspect.getsource(WalletPaymentView)
        for field in ['status', 'payment_id', 'installment_number',
                      'amount_php', 'amount_eth', 'eth_rate',
                      'tx_hash', 'block_number']:
            assert f"'{field}'" in source, f"Missing field: {field}"


# ── 3.2  SystemWalletInfoView ─────────────────────────────────────

class TestSystemWalletInfoView:
    def test_view_exists_and_has_get_method(self):
        assert hasattr(SystemWalletInfoView, 'get')

    def test_view_requires_authentication(self):
        assert len(SystemWalletInfoView.authentication_classes) > 0

    def test_view_returns_all_required_fields(self):
        """Structural: response includes all required wallet info fields."""
        source = inspect.getsource(SystemWalletInfoView)
        for field in ['wallet_address', 'chain_id', 'rpc_url',
                      'eth_php_rate', 'rate_source']:
            assert f"'{field}'" in source, f"Missing field: {field}"

    def test_view_handles_blockchain_disabled(self):
        """Structural: returns 503 when blockchain is not enabled."""
        source = inspect.getsource(SystemWalletInfoView)
        assert "BLOCKCHAIN_ENABLED" in source
        assert "503" in source or "SERVICE_UNAVAILABLE" in source

    def test_view_handles_rate_unavailable(self):
        """Structural: returns 503 when exchange rate is unavailable."""
        source = inspect.getsource(SystemWalletInfoView)
        assert "ExchangeRateUnavailableError" in source

    def test_view_fetches_live_rate(self):
        """Structural: calls get_eth_php_rate for live rate."""
        source = inspect.getsource(SystemWalletInfoView)
        assert "get_eth_php_rate" in source

    def test_view_uses_cryptocompare_rate(self):
        """Structural: rate_info dict with rate and source keys."""
        source = inspect.getsource(SystemWalletInfoView)
        assert "rate_info['rate']" in source
        assert "rate_info['source']" in source


# ── Integration-style tests (mocked dependencies) ─────────────────

class TestWalletPaymentVerificationFlow:
    """Test the full verification logic with mocked blockchain."""

    def _make_request(self, data, customer_id="cust_123"):
        request = MagicMock()
        request.data = data
        request.user = MagicMock()
        request.user.customer_id = customer_id
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        return request

    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_missing_tx_hash(self, mock_perm):
        view = WalletPaymentView()
        request = self._make_request({"installment_number": 1})
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 400

    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_invalid_tx_hash_format(self, mock_perm):
        view = WalletPaymentView()
        request = self._make_request({
            "tx_hash": "not_a_valid_hash",
            "installment_number": 1
        })
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 400

    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_missing_installment_number(self, mock_perm):
        view = WalletPaymentView()
        request = self._make_request({
            "tx_hash": "0x" + "a" * 64
        })
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 400

    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_zero_installment_number(self, mock_perm):
        view = WalletPaymentView()
        request = self._make_request({
            "tx_hash": "0x" + "a" * 64,
            "installment_number": 0
        })
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 400

    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_if_loan_not_found(self, mock_perm, mock_find):
        mock_find.return_value = None
        view = WalletPaymentView()
        request = self._make_request({
            "tx_hash": "0x" + "a" * 64,
            "installment_number": 1
        })
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 404

    @patch("loans.models.application.LoanApplication.find_by_id")
    @patch.object(WalletPaymentView, 'check_customer_permission', return_value=(True, None))
    def test_rejects_if_loan_not_disbursed(self, mock_perm, mock_find):
        app = MagicMock()
        app.customer_id = "cust_123"
        app.status = "approved"  # not disbursed
        mock_find.return_value = app

        view = WalletPaymentView()
        request = self._make_request({
            "tx_hash": "0x" + "a" * 64,
            "installment_number": 1
        })
        response = view.post(request, "6650a1b2c3d4e5f6a7b8c9d0")
        assert response.status_code == 400


class TestSystemWalletInfoFlow:
    """Test system wallet info with mocked dependencies."""

    @patch("loans.blockchain.services.eth_price_service.get_eth_php_rate")
    @patch("loans.blockchain.client.get_web3")
    @patch("loans.blockchain.client.get_account")
    @patch.object(SystemWalletInfoView, 'check_customer_permission', return_value=(True, None))
    def test_returns_wallet_info(self, mock_perm, mock_account, mock_w3, mock_rate):
        mock_acc = MagicMock()
        mock_acc.address = "0x79Af1cD4Ffb33b8D9cbBC53d276e88Fbd05bA163"
        mock_account.return_value = mock_acc
        mock_w3.return_value = MagicMock()

        mock_rate.return_value = {
            "rate": 130000.0,
            "source": "cryptocompare",
            "fetched_at": 1710000000.0,
        }

        view = SystemWalletInfoView()
        request = MagicMock()
        request.user = MagicMock()

        with patch("loans.views.customer_views.settings") as mock_settings:
            mock_settings.BLOCKCHAIN_ENABLED = True
            mock_settings.BLOCKCHAIN_CHAIN_ID = 1337
            mock_settings.BLOCKCHAIN_RPC_URL = "http://127.0.0.1:7545"
            response = view.get(request)

        assert response.status_code == 200
        data = response.data['data']
        assert data['wallet_address'] == "0x79Af1cD4Ffb33b8D9cbBC53d276e88Fbd05bA163"
        assert data['chain_id'] == 1337
        assert data['eth_php_rate'] == 130000.0
        assert data['rate_source'] == "cryptocompare"

    @patch.object(SystemWalletInfoView, 'check_customer_permission', return_value=(True, None))
    def test_returns_503_when_blockchain_disabled(self, mock_perm):
        view = SystemWalletInfoView()
        request = MagicMock()
        request.user = MagicMock()

        with patch("loans.views.customer_views.settings") as mock_settings:
            mock_settings.BLOCKCHAIN_ENABLED = False
            response = view.get(request)

        assert response.status_code == 503
