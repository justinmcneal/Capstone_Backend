"""
Service for AuditRegistry contract interactions (read-only).

Handles: getFullAuditTrail, getEntry
"""

import logging

from web3 import Web3

from loans.blockchain.client import get_contract, call_view

logger = logging.getLogger("blockchain")


def _to_bytes32(value):
    """Convert a string to bytes32 (keccak256 hash)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    return Web3.keccak(text=str(value))


# AuditAction enum labels for human-readable output
AUDIT_ACTION_LABELS = {
    0: "LoanCreated",
    1: "LoanSubmitted",
    2: "LoanAssigned",
    3: "LoanApproved",
    4: "LoanRejected",
    5: "LoanDisbursed",
    6: "PaymentRecorded",
    7: "PenaltyApplied",
    8: "PenaltyWaived",
    9: "DocumentVerified",
    10: "ConsentRecorded",
    11: "SystemConfigChanged",
}


def get_audit_trail(resource_id):
    """
    Fetch the full audit trail for a resource from the AuditRegistry contract.

    Args:
        resource_id: Resource identifier (string, hashed to bytes32)

    Returns:
        list of dicts, each with:
            resource_id, resource_type, action, action_label, details_hash,
            previous_state_hash, new_state_hash, actor, timestamp, block_number
    """
    contract = get_contract("auditRegistry")
    resource_id_bytes = _to_bytes32(resource_id)

    raw_entries = call_view(contract, "getFullAuditTrail", resource_id_bytes)

    entries = []
    for entry in raw_entries:
        action_int = entry[3] if isinstance(entry[3], int) else int(entry[3])
        entries.append({
            "resource_id": entry[0].hex() if isinstance(entry[0], bytes) else entry[0],
            "resource_type": entry[1].hex() if isinstance(entry[1], bytes) else entry[1],
            "details_hash": entry[2].hex() if isinstance(entry[2], bytes) else entry[2],
            "action": action_int,
            "action_label": AUDIT_ACTION_LABELS.get(action_int, f"Unknown({action_int})"),
            "previous_state_hash": entry[4].hex() if isinstance(entry[4], bytes) else entry[4],
            "new_state_hash": entry[5].hex() if isinstance(entry[5], bytes) else entry[5],
            "actor": entry[6],
            "timestamp": entry[7],
            "block_number": entry[8],
        })

    logger.debug("getFullAuditTrail: resource=%s entries=%d", resource_id, len(entries))
    return entries


def get_audit_entry(entry_id):
    """
    Fetch a single audit entry by its ID.

    Args:
        entry_id: Entry identifier (bytes32 hex string or bytes)

    Returns:
        dict with audit entry fields
    """
    contract = get_contract("auditRegistry")

    if isinstance(entry_id, str):
        entry_id_bytes = bytes.fromhex(entry_id.replace("0x", ""))
    else:
        entry_id_bytes = entry_id

    entry = call_view(contract, "getEntry", entry_id_bytes)

    action_int = entry[3] if isinstance(entry[3], int) else int(entry[3])
    return {
        "resource_id": entry[0].hex() if isinstance(entry[0], bytes) else entry[0],
        "resource_type": entry[1].hex() if isinstance(entry[1], bytes) else entry[1],
        "details_hash": entry[2].hex() if isinstance(entry[2], bytes) else entry[2],
        "action": action_int,
        "action_label": AUDIT_ACTION_LABELS.get(action_int, f"Unknown({action_int})"),
        "previous_state_hash": entry[4].hex() if isinstance(entry[4], bytes) else entry[4],
        "new_state_hash": entry[5].hex() if isinstance(entry[5], bytes) else entry[5],
        "actor": entry[6],
        "timestamp": entry[7],
        "block_number": entry[8],
    }
