"""
Root conftest — shared fixtures for all tests.

Uses mongomock to substitute MongoDB so tests run without a real database.
"""

import mongomock
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _mock_mongodb(settings):
    """
    Replace settings.MONGODB with a mongomock client for every test.
    This ensures tests never touch the real database.
    """
    client = mongomock.MongoClient()
    db = client["test_capstone"]
    settings.MONGODB = db
    yield db
    client.close()


@pytest.fixture(autouse=True)
def _use_locmem_cache(settings):
    """
    Ensure tests use an in-memory cache backend to avoid external Redis dependency.
    """
    settings.CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
    yield


@pytest.fixture
def blockchain_settings(settings):
    """Configure blockchain settings for testing."""
    settings.BLOCKCHAIN_ENABLED = True
    settings.BLOCKCHAIN_RPC_URL = "http://127.0.0.1:7545"
    settings.BLOCKCHAIN_CHAIN_ID = 1337
    settings.BLOCKCHAIN_WALLET_KEY = "0x" + "ab" * 32  # Fake 32-byte key
    settings.BLOCKCHAIN_GAS_LIMIT = 6721975
    settings.BLOCKCHAIN_GAS_PRICE_GWEI = 20
    settings.BLOCKCHAIN_ABI_DIR = "loans/blockchain/abis"
    settings.BLOCKCHAIN_CONTRACT_ADDRESSES = {
        "loanApplication": "0x1000000000000000000000000000000000000001",
        "loanReview": "0x1000000000000000000000000000000000000002",
        "loanApproval": "0x1000000000000000000000000000000000000003",
        "disbursementMethod": "0x1000000000000000000000000000000000000004",
        "disbursementExecution": "0x1000000000000000000000000000000000000005",
        "repaymentSchedule": "0x1000000000000000000000000000000000000006",
        "paymentRecording": "0x1000000000000000000000000000000000000007",
        "auditRegistry": "0x1000000000000000000000000000000000000008",
        "accessControl": "0x1000000000000000000000000000000000000009",
        "loanCore": "0x1000000000000000000000000000000000000010",
    }
    return settings


@pytest.fixture
def mock_tx_result():
    """Standard successful transaction result dict."""
    return {
        "tx_hash": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "gas_used": 150000,
        "block_number": 42,
        "status": 1,
    }


@pytest.fixture
def mock_web3():
    """A mocked Web3 instance."""
    w3 = MagicMock()
    w3.is_connected.return_value = True
    w3.eth.chain_id = 1337
    w3.eth.get_transaction_count.return_value = 0
    w3.eth.send_raw_transaction.return_value = b"\x00" * 32
    w3.eth.wait_for_transaction_receipt.return_value = {
        "transactionHash": b"\xab" * 32,
        "status": 1,
        "gasUsed": 150000,
        "blockNumber": 42,
    }
    return w3


@pytest.fixture
def mock_account():
    """A mocked Account object."""
    account = MagicMock()
    account.address = "0x934c667C8EeF61F34084331650e16BF9E85529f6"
    account.sign_transaction.return_value = MagicMock(raw_transaction=b"\x00" * 100)
    return account


@pytest.fixture
def mock_contract():
    """A mocked web3 Contract instance."""
    contract = MagicMock()
    contract.address = "0x1000000000000000000000000000000000000001"

    # Make functions[method](*args).build_transaction() and .call() work
    fn_mock = MagicMock()
    fn_mock.build_transaction.return_value = {
        "from": "0x934c667C8EeF61F34084331650e16BF9E85529f6",
        "nonce": 0,
        "gas": 6721975,
        "gasPrice": 20000000000,
        "chainId": 1337,
        "data": "0x",
    }
    fn_mock.call.return_value = (b"\x00" * 32,)
    contract.functions.__getitem__ = MagicMock(return_value=lambda *a: fn_mock)

    return contract
