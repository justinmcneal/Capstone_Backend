"""Shared serialization helpers for the loans domain."""

PUBLIC_BLOCKCHAIN_ACTIONS = frozenset(
    {
        "submit",
        "approve",
        "reject",
        "disburse",
        "schedule",
        "payment",
        "penalty_applied",
        "penalty_waived",
    }
)


def _iso_or_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def disbursement_failure_code(application):
    """Return a stable public failure category without stored exception text."""
    if getattr(application, "disbursement_status", "") == "failed":
        return "DISBURSEMENT_FAILED"
    if getattr(application, "disbursement_status", "") == "cancelled":
        return "DISBURSEMENT_CANCELLED"
    return None


def _public_blockchain_transaction(transaction):
    """Serialize the customer/officer transaction allowlist."""
    return {
        "tx_hash": getattr(transaction, "tx_hash", ""),
        "action": getattr(transaction, "action", ""),
        "status": getattr(transaction, "status", ""),
        "block_number": getattr(transaction, "block_number", 0),
        "created_at": _iso_or_value(getattr(transaction, "created_at", None)),
        "completed_at": _iso_or_value(getattr(transaction, "completed_at", None)),
    }


def serialize_customer_blockchain_transaction(transaction):
    """Return the blockchain fields approved for a customer."""
    return _public_blockchain_transaction(transaction)


def serialize_officer_blockchain_transaction(transaction):
    """Return the blockchain fields approved for a scoped officer."""
    return _public_blockchain_transaction(transaction)


def serialize_public_blockchain_audit_entry(entry):
    """Minimize an on-chain audit entry for customer/officer responses."""
    entry = entry or {}
    return {
        "action": entry.get("action"),
        "action_label": entry.get("action_label", ""),
        "timestamp": _iso_or_value(entry.get("timestamp")),
        "block_number": entry.get("block_number", 0),
    }


def serialize_public_blockchain_hashes(tx_hashes):
    """Return only recognized action/hash pairs from denormalized loan state."""
    if not isinstance(tx_hashes, dict):
        return {}
    return {
        action: tx_hash
        for action, tx_hash in tx_hashes.items()
        if action in PUBLIC_BLOCKCHAIN_ACTIONS and isinstance(tx_hash, str) and tx_hash
    }


def serialize_admin_blockchain_transaction(document):
    """Return an operational admin allowlist without free-form/internal fields."""
    document = document or {}
    tx_status = str(document.get("status", "") or "")
    return {
        "id": str(document.get("_id", "")),
        "tx_hash": document.get("tx_hash", ""),
        "contract_name": document.get("contract_name", ""),
        "method": document.get("method", ""),
        "loan_id": document.get("loan_id", ""),
        "action": document.get("action", ""),
        "status": tx_status,
        "gas_used": document.get("gas_used", 0),
        "gas_price": document.get("gas_price", 0),
        "block_number": document.get("block_number", 0),
        "failure_code": (
            "BLOCKCHAIN_TRANSACTION_FAILED" if tx_status == "failed" else None
        ),
        "created_at": _iso_or_value(document.get("created_at")),
        "completed_at": _iso_or_value(document.get("completed_at")),
    }


def serialize_internal_note(note):
    """Normalize a stored note entry for API responses."""
    if not note:
        return None

    created_at = note.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    return {
        "content": note.get("content", ""),
        "author_id": note.get("author_id"),
        "author_role": note.get("author_role"),
        "created_at": created_at,
    }
