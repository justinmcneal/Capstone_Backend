"""
Phase 1 — Backend Foundation tests for ETH Wallet Transfer.

Tests:
  1.1  wallet_address field in CustomerProfile
  1.2  wallet_address validation in serializer
  1.3  ETH price service (CryptoCompare, caching)
  1.4  send_eth_transfer() direct ETH transfer
"""

from unittest.mock import MagicMock, patch

import pytest

from profiles.models.profile_models import CustomerProfile
from profiles.serializers.profile_serializers import CustomerProfileSerializer
from loans.blockchain.services.eth_price_service import (
    ExchangeRateUnavailableError,
    get_eth_php_rate,
    php_to_eth,
    _cache,
    _CACHE_TTL,
)


# ── 1.1  CustomerProfile wallet_address ────────────────────────────

class TestCustomerProfileWalletAddress:
    def test_wallet_address_set_via_kwarg(self):
        p = CustomerProfile(
            customer_id="test",
            wallet_address="0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28",
        )
        assert p.wallet_address == "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28"

    def test_wallet_address_defaults_to_none(self):
        p = CustomerProfile(customer_id="test")
        assert p.wallet_address is None

    def test_wallet_address_in_to_dict(self):
        addr = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28"
        p = CustomerProfile(customer_id="test", wallet_address=addr)
        d = p.to_dict()
        assert "wallet_address" in d
        assert d["wallet_address"] == addr


# ── 1.2  Serializer validation ─────────────────────────────────────

class TestWalletAddressValidation:
    def _validate(self, value):
        s = CustomerProfileSerializer(data={"wallet_address": value}, partial=True)
        return s.is_valid(), s.errors

    def test_valid_eth_address(self):
        ok, _ = self._validate("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28")
        assert ok

    def test_blank_allowed(self):
        ok, _ = self._validate("")
        assert ok

    def test_none_allowed(self):
        ok, _ = self._validate(None)
        assert ok

    def test_rejects_missing_0x_prefix(self):
        ok, errs = self._validate("742d35Cc6634C0532925a3b844Bc9e7595f2bD28")
        assert not ok
        assert "wallet_address" in errs

    def test_rejects_too_short(self):
        ok, errs = self._validate("0x742d35Cc")
        assert not ok
        assert "wallet_address" in errs

    def test_rejects_invalid_hex(self):
        ok, errs = self._validate("0xZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ")
        assert not ok
        assert "wallet_address" in errs


# ── 1.3  ETH price service ─────────────────────────────────────────

class TestEthPriceService:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _cache.update(rate=None, source=None, fetched_at=0)
        yield
        _cache.update(rate=None, source=None, fetched_at=0)

    @patch("loans.blockchain.services.eth_price_service.requests.get")
    def test_fetches_rate_from_cryptocompare(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"PHP": 130000.0},
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = get_eth_php_rate()
        assert result["rate"] == 130000.0
        assert result["source"] == "cryptocompare"
        assert result["fetched_at"] > 0

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "cryptocompare" in args[0]
        assert kwargs["params"] == {"fsym": "ETH", "tsyms": "PHP"}

    @patch("loans.blockchain.services.eth_price_service.requests.get")
    def test_cache_prevents_duplicate_calls(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"PHP": 130000.0},
        )
        mock_get.return_value.raise_for_status = MagicMock()

        get_eth_php_rate()
        get_eth_php_rate()  # second call should be cached
        assert mock_get.call_count == 1

    @patch("loans.blockchain.services.eth_price_service.requests.get")
    def test_raises_when_api_unreachable(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        with pytest.raises(ExchangeRateUnavailableError):
            get_eth_php_rate()

    @patch("loans.blockchain.services.eth_price_service.requests.get")
    def test_php_to_eth_conversion(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"PHP": 100000.0},
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = php_to_eth(50000)
        assert result["eth_amount"] == pytest.approx(0.5, rel=1e-6)
        assert result["rate"] == 100000.0
        assert result["source"] == "cryptocompare"

    def test_cache_ttl_is_five_minutes(self):
        assert _CACHE_TTL == 300

    @patch("loans.blockchain.services.eth_price_service.requests.get")
    def test_no_api_key_in_request(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"PHP": 130000.0},
        )
        mock_get.return_value.raise_for_status = MagicMock()

        get_eth_php_rate()
        _, kwargs = mock_get.call_args
        # Only fsym and tsyms params — no api_key or authorization
        assert "api_key" not in kwargs.get("params", {})
        assert "apikey" not in kwargs.get("params", {})
        assert "Authorization" not in kwargs.get("headers", {})


# ── 1.4  send_eth_transfer (mocked web3) ──────────────────────────

class TestSendEthTransfer:
    @patch("loans.blockchain.client.get_account")
    @patch("loans.blockchain.client.get_web3")
    @patch("loans.blockchain.client._check_enabled")
    def test_send_eth_transfer_success(self, mock_check, mock_get_web3, mock_get_account):
        from loans.blockchain.client import send_eth_transfer

        mock_w3 = MagicMock()
        mock_get_web3.return_value = mock_w3

        mock_account = MagicMock()
        mock_account.address = "0x79Af1cD4Ffb33b8D9cbBC53d276e88Fbd05bA163"
        mock_account.sign_transaction.return_value = MagicMock(
            raw_transaction=b"signed_tx",
        )
        mock_get_account.return_value = mock_account

        mock_w3.eth.get_transaction_count.return_value = 5
        mock_w3.eth.gas_price = 20000000000

        mock_tx_hash = b"\x01" * 32
        mock_w3.eth.send_raw_transaction.return_value = mock_tx_hash

        # Receipt accessed via dict-style keys
        mock_receipt = {
            "transactionHash": mock_tx_hash,
            "status": 1,
            "gasUsed": 21000,
            "blockNumber": 42,
        }
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        result = send_eth_transfer(
            "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28",
            10000000000000000,  # 0.01 ETH in wei
        )

        assert result["status"] == 1
        assert result["gas_used"] == 21000
        assert result["block_number"] == 42
        assert result["amount_wei"] == 10000000000000000
        assert result["tx_hash"].startswith("0x")
