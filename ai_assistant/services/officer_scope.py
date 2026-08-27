from dataclasses import dataclass

from accounts.services.consent_service import ConsentService
from accounts.utils.access_control import AccessControlMixin
from accounts.utils.response_helpers import error_response
from rest_framework import status

from loans.models import LoanApplication


@dataclass(frozen=True)
class OfficerAssistantScope:
    officer_id: str
    application_id: str
    customer_id: str
    application: LoanApplication


def resolve_officer_scope(request, application_id):
    """Resolve an assigned application after enforcing the officer role."""
    allowed, actor_or_response = AccessControlMixin().require_roles(
        request, {"loan_officer"}
    )
    if not allowed:
        return None, actor_or_response

    application = LoanApplication.find_by_id(application_id)
    officer_id = str(getattr(request.user, "customer_id", "") or "")
    if (
        not application
        or str(getattr(application, "assigned_officer", "") or "") != officer_id
    ):
        return None, error_response(
            message="Resource not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return OfficerAssistantScope(
        officer_id=officer_id,
        application_id=str(application.id),
        customer_id=str(application.customer_id),
        application=application,
    ), None


def revalidate_officer_scope(scope):
    """Confirm the application is still assigned to the same officer/customer."""
    if not scope:
        return False

    application = LoanApplication.find_by_id(scope.application_id)
    return bool(
        application
        and str(application.id) == str(scope.application_id)
        and str(getattr(application, "assigned_officer", "") or "")
        == str(scope.officer_id)
        and str(getattr(application, "customer_id", "") or "")
        == str(scope.customer_id)
    )


def has_current_ai_consent(scope):
    """Return the current customer AI-consent decision for this scope."""
    if not scope:
        return False
    try:
        return bool(ConsentService.check_ai_consent(scope.customer_id, "customer"))
    except Exception:
        return False
