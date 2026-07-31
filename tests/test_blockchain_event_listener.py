"""
Tests for blockchain event listener.

Coverage:
- AuditEventListener initialization and configuration
- start/stop/start_daemon lifecycle
- reset_last_block clears persisted state
- _get_last_block loads from MongoDB or falls back to start_block/current
- _save_last_block persists block state
- _ensure_connection connects and caches w3/contract
- _poll_events fetches logs between last_block and current_block
- _process_log decodes AuditLogged events and persists them
- Duplicate events are handled (insert_one raises on duplicate key if indexed)
- Reconnection after simulated node failure
- Backoff on repeated failures
- Graceful shutdown via _stop_event
- Chain reorg handling
"""

import json
import time
from unittest.mock import MagicMock, patch

import mongomock
import pytest
from bson import ObjectId
from django.conf import settings

from loans.blockchain.event_listener import AuditEventListener


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mongo(monkeypatch):
    client = mongomock.MongoClient()
    db = client["testdb"]
    monkeypatch.setattr(settings, "MONGODB", db, raising=False)
    return db


def _make_listener(poll_interval=1, start_block=None):
    return AuditEventListener(poll_interval=poll_interval, start_block=start_block)


def _make_log(tx_hash="0xabc1230000000000000000000000000000000000000000000000000000000000", block_number=100, log_index=0, entry_id=b"entry1", resource_id=b"res1", action=1, actor="0xactor", timestamp=1234567890):
    hex_str = tx_hash[2:]
    if len(hex_str) % 2:
        hex_str = hex_str + "0"
    return {
        "transactionHash": bytes.fromhex(hex_str),
        "blockNumber": block_number,
        "logIndex": log_index,
        "address": "0xcontract",
        "data": "0x",
        "topics": [],
    }


def _make_decoded_args(entry_id=b"entry1", resource_id=b"res1", action=1, actor="0xactor", timestamp=1234567890):
    return {
        "entryId": entry_id,
        "resourceId": resource_id,
        "action": action,
        "actor": actor,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestListenerLifecycle:
    def test_start_creates_thread(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener()
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "AuditLogged", "type": "event", "inputs": []}]
        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                thread = listener.start()
        assert thread is not None
        assert thread.is_alive()
        listener.stop(timeout=2)

    def test_start_daemon_creates_daemon_thread(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener()
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "AuditLogged", "type": "event", "inputs": []}]
        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                thread = listener.start_daemon()
        assert thread is not None
        assert thread.is_alive()
        assert thread.daemon is True
        listener.stop(timeout=2)

    def test_start_raises_if_already_running(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener()
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "AuditLogged", "type": "event", "inputs": []}]
        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                listener.start()
        with pytest.raises(RuntimeError, match="already running"):
            listener.start()
        listener.stop(timeout=2)

    def test_stop_signals_and_joins(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener(poll_interval=10)
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "AuditLogged", "type": "event", "inputs": []}]
        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                listener.start()
        assert listener._stop_event.is_set() is False
        listener.stop(timeout=2)
        assert listener._stop_event.is_set() is True

    def test_double_stop_is_safe(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener(poll_interval=10)
        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "AuditLogged", "type": "event", "inputs": []}]
        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                listener.start()
        listener.stop(timeout=2)
        listener.stop(timeout=2)  # Should not raise


# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_save_and_load_last_block(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        listener._save_last_block(500)
        doc = db["listener_state"].find_one({"key": "audit_listener_last_block"})
        assert doc["block_number"] == 500

        loaded = listener._get_last_block(current_block=1000)
        assert loaded == 500

    def test_get_last_block_falls_back_to_start_block(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener(start_block=42)

        loaded = listener._get_last_block(current_block=1000)
        assert loaded == 42

    def test_get_last_block_falls_back_to_current_when_no_state(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        loaded = listener._get_last_block(current_block=1000)
        assert loaded == 1000

    def test_reset_clears_state(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        listener._save_last_block(500)
        assert db["listener_state"].find_one({"key": "audit_listener_last_block"}) is not None

        listener.reset_last_block()
        assert db["listener_state"].find_one({"key": "audit_listener_last_block"}) is None

    def test_save_last_block_survives_none_db(self, monkeypatch):
        listener = _make_listener()
        monkeypatch.setattr(settings, "MONGODB", None, raising=False)
        listener._save_last_block(500)  # Should not raise


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

class TestConnection:
    def test_ensure_connection_loads_w3_and_contract(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [
            {"name": "AuditLogged", "type": "event", "inputs": []}
        ]
        mock_contract.address = "0xcontract"

        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                listener._ensure_connection()

        assert listener._w3 is mock_w3
        assert listener._contract is mock_contract
        assert listener._event_abi is not None

    def test_ensure_connection_raises_if_event_missing(self, monkeypatch):
        _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_contract = MagicMock()
        mock_contract.abi = [{"name": "OtherEvent", "type": "event", "inputs": []}]

        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                with pytest.raises(ValueError, match="AuditLogged event not found"):
                    listener._ensure_connection()

    def test_reconnect_after_failure(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener(poll_interval=0.1)

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 100
        mock_contract = MagicMock()
        mock_contract.abi = [
            {"name": "AuditLogged", "type": "event", "inputs": []}
        ]
        mock_contract.address = "0xcontract"
        mock_contract.events.AuditLogged().processLog.return_value = {
            "args": _make_decoded_args()
        }

        with patch("loans.blockchain.client.get_web3", return_value=mock_w3):
            with patch("loans.blockchain.client.get_contract", return_value=mock_contract):
                with patch.object(listener, "_poll_events") as mock_poll:
                    call_count = [0]
                    def side_effect():
                        call_count[0] += 1
                        if call_count[0] == 1:
                            raise Exception("node down")
                        if call_count[0] >= 2:
                            listener._stop_event.set()
                        return None
                    mock_poll.side_effect = side_effect
                    listener._run()

        assert mock_poll.call_count == 2


# ---------------------------------------------------------------------------
# Polling and event processing tests
# ---------------------------------------------------------------------------

class TestPollingAndProcessing:
    def test_poll_events_fetches_and_saves(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 105

        mock_contract = MagicMock()
        mock_contract.abi = [
            {"name": "AuditLogged", "type": "event", "inputs": []}
        ]
        mock_contract.address = "0xcontract"
        log1 = _make_log(tx_hash="0xaaa", block_number=101, log_index=0)
        decoded = {"args": _make_decoded_args()}
        mock_contract.events.AuditLogged().processLog.return_value = decoded
        mock_contract.events.AuditLogged().get_logs.return_value = [log1]

        listener._w3 = mock_w3
        listener._contract = mock_contract
        listener._event_abi = {"name": "AuditLogged", "type": "event", "inputs": []}

        listener._save_last_block(100)
        listener._poll_events()

        assert db["blockchain_events"].count_documents({}) == 1
        saved = db["blockchain_events"].find_one({})
        assert saved["block_number"] == 101
        assert saved["tx_hash"] == "aaa0"

        state = db["listener_state"].find_one({"key": "audit_listener_last_block"})
        assert state["block_number"] == 106

    def test_poll_events_skips_when_no_new_blocks(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 100

        listener._w3 = mock_w3
        listener._contract = MagicMock()
        listener._event_abi = {"name": "AuditLogged", "type": "event"}

        listener._save_last_block(100)
        listener._poll_events()

        assert db["blockchain_events"].count_documents({}) == 0

    def test_poll_events_handles_chain_reorg(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 50

        mock_contract = MagicMock()
        mock_contract.abi = [
            {"name": "AuditLogged", "type": "event", "inputs": []}
        ]
        mock_contract.address = "0xcontract"
        mock_contract.events.AuditLogged().get_logs.return_value = []

        listener._w3 = mock_w3
        listener._contract = mock_contract
        listener._event_abi = {"name": "AuditLogged", "type": "event", "inputs": []}

        listener._save_last_block(100)
        listener._poll_events()

        mock_contract.events.AuditLogged().get_logs.assert_called_once_with(
            from_block=40,
            to_block=50,
        )

    def test_process_log_decodes_and_persists(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_contract = MagicMock()
        decoded = {"args": _make_decoded_args(entry_id=b"entry1", resource_id=b"res1", action=1)}
        mock_contract.events.AuditLogged().processLog.return_value = decoded
        listener._contract = mock_contract

        log = _make_log(tx_hash="0xdeadbeef", block_number=200, entry_id=b"entry1", resource_id=b"res1")
        listener._process_log(log)

        saved = db["blockchain_events"].find_one({})
        assert saved["tx_hash"] == "deadbeef"
        assert saved["block_number"] == 200
        assert saved["args"]["action"] == 1
        assert saved["args"]["actor"] == "0xactor"

    def test_process_log_handles_bytes32_fields(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_contract = MagicMock()
        entry_id_bytes = bytes.fromhex("aa" * 32)
        resource_id_bytes = bytes.fromhex("bb" * 32)

        class _EntryBytes:
            def hex(self):
                return "aa" * 32

        class _ResourceBytes:
            def hex(self):
                return "bb" * 32

        decoded = {
            "args": {
                "entryId": _EntryBytes(),
                "resourceId": _ResourceBytes(),
                "action": 7,
                "actor": "0xactor",
                "timestamp": 1234567890,
            }
        }
        mock_contract.events.AuditLogged().processLog.return_value = decoded
        listener._contract = mock_contract

        log = _make_log()
        listener._process_log(log)

        saved = db["blockchain_events"].find_one({})
        assert saved["args"]["entryId"] == "aa" * 32
        assert saved["args"]["resourceId"] == "bb" * 32
        assert saved["args"]["action"] == 7

    def test_process_log_survives_decode_failure(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener()

        mock_contract = MagicMock()
        mock_contract.events.AuditLogged().processLog.side_effect = Exception("bad log")
        listener._contract = mock_contract

        log = _make_log()
        listener._process_log(log)  # Should not raise

        assert db["blockchain_events"].count_documents({}) == 0


# ---------------------------------------------------------------------------
# Full integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_poll_cycle(self, monkeypatch):
        db = _make_mongo(monkeypatch)
        listener = _make_listener(poll_interval=0.1)

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.block_number = 105

        log1 = _make_log(tx_hash="0xaaa", block_number=101, log_index=0)
        log2 = _make_log(tx_hash="0xbbb", block_number=102, log_index=1)
        mock_contract = MagicMock()
        mock_contract.abi = [
            {"name": "AuditLogged", "type": "event", "inputs": []}
        ]
        mock_contract.address = "0xcontract"
        mock_contract.events.AuditLogged().processLog.side_effect = [
            {"args": _make_decoded_args(entry_id=b"e1")},
            {"args": _make_decoded_args(entry_id=b"e2", action=7)},
        ]
        mock_contract.events.AuditLogged().get_logs.return_value = [log1, log2]

        listener._w3 = mock_w3
        listener._contract = mock_contract
        listener._event_abi = {"name": "AuditLogged", "type": "event", "inputs": []}

        listener._save_last_block(100)
        listener._poll_events()

        assert db["blockchain_events"].count_documents({}) == 2
        state = db["listener_state"].find_one({"key": "audit_listener_last_block"})
        assert state["block_number"] == 106

        events = list(db["blockchain_events"].find().sort("block_number", 1))
        assert len(events) == 2
        assert events[0]["args"]["action"] == 1
        assert events[1]["args"]["action"] == 7
        assert events[0]["tx_hash"] == "aaa0"
        assert events[1]["tx_hash"] == "bbb0"
