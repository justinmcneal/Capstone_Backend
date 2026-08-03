import logging
from typing import ClassVar

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken

from accounts.models import Admin, Customer, LoanOfficer
from accounts.utils.token_utils import TokenUtils

logger = logging.getLogger("authentication")


class AuthenticatedUser:
    """
    User object representing an authenticated user.

    Supports three user types:
    - customer: MSME microentrepreneurs
    - loan_officer: Bank/microfinance staff
    - admin: System administrators
    """

    def __init__(
        self,
        customer_id,
        email,
        verified,
        role="customer",
        *,
        active=True,
        must_change_password=False,
        security_version=1,
        session_id=None,
    ):
        self.customer_id = customer_id  # User ID (works for all user types)
        self.email = email
        self.verified = verified
        self.role = role
        self.is_authenticated = True
        self.is_active = active
        self.must_change_password = must_change_password
        self.security_version = security_version
        self.session_id = session_id

    def __str__(self):
        role_display = self.role.replace("_", " ").title()
        return f"{role_display}: {self.email}"

    def get(self, key, default=None):
        return getattr(self, key, default)

    @property
    def user_id(self):
        """Alias for customer_id for clearer semantics"""
        return self.customer_id

    @property
    def pk(self):
        """
        Django/DRF compatibility primary key alias.
        Required by UserRateThrottle which reads request.user.pk.
        """
        return self.customer_id

    @property
    def id(self):
        """Django-style id alias for compatibility with generic code paths."""
        return self.customer_id

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_loan_officer(self):
        return self.role == "loan_officer"

    @property
    def is_customer(self):
        return self.role == "customer"


class CustomJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that checks for blacklisted access tokens.
    """

    TEMPORARY_PASSWORD_ALLOWED_URLS: ClassVar[set[str]] = {
        "change-password",
        "logout",
        "loan-officer-logout",
        "admin-logout",
        "active-sessions",
    }

    def authenticate(self, request):
        """
        Authenticate the request and check if token is blacklisted.
        """
        raw_token = None

        # 1) Standard Bearer token authentication.
        header = self.get_header(request)
        if header is not None:
            header_token = self.get_raw_token(header)
            if header_token is not None:
                raw_token = header_token.decode()

        # 2) Fallback to HttpOnly auth cookie for browser-based sessions.
        if raw_token is None:
            access_cookie_name = getattr(
                settings,
                "AUTH_ACCESS_COOKIE_NAME",
                "access_token",
            )
            raw_token = request.COOKIES.get(access_cookie_name)

        if raw_token is None:
            return None

        # Check if access token is blacklisted
        if TokenUtils.is_token_blacklisted(raw_token, token_type="access"):
            logger.warning("Attempt to use blacklisted access token")
            raise AuthenticationFailed("Token has been revoked")

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        if user.must_change_password:
            url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
            if url_name not in self.TEMPORARY_PASSWORD_ALLOWED_URLS:
                exc = PermissionDenied(
                    "You must change your password before accessing this resource. "
                    "Please use POST /change-password/.",
                    code="password_change_required",
                )
                exc.status_code = 423
                raise exc
        return user, validated_token

    @staticmethod
    def _get_live_user(customer_id, role):
        try:
            object_id = ObjectId(str(customer_id))
        except (InvalidId, TypeError, ValueError):
            return None
        if role == "customer":
            return Customer.find_one({"_id": object_id})
        if role == "loan_officer":
            return LoanOfficer.find_one({"_id": object_id})
        if role == "admin":
            return Admin.find_one({"_id": object_id})
        return None

    def get_user(self, validated_token):
        """
        Get user object from validated token claims.
        """
        try:
            customer_id = validated_token.get("customer_id")
            email = validated_token.get("email")
            verified = validated_token.get("verified")
            role = validated_token.get("role", "customer")
            session_id = validated_token.get("session_id")
            token_security_version = validated_token.get("security_version")

            if not customer_id:
                raise InvalidToken(
                    "Token contained no recognizable user identification"
                )

            # Tokens issued before session binding/security versioning are
            # intentionally invalidated; they cannot be revoked reliably.
            if not session_id or token_security_version is None:
                raise AuthenticationFailed("Session is no longer valid")

            live_user = self._get_live_user(customer_id, role)
            if live_user is None:
                raise AuthenticationFailed("Account is no longer available")

            active = bool(getattr(live_user, "active", True))
            deleted = getattr(live_user, "deleted_at", None) is not None
            live_verified = bool(getattr(live_user, "verified", True))
            account_state = getattr(live_user, "account_state", "active")
            live_security_version = int(getattr(live_user, "security_version", 1))
            if (
                not active
                or deleted
                or (role == "customer" and account_state != "active")
            ):
                raise AuthenticationFailed("Account is inactive")
            if not live_verified:
                raise AuthenticationFailed("Account is not verified")
            if int(token_security_version) != live_security_version:
                raise AuthenticationFailed("Session has been revoked")
            if not TokenUtils.is_session_active(
                customer_id, role, session_id, live_security_version
            ):
                raise AuthenticationFailed("Session is no longer active")

            return AuthenticatedUser(
                customer_id=customer_id,
                email=getattr(live_user, "email", email),
                verified=live_verified if verified is None else verified,
                role=role,
                active=active,
                must_change_password=bool(
                    getattr(live_user, "must_change_password", False)
                ),
                security_version=live_security_version,
                session_id=session_id,
            )
        except (KeyError, TypeError, ValueError):
            raise InvalidToken("Token contained no recognizable user identification")
