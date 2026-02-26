"""
Centralized RBAC + ABAC helpers for API views.

RBAC:
- Role enforcement (customer / loan_officer / admin)
- Admin permission and super-admin checks
- Active account checks for privileged roles

ABAC:
- Resource ownership checks
- Officer/admin scoping for loan application actions
"""
from __future__ import annotations

from typing import Iterable

from bson import ObjectId
from django.conf import settings
from rest_framework import status

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.response_helpers import error_response


class AccessControlMixin:
    """Reusable authorization helpers for APIView classes."""

    _ACTOR_CACHE_ATTR = "_auth_actor"

    def _role(self, request):
        return str(getattr(request.user, "role", "") or "").strip().lower()

    def _subject_id(self, request):
        return str(getattr(request.user, "customer_id", "") or "").strip()

    def _id_variants(self, raw_id):
        """
        Return identifier variants for mixed ObjectId/string legacy storage.

        Example:
        "65..." -> [ObjectId("65..."), "65..."]
        """
        if raw_id is None:
            return []

        variants = []
        if isinstance(raw_id, ObjectId):
            variants.append(raw_id)
            variants.append(str(raw_id))
        else:
            text = str(raw_id).strip()
            if not text:
                return []
            if ObjectId.is_valid(text):
                variants.append(ObjectId(text))
            variants.append(text)

        seen = set()
        deduped = []
        for value in variants:
            marker = (type(value).__name__, str(value))
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(value)
        return deduped

    def _concealed_denied(self, message="Resource not found"):
        return error_response(message=message, status_code=status.HTTP_404_NOT_FOUND)

    def _role_error_message(self, allowed_roles: set[str]):
        roles = set(allowed_roles)
        if roles == {"customer"}:
            return "Customer access required"
        if roles == {"admin"}:
            return "Admin access required"
        if roles == {"loan_officer"}:
            return "Loan officer access required"
        if roles == {"loan_officer", "admin"}:
            return "Loan officer or admin access required"
        return "Insufficient role permissions"

    def _load_actor(self, request):
        if hasattr(request, self._ACTOR_CACHE_ATTR):
            return getattr(request, self._ACTOR_CACHE_ATTR)

        role = self._role(request)
        subject_id = self._subject_id(request)

        actor = None
        if not role or not subject_id:
            setattr(request, self._ACTOR_CACHE_ATTR, None)
            return None

        query_candidates = []
        if ObjectId.is_valid(subject_id):
            query_candidates.append({"_id": ObjectId(subject_id)})
        query_candidates.append({"_id": subject_id})

        if role in {"admin", "super_admin"}:
            for query in query_candidates:
                actor = Admin.find_one(query)
                if actor:
                    break
        elif role == "loan_officer":
            for query in query_candidates:
                actor = LoanOfficer.find_one(query)
                if actor:
                    break
        elif role == "customer":
            for query in query_candidates:
                actor = Customer.find_one(query)
                if actor:
                    break

        setattr(request, self._ACTOR_CACHE_ATTR, actor)
        return actor

    def require_roles(
        self,
        request,
        allowed_roles: Iterable[str],
        require_existing_actor: bool = True,
        enforce_active_for_privileged: bool = True,
    ):
        """
        RBAC check by role (+ actor existence and active status where required).

        Returns:
            (True, actor) on success
            (False, response) on failure
        """
        allowed = {str(r).strip().lower() for r in allowed_roles if str(r).strip()}
        role = self._role(request)

        if role not in allowed:
            return False, error_response(
                message=self._role_error_message(allowed),
                status_code=status.HTTP_403_FORBIDDEN,
            )

        actor = self._load_actor(request)
        if require_existing_actor and actor is None:
            return False, error_response(
                message="Authenticated account not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if (
            enforce_active_for_privileged
            and role in {"admin", "super_admin", "loan_officer"}
            and actor is not None
            and hasattr(actor, "active")
            and not actor.active
        ):
            return False, error_response(
                message="Account is deactivated",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return True, actor

    def require_customer(self, request):
        return self.require_roles(request, {"customer"})

    def require_officer_or_admin(self, request):
        return self.require_roles(request, {"loan_officer", "admin", "super_admin"})

    def require_admin(self, request, required_permissions=None, super_admin_only=False):
        """
        RBAC check for admin role plus fine-grained permission checks.

        Returns:
            (True, admin) on success
            (False, response) on failure
        """
        has_role, result = self.require_roles(request, {"admin", "super_admin"})
        if not has_role:
            return False, result

        admin = result
        if not admin:
            return False, error_response(
                message="Admin not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if super_admin_only and not getattr(admin, "super_admin", False):
            return False, error_response(
                message="Super admin access required",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        permissions = list(required_permissions or [])
        if permissions and not admin.has_all_permissions(permissions):
            return False, error_response(
                message="Insufficient permissions",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return True, admin

    def require_owner(self, request, owner_id, conceal_existence=True):
        """
        ABAC owner check (subject.customer_id must match resource owner id).

        Returns:
            (True, request.user) on success
            (False, response) on failure
        """
        subject_id = self._subject_id(request)
        owner = str(owner_id or "").strip()

        if subject_id and owner and subject_id == owner:
            return True, request.user

        status_code = status.HTTP_404_NOT_FOUND if conceal_existence else status.HTTP_403_FORBIDDEN
        message = "Resource not found" if conceal_existence else "You do not own this resource"
        return False, error_response(message=message, status_code=status_code)

    def require_application_scope(self, request, application, allow_unassigned=True, conceal_existence=True):
        """
        ABAC check for application access:
        - Admins: full access
        - Loan officers: only assigned apps, or unassigned when allow_unassigned=True

        Returns:
            (True, actor) on success
            (False, response) on failure
        """
        has_role, actor_or_response = self.require_officer_or_admin(request)
        if not has_role:
            return False, actor_or_response

        role = self._role(request)
        if role in {"admin", "super_admin"}:
            return True, actor_or_response

        assigned_officer = str(getattr(application, "assigned_officer", "") or "").strip()
        subject_id = self._subject_id(request)

        if not assigned_officer:
            if allow_unassigned:
                return True, actor_or_response
            status_code = status.HTTP_404_NOT_FOUND if conceal_existence else status.HTTP_403_FORBIDDEN
            return False, error_response(
                message="Application not found" if conceal_existence else "Application is not assigned to you",
                status_code=status_code,
            )

        if assigned_officer != subject_id:
            status_code = status.HTTP_404_NOT_FOUND if conceal_existence else status.HTTP_403_FORBIDDEN
            return False, error_response(
                message="Application not found" if conceal_existence else "Application is assigned to another officer",
                status_code=status_code,
            )

        return True, actor_or_response

    def get_officer_scoped_customer_ids(self, request, include_unassigned=True):
        """
        Return customer IDs a loan officer can access for document-level operations.

        Scope for `loan_officer`:
        - customers with applications assigned to this officer
        - optionally customers with unassigned submitted/under_review applications

        Returns:
            (True, None) for admin/super_admin (unrestricted)
            (True, set[str]) for loan_officer
            (False, response) on permission failure
        """
        has_role, actor_or_response = self.require_officer_or_admin(request)
        if not has_role:
            return False, actor_or_response

        role = self._role(request)
        if role in {"admin", "super_admin"}:
            return True, None

        subject_id = self._subject_id(request)
        if not subject_id:
            return False, self._concealed_denied("Authenticated account not found")

        db = getattr(settings, "MONGODB", None)
        if db is None:
            return False, error_response(
                message="Database is not configured",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        applications = db["loan_applications"]

        # Always allow customers currently handled by this officer.
        customer_ids = set()
        for row in applications.find({"assigned_officer": subject_id}, {"customer_id": 1}):
            customer_id = str(row.get("customer_id", "") or "").strip()
            if customer_id:
                customer_ids.add(customer_id)

        if include_unassigned:
            # Allow unassigned pending queues, but do not leak customers
            # actively assigned to another officer.
            pending_statuses = {"submitted", "under_review"}
            unassigned_customers = set()
            blocked_customers = set()

            for row in applications.find(
                {
                    "status": {"$in": list(pending_statuses)},
                    "$or": [
                        {"assigned_officer": None},
                        {"assigned_officer": ""},
                        {"assigned_officer": {"$exists": False}},
                    ],
                },
                {"customer_id": 1},
            ):
                customer_id = str(row.get("customer_id", "") or "").strip()
                if customer_id:
                    unassigned_customers.add(customer_id)

            for row in applications.find(
                {
                    "status": {"$in": list(pending_statuses)},
                    "assigned_officer": {"$nin": [None, "", subject_id]},
                },
                {"customer_id": 1},
            ):
                customer_id = str(row.get("customer_id", "") or "").strip()
                if customer_id:
                    blocked_customers.add(customer_id)

            customer_ids.update(unassigned_customers - blocked_customers)

        # Include customers who uploaded documents (e.g. during profile
        # completion) but don't yet have a submitted loan application.
        # This ensures officers can review pending/needs_review documents
        # even before the customer submits a formal application.
        docs_collection = db["documents"]
        doc_customer_ids = set()
        for row in docs_collection.find(
            {"status": {"$in": ["pending", "needs_review"]}},
            {"customer_id": 1},
        ):
            cid = str(row.get("customer_id", "") or "").strip()
            if cid and cid not in customer_ids:
                doc_customer_ids.add(cid)

        if doc_customer_ids:
            # Exclude customers whose documents are already covered
            # by an application assigned to another officer.
            customer_ids.update(doc_customer_ids - blocked_customers)

        return True, customer_ids

    def require_customer_scope_for_officer(
        self,
        request,
        customer_id,
        include_unassigned=True,
        conceal_existence=True,
    ):
        """
        ABAC check for officer/admin access to customer-owned resources (e.g., documents).

        Admin/super_admin: always allowed.
        Loan officer: allowed only when customer is in officer scope.
        """
        has_scope, result = self.get_officer_scoped_customer_ids(
            request,
            include_unassigned=include_unassigned,
        )
        if not has_scope:
            return False, result

        # Admin/super_admin path returns None (unrestricted).
        if result is None:
            return True, request.user

        scoped_customer_ids = result
        target_id = str(customer_id or "").strip()
        if target_id and target_id in scoped_customer_ids:
            return True, request.user

        if conceal_existence:
            return False, self._concealed_denied("Resource not found")
        return False, error_response(
            message="Resource is outside your assigned scope",
            status_code=status.HTTP_403_FORBIDDEN,
        )
