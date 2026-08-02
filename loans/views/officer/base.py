from accounts.utils.access_control import AccessControlMixin
from loans.utils.serialization import serialize_internal_note
import logging

logger = logging.getLogger("loans")


def internal_note_summary(app):
    notes = app.internal_notes or []
    latest = serialize_internal_note(notes[-1]) if notes else None
    return {
        "internal_notes_count": len(notes),
        "latest_internal_note": latest,
    }


class LoanOfficerRequiredMixin(AccessControlMixin):
    """Mixin to require loan officer or admin role"""

    def check_officer_permission(self, request):
        return self.require_officer_or_admin(request)

    @staticmethod
    def _actor_id(actor):
        """
        Resolve a stable actor ID across auth/user object types.

        - AuthenticatedUser wrapper uses `customer_id` for all roles
        - LoanOfficer/Admin domain models expose `.id`
        """
        value = (
            getattr(actor, "customer_id", None)
            or getattr(actor, "user_id", None)
            or getattr(actor, "id", None)
            or getattr(actor, "_id", None)
        )
        return str(value or "")

    @staticmethod
    def _actor_type(actor):
        role = str(getattr(actor, "role", "") or "").strip().lower()
        return role if role in {"admin", "loan_officer", "customer"} else "system"

    def check_application_scope(self, request, application, allow_unassigned=True):
        return self.require_application_scope(
            request,
            application,
            allow_unassigned=allow_unassigned,
            conceal_existence=True,
        )
