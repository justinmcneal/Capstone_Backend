"""
Unit tests for loans.blockchain.exceptions.
"""

import pytest

from loans.blockchain.exceptions import (
    BlockchainError,
    BlockchainConnectionError,
    BlockchainDisabledError,
    BlockchainTransactionFailed,
    ContractNotFoundError,
)


class TestExceptions:
    def test_hierarchy(self):
        assert issubclass(BlockchainConnectionError, BlockchainError)
        assert issubclass(BlockchainTransactionFailed, BlockchainError)
        assert issubclass(ContractNotFoundError, BlockchainError)
        assert issubclass(BlockchainDisabledError, BlockchainError)
        assert issubclass(BlockchainError, Exception)

    def test_transaction_failed_attributes(self):
        exc = BlockchainTransactionFailed(
            "reverted",
            tx_hash="0xabc",
            receipt={"status": 0},
        )
        assert str(exc) == "reverted"
        assert exc.tx_hash == "0xabc"
        assert exc.receipt == {"status": 0}

    def test_transaction_failed_defaults(self):
        exc = BlockchainTransactionFailed("error")
        assert exc.tx_hash is None
        assert exc.receipt is None

    def test_contract_not_found_attributes(self):
        exc = ContractNotFoundError("loanApplication")
        assert exc.contract_name == "loanApplication"
        assert "loanApplication" in str(exc)

    def test_blockchain_disabled_error(self):
        exc = BlockchainDisabledError("Blockchain is off")
        assert str(exc) == "Blockchain is off"

    def test_exceptions_are_catchable_as_base(self):
        with pytest.raises(BlockchainError):
            raise BlockchainConnectionError("test")

        with pytest.raises(BlockchainError):
            raise ContractNotFoundError("test")

        with pytest.raises(BlockchainError):
            raise BlockchainTransactionFailed("test")

        with pytest.raises(BlockchainError):
            raise BlockchainDisabledError("test")
