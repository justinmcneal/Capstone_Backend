"""Payment submission and posting services.

Payment records are created before schedule mutation. The payment's idempotency
key is also written to the installment during the atomic balance update, allowing
an interrupted request to recover without applying the same payment twice.
"""

import hashlib

from pymongo.errors import DuplicateKeyError

from loans.models import LoanPayment
from loans.utils.money import from_centavos, to_centavos
from loans.utils.time import utcnow


class PaymentServiceError(ValueError):
    """A safe payment-domain error that can be returned to an API client."""


class PaymentConflictError(PaymentServiceError):
    """An idempotency key or external reference was reused incompatibly."""


def normalize_idempotency_key(value):
    key = str(value or "").strip()
    if not 8 <= len(key) <= 128:
        raise PaymentServiceError(
            "Idempotency-Key must contain between 8 and 128 characters"
        )
    return key


def scoped_idempotency_key(scope, actor_id, value):
    """Namespace a client key without exposing it or exceeding index limits."""
    key = normalize_idempotency_key(value)
    material = f"{scope}:{actor_id}:{key}".encode()
    return f"{scope}:{hashlib.sha256(material).hexdigest()}"


def _assert_same_payment(payment, *, loan_id, installment_number, amount, method):
    same_payload = (
        str(payment.loan_id) == str(loan_id)
        and payment.installment_number == installment_number
        and payment.amount_centavos == to_centavos(amount)
        and payment.payment_method == method
    )
    if not same_payload:
        raise PaymentConflictError(
            "Idempotency-Key was already used for a different payment"
        )


def _find_duplicate(idempotency_key, reference_fingerprint):
    payment = LoanPayment.find_one({"idempotency_key": idempotency_key})
    if payment:
        return payment
    if reference_fingerprint:
        payment = LoanPayment.find_one({"reference_fingerprint": reference_fingerprint})
        if payment:
            raise PaymentConflictError(
                "This external payment reference has already been submitted"
            )
    return None


def _query_metadata(schedule, installment_number):
    """Return denormalized, indexed payment scope and timing metadata."""
    from loans.models import LoanApplication

    application = LoanApplication.find_by_id(schedule.loan_id)
    timing_status = "payoff" if installment_number == 0 else "unknown"
    installment = schedule.get_installment(installment_number)
    due_date = installment.get("due_date") if installment else None
    if due_date and installment_number:
        timing_status = "on_time" if utcnow().date() <= due_date.date() else "late"
    return {
        "timing_status": timing_status,
        "scope_officer_id": str(getattr(application, "assigned_officer", "") or "")
        if application
        else "",
        "loan_disbursed": bool(
            application
            and getattr(application, "status", "")
            in {"disbursed", "completed", "written_off"}
        ),
    }


def create_pending_submission(
    *,
    schedule,
    installment_number,
    amount,
    payment_method,
    reference,
    notes,
    customer_id,
    idempotency_key,
):
    """Record customer-provided evidence without applying it to the balance."""
    key = normalize_idempotency_key(idempotency_key)
    fingerprint = LoanPayment.fingerprint_reference(payment_method, reference)
    existing = _find_duplicate(key, fingerprint)
    if existing:
        _assert_same_payment(
            existing,
            loan_id=schedule.loan_id,
            installment_number=installment_number,
            amount=amount,
            method=payment_method,
        )
        return existing, True

    payment = LoanPayment(
        loan_id=schedule.loan_id,
        schedule_id=schedule.id,
        customer_id=str(customer_id),
        installment_number=installment_number,
        amount=amount,
        amount_centavos=to_centavos(amount),
        payment_method=payment_method,
        reference=reference,
        reference_fingerprint=fingerprint,
        notes=notes,
        recorded_by=str(customer_id),
        payment_status="pending_verification",
        idempotency_key=key,
        verification_source="customer_submission",
        blockchain_sync_status="not_started",
        **_query_metadata(schedule, installment_number),
    )
    try:
        payment.save()
    except DuplicateKeyError:
        existing = _find_duplicate(key, fingerprint)
        if not existing:
            raise
        _assert_same_payment(
            existing,
            loan_id=schedule.loan_id,
            installment_number=installment_number,
            amount=amount,
            method=payment_method,
        )
        return existing, True
    return payment, False


def post_verified_payment(
    *,
    schedule,
    installment_number,
    amount,
    payment_method,
    reference,
    notes,
    recorded_by,
    idempotency_key,
    verification_source,
    recorded_by_type="system",
    extra_fields=None,
):
    """Idempotently create and apply an already verified payment."""
    key = normalize_idempotency_key(idempotency_key)
    fingerprint = (
        LoanPayment.fingerprint_reference(payment_method, reference)
        if reference
        else ""
    )
    existing = _find_duplicate(key, fingerprint)
    replayed = existing is not None

    if existing:
        _assert_same_payment(
            existing,
            loan_id=schedule.loan_id,
            installment_number=installment_number,
            amount=amount,
            method=payment_method,
        )
        if existing.payment_status == "posted":
            installment = schedule.get_installment(installment_number)
            return existing, installment, True
        if existing.payment_status == "failed":
            raise PaymentConflictError(
                existing.failure_reason or "The previous payment attempt failed"
            )
        payment = existing
    else:
        fields = {**_query_metadata(schedule, installment_number), **(extra_fields or {})}
        payment = LoanPayment(
            loan_id=schedule.loan_id,
            schedule_id=schedule.id,
            customer_id=schedule.customer_id,
            installment_number=installment_number,
            amount=amount,
            amount_centavos=to_centavos(amount),
            payment_method=payment_method,
            reference=reference,
            reference_fingerprint=fingerprint,
            notes=notes,
            recorded_by=str(recorded_by),
            payment_status="posting",
            idempotency_key=key,
            verification_source=verification_source,
            **fields,
        )
        try:
            payment.save()
        except DuplicateKeyError:
            payment = _find_duplicate(key, fingerprint)
            if not payment:
                raise
            _assert_same_payment(
                payment,
                loan_id=schedule.loan_id,
                installment_number=installment_number,
                amount=amount,
                method=payment_method,
            )
            replayed = True

    try:
        installment, schedule_replay = schedule.apply_payment_atomic(
            installment_number,
            amount,
            payment.idempotency_key,
        )
        payment.mark_posted(verification_source)
        _sync_paid_off_application(
            schedule, actor_id=recorded_by, actor_type=recorded_by_type
        )
        return payment, installment, replayed or schedule_replay
    except Exception as exc:
        # Do not mark failed if the schedule already contains the token: a later
        # replay must be able to finish a payment-status write interrupted after
        # the schedule mutation.
        refreshed = schedule.find_one({"_id": schedule._id})
        tokens = refreshed.applied_payment_tokens if refreshed else []
        if payment.idempotency_key not in tokens:
            payment.mark_failed(exc)
        raise


def _sync_paid_off_application(schedule, actor_id=None, actor_type="system"):
    """Keep the loan lifecycle state aligned with an exactly settled schedule."""
    refreshed = schedule.find_one({"_id": schedule._id}) if schedule._id else schedule
    if not refreshed or not refreshed.is_paid_off():
        return
    from loans.models import LoanApplication

    application = LoanApplication.find_by_id(refreshed.loan_id)
    if application and hasattr(application, "mark_paid_off"):
        application.mark_paid_off(
            refreshed.paid_off_at,
            actor_id=actor_id,
            actor_type=actor_type,
            source="verified_payment",
            allow_legacy_schedule=True,
        )


def post_verified_early_payoff(
    *,
    schedule,
    amount,
    payment_method,
    reference,
    notes,
    recorded_by,
    idempotency_key,
    verification_source,
    recorded_by_type="system",
):
    """Post one verified cash/check payment across all open installments."""
    key = normalize_idempotency_key(idempotency_key)
    fingerprint = (
        LoanPayment.fingerprint_reference(payment_method, reference)
        if reference
        else ""
    )
    existing = _find_duplicate(key, fingerprint)
    replayed = existing is not None
    if existing:
        _assert_same_payment(
            existing,
            loan_id=schedule.loan_id,
            installment_number=0,
            amount=amount,
            method=payment_method,
        )
        if existing.payment_status == "posted":
            _sync_paid_off_application(
                schedule, actor_id=recorded_by, actor_type=recorded_by_type
            )
            return existing, existing.allocations, True
        if existing.payment_status == "failed":
            raise PaymentConflictError(
                existing.failure_reason or "The previous payoff attempt failed"
            )
        payment = existing
    else:
        prepared_allocations = []
        for installment in schedule.installments:
            remaining = max(
                schedule._required_centavos(installment)
                - schedule._centavos(installment, "paid_amount"),
                0,
            )
            if remaining:
                prepared_allocations.append(
                    {
                        "installment_number": installment["number"],
                        "amount_centavos": remaining,
                        "amount": from_centavos(remaining),
                    }
                )
        payment = LoanPayment(
            loan_id=schedule.loan_id,
            schedule_id=schedule.id,
            customer_id=schedule.customer_id,
            installment_number=0,
            amount=from_centavos(to_centavos(amount)),
            amount_centavos=to_centavos(amount),
            payment_method=payment_method,
            reference=reference,
            reference_fingerprint=fingerprint,
            notes=notes,
            recorded_by=str(recorded_by),
            payment_status="posting",
            idempotency_key=key,
            verification_source=verification_source,
            blockchain_sync_status="not_applicable",
            allocations=prepared_allocations,
            **_query_metadata(schedule, 0),
        )
        try:
            payment.save()
        except DuplicateKeyError:
            payment = _find_duplicate(key, fingerprint)
            if not payment:
                raise
            _assert_same_payment(
                payment,
                loan_id=schedule.loan_id,
                installment_number=0,
                amount=amount,
                method=payment_method,
            )
            replayed = True

    try:
        allocations, schedule_replay = schedule.apply_early_payoff_atomic(
            amount, payment.idempotency_key
        )
        if not allocations and payment.allocations:
            allocations = payment.allocations
        payment.allocations = allocations
        payment.mark_posted(verification_source)
        _sync_paid_off_application(
            schedule, actor_id=recorded_by, actor_type=recorded_by_type
        )
        return payment, allocations, replayed or schedule_replay
    except Exception as exc:
        refreshed = schedule.find_one({"_id": schedule._id})
        tokens = refreshed.applied_payment_tokens if refreshed else []
        if payment.idempotency_key not in tokens:
            payment.mark_failed(exc)
        raise
