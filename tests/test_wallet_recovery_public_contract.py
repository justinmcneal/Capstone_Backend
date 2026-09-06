"""Public wallet-recovery response and cancellation guard contracts."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from loans.views.officer.wallet_recovery import WalletDisbursementRecoveryView


def _application(**overrides):
    values = {
        "id": "loan-1",
        "status": "approved",
        "disbursement_status": "pending",
        "disbursement_failure_code": None,
        "eth_disbursement_tx_hash": None,
        "eth_disbursement_tx_status": "",
        "eth_disbursement_raw_transaction": "",
        "eth_disbursement_prepared_at": None,
        "eth_disbursement_broadcast_at": None,
        "eth_disbursement_last_checked_at": None,
        "eth_disbursement_block_number": None,
        "eth_disbursement_rebroadcast_count": 0,
        "disbursement_worker_owner": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_status_returns_only_server_allowed_recovery_actions():
    safe_pending = WalletDisbursementRecoveryView._data(_application())
    broadcast = WalletDisbursementRecoveryView._data(
        _application(
            eth_disbursement_tx_hash="0xabc",
            eth_disbursement_tx_status="broadcast",
            eth_disbursement_broadcast_at="2026-09-06T00:00:00Z",
        )
    )
    failed = WalletDisbursementRecoveryView._data(
        _application(disbursement_status="failed", eth_disbursement_tx_status="reverted")
    )

    assert safe_pending["available_actions"] == ["reconcile", "cancel"]
    assert broadcast["available_actions"] == ["reconcile"]
    assert failed["available_actions"] == ["retry"]
    for payload in (safe_pending, broadcast, failed):
        assert "eth_disbursement_raw_transaction" not in payload
        assert "disbursement_worker_owner" not in payload


def test_cancel_requires_a_reason_before_touching_wallet_state(monkeypatch):
    application = _application()
    actor = SimpleNamespace(customer_id="officer-1")
    monkeypatch.setattr(
        WalletDisbursementRecoveryView,
        "_application",
        lambda self, request, application_id: (application, None, actor),
    )
    cancel = MagicMock()
    monkeypatch.setattr(
        "loans.views.officer.wallet_recovery.LoanApplication.cancel_wallet_disbursement",
        cancel,
    )
    request = MagicMock(data={"action": "cancel", "reason": "   "})

    response = WalletDisbursementRecoveryView().post(request, "loan-1")

    assert response.status_code == 400
    assert response.data["errors"]["reason"]
    cancel.assert_not_called()
