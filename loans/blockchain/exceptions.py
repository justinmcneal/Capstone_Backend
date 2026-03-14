"""Custom exceptions for blockchain operations."""


class BlockchainError(Exception):
    """Base exception for all blockchain-related errors."""
    pass


class BlockchainConnectionError(BlockchainError):
    """Raised when unable to connect to the blockchain RPC provider."""
    pass


class BlockchainTransactionFailed(BlockchainError):
    """Raised when a transaction reverts or fails on-chain."""

    def __init__(self, message, tx_hash=None, receipt=None):
        super().__init__(message)
        self.tx_hash = tx_hash
        self.receipt = receipt


class ContractNotFoundError(BlockchainError):
    """Raised when a contract name has no configured address or ABI."""

    def __init__(self, contract_name):
        super().__init__(f"Contract '{contract_name}' not found in configuration")
        self.contract_name = contract_name


class BlockchainDisabledError(BlockchainError):
    """Raised when blockchain operations are called but BLOCKCHAIN_ENABLED is False."""
    pass
