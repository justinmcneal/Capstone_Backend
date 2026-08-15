"""Stage 1 Loans authorization and public-response contract regressions."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from accounts.models import Admin, Customer, LoanOfficer
from loans.blockchain.models import BlockchainTransaction
from loans.models import LoanApplication, LoanProduct, RepaymentSchedule
from loans.views.admin.blockchain import AdminBlockchainTransactionsView
from loans.views.customer.applications import ApplicationDetailView
from loans.views.customer.blockchain import (
    CustomerBlockchainView,
    SystemWalletInfoView,
    WalletPaymentView,
)
from loans.views.officer.blockchain import BlockchainStatusView
from loans.views.officer.disburse import DisburseView
from loans.views.officer.wallet_recovery import WalletDisbursementRecoveryView


def _auth(account, role):
    return AuthenticatedUser(
        customer_id=str(account.id),
        email=account.email,
        verified=True,
        role=role,
    )


def _officer(label):
    return LoanOfficer(
        employee_id=f"STAGE1-{label}-{ObjectId()}",
        first_name=label,
        last_name="Officer",
        email=f"stage1-{label.lower()}-{ObjectId()}@example.com",
        password="hashed",
        department="Loans",
        active=True,
    ).save()


def _customer(label="owner"):
    return Customer(
        first_name=label,
        last_name="Customer",
        email=f"stage1-{label}-{ObjectId()}@example.com",
        password="hashed",
        verified=True,
        active=True,
    ).save()


def _admin():
    return Admin(
        username=f"stage1-admin-{ObjectId()}",
        email=f"stage1-admin-{ObjectId()}@example.com",
        password="hashed",
        permissions=["view_logs"],
        active=True,
    ).save()


def _application(customer, officer, **overrides):
    product = LoanProduct(
        name="Stage 1 Product",
        code=f"S1-{ObjectId()}",
        min_amount=1000,
        max_amount=50000,
        interest_rate=0.01,
        min_term_months=1,
        max_term_months=12,
        active=True,
    ).save()
    values = {
        "customer_id": str(customer.id),
        "product_id": product.id,
        "requested_amount": 10000,
        "approved_amount": 10000,
        "term_months": 3,
        "status": "approved",
        "assigned_officer": str(officer.id),
    }
    values.update(overrides)
    return LoanApplication(**values).save()


def _request(method, path, user, data=None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data or {}, format="json")
    force_authenticate(request, user=user)
    return request


def test_other_officer_cannot_read_blockchain_status_before_chain_lookup(
    settings, monkeypatch
):
    settings.BLOCKCHAIN_ENABLED = True
    owner = _customer()
    assigned = _officer("Assigned")
    other = _officer("Other")
    application = _application(owner, assigned)
    find_transactions = MagicMock(
        side_effect=AssertionError("must not query chain log")
    )
    monkeypatch.setattr(BlockchainTransaction, "find_by_loan", find_transactions)

    request = _request(
        "get",
        f"/api/loans/officer/applications/{application.id}/blockchain/",
        _auth(other, "loan_officer"),
    )
    response = BlockchainStatusView.as_view()(request, application_id=application.id)

    assert response.status_code == 404
    assert response.data["message"] == "Application not found"
    find_transactions.assert_not_called()


@pytest.mark.parametrize("audience", ["customer", "officer"])
def test_customer_and_officer_blockchain_payloads_use_safe_allowlists(
    settings, monkeypatch, audience
):
    settings.BLOCKCHAIN_ENABLED = True
    settings.BLOCKCHAIN_EXPLORER_URL = "https://explorer.example"
    owner = _customer(audience)
    officer = _officer(audience.title())
    application = _application(
        owner,
        officer,
        blockchain_tx_hashes={"approve": "0xapproved", "internal": "0xsecret"},
    )
    BlockchainTransaction(
        tx_hash="0xtransaction",
        contract_name="InternalApprovalContract",
        method="approveWithSecretArgs",
        loan_id=application.id,
        action="approve",
        status="failed",
        error="rpc host and credential detail",
        details={"private": "payload"},
        idempotency_key="internal-idempotency-key",
        created_at=datetime.now(timezone.utc),
    ).save()
    monkeypatch.setattr(
        "loans.blockchain.services.audit_service.get_audit_trail",
        lambda _loan_id: [
            {
                "action": 3,
                "action_label": "LoanApproved",
                "timestamp": 123,
                "block_number": 9,
                "actor": "0xprivate-actor",
                "details_hash": "0xprivate-hash",
                "previous_state_hash": "0xprevious",
            }
        ],
    )

    if audience == "customer":
        request = _request(
            "get",
            f"/api/loans/applications/{application.id}/blockchain/",
            _auth(owner, "customer"),
        )
        response = CustomerBlockchainView.as_view()(
            request, application_id=application.id
        )
    else:
        request = _request(
            "get",
            f"/api/loans/officer/applications/{application.id}/blockchain/",
            _auth(officer, "loan_officer"),
        )
        response = BlockchainStatusView.as_view()(
            request, application_id=application.id
        )

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["tx_hashes"] == {"approve": "0xapproved"}
    assert payload["transaction_history_available"] is True
    assert payload["audit_trail_available"] is True
    transaction = payload["transactions"][0]
    assert set(transaction) == {
        "tx_hash",
        "action",
        "status",
        "block_number",
        "created_at",
        "completed_at",
    }
    assert set(payload["audit_trail"][0]) == {
        "action",
        "action_label",
        "timestamp",
        "block_number",
    }
    serialized = repr(payload)
    for forbidden in (
        "InternalApprovalContract",
        "approveWithSecretArgs",
        "credential detail",
        "private-actor",
        "private-hash",
        "internal-idempotency-key",
        "0xsecret",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "query",
    [
        {"unknown": "value"},
        {"action": "not-an-action"},
        {"status": "not-a-status"},
        {"start_date": "2026-99-01"},
        {"start_date": "2026-08-02", "end_date": "2026-08-01"},
        {"page": "0"},
        {"page_size": "101"},
        {"search": "x" * 101},
    ],
)
def test_admin_blockchain_query_contract_rejects_invalid_input(query):
    admin = _admin()
    request = _request(
        "get", "/api/loans/admin/blockchain/transactions/", _auth(admin, "admin"), query
    )

    response = AdminBlockchainTransactionsView.as_view()(request)

    assert response.status_code == 400
    assert response.data["code"] == "INVALID_BLOCKCHAIN_QUERY"


def test_admin_blockchain_search_is_literal_and_response_is_minimized():
    admin = _admin()
    BlockchainTransaction(
        tx_hash="0xanything",
        contract_name="LoanApproval",
        method="approveLoan",
        loan_id="loan-1",
        action="approve",
        status="failed",
        error="provider secret detail",
        details={"raw": "private"},
        idempotency_key="private-key",
    ).save()

    literal_request = _request(
        "get",
        "/api/loans/admin/blockchain/transactions/",
        _auth(admin, "admin"),
        {"search": ".*"},
    )
    literal_response = AdminBlockchainTransactionsView.as_view()(literal_request)
    assert literal_response.status_code == 200
    assert literal_response.data["data"]["total"] == 0

    list_request = _request(
        "get",
        "/api/loans/admin/blockchain/transactions/",
        _auth(admin, "admin"),
        {"status": "failed"},
    )
    list_response = AdminBlockchainTransactionsView.as_view()(list_request)
    transaction = list_response.data["data"]["transactions"][0]
    assert transaction["failure_code"] == "BLOCKCHAIN_TRANSACTION_FAILED"
    assert "error" not in transaction
    assert "details" not in transaction
    assert "idempotency_key" not in transaction
    assert "provider secret detail" not in repr(list_response.data)


def test_customer_application_replaces_stored_disbursement_error_with_code():
    owner = _customer("failure-code")
    officer = _officer("Failure")
    application = _application(
        owner,
        officer,
        disbursement_status="failed",
        disbursement_error="mongodb.internal:27017 secret provider failure",
    )
    request = _request(
        "get",
        f"/api/loans/applications/{application.id}/",
        _auth(owner, "customer"),
    )

    response = ApplicationDetailView.as_view()(request, application_id=application.id)

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["disbursement_failure_code"] == "DISBURSEMENT_FAILED"
    assert "disbursement_error" not in payload
    assert "mongodb.internal" not in repr(payload)


def test_disbursement_and_wallet_recovery_serializers_omit_internal_failure_data():
    application = SimpleNamespace(
        id="loan-1",
        status="approved",
        disbursement_status="failed",
        disbursed_amount=10000,
        disbursement_method="wallet",
        disbursement_reference="reference-1",
        disbursement_requested_at=None,
        disbursed_at=None,
        disbursement_error="private RPC failure",
        eth_disbursement_tx_hash="0xtx",
        eth_disbursement_amount="1",
        eth_disbursement_rate=10000,
        eth_disbursement_recipient="0xrecipient",
        eth_disbursement_tx_status="failed",
        eth_disbursement_nonce=99,
        eth_disbursement_prepared_at=None,
        eth_disbursement_broadcast_at=None,
        eth_disbursement_last_checked_at=None,
        eth_disbursement_block_number=None,
        eth_disbursement_rebroadcast_count=1,
        eth_disbursement_amount_wei="100",
        eth_disbursement_recovery_history=[{"reason": "private"}],
    )

    disbursement = DisburseView._response_data(application)
    recovery = WalletDisbursementRecoveryView._data(application)

    assert disbursement["disbursement_failure_code"] == "DISBURSEMENT_FAILED"
    assert recovery["disbursement_failure_code"] == "DISBURSEMENT_FAILED"
    for payload in (disbursement, recovery):
        assert "disbursement_error" not in payload
        assert "private RPC failure" not in repr(payload)
    assert "nonce" not in recovery
    assert "amount_wei" not in recovery
    assert "recovery_history" not in recovery


def test_wallet_verification_failure_returns_stable_error(settings, monkeypatch):
    settings.BLOCKCHAIN_ENABLED = True
    owner = _customer("wallet-error")
    officer = _officer("Wallet")
    application = _application(owner, officer, status="disbursed")
    RepaymentSchedule(
        loan_id=application.id,
        customer_id=str(owner.id),
        principal=10000,
        term_months=1,
        installments=[
            {
                "number": 1,
                "total_amount": 10000,
                "paid_amount": 0,
                "status": "pending",
            }
        ],
    ).save()
    monkeypatch.setattr(
        "loans.blockchain.client.get_web3",
        MagicMock(side_effect=RuntimeError("https://rpc.internal secret-token")),
    )
    request = _request(
        "post",
        f"/api/loans/applications/{application.id}/wallet-payment/",
        _auth(owner, "customer"),
        {"tx_hash": "0x" + "a" * 64, "installment_number": 1},
    )

    response = WalletPaymentView.as_view()(request, application_id=application.id)

    assert response.status_code == 503
    assert response.data["code"] == "BLOCKCHAIN_VERIFICATION_UNAVAILABLE"
    assert "rpc.internal" not in repr(response.data)
    assert "secret-token" not in repr(response.data)


def test_system_wallet_response_omits_rpc_and_connection_exception(
    settings, monkeypatch
):
    settings.BLOCKCHAIN_ENABLED = True
    settings.BLOCKCHAIN_RPC_URL = "https://private-rpc.example/secret"
    owner = _customer("system-wallet")
    monkeypatch.setattr(
        "loans.blockchain.client.get_account",
        MagicMock(side_effect=RuntimeError("private-rpc.example credential")),
    )
    request = _request("get", "/api/loans/system-wallet/", _auth(owner, "customer"))

    response = SystemWalletInfoView.as_view()(request)

    assert response.status_code == 503
    assert response.data["code"] == "BLOCKCHAIN_CONNECTION_UNAVAILABLE"
    assert "private-rpc.example" not in repr(response.data)
    assert "credential" not in repr(response.data)


def test_manual_disbursement_exception_returns_stable_error(monkeypatch):
    owner = _customer("manual-error")
    officer = _officer("Manual")
    application = _application(owner, officer)
    monkeypatch.setattr(
        "loans.views.officer.disburse.execute_manual_disbursement",
        MagicMock(side_effect=RuntimeError("mongodb.internal secret detail")),
    )
    request = _request(
        "post",
        f"/api/loans/officer/applications/{application.id}/disburse/",
        _auth(officer, "loan_officer"),
        {"method": "cash", "amount": 10000},
    )
    request.META["HTTP_IDEMPOTENCY_KEY"] = "stage1-disbursement-key"

    response = DisburseView.as_view()(request, application_id=application.id)

    assert response.status_code == 500
    assert response.data["code"] == "DISBURSEMENT_EXECUTION_FAILED"
    assert "mongodb.internal" not in repr(response.data)
    assert "secret detail" not in repr(response.data)
