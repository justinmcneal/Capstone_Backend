"""
Lightweight blockchain event listener skeleton.

This module provides a simple, optional event listener that can be started
from a management command or a long-running process to capture on-chain
AuditRegistry events and mirror them to MongoDB. It is intentionally
minimal and safe — it does not start automatically on import.

Usage (manual):
    from loans.blockchain.event_listener import start_audit_listener
    start_audit_listener(poll_interval=5)

"""
import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger("blockchain.event_listener")


def _process_event(entry):
    # Minimal processing: store event JSON in MongoDB `blockchain_events` collection
    try:
        db = getattr(settings, 'MONGODB', None)
        if db is None:
            return
        db['blockchain_events'].insert_one(entry)
    except Exception as exc:
        logger.exception("Failed to persist blockchain event: %s", exc)


def _listen_loop(poll_interval=5):
    """Poll AuditRegistry events and persist new ones."""
    from loans.blockchain.client import get_web3, get_contract, call_view

    w3 = get_web3()
    contract = get_contract('auditRegistry')

    last_block = w3.eth.block_number if w3 else None

    while True:
        try:
            if not w3:
                time.sleep(poll_interval)
                continue

            current_block = w3.eth.block_number
            # Fetch logs for AuditLogged event
            event_abi = None
            for abi in contract.abi:
                if abi.get('name') == 'AuditLogged' and abi.get('type') == 'event':
                    event_abi = abi
                    break

            if event_abi is None:
                time.sleep(poll_interval)
                continue

            from web3._utils.events import construct_event_filter_params
            params = construct_event_filter_params(event_abi, contract_address=contract.address, fromBlock=last_block or 0, toBlock=current_block)
            logs = w3.eth.get_logs(params)
            for log in logs:
                try:
                    decoded = contract.events.AuditLogged().processLog(log)
                    entry = {
                        'tx_hash': log['transactionHash'].hex(),
                        'block_number': log['blockNumber'],
                        'args': dict(decoded['args']),
                        'timestamp': int(time.time()),
                    }
                    _process_event(entry)
                except Exception:
                    logger.exception('Failed to decode/process log')

            last_block = current_block + 1
        except Exception:
            logger.exception('Event listener loop failed')
        time.sleep(poll_interval)


def start_audit_listener(poll_interval=5):
    """Start the audit registry listener in a daemon thread."""
    thread = threading.Thread(target=_listen_loop, args=(poll_interval,), daemon=True)
    thread.start()
    logger.info('Started audit listener thread (poll_interval=%s)', poll_interval)
    return thread
