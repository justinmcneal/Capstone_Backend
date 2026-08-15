"""Stage 4 Loans persistence, search, bounds, and job-control regressions."""

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

from bson import ObjectId
from cryptography.fernet import Fernet
from django.core.management import call_command
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.authentication import AuthenticatedUser
from loans.models import LoanApplication, LoanPayment, RepaymentSchedule
from loans.services.job_control import (
    acquire_job_lease,
    release_job_lease,
    run_bounded_scan,
)
from loans.services.persistence import (
    LOAN_VALIDATORS,
    loan_data_inventory,
    prepare_loan_backfill,
)
from loans.services.related_data import find_models_bounded
from loans.utils.time import utcnow
from loans.views.customer.products import LoanProductListView
from loans.views.officer.schedule_export import BulkRepaymentScheduleExportView


def _application(**overrides):
    values = {
        "customer_id": str(ObjectId()),
        "product_id": str(ObjectId()),
        "requested_amount": 1_000,
        "approved_amount": 1_000,
        "term_months": 1,
        "status": "disbursed",
        "assigned_officer": "officer-stage4",
    }
    values.update(overrides)
    return LoanApplication(**values).save()


def _schedule(application):
    return RepaymentSchedule(
        loan_id=application.id,
        customer_id=application.customer_id,
        principal=1_000,
        total_amount=1_000,
        installments=[
            {
                "number": 1,
                "principal": 1_000,
                "interest": 0,
                "total_amount": 1_000,
                "paid_amount": 0,
                "status": "pending",
                "due_date": utcnow() + timedelta(days=2),
            }
        ],
    ).save()


def test_validator_manifest_covers_every_primary_collection_and_encrypted_shapes():
    assert set(LOAN_VALIDATORS) == {
        "loan_products",
        "loan_applications",
        "repayment_schedules",
        "loan_payments",
        "blockchain_transactions",
    }
    schedule = LOAN_VALIDATORS["repayment_schedules"]["$jsonSchema"]
    assert schedule["properties"]["installments"]["pattern"].startswith("^encbson")
    payment = LOAN_VALIDATORS["loan_payments"]["$jsonSchema"]
    assert "reference_search_index" in payment["required"]
    assert "scope_officer_id" in payment["required"]
    assert payment["properties"]["payment_method"]["enum"] == [
        "cash",
        "check",
        "wallet",
    ]
    application = LOAN_VALIDATORS["loan_applications"]["$jsonSchema"]
    assert application["properties"]["disbursement_method"]["oneOf"][1][
        "enum"
    ] == ["cash", "check", "wallet"]


def test_inventory_is_count_only_and_detects_legacy_and_duplicate_rows(settings):
    settings.MONGODB["loan_products"].insert_many(
        [
            {"name": "One", "code": "DUP", "description": "secret-one"},
            {"name": "Two", "code": "DUP", "description": "secret-two"},
        ]
    )
    result = loan_data_inventory(limit=10)
    product = result["collections"]["loan_products"]
    assert product["duplicate_unique_values"] == 1
    assert product["plaintext_sensitive"] == 2
    assert product["missing_required"] == 2
    assert "DUP" not in repr(result)
    assert "secret-one" not in repr(result)
    assert "secret-two" not in repr(result)


def test_inventory_flags_unsupported_settlement_values(settings):
    settings.MONGODB["loan_payments"].insert_one(
        {
            "loan_id": str(ObjectId()),
            "customer_id": str(ObjectId()),
            "payment_method": "card",
            "payment_status": "posted",
            "recorded_at": utcnow(),
        }
    )

    payment = loan_data_inventory(limit=10)["collections"]["loan_payments"]

    assert payment["invalid_enum"] == 1


def test_payment_backfill_builds_search_scope_timing_and_centavos(settings):
    application = _application()
    schedule = _schedule(application)
    raw = {
        "_id": ObjectId(),
        "loan_id": application.id,
        "schedule_id": schedule.id,
        "customer_id": application.customer_id,
        "installment_number": 1,
        "amount": 125.5,
        "payment_method": "cash",
        "payment_status": "posted",
        "reference": " OR-Stage4  ",
        "notes": "counter",
        "recorded_at": utcnow(),
    }
    update = prepare_loan_backfill("loan_payments", raw)
    assert update["amount_centavos"] == 12_550
    assert update["reference_search_index"] in LoanPayment.reference_search_candidates(
        "or-stage4"
    )
    assert update["scope_officer_id"] == "officer-stage4"
    assert update["timing_status"] == "on_time"
    assert update["loan_disbursed"] is True


def test_backfill_command_is_dry_run_by_default(settings):
    if not getattr(settings, "FIELD_ENCRYPTION_KEY", ""):
        settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    raw_id = settings.MONGODB["loan_payments"].insert_one(
        {
            "loan_id": str(ObjectId()),
            "customer_id": str(ObjectId()),
            "installment_number": 1,
            "amount": 10,
            "payment_method": "cash",
            "payment_status": "posted",
            "reference": "LEGACY-STAGE4",
            "recorded_at": utcnow(),
        }
    ).inserted_id
    output = StringIO()
    call_command("backfill_loan_data", limit=10, stdout=output)
    stored = settings.MONGODB["loan_payments"].find_one({"_id": raw_id})
    assert "DRY-RUN" in output.getvalue()
    assert "reference_search_index" not in stored


def test_payment_reference_search_is_keyed_exact_and_not_ciphertext_regex(settings):
    application = _application()
    schedule = _schedule(application)
    payment = LoanPayment(
        loan_id=application.id,
        schedule_id=schedule.id,
        customer_id=application.customer_id,
        installment_number=1,
        amount=100,
        payment_method="cash",
        payment_status="posted",
        reference=" OR-EXACT-100 ",
        recorded_at=utcnow(),
    ).save()
    raw = settings.MONGODB["loan_payments"].find_one({"_id": payment._id})
    assert raw["reference_search_index"] in LoanPayment.reference_search_candidates(
        "or-exact-100"
    )
    assert raw["reference_search_index"] not in {"OR-EXACT-100", "or-exact-100"}


def test_job_lease_rejects_overlap_and_bounded_scan_resumes(settings):
    owner = acquire_job_lease("stage4-overlap", owner="worker-a")
    assert owner == "worker-a"
    assert acquire_job_lease("stage4-overlap", owner="worker-b") is None
    release_job_lease("stage4-overlap", owner)

    settings.LOAN_JOB_BATCH_SIZE = 2
    settings.LOAN_JOB_MAX_BATCHES = 1
    settings.MONGODB["stage4_rows"].insert_many(
        [{"value": number} for number in range(5)]
    )
    seen = []
    first = run_bounded_scan(
        "stage4-checkpoint", "stage4_rows", {}, lambda row: seen.append(row["value"])
    )
    second = run_bounded_scan(
        "stage4-checkpoint", "stage4_rows", {}, lambda row: seen.append(row["value"])
    )
    assert first == {"processed": 2, "complete": False, "lease_acquired": True}
    assert second == {"processed": 2, "complete": False, "lease_acquired": True}
    assert seen == [0, 1, 2, 3]


def test_bounded_lookup_reports_truncation(settings):
    settings.MONGODB["loan_applications"].insert_many(
        [
            {
                "customer_id": str(ObjectId()),
                "product_id": str(ObjectId()),
                "requested_amount": 100,
                "term_months": 1,
                "status": "submitted",
            }
            for _ in range(3)
        ]
    )
    applications, truncated = find_models_bounded(LoanApplication, {}, limit=2)
    assert len(applications) == 2
    assert truncated is True


def test_loan_celery_jobs_have_dedicated_bounds_and_routes(settings):
    recurring = {
        "loans.tasks.check_overdue_installments_task",
        "loans.reconcile_repayment_lifecycle",
        "loans.reconcile_wallet_disbursements_task",
    }
    assert recurring <= set(settings.CELERY_TASK_ANNOTATIONS)
    assert all(
        settings.CELERY_TASK_ROUTES[name]["queue"] == "loans" for name in recurring
    )
    assert all(
        settings.CELERY_TASK_ANNOTATIONS[name]["acks_late"] for name in recurring
    )
    assert settings.LOAN_TASK_SOFT_TIME_LIMIT < settings.LOAN_TASK_TIME_LIMIT
    assert settings.LOAN_TASK_TIME_LIMIT <= settings.LOAN_JOB_LEASE_SECONDS


def test_customer_products_are_database_paginated(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        "loans.views.customer.products.LoanProduct.count", staticmethod(lambda **_: 9)
    )

    def find(**kwargs):
        calls.update(kwargs)
        return []

    monkeypatch.setattr(
        "loans.views.customer.products.LoanProduct.find", staticmethod(find)
    )
    monkeypatch.setattr(
        LoanProductListView,
        "check_customer_permission",
        lambda self, request: (True, request.user),
    )
    user = AuthenticatedUser(
        customer_id=str(ObjectId()),
        email="stage4@example.com",
        verified=True,
        role="customer",
    )
    request = APIRequestFactory().get("/api/loans/products/?page=2&page_size=3")
    force_authenticate(request, user=user)
    response = LoanProductListView.as_view()(request)
    assert response.status_code == 200
    assert calls == {"active_only": True, "skip": 3, "limit": 3}
    assert response.data["data"]["total_pages"] == 3


def test_synchronous_export_rejects_more_than_configured_rows(settings, monkeypatch):
    settings.LOAN_EXPORT_MAX_ROWS = 3
    monkeypatch.setattr(
        BulkRepaymentScheduleExportView,
        "check_officer_permission",
        lambda self, request: (True, request.user),
    )
    monkeypatch.setattr(
        BulkRepaymentScheduleExportView,
        "_iter_rows",
        lambda self, *args: iter([{"row": number} for number in range(4)]),
    )
    user = SimpleNamespace(
        customer_id="admin-stage4",
        role="admin",
        is_authenticated=True,
    )
    request = APIRequestFactory().get("/api/loans/officer/schedules/export/")
    force_authenticate(request, user=user)
    response = BulkRepaymentScheduleExportView.as_view()(request)
    assert response.status_code == 413
    assert response.data["code"] == "LOAN_EXPORT_LIMIT_EXCEEDED"
