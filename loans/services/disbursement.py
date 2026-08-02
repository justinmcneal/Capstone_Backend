"""Durable loan-disbursement state transitions."""

from loans.models import LoanProduct, RepaymentSchedule
from loans.services.payment import scoped_idempotency_key

MANUAL_DISBURSEMENT_METHODS = {"cash", "check"}
EXTERNAL_DISBURSEMENT_METHODS = {"gcash", "bank_transfer", "wallet"}


def disbursement_idempotency_key(actor_id, client_key):
    return scoped_idempotency_key("disbursement", actor_id, client_key)


def begin_disbursement(
    *, application, amount, method, reference, actor_id, idempotency_key
):
    """Reserve a disbursement without claiming external settlement."""
    return application.begin_disbursement(
        amount=amount,
        method=method,
        reference=reference,
        processed_by=actor_id,
        idempotency_key=idempotency_key,
    )


def execute_manual_disbursement(
    *, application, amount, method, reference, actor_id, idempotency_key
):
    """Execute an officer-confirmed cash/check disbursement exactly once."""
    application, _request_replayed = begin_disbursement(
        application=application,
        amount=amount,
        method=method,
        reference=reference,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    if application.disbursement_status == "executed":
        return application, RepaymentSchedule.find_by_loan(application.id), True

    try:
        product = LoanProduct.find_by_id(application.product_id)
        if not product:
            raise ValueError("Loan product not found; repayment schedule cannot be created")

        schedule = RepaymentSchedule.find_by_loan(application.id)
        if not schedule:
            schedule = RepaymentSchedule.generate_for_loan(application, product)

        application, completion_replayed = application.complete_disbursement(
            idempotency_key
        )
        return application, schedule, completion_replayed
    except Exception as exc:
        application.fail_disbursement(idempotency_key, exc)
        raise
