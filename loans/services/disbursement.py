"""Durable loan-disbursement state transitions."""

from loans.models import LoanProduct, RepaymentSchedule
from loans.services.payment import scoped_idempotency_key

MANUAL_DISBURSEMENT_METHODS = {"cash", "check"}
WALLET_DISBURSEMENT_METHODS = {"wallet"}
PLANNED_PROVIDER_DISBURSEMENT_METHODS = {"gcash", "bank_transfer"}
# Compatibility set for persisted records and dispatch validation. The canonical
# settlement policy still blocks planned provider methods before mutation.
EXTERNAL_DISBURSEMENT_METHODS = (
    WALLET_DISBURSEMENT_METHODS | PLANNED_PROVIDER_DISBURSEMENT_METHODS
)


def disbursement_idempotency_key(actor_id, client_key):
    return scoped_idempotency_key("disbursement", actor_id, client_key)


def begin_disbursement(
    *,
    application,
    amount,
    method,
    reference,
    actor_id,
    idempotency_key,
    actor_type="system",
):
    """Reserve a disbursement without claiming external settlement."""
    return application.begin_disbursement(
        amount=amount,
        method=method,
        reference=reference,
        processed_by=actor_id,
        idempotency_key=idempotency_key,
        processed_by_type=actor_type,
    )


def execute_manual_disbursement(
    *,
    application,
    amount,
    method,
    reference,
    actor_id,
    idempotency_key,
    actor_type="system",
):
    """Execute an officer-confirmed cash/check disbursement exactly once."""
    application, _request_replayed = begin_disbursement(
        application=application,
        amount=amount,
        method=method,
        reference=reference,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        actor_type=actor_type,
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
