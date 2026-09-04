"""Stage 2 regression tests for guarded Loans lifecycle mutations."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from loans.models import LoanApplication, LoanTransitionConflict
from loans.tasks import _complete_wallet_disbursement


def _application(**overrides):
    values = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 20_000,
        "term_months": 6,
        "status": "under_review",
        "assigned_officer": "officer-a",
    }
    values.update(overrides)
    return LoanApplication(**values).save()


def _attempt(callback):
    try:
        callback()
        return "won"
    except LoanTransitionConflict:
        return "conflict"


def test_concurrent_approve_and_reject_have_exactly_one_winner():
    application = _application()
    approve_copy = LoanApplication.find_by_id(application.id)
    reject_copy = LoanApplication.find_by_id(application.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda callback: _attempt(callback),
                (
                    lambda: approve_copy.approve("officer-a", 18_000),
                    lambda: reject_copy.reject("officer-a", "Not eligible"),
                ),
            )
        )

    stored = LoanApplication.find_by_id(application.id)
    assert sorted(results) == ["conflict", "won"]
    assert stored.status in {"approved", "rejected"}
    assert len(stored.lifecycle_transitions) == 1
    assert stored.last_transition_id.startswith("loan_evt_")


def test_review_actor_must_match_assignment_while_admin_preserves_it():
    application = _application(assigned_officer="officer-a")
    with pytest.raises(LoanTransitionConflict, match="another loan officer"):
        LoanApplication.find_by_id(application.id).approve("officer-b", 18_000)

    admin_review = LoanApplication.find_by_id(application.id)
    admin_review.approve(
        "admin-a",
        18_000,
        actor_type="admin",
    )
    stored = LoanApplication.find_by_id(application.id)
    assert stored.status == "approved"
    assert stored.assigned_officer == "officer-a"
    assert stored.lifecycle_transitions[-1]["actor_id"] == "admin-a"
    assert stored.lifecycle_transitions[-1]["actor_type"] == "admin"


def test_concurrent_assignment_has_exactly_one_winner():
    application = _application(status="submitted", assigned_officer=None)
    first = LoanApplication.find_by_id(application.id)
    second = LoanApplication.find_by_id(application.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda callback: _attempt(callback),
                (
                    lambda: first.assign_officer("officer-a", actor_type="system"),
                    lambda: second.assign_officer("officer-b", actor_type="system"),
                ),
            )
        )

    stored = LoanApplication.find_by_id(application.id)
    assert sorted(results) == ["conflict", "won"]
    assert stored.assigned_officer in {"officer-a", "officer-b"}
    assert len(stored.lifecycle_transitions) == 1


def test_concurrent_reassignment_has_exactly_one_winner():
    application = _application(assigned_officer="officer-original")
    first = LoanApplication.find_by_id(application.id)
    second = LoanApplication.find_by_id(application.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda callback: _attempt(callback),
                (
                    lambda: first.reassign("officer-a", actor_id="admin-a"),
                    lambda: second.reassign("officer-b", actor_id="admin-b"),
                ),
            )
        )

    stored = LoanApplication.find_by_id(application.id)
    assert sorted(results) == ["conflict", "won"]
    assert stored.assigned_officer in {"officer-a", "officer-b"}


def test_concurrent_encrypted_note_appends_are_not_lost():
    application = _application()

    def append(index):
        copy = LoanApplication.find_by_id(application.id)
        copy.add_internal_note("officer-a", "loan_officer", f"note-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(20)))

    stored = LoanApplication.find_by_id(application.id)
    assert {note["content"] for note in stored.internal_notes} == {
        f"note-{index}" for index in range(20)
    }
    assert len(stored.lifecycle_transitions) == 20


def test_concurrent_missing_document_requests_preserve_history():
    application = _application()

    def request(document_type):
        copy = LoanApplication.find_by_id(application.id)
        copy.request_missing_documents(
            "officer-a", [document_type], reason=f"Need {document_type}"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(request, ("valid_id", "bank_statement")))

    stored = LoanApplication.find_by_id(application.id)
    assert {
        history["requested_documents"][0] for history in stored.document_request_history
    } == {"valid_id", "bank_statement"}
    assert len(stored.lifecycle_transitions) == 2


def test_submit_and_resubmit_reject_stale_replays():
    draft = _application(status="draft", assigned_officer=None)
    draft_copy = LoanApplication.find_by_id(draft.id)
    draft.submit()
    with pytest.raises(LoanTransitionConflict):
        draft_copy.submit()

    rejected = _application(status="rejected")
    rejected_copy = LoanApplication.find_by_id(rejected.id)
    rejected.resubmit()
    with pytest.raises(LoanTransitionConflict):
        rejected_copy.resubmit()


def test_transition_id_correlates_audit_notification_and_blockchain(
    settings, monkeypatch
):
    application = _application()
    audit = MagicMock()
    monkeypatch.setattr("loans.services.audit.record_loan_audit", audit)

    application.approve("officer-a", 18_000)
    transition_id = application.last_transition_id
    application._log_status_transition(
        "loan_approved",
        "officer-a",
        "loan_officer",
        "approved",
    )

    assert transition_id.startswith("loan_evt_")
    assert audit.call_args.kwargs["details"]["transition_id"] == transition_id

    create_notification = MagicMock(return_value=None)
    monkeypatch.setattr(
        "notifications.services.email_sender.create_and_broadcast_notification",
        create_notification,
    )
    from notifications.services.email_sender import EmailSender

    sender = EmailSender()
    monkeypatch.setattr(sender, "send", MagicMock(return_value=True))
    sender.send_loan_approved(
        customer_email="stage2@example.com",
        customer_name="Stage Two",
        loan_id=application.id,
        approved_amount=18_000,
        customer_id=application.customer_id,
        delivery_key=transition_id,
    )
    assert create_notification.call_args.kwargs["idempotency_key"] == transition_id

    settings.BLOCKCHAIN_ENABLED = True
    delay = MagicMock()
    monkeypatch.setattr("loans.blockchain.tasks.sync_approval_to_chain.delay", delay)
    from loans.blockchain.sync import sync_approval

    sync_approval(application.id, transition_id)
    delay.assert_called_once_with(application.id, transition_id)


def test_failed_raw_rebroadcast_does_not_increment_counter(monkeypatch):
    application = _application(
        status="approved",
        approved_amount=20_000,
        disbursement_method="wallet",
        disbursement_status="pending",
        eth_disbursement_tx_hash="0xprepared",
        eth_disbursement_raw_transaction="0x0102",
        eth_disbursement_recipient="0x0000000000000000000000000000000000000001",
        eth_disbursement_amount_wei=1,
        eth_disbursement_tx_status="prepared",
    )

    class MissingEth:
        @staticmethod
        def get_transaction_receipt(_tx_hash):
            from web3.exceptions import TransactionNotFound

            raise TransactionNotFound("missing")

        @staticmethod
        def get_transaction(_tx_hash):
            from web3.exceptions import TransactionNotFound

            raise TransactionNotFound("missing")

    monkeypatch.setattr(
        "loans.blockchain.client.get_web3",
        lambda: type("Web3", (), {"eth": MissingEth()})(),
    )
    monkeypatch.setattr(
        "loans.blockchain.client.send_prepared_eth_transfer",
        MagicMock(side_effect=RuntimeError("broadcast failed")),
    )

    with pytest.raises(RuntimeError, match="broadcast failed"):
        _complete_wallet_disbursement(application, "worker-stage2")

    stored = LoanApplication.find_by_id(application.id)
    assert stored.eth_disbursement_rebroadcast_count == 0
