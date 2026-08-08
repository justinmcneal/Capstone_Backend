from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import BlacklistedToken, RefreshTokenEntry
from accounts.utils.exception_types import NON_FATAL_EXCEPTIONS

if TYPE_CHECKING:
    from accounts.models import Customer

logger = logging.getLogger("authentication")


class TokenUtils:
    """Utility class for token issuance, validation, and session revocation."""

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_membership_query(
        customer_id: str, role: str = "customer", active_only: bool = False
    ) -> dict:
        query: dict[str, Any] = {"customer": str(customer_id)}
        and_filters: list[dict[str, Any]] = []

        # Backward compatible: older customer token records may not have a role field.
        if role == "customer":
            and_filters.append(
                {"$or": [{"role": "customer"}, {"role": {"$exists": False}}]}
            )
        else:
            and_filters.append({"role": role})

        # Backward compatible: older entries may not have is_active field.
        if active_only:
            and_filters.append(
                {"$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}
            )

        if and_filters:
            query["$and"] = and_filters

        return query

    @staticmethod
    def _store_refresh_token_entry(
        customer_id: str,
        refresh_token: str,
        role: str = "customer",
        expires_at: datetime | None = None,
        session_id: str | None = None,
        security_version: int = 1,
    ) -> None:
        if expires_at is None:
            parsed_refresh = RefreshToken(refresh_token)  # type: ignore[arg-type]
            expires_at = datetime.fromtimestamp(parsed_refresh["exp"], tz=timezone.utc)

        refresh_entry = RefreshTokenEntry(
            customer=str(customer_id),
            role=role,
            token_hash=TokenUtils._hash_token(refresh_token),
            session_id=session_id,
            security_version=security_version,
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            is_active=True,
            revoked_at=None,
        )
        refresh_entry.save()

        from accounts.models.activity import ActiveSession

        ActiveSession.from_refresh_token(
            user_id=str(customer_id),
            role=role,
            refresh_token=refresh_token,
        ).save()

    @staticmethod
    def _get_token_lifetimes(
        token_type: str = "no_remember_me",
    ) -> dict[str, timedelta]:
        lifetimes = getattr(settings, "TOKEN_LIFETIMES", {})
        default_lifetimes = lifetimes.get(
            "no_remember_me",
            {
                "access": timedelta(minutes=30),
                "refresh": timedelta(days=7),
            },
        )
        return lifetimes.get(token_type, default_lifetimes)

    @staticmethod
    def generate_jwt_tokens(
        customer: Customer, token_type: str = "no_remember_me"
    ) -> dict[str, str]:
        """
        Generate JWT access and refresh tokens for a customer with dynamic lifetimes.
        Invalidates all existing refresh tokens for this customer (single-device enforcement).

        Args:
            customer: Customer object
            token_type: 'remember_me', 'no_remember_me', or 'signup'

        Returns:
            dict with access and refresh tokens
        """
        lifetimes = TokenUtils._get_token_lifetimes(token_type)
        session_id = str(uuid.uuid4())
        security_version = int(getattr(customer, "security_version", 1))

        # Single-device enforcement: Invalidate all existing refresh tokens for this customer.
        customer_query = TokenUtils._token_membership_query(
            customer.id, role="customer", active_only=True
        )
        existing_tokens = RefreshTokenEntry.find(customer_query)
        invalidated_count = len(existing_tokens)
        if invalidated_count > 0:
            TokenUtils.revoke_all_sessions(customer.id, "customer")
            logger.info(
                f"Invalidated {invalidated_count} existing refresh token(s) for {customer.email}"
            )

        # Create refresh token
        refresh = RefreshToken()
        refresh["customer_id"] = str(customer.id)
        refresh["email"] = customer.email
        refresh["verified"] = customer.verified
        refresh["role"] = customer.role
        # Do not override SimpleJWT's reserved "token_type" claim ("refresh"/"access").
        # Store remember-me/signup semantics in a custom claim instead.
        refresh["session_type"] = token_type
        refresh["session_id"] = session_id
        refresh["security_version"] = security_version

        refresh.set_exp(lifetime=lifetimes["refresh"])

        access = refresh.access_token
        access["customer_id"] = str(customer.id)
        access["email"] = customer.email
        access["verified"] = customer.verified
        access["role"] = customer.role
        access["session_type"] = token_type
        access["session_id"] = session_id
        access["security_version"] = security_version
        access.set_exp(lifetime=lifetimes["access"])

        # Store new refresh token hash in DB
        TokenUtils._store_refresh_token_entry(
            customer_id=customer.id,
            refresh_token=str(refresh),
            role="customer",
            expires_at=datetime.fromtimestamp(refresh["exp"], tz=timezone.utc),
            session_id=session_id,
            security_version=security_version,
        )

        return {"access": str(access), "refresh": str(refresh)}

    @staticmethod
    def generate_tokens(
        user_id: str,
        email: str,
        verified: bool = True,
        role: str = "customer",
        token_type: str = "no_remember_me",
        security_version: int = 1,
        must_change_password: bool = False,
        token_transport: str = "body",
    ) -> dict[str, str]:
        """
        Generate JWT tokens for non-customer users (admin, loan officer).

        Each successful login creates an independent active session. Existing
        sessions remain valid until the user or a security-sensitive workflow
        explicitly revokes them.

        Args:
            user_id: User's ID
            email: User's email
            verified: Whether user is verified
            role: User role (admin, loan_officer)
            token_type: 'remember_me', 'no_remember_me', or 'signup'

        Returns:
            dict with access and refresh tokens
        """
        lifetimes = TokenUtils._get_token_lifetimes(token_type)
        session_id = str(uuid.uuid4())

        # Create refresh token
        refresh = RefreshToken()
        refresh["customer_id"] = str(user_id)  # Using same claim name for consistency
        refresh["email"] = email
        refresh["verified"] = verified
        refresh["role"] = role
        # Do not override SimpleJWT's reserved "token_type" claim ("refresh"/"access").
        # Store remember-me/signup semantics in a custom claim instead.
        refresh["session_type"] = token_type
        refresh["session_id"] = session_id
        refresh["security_version"] = int(security_version)
        refresh["must_change_password"] = bool(must_change_password)
        refresh["token_transport"] = token_transport

        # Set expiration from centralized lifetime config
        refresh.set_exp(lifetime=lifetimes["refresh"])

        access = refresh.access_token
        access["customer_id"] = str(user_id)
        access["email"] = email
        access["verified"] = verified
        access["role"] = role
        access["session_type"] = token_type
        access["session_id"] = session_id
        access["security_version"] = int(security_version)
        access["must_change_password"] = bool(must_change_password)
        access.set_exp(lifetime=lifetimes["access"])

        TokenUtils._store_refresh_token_entry(
            customer_id=user_id,
            refresh_token=str(refresh),
            role=role,
            expires_at=datetime.fromtimestamp(refresh["exp"], tz=timezone.utc),
            session_id=session_id,
            security_version=int(security_version),
        )

        return {"access": str(access), "refresh": str(refresh)}

    @staticmethod
    def generate_2fa_temp_token(
        user_id: str,
        email: str,
        role: str = "customer",
        token_type: str = "no_remember_me",
        security_version: int = 1,
        must_change_password: bool = False,
        token_transport: str = "body",
    ) -> str:
        """
        Generate a temporary token for 2FA verification.
        This token is short-lived and only valid for completing 2FA.

        Args:
            user_id: User's ID
            email: User's email
            role: User role

        Returns:
            str: Temporary JWT refresh token
        """
        # Create a short-lived refresh token for 2FA verification
        refresh = RefreshToken()
        refresh["customer_id"] = str(user_id)
        refresh["email"] = email
        refresh["role"] = role
        refresh["is_2fa_temp"] = True  # Flag to identify this as a temp 2FA token
        refresh["session_type"] = token_type
        refresh["security_version"] = int(security_version)
        refresh["must_change_password"] = bool(must_change_password)
        refresh["token_transport"] = token_transport

        # Very short expiration - just enough to complete 2FA
        refresh.set_exp(lifetime=timedelta(minutes=5))

        # Return the refresh token (not access token) so it can be parsed back
        return str(refresh)

    @staticmethod
    def blacklist_token(token: str, token_type: str = "refresh") -> bool:
        """
        Add a token to the blacklist.

        Args:
            token: The token string
            token_type: 'access' or 'refresh'
        """
        try:
            token_hash = TokenUtils._hash_token(token)

            # Repeated logout/termination calls are successful even after the
            # JWT expires, because the durable hash already proves revocation.
            if BlacklistedToken.find_one(
                {"token": token_hash, "token_type": token_type}
            ):
                if token_type == "refresh":
                    RefreshTokenEntry.update_many(
                        {"token_hash": token_hash},
                        {
                            "$set": {
                                "is_active": False,
                                "revoked_at": datetime.now(timezone.utc),
                            }
                        },
                    )
                return True

            if token_type == "refresh":
                parsed_token = RefreshToken(token)  # type: ignore[arg-type]
            else:
                # For access tokens, we just store their hash
                parsed_token = AccessToken(token)  # type: ignore[arg-type,assignment]

            expires_at = datetime.fromtimestamp(parsed_token["exp"], tz=timezone.utc)

            blacklisted_token = BlacklistedToken(
                token=token_hash, token_type=token_type, expires_at=expires_at
            )
            blacklisted_token.save()

            # Mark refresh token entries inactive/revoked.
            if token_type == "refresh":
                RefreshTokenEntry.update_many(
                    {"token_hash": token_hash},
                    {
                        "$set": {
                            "is_active": False,
                            "revoked_at": datetime.now(timezone.utc),
                        }
                    },
                )

            logger.info(f"Blacklisted {token_type} token")
            return True
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Failed to blacklist token: {e!s}")
            return False

    @staticmethod
    def blacklist_tokens_on_logout(
        access_token: str | None, refresh_token: str | None
    ) -> bool:
        """
        Blacklist both access and refresh tokens on logout.

        Args:
            access_token: The access token string
            refresh_token: The refresh token string
        """
        try:
            results = []
            if access_token:
                results.append(
                    TokenUtils.blacklist_token(access_token, token_type="access")
                )
            if refresh_token:
                results.append(
                    TokenUtils.blacklist_token(refresh_token, token_type="refresh")
                )
            return bool(results) and all(results)
        except NON_FATAL_EXCEPTIONS as e:
            logger.error(f"Failed to blacklist tokens on logout: {e!s}")
            return False

    @staticmethod
    def is_token_blacklisted(token: str, token_type: str = "refresh") -> bool:
        """Check if a token is blacklisted."""
        token_hash = TokenUtils._hash_token(token)
        return (
            BlacklistedToken.find_one({"token": token_hash, "token_type": token_type})
            is not None
        )

    @staticmethod
    def is_refresh_token_valid(
        customer_id: str, token: str, role: str = "customer"
    ) -> bool:
        """
        Check if the refresh token is valid for this customer.
        Used for active-session membership validation.
        """
        token_hash = TokenUtils._hash_token(token)
        query = TokenUtils._token_membership_query(
            customer_id, role=role, active_only=True
        )
        query["token_hash"] = token_hash
        entry = RefreshTokenEntry.find_one(query)

        if not entry:
            return False
        if getattr(entry, "revoked_at", None):
            return False
        if entry.expires_at:
            expires_at = entry.expires_at
            if (
                expires_at.tzinfo is None
                or expires_at.tzinfo.utcoffset(expires_at) is None
            ):
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                return False
        return not TokenUtils.is_token_blacklisted(token, token_type="refresh")

    @staticmethod
    def revoke_session(user_id: str, role: str, session_id: str) -> bool:
        """Idempotently revoke one session without retaining its credential."""
        now = datetime.now(timezone.utc)
        query = TokenUtils._token_membership_query(user_id, role=role)
        query["session_id"] = session_id
        RefreshTokenEntry.update_many(
            query, {"$set": {"is_active": False, "revoked_at": now}}
        )

        from accounts.models.activity import ActiveSession

        ActiveSession.update_many(
            {"user_id": str(user_id), "role": role, "session_id": session_id},
            {"$set": {"is_active": False}},
        )
        return True

    @staticmethod
    def revoke_all_sessions(
        user_id: str, role: str, except_session_id: str | None = None
    ) -> bool:
        """Idempotently revoke all membership, optionally preserving one session."""
        now = datetime.now(timezone.utc)
        token_query = TokenUtils._token_membership_query(user_id, role=role)
        session_query: dict[str, Any] = {"user_id": str(user_id), "role": role}
        if except_session_id:
            token_query["session_id"] = {"$ne": except_session_id}
            session_query["session_id"] = {"$ne": except_session_id}
        RefreshTokenEntry.update_many(
            token_query, {"$set": {"is_active": False, "revoked_at": now}}
        )

        from accounts.models.activity import ActiveSession

        ActiveSession.update_many(session_query, {"$set": {"is_active": False}})
        return True

    @staticmethod
    def is_session_active(
        user_id: str, role: str, session_id: str, security_version: int
    ) -> bool:
        query = TokenUtils._token_membership_query(user_id, role=role, active_only=True)
        query.update(
            {
                "session_id": session_id,
                "security_version": int(security_version),
            }
        )
        return RefreshTokenEntry.find_one(query) is not None
