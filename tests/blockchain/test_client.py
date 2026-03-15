"""
Unit tests for loans.blockchain.client module.

All Web3/network calls are mocked so tests run without a blockchain node.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from web3 import Web3

from loans.blockchain.client import (
    _check_enabled,
    _load_abi,
    clear_cache,
    get_web3,
    get_account,
    get_contract,
    send_transaction,
    call_view,
    _contract_cache,
)
from loans.blockchain.exceptions import (
    BlockchainConnectionError,
    BlockchainDisabledError,
    BlockchainTransactionFailed,
    ContractNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_caches():
    """Ensure caches are clean before and after each test."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# _check_enabled
# ---------------------------------------------------------------------------

class TestCheckEnabled:
    def test_raises_when_disabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            _check_enabled()

    def test_passes_when_enabled(self, settings):
        settings.BLOCKCHAIN_ENABLED = True
        _check_enabled()  # Should not raise


# ---------------------------------------------------------------------------
# get_web3
# ---------------------------------------------------------------------------

class TestGetWeb3:
    def test_disabled_raises(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            get_web3()

    @patch("loans.blockchain.client.Web3")
    def test_returns_connected_instance(self, MockWeb3, blockchain_settings):
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.chain_id = 1337
        mock_w3.middleware_onion = MagicMock()
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()

        w3 = get_web3()

        assert w3 is mock_w3
        mock_w3.middleware_onion.inject.assert_called_once()

    @patch("loans.blockchain.client.Web3")
    def test_raises_when_not_connected(self, MockWeb3, blockchain_settings):
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = False
        mock_w3.middleware_onion = MagicMock()
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()

        with pytest.raises(BlockchainConnectionError, match="Cannot connect"):
            get_web3()

    @patch("loans.blockchain.client.Web3")
    def test_caches_result(self, MockWeb3, blockchain_settings):
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.chain_id = 1337
        mock_w3.middleware_onion = MagicMock()
        MockWeb3.return_value = mock_w3
        MockWeb3.HTTPProvider = MagicMock()

        w3_a = get_web3()
        w3_b = get_web3()

        assert w3_a is w3_b
        # Web3() constructor only called once thanks to lru_cache
        assert MockWeb3.call_count == 1


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------

class TestGetAccount:
    def test_disabled_raises(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            get_account()

    @patch("loans.blockchain.client.get_web3")
    def test_returns_account_from_key(self, mock_get_web3, blockchain_settings):
        mock_w3 = MagicMock()
        mock_account = MagicMock()
        mock_account.address = "0xABCD"
        mock_w3.eth.account.from_key.return_value = mock_account
        mock_get_web3.return_value = mock_w3

        account = get_account()

        assert account.address == "0xABCD"
        # Key should have 0x prefix
        mock_w3.eth.account.from_key.assert_called_once()

    @patch("loans.blockchain.client.get_web3")
    def test_raises_when_no_key(self, mock_get_web3, blockchain_settings):
        blockchain_settings.BLOCKCHAIN_WALLET_KEY = ""
        mock_get_web3.return_value = MagicMock()

        with pytest.raises(BlockchainConnectionError, match="BLOCKCHAIN_WALLET_KEY"):
            get_account()

    @patch("loans.blockchain.client.get_web3")
    def test_adds_0x_prefix_if_missing(self, mock_get_web3, blockchain_settings):
        blockchain_settings.BLOCKCHAIN_WALLET_KEY = "ab" * 32  # no 0x prefix
        mock_w3 = MagicMock()
        mock_w3.eth.account.from_key.return_value = MagicMock()
        mock_get_web3.return_value = mock_w3

        get_account()

        call_arg = mock_w3.eth.account.from_key.call_args[0][0]
        assert call_arg.startswith("0x")


# ---------------------------------------------------------------------------
# _load_abi
# ---------------------------------------------------------------------------

class TestLoadAbi:
    def test_loads_existing_abi(self, blockchain_settings, tmp_path):
        # Create a temp ABI file
        abi_dir = tmp_path / "abis"
        abi_dir.mkdir()
        abi_file = abi_dir / "TestContract.json"
        abi_data = [{"type": "function", "name": "foo"}]
        abi_file.write_text(json.dumps(abi_data))

        blockchain_settings.BLOCKCHAIN_ABI_DIR = str(abi_dir)

        result = _load_abi("TestContract")
        assert result == abi_data

    def test_raises_for_missing_abi(self, blockchain_settings, tmp_path):
        abi_dir = tmp_path / "abis"
        abi_dir.mkdir()
        blockchain_settings.BLOCKCHAIN_ABI_DIR = str(abi_dir)

        with pytest.raises(ContractNotFoundError):
            _load_abi("NonExistent")


# ---------------------------------------------------------------------------
# get_contract
# ---------------------------------------------------------------------------

class TestGetContract:
    def test_disabled_raises(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            get_contract("loanApplication")

    @patch("loans.blockchain.client._load_abi")
    @patch("loans.blockchain.client.get_web3")
    def test_returns_contract_instance(self, mock_get_web3, mock_load_abi, blockchain_settings):
        mock_abi = [{"type": "function", "name": "createApplication"}]
        mock_load_abi.return_value = mock_abi
        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract
        mock_get_web3.return_value = mock_w3

        result = get_contract("loanApplication")

        assert result is mock_contract
        mock_load_abi.assert_called_once_with("LoanApplication")

    @patch("loans.blockchain.client._load_abi")
    @patch("loans.blockchain.client.get_web3")
    def test_caches_contract(self, mock_get_web3, mock_load_abi, blockchain_settings):
        mock_load_abi.return_value = []
        mock_w3 = MagicMock()
        mock_w3.eth.contract.return_value = MagicMock()
        mock_get_web3.return_value = mock_w3

        c1 = get_contract("loanApplication")
        c2 = get_contract("loanApplication")

        assert c1 is c2
        assert mock_load_abi.call_count == 1

    def test_raises_for_unknown_key(self, blockchain_settings):
        # Key exists in settings but not in CONTRACT_NAME_MAP
        blockchain_settings.BLOCKCHAIN_CONTRACT_ADDRESSES["bogusKey"] = "0x0000000000000000000000000000000000000099"
        with pytest.raises(ContractNotFoundError):
            get_contract("bogusKey")

    def test_raises_for_missing_address(self, blockchain_settings):
        # Key is in CONTRACT_NAME_MAP but has no address
        blockchain_settings.BLOCKCHAIN_CONTRACT_ADDRESSES = {}
        with pytest.raises(ContractNotFoundError):
            get_contract("loanApplication")


# ---------------------------------------------------------------------------
# send_transaction
# ---------------------------------------------------------------------------

class TestSendTransaction:
    def test_disabled_raises(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            send_transaction(MagicMock(), "foo")

    @patch("loans.blockchain.client.get_account")
    @patch("loans.blockchain.client.get_web3")
    def test_successful_transaction(self, mock_get_web3, mock_get_account, blockchain_settings):
        mock_w3 = MagicMock()
        mock_w3.eth.get_transaction_count.return_value = 5
        mock_w3.eth.send_raw_transaction.return_value = b"\xab" * 32
        mock_w3.eth.wait_for_transaction_receipt.return_value = {
            "transactionHash": b"\xab" * 32,
            "status": 1,
            "gasUsed": 120000,
            "blockNumber": 10,
        }
        mock_get_web3.return_value = mock_w3

        mock_acct = MagicMock()
        mock_acct.address = "0x1234567890123456789012345678901234567890"
        mock_acct.sign_transaction.return_value = MagicMock(raw_transaction=b"\x00" * 50)
        mock_get_account.return_value = mock_acct

        # Build a mock contract with a callable function
        contract = MagicMock()
        fn_mock = MagicMock()
        fn_mock.build_transaction.return_value = {"nonce": 5}
        contract.functions.__getitem__.return_value = lambda *a: fn_mock
        contract.address = "0xCONTRACT"

        result = send_transaction(contract, "testMethod", 1, 2)

        assert result["gas_used"] == 120000
        assert result["block_number"] == 10
        assert result["status"] == 1
        assert result["tx_hash"] == (b"\xab" * 32).hex()

    @patch("loans.blockchain.client.get_account")
    @patch("loans.blockchain.client.get_web3")
    def test_reverted_transaction_raises(self, mock_get_web3, mock_get_account, blockchain_settings):
        mock_w3 = MagicMock()
        mock_w3.eth.get_transaction_count.return_value = 0
        mock_w3.eth.send_raw_transaction.return_value = b"\xab" * 32
        mock_w3.eth.wait_for_transaction_receipt.return_value = {
            "transactionHash": b"\xab" * 32,
            "status": 0,  # Reverted!
            "gasUsed": 21000,
            "blockNumber": 11,
        }
        mock_get_web3.return_value = mock_w3

        mock_acct = MagicMock()
        mock_acct.address = "0x1234567890123456789012345678901234567890"
        mock_acct.sign_transaction.return_value = MagicMock(raw_transaction=b"\x00")
        mock_get_account.return_value = mock_acct

        contract = MagicMock()
        fn_mock = MagicMock()
        fn_mock.build_transaction.return_value = {}
        contract.functions.__getitem__.return_value = lambda *a: fn_mock
        contract.address = "0xCONTRACT"

        with pytest.raises(BlockchainTransactionFailed, match="reverted"):
            send_transaction(contract, "badMethod")


# ---------------------------------------------------------------------------
# call_view
# ---------------------------------------------------------------------------

class TestCallView:
    def test_disabled_raises(self, settings):
        settings.BLOCKCHAIN_ENABLED = False
        with pytest.raises(BlockchainDisabledError):
            call_view(MagicMock(), "foo")

    def test_returns_call_result(self, blockchain_settings):
        contract = MagicMock()
        fn_mock = MagicMock()
        fn_mock.call.return_value = (42, "hello")
        contract.functions.__getitem__.return_value = lambda *a: fn_mock

        result = call_view(contract, "someView", "arg1")

        assert result == (42, "hello")


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------

class TestClearCache:
    @patch("loans.blockchain.client._load_abi")
    @patch("loans.blockchain.client.get_web3")
    def test_clears_all_caches(self, mock_get_web3, mock_load_abi, blockchain_settings):
        mock_load_abi.return_value = []
        mock_w3 = MagicMock()
        mock_w3.eth.contract.return_value = MagicMock()
        mock_get_web3.return_value = mock_w3

        get_contract("loanApplication")
        assert "loanApplication" in _contract_cache

        clear_cache()

        assert len(_contract_cache) == 0
