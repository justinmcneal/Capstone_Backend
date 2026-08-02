"""
Lightweight blockchain event listener for AuditRegistry events.

Features:
- Polls AuditRegistry contract for AuditLogged events
- Persists last processed block to MongoDB for crash recovery
- Reconnects to blockchain node with exponential backoff on failure
- Graceful shutdown via threading Event
- Deduplicates events by tx_hash + log_index

Usage:
    from loans.blockchain.event_listener import AuditEventListener

    listener = AuditEventListener(poll_interval=5)
    listener.start()
    # ... later ...
    listener.stop()

Or as a daemon thread (auto-stops on process exit):
    listener = AuditEventListener(poll_interval=5)
    listener.start_daemon()

"""

import logging
import threading
import time

from django.conf import settings

logger = logging.getLogger("blockchain.event_listener")


class AuditEventListener:
    """
    Polls the AuditRegistry contract for AuditLogged events and mirrors
    them to MongoDB with persistent state and reconnection support.
    """

    LISTENER_STATE_COLLECTION = "listener_state"
    EVENTS_COLLECTION = "blockchain_events"
    MAX_BACKOFF_SECONDS = 60
    BASE_BACKOFF_SECONDS = 2

    def __init__(self, poll_interval=5, start_block=None):
        self.poll_interval = poll_interval
        self.start_block = start_block
        self._stop_event = threading.Event()
        self._thread = None
        self._w3 = None
        self._contract = None
        self._backoff = self.BASE_BACKOFF_SECONDS
        self._event_abi = None

    def start(self):
        """Start the listener in a background thread (non-daemon)."""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Listener is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._thread.start()
        logger.info("Started audit listener (poll_interval=%s)", self.poll_interval)
        return self._thread

    def start_daemon(self):
        """Start the listener as a daemon thread (auto-exits with process)."""
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Listener is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Started audit listener daemon (poll_interval=%s)", self.poll_interval)
        return self._thread

    def stop(self, timeout=None):
        """Signal the listener to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Audit listener stopped")

    def reset_last_block(self):
        """Clear persisted last_block so the listener replays from start_block."""
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return
        db[self.LISTENER_STATE_COLLECTION].delete_one({"key": "audit_listener_last_block"})
        logger.info("Reset listener last_block state")

    def _run(self):
        """Main listener loop with reconnection and backoff."""
        while not self._stop_event.is_set():
            try:
                self._ensure_connection()
                self._poll_events()
                self._backoff = self.BASE_BACKOFF_SECONDS
            except Exception as exc:
                logger.exception("Event listener loop failed: %s", exc)
                self._backoff = min(self._backoff * 2, self.MAX_BACKOFF_SECONDS)
                logger.info("Backing off for %s seconds", self._backoff)
            self._stop_event.wait(self._backoff if not self._w3 else self.poll_interval)

    def _ensure_connection(self):
        """Connect to blockchain node and contract, reconnecting if needed."""
        from loans.blockchain.client import get_web3, get_contract

        if self._w3 is None or not self._w3.is_connected():
            self._w3 = get_web3()
            self._contract = get_contract("auditRegistry")
            self._event_abi = None
            logger.info("Connected to blockchain node")

        if self._contract is None:
            self._contract = get_contract("auditRegistry")

        if self._event_abi is None:
            for abi in self._contract.abi:
                if abi.get("name") == "AuditLogged" and abi.get("type") == "event":
                    self._event_abi = abi
                    break
            if self._event_abi is None:
                raise ValueError("AuditLogged event not found in contract ABI")

    def _poll_events(self):
        """Fetch and process new AuditLogged events."""
        current_block = self._w3.eth.block_number
        last_block = self._get_last_block(current_block)

        if current_block < last_block:
            if last_block == current_block + 1:
                return {"processed": 0, "next_block": last_block}
            logger.warning(
                "Chain reorg detected: current=%d < next_block=%d",
                current_block,
                last_block,
            )
            last_block = max(0, current_block - 10)

        logs = self._contract.events.AuditLogged().get_logs(
            from_block=last_block,
            to_block=current_block,
        )

        processed = 0
        for log in logs:
            if self._stop_event.is_set():
                break
            if not self._process_log(log):
                raise RuntimeError("Blockchain event could not be persisted")
            processed += 1

        if not self._stop_event.is_set():
            self._save_last_block(current_block + 1)
        return {"processed": processed, "next_block": current_block + 1}

    def _get_last_block(self, current_block):
        """Load persisted last_block, falling back to start_block or current."""
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return self.start_block or current_block

        doc = db[self.LISTENER_STATE_COLLECTION].find_one({"key": "audit_listener_last_block"})
        if doc and "block_number" in doc:
            return doc["block_number"]

        initial_block = self.start_block if self.start_block is not None else current_block
        self._save_last_block(initial_block)
        return initial_block

    def _save_last_block(self, block_number):
        """Persist last processed block to MongoDB."""
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return
        db[self.LISTENER_STATE_COLLECTION].update_one(
            {"key": "audit_listener_last_block"},
            {"$set": {"block_number": block_number, "updated_at": int(time.time())}},
            upsert=True,
        )

    def _process_log(self, log):
        """Decode and persist a single AuditLogged event."""
        try:
            from collections.abc import Mapping

            event = self._contract.events.AuditLogged()
            decoded = None
            processor = getattr(event, "process_log", None)
            if processor:
                decoded = processor(log)
            if not isinstance(decoded, Mapping):
                decoded = event.processLog(log)
            tx_hash = log["transactionHash"].hex()
            entry = {
                "tx_hash": tx_hash,
                "log_index": log.get("logIndex", 0),
                "block_number": log["blockNumber"],
                "args": {
                    "entryId": decoded["args"].get("entryId", b"").hex()
                    if hasattr(decoded["args"].get("entryId", b""), "hex")
                    else str(decoded["args"].get("entryId", "")),
                    "resourceId": decoded["args"].get("resourceId", b"").hex()
                    if hasattr(decoded["args"].get("resourceId", b""), "hex")
                    else str(decoded["args"].get("resourceId", "")),
                    "action": decoded["args"].get("action"),
                    "actor": decoded["args"].get("actor"),
                    "timestamp": decoded["args"].get("timestamp"),
                },
                "timestamp": int(time.time()),
            }
            self._persist_event(entry)
            return True
        except Exception:
            logger.exception(
                "Failed to decode/process log %s", log.get("transactionHash", "?")
            )
            return False

    def _persist_event(self, entry):
        """Persist event to MongoDB, skipping duplicates."""
        db = getattr(settings, "MONGODB", None)
        if db is None:
            return
        event_id = f"{entry['tx_hash']}:{entry['log_index']}"
        db[self.EVENTS_COLLECTION].update_one(
            {"_id": event_id},
            {"$setOnInsert": entry},
            upsert=True,
        )


def start_audit_listener(poll_interval=5, start_block=None):
    """
    Start the audit registry listener as a daemon thread.

    Args:
        poll_interval: Seconds between blockchain polls
        start_block: Optional block number to start from (default: current block)

    Returns:
        AuditEventListener instance
    """
    listener = AuditEventListener(poll_interval=poll_interval, start_block=start_block)
    listener.start_daemon()
    return listener
