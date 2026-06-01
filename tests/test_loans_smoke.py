"""Smoke tests for loan services with mocked external dependencies."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from loans.blockchain.client import send_eth_transfer, send_transaction
from loans.services.qualification import qualify_customer


def test_ai_qualification_can_be_disabled(settings, monkeypatch):
    settings.LOANS_AI_QUALIFICATION_ENABLED = False

    product = SimpleNamespace(
        name="Test Product",
        min_amount=5000,
        max_amount=50000,
        min_business_months=6,
        min_monthly_income=5000,
        required_documents=["valid_id"],
    )
    data = {
        "personal": None,
        "business": SimpleNamespace(
            business_age_months=12,
            estimated_monthly_income=10000,
            is_registered=True,
        ),
        "alternative": SimpleNamespace(
            has_bank_account=True,
            has_ewallet=True,
            utility_payment_history="on_time",
        ),
        "documents": [],
    }

    monkeypatch.setattr(
        "loans.services.qualification.get_customer_data",
        lambda customer_id: data,
    )
    monkeypatch.setattr(
        "loans.services.qualification.get_llm_service",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    result = qualify_customer(
        customer_id="cust-1",
        product=product,
        requested_amount=10000,
        term_months=12,
        purpose="Working capital",
    )

    assert result["ai_used"] is False
    assert "AI disabled" in result["reasoning"]


@patch("loans.blockchain.client.get_account")
@patch("loans.blockchain.client.get_web3")
def test_blockchain_client_smoke_hash_formats(mock_get_web3, mock_get_account, blockchain_settings):
    mock_w3 = MagicMock()
    mock_w3.eth.get_transaction_count.return_value = 5
    mock_w3.eth.gas_price = 123
    mock_w3.eth.send_raw_transaction.return_value = b"\x01" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {
        "transactionHash": b"\xab" * 32,
        "status": 1,
        "gasUsed": 21000,
        "blockNumber": 10,
    }
    mock_w3.eth.contract.return_value = MagicMock()
    mock_w3.middleware_onion = MagicMock()
    mock_get_web3.return_value = mock_w3

    mock_acct = MagicMock()
    mock_acct.address = "0x1234567890123456789012345678901234567890"
    mock_acct.sign_transaction.return_value = MagicMock(raw_transaction=b"\x00" * 50)
    mock_get_account.return_value = mock_acct

    contract = MagicMock()
    fn_mock = MagicMock()
    fn_mock.estimate_gas.return_value = 21000
    fn_mock.build_transaction.return_value = {}
    contract.functions.__getitem__.return_value = lambda *a: fn_mock
    contract.address = "0xCONTRACT"

    result = send_transaction(contract, "testMethod", 1, 2)
    assert result["tx_hash"] == (b"\xab" * 32).hex()

    eth_result = send_eth_transfer(
        "0x5F034623bFD198980e8Af188702b871458E5d854",
        1000000000000000,
    )
    assert eth_result["tx_hash"].startswith("0x")
    assert len(eth_result["tx_hash"]) == 66
