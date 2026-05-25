"""
Service for AuditRegistry contract interactions.

Handles: getFullAuditTrail, getEntry, log
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


def _to_bytes32_label(value):
    """Convert a short label to bytes32 (padded ASCII)."""
    if isinstance(value, bytes) and len(value) == 32:
        return value
    raw = Web3.to_bytes(text=str(value))
    if len(raw) <= 32:
        return raw.ljust(32, b"\x00")
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

AUDIT_ACTION_ENUM = {
    "PenaltyApplied": 7,
    "PenaltyWaived": 8,
    "ConsentRecorded": 10,
}


def log_audit_entry_onchain(resource_id, resource_type, action, details_hash,
                            previous_state_hash=None, new_state_hash=None):
    """
    Log an audit entry to AuditRegistry.

    Args:
        resource_id: Unique resource identifier (string, hashed to bytes32)
        resource_type: Resource type label (string, bytes32 padded)
        action: AuditAction enum int
        details_hash: Hashable detail payload (string, hashed to bytes32)
        previous_state_hash: Optional previous state (string, hashed to bytes32)
        new_state_hash: Optional new state (string, hashed to bytes32)

    Returns:
        dict with tx_hash, gas_used, block_number, status
    """
    from loans.blockchain.client import send_transaction

    contract = get_contract("auditRegistry")
    resource_id_bytes = _to_bytes32(resource_id)
    resource_type_bytes = _to_bytes32_label(resource_type)
    details_bytes = _to_bytes32(details_hash)
    prev_bytes = _to_bytes32(previous_state_hash) if previous_state_hash else b"\x00" * 32
    new_bytes = _to_bytes32(new_state_hash) if new_state_hash else b"\x00" * 32

    result = send_transaction(
        contract,
        "log",
        resource_id_bytes,
        resource_type_bytes,
        int(action),
        details_bytes,
        prev_bytes,
        new_bytes,
    )

    logger.info("auditRegistry.log on-chain: resource=%s action=%s tx=%s",
                resource_id, action, result["tx_hash"][:18])
    return result


def log_penalty_onchain(loan_id, installment_number, amount, reason="", waived=False):
    """
    Record a penalty apply/waive event on-chain via AuditRegistry.
    """
    action = AUDIT_ACTION_ENUM["PenaltyWaived"] if waived else AUDIT_ACTION_ENUM["PenaltyApplied"]
    details = f"{loan_id}:{installment_number}:{amount}:{reason}".strip()
    previous_state = "applied" if waived else "none"
    new_state = "waived" if waived else "applied"
    return log_audit_entry_onchain(
        resource_id=f"{loan_id}:{installment_number}",
        resource_type="penalty",
        action=action,
        details_hash=details or "penalty",
        previous_state_hash=previous_state,
        new_state_hash=new_state,
    )


def log_consent_onchain(user_id, user_type, data_consent, ai_consent,
                        consent_version, consent_timestamp, previous_state=None):
    """
    Record a consent update event on-chain via AuditRegistry.
    """
    action = AUDIT_ACTION_ENUM["ConsentRecorded"]
    resource_id = f"{user_id}:{consent_version}:{consent_timestamp}"
    detail_payload = f"{user_type}:{data_consent}:{ai_consent}:{consent_version}:{consent_timestamp}"
    prev_state = None
    if previous_state:
        prev_state = (
            f"{previous_state.get('data_consent')}:{previous_state.get('ai_consent')}:"
            f"{previous_state.get('consent_version')}"
        )
    new_state = f"{data_consent}:{ai_consent}:{consent_version}"
    return log_audit_entry_onchain(
        resource_id=resource_id,
        resource_type="consent",
        action=action,
        details_hash=detail_payload,
        previous_state_hash=prev_state,
        new_state_hash=new_state,
    )


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
        raw_action = entry[3]
        if isinstance(raw_action, int):
            action_int = raw_action
        elif isinstance(raw_action, bytes):
            action_int = int.from_bytes(raw_action, byteorder='big')
        else:
            action_int = int(raw_action)
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

    raw_action = entry[3]
    if isinstance(raw_action, int):
        action_int = raw_action
    elif isinstance(raw_action, bytes):
        action_int = int.from_bytes(raw_action, byteorder='big')
    else:
        action_int = int(raw_action)
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
