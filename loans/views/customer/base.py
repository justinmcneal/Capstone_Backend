import logging

from accounts.utils.access_control import AccessControlMixin

logger = logging.getLogger("loans")


class CustomerRoleRequiredMixin(AccessControlMixin):
    """Require customer role for customer-facing loan endpoints."""

    def check_customer_permission(self, request):
        return self.require_customer(request)


def _serialize_customer_application_detail(app, product):
    interest_rate_monthly_pct = None
    if product and product.interest_rate is not None:
        try:
            interest_rate_monthly_pct = round(float(product.interest_rate) * 100, 2)
        except (TypeError, ValueError):
            interest_rate_monthly_pct = None

    return {
        "id": app.id,
        "product": {
            "id": product.id if product else None,
            "name": product.name if product else "Unknown",
        },
        "requested_amount": app.requested_amount,
        "recommended_amount": app.recommended_amount,
        "approved_amount": app.approved_amount,
        "term_months": app.term_months,
        "interest_rate": interest_rate_monthly_pct,
        "purpose": app.purpose,
        "status": app.status,
        "eligibility_score": app.eligibility_score,
        "risk_category": app.risk_category,
        "rejection_reason": app.rejection_reason,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "decision_date": app.decision_date.isoformat() if app.decision_date else None,
        "preferred_disbursement_method": app.preferred_disbursement_method,
        "disbursement_status": app.disbursement_status,
        "disbursement_method": app.disbursement_method,
        "disbursed_amount": app.disbursed_amount,
        "disbursement_requested_at": (
            app.disbursement_requested_at.isoformat()
            if app.disbursement_requested_at
            else None
        ),
        "disbursement_error": app.disbursement_error,
        "repayment_status": app.repayment_status,
        "paid_off_at": app.paid_off_at.isoformat() if app.paid_off_at else None,
        "disbursed_at": app.disbursed_at.isoformat() if app.disbursed_at else None,
        "created_at": app.created_at.isoformat(),
    }


def _safe_customer_display_name(user):
    full_name = getattr(user, "full_name", None)
    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()

    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    name_parts = [
        part.strip()
        for part in [first_name, last_name]
        if isinstance(part, str) and part.strip()
    ]
    if name_parts:
        return " ".join(name_parts)

    email = getattr(user, "email", None)
    if isinstance(email, str) and email.strip():
        return email.strip()

    return "Customer"
