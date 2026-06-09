from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from datetime import datetime, timedelta, timezone

from accounts.models import LoanOfficer
from accounts.utils.token_utils import TokenUtils
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.auth_cookies import (
    clear_auth_cookies,
    get_access_token_from_request,
    get_refresh_token_from_request,
    set_auth_cookies,
)
from accounts.utils.email_utils import EmailUtils
from accounts.utils.throttles import LoanOfficerLoginRateThrottle
from accounts.utils.validation_utils import parse_bool
from analytics.models import AuditLog
import logging

logger = logging.getLogger("loan_officer_auth")
GENERIC_LOGIN_ERROR_MESSAGE = "Invalid email/username or password."


def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _log_loan_officer_login_failure(request, email, reason, officer=None):
    ip_address = _get_client_ip(request)
    logger.warning(
        "login_failed role=loan_officer reason=%s email=%s ip=%s",
        reason,
        email,
        ip_address,
    )
    try:
        AuditLog.log_action(
            action="user_login_failed",
            user_id=getattr(officer, "id", None),
            user_type="loan_officer",
            user_email=getattr(officer, "email", "") if officer else email,
            description="Loan officer login failed",
            details={
                "reason": reason,
                "email": email,
            },
            ip_address=ip_address,
        )
    except Exception as log_error:
        logger.error(
            "failed_to_write_audit action=user_login_failed role=loan_officer email=%s error=%s",
            email,
            str(log_error),
        )


class LoanOfficerLoginView(APIView):
    """
    Login endpoint for loan officers.

    POST /api/auth/loan-officer/login/
    {
        "email": "officer@example.com",
        "password": "password123",
        "remember_me": true
    }
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoanOfficerLoginRateThrottle]

    def post(self, request):
        try:
            email = EmailUtils.normalize_email(str(request.data.get("email") or ""))
            password = request.data.get("password", "")
            if not isinstance(password, str):
                return error_response(
                    message="password must be a string",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            remember_me_raw = request.data.get("remember_me", False)
            remember_valid, remember_me, remember_error = parse_bool(
                remember_me_raw, "remember_me"
            )
            if not remember_valid:
                return error_response(
                    message="Invalid remember_me value",
                    errors={"remember_me": remember_error},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if not email or not password:
                return error_response(
                    message="Email and password are required",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Find loan officer
            officer = LoanOfficer.find_one({"email": email})

            if not officer:
                _log_loan_officer_login_failure(request, email, "user_not_found")
                return error_response(
                    message=GENERIC_LOGIN_ERROR_MESSAGE,
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Check if account is active
            if not officer.active:
                _log_loan_officer_login_failure(
                    request,
                    email,
                    "account_deactivated",
                    officer=officer,
                )
                return error_response(
                    message=GENERIC_LOGIN_ERROR_MESSAGE,
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Check lockout
            if officer.locked_until and officer.locked_until > datetime.now(
                timezone.utc
            ):
                remaining = (
                    officer.locked_until - datetime.now(timezone.utc)
                ).seconds // 60
                _log_loan_officer_login_failure(
                    request,
                    email,
                    f"account_locked_{remaining}m_remaining",
                    officer=officer,
                )
                return error_response(
                    message=GENERIC_LOGIN_ERROR_MESSAGE,
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Verify password
            if not officer.check_password(password):
                # Increment failed attempts
                officer.failed_login_attempts += 1

                if officer.failed_login_attempts >= 5:
                    officer.locked_until = datetime.now(timezone.utc) + timedelta(
                        minutes=15
                    )
                    officer.save()
                    _log_loan_officer_login_failure(
                        request,
                        email,
                        "password_incorrect_account_locked",
                        officer=officer,
                    )
                    return error_response(
                        message=GENERIC_LOGIN_ERROR_MESSAGE,
                        status_code=status.HTTP_401_UNAUTHORIZED,
                    )

                officer.save()
                _log_loan_officer_login_failure(
                    request,
                    email,
                    f"password_incorrect_{5 - officer.failed_login_attempts}_attempts_remaining",
                    officer=officer,
                )
                return error_response(
                    message=GENERIC_LOGIN_ERROR_MESSAGE,
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )

            # Reset failed attempts on successful login
            officer.failed_login_attempts = 0
            officer.locked_until = None
            officer.last_login_attempt = datetime.now(timezone.utc)
            officer.save()

            # Check if 2FA is enabled
            if officer.two_factor_enabled:
                # Generate temporary token for 2FA verification
                temp_token = TokenUtils.generate_2fa_temp_token(
                    user_id=officer.id, email=officer.email, role="loan_officer"
                )
                return success_response(
                    data={
                        "requires_2fa": True,
                        "temp_token": temp_token,
                        "must_change_password": officer.must_change_password,
                    },
                    message="2FA verification required",
                )

            # Generate tokens
            token_type = "remember_me" if remember_me else "no_remember_me"
            tokens = TokenUtils.generate_tokens(
                user_id=officer.id,
                email=officer.email,
                verified=officer.verified,
                role="loan_officer",
                token_type=token_type,
            )

            # Audit log for loan officer login
            AuditLog.log_action(
                action="user_login",
                user_id=officer.id,
                user_type="loan_officer",
                user_email=officer.email,
                description=f"Loan officer {officer.full_name} logged in",
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            response = success_response(
                data={
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                    "user": {
                        "id": officer.id,
                        "email": officer.email,
                        "first_name": officer.first_name,
                        "last_name": officer.last_name,
                        "full_name": officer.full_name,
                        "phone": officer.phone,
                        "department": officer.department,
                        "employee_id": officer.employee_id,
                        "role": "loan_officer",
                        "last_login_attempt": officer.last_login_attempt.isoformat() if officer.last_login_attempt else None,
                    },
                    "must_change_password": officer.must_change_password,
                },
                message="Login successful",
            )
            set_auth_cookies(response, tokens["access"], tokens["refresh"])
            return response

        except Exception as e:
            logger.error(f"Loan officer login error: {str(e)}")
            return error_response(
                message="An error occurred during login",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LoanOfficerLogoutView(APIView):
    """
    Logout endpoint for loan officers.

    POST /api/auth/loan-officer/logout/
    {
        "refresh_token": "..."
    }
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        try:
            refresh_token = get_refresh_token_from_request(request)
            access_token = get_access_token_from_request(request)

            # Extract user info from token before blacklisting
            user_id = None
            user_email = ""
            try:
                import jwt as pyjwt

                token_to_decode = access_token or refresh_token
                if token_to_decode:
                    payload = pyjwt.decode(
                        token_to_decode,
                        options={"verify_signature": False, "verify_exp": False},
                    )
                    user_id = payload.get("customer_id")
                    user_email = payload.get("email", "")
            except Exception:
                logger.warning(
                    "Could not decode token for audit log user info during logout"
                )

            if refresh_token:
                TokenUtils.blacklist_token(refresh_token, token_type="refresh")

            if access_token:
                TokenUtils.blacklist_token(access_token, token_type="access")

            # Audit log for loan officer logout
            AuditLog.log_action(
                action="user_logout",
                user_id=user_id,
                user_type="loan_officer",
                user_email=user_email,
                description="Loan officer logged out",
                ip_address=request.META.get("REMOTE_ADDR", ""),
            )

            response = success_response(message="Logged out successfully")
            clear_auth_cookies(response)
            return response

        except Exception as e:
            logger.error(f"Loan officer logout error: {str(e)}")
            response = success_response(message="Logged out successfully")
            clear_auth_cookies(response)
            return response


class LoanOfficerProfileView(APIView):
    """
    Get or update the authenticated Loan Officer's profile.
    
    GET /api/auth/loan-officer/me/
    PUT /api/auth/loan-officer/me/
    """
    from rest_framework.permissions import IsAuthenticated
    from accounts.authentication import CustomJWTAuthentication
    
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from accounts.utils.user_detection import get_authenticated_user
        try:
            user, user_type = get_authenticated_user(request)
            if not user or user_type != "loan_officer":
                return error_response(message="Unauthorized", status_code=status.HTTP_401_UNAUTHORIZED)
            
            return success_response(data={
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "full_name": user.full_name,
                "phone": user.phone,
                "department": user.department,
                "employee_id": user.employee_id,
                "role": "loan_officer",
                "last_login_attempt": user.last_login_attempt.isoformat() if user.last_login_attempt else None,
            })
        except Exception as e:
            logger.error(f"Get Loan Officer Profile error: {str(e)}")
            return error_response(message="Failed to retrieve profile", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request):
        from accounts.utils.user_detection import get_authenticated_user
        from accounts.utils.validation_utils import validate_person_name, validate_phone_number
        from accounts.utils.validation_utils import sanitize_text
        
        try:
            user, user_type = get_authenticated_user(request)
            if not user or user_type != "loan_officer":
                return error_response(message="Unauthorized", status_code=status.HTTP_401_UNAUTHORIZED)
                
            data = request.data
            changes = False
            
            if "first_name" in data:
                is_valid, error_msg, normalized_name = validate_person_name(data["first_name"], "First name", 50)
                if not is_valid:
                    return error_response(message=error_msg, errors={"first_name": error_msg}, status_code=status.HTTP_400_BAD_REQUEST)
                user.first_name = normalized_name
                changes = True
                
            if "last_name" in data:
                is_valid, error_msg, normalized_name = validate_person_name(data["last_name"], "Last name", 50)
                if not is_valid:
                    return error_response(message=error_msg, errors={"last_name": error_msg}, status_code=status.HTTP_400_BAD_REQUEST)
                user.last_name = normalized_name
                changes = True
                
            if "phone" in data:
                phone_raw = data["phone"]
                if phone_raw is not None and not isinstance(phone_raw, str):
                    return error_response(message="phone must be a string", errors={"phone": "phone must be a string"}, status_code=status.HTTP_400_BAD_REQUEST)
                is_valid, phone_error, normalized_phone = validate_phone_number(phone_raw, field_name="Phone", required=False, min_digits=11, max_digits=11)
                if not is_valid:
                    return error_response(message=phone_error, errors={"phone": phone_error}, status_code=status.HTTP_400_BAD_REQUEST)
                user.phone = normalized_phone
                changes = True

            if changes:
                user.save()
                AuditLog.log_action(
                    action="profile_updated",
                    user_id=user.id,
                    user_type="loan_officer",
                    user_email=user.email,
                    description=f"Loan officer {user.email} updated their profile",
                    ip_address=request.META.get("REMOTE_ADDR", ""),
                )
                
            return success_response(data={
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "full_name": user.full_name,
                "phone": user.phone,
                "department": user.department,
                "employee_id": user.employee_id,
                "role": "loan_officer",
                "last_login_attempt": user.last_login_attempt.isoformat() if user.last_login_attempt else None,
            }, message="Profile updated successfully")
            
        except Exception as e:
            logger.error(f"Update Loan Officer Profile error: {str(e)}")
            return error_response(message="Failed to update profile", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

