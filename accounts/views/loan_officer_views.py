from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from datetime import datetime, timedelta
from bson import ObjectId

from accounts.models import LoanOfficer
from accounts.utils.token_utils import TokenUtils
from accounts.utils.response_helpers import success_response, error_response
from accounts.utils.auth_cookies import (
    clear_auth_cookies,
    get_access_token_from_request,
    get_refresh_token_from_request,
    set_auth_cookies,
)
from accounts.services import LockoutService
from accounts.utils.email_utils import EmailUtils
from accounts.utils.validation_utils import parse_bool
from analytics.models import AuditLog
import logging

logger = logging.getLogger('loan_officer_auth')


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
    
    def post(self, request):
        try:
            email = EmailUtils.normalize_email(str(request.data.get('email') or ''))
            password = request.data.get('password', '')
            client_ip = request.META.get('REMOTE_ADDR', '')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            if not isinstance(password, str):
                return error_response(
                    message="password must be a string",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            remember_me_raw = request.data.get('remember_me', False)
            remember_valid, remember_me, remember_error = parse_bool(remember_me_raw, 'remember_me')
            if not remember_valid:
                return error_response(
                    message="Invalid remember_me value",
                    errors={'remember_me': remember_error},
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            if not email or not password:
                return error_response(
                    message="Email and password are required",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Find loan officer
            officer = LoanOfficer.find_one({'email': email})
            
            if not officer:
                AuditLog.log_action(
                    action='user_login_failed',
                    user_type='loan_officer',
                    user_email=email,
                    description='Loan officer login failed',
                    ip_address=client_ip,
                    details={
                        'reason': 'account_not_found',
                        'user_agent': user_agent,
                    }
                )
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if account is active
            if not officer.active:
                AuditLog.log_action(
                    action='user_login_failed',
                    user_id=officer.id,
                    user_type='loan_officer',
                    user_email=officer.email,
                    description='Loan officer login failed',
                    ip_address=client_ip,
                    details={
                        'reason': 'account_inactive',
                        'user_agent': user_agent,
                    }
                )
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check lockout
            if officer.locked_until and officer.locked_until > datetime.utcnow():
                remaining = (officer.locked_until - datetime.utcnow()).seconds // 60
                AuditLog.log_action(
                    action='user_login_failed',
                    user_id=officer.id,
                    user_type='loan_officer',
                    user_email=officer.email,
                    description='Loan officer login failed',
                    ip_address=client_ip,
                    details={
                        'reason': 'account_locked',
                        'minutes_remaining': remaining,
                        'user_agent': user_agent,
                    }
                )
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Verify password
            if not officer.check_password(password):
                # Increment failed attempts
                officer.failed_login_attempts += 1
                
                if officer.failed_login_attempts >= 5:
                    officer.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    officer.save()
                    AuditLog.log_action(
                        action='user_login_failed',
                        user_id=officer.id,
                        user_type='loan_officer',
                        user_email=officer.email,
                        description='Loan officer login failed',
                        ip_address=client_ip,
                        details={
                            'reason': 'password_mismatch',
                            'failed_attempts': officer.failed_login_attempts,
                            'account_locked_after_attempt': True,
                            'user_agent': user_agent,
                        }
                    )
                    return error_response(
                        message="Invalid credentials",
                        status_code=status.HTTP_401_UNAUTHORIZED
                    )
                
                officer.save()
                AuditLog.log_action(
                    action='user_login_failed',
                    user_id=officer.id,
                    user_type='loan_officer',
                    user_email=officer.email,
                    description='Loan officer login failed',
                    ip_address=client_ip,
                    details={
                        'reason': 'password_mismatch',
                        'failed_attempts': officer.failed_login_attempts,
                        'account_locked_after_attempt': False,
                        'user_agent': user_agent,
                    }
                )
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Reset failed attempts on successful login
            officer.failed_login_attempts = 0
            officer.locked_until = None
            officer.last_login_attempt = datetime.utcnow()
            officer.save()
            
            # Check if 2FA is enabled
            if officer.two_factor_enabled:
                # Generate temporary token for 2FA verification
                temp_token = TokenUtils.generate_2fa_temp_token(
                    user_id=officer.id,
                    email=officer.email,
                    role='loan_officer'
                )
                return success_response(
                    data={
                        'requires_2fa': True,
                        'temp_token': temp_token,
                        'must_change_password': officer.must_change_password
                    },
                    message="2FA verification required"
                )
            
            # Generate tokens
            refresh_days = 3 if remember_me else 1
            tokens = TokenUtils.generate_tokens(
                user_id=officer.id,
                email=officer.email,
                verified=officer.verified,
                role='loan_officer',
                refresh_token_days=refresh_days
            )
            
            # Audit log for loan officer login
            AuditLog.log_action(
                action='user_login',
                user_id=officer.id,
                user_type='loan_officer',
                user_email=officer.email,
                description=f'Loan officer {officer.full_name} logged in',
                ip_address=client_ip,
                details={
                    'user_agent': user_agent,
                }
            )
            
            response = success_response(
                data={
                    'access_token': tokens['access'],
                    'refresh_token': tokens['refresh'],
                    'user': {
                        'id': officer.id,
                        'email': officer.email,
                        'full_name': officer.full_name,
                        'department': officer.department,
                        'employee_id': officer.employee_id,
                        'role': 'loan_officer'
                    },
                    'must_change_password': officer.must_change_password
                },
                message="Login successful"
            )
            set_auth_cookies(response, tokens['access'], tokens['refresh'])
            return response
            
        except Exception as e:
            logger.error(f"Loan officer login error: {str(e)}")
            return error_response(
                message="An error occurred during login",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
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
    
    def post(self, request):
        try:
            refresh_token = get_refresh_token_from_request(request)
            access_token = get_access_token_from_request(request)
            
            if refresh_token:
                TokenUtils.blacklist_token(refresh_token, token_type='refresh')
            
            if access_token:
                TokenUtils.blacklist_token(access_token, token_type='access')
            
            # Audit log for loan officer logout
            AuditLog.log_action(
                action='user_logout',
                user_type='loan_officer',
                description='Loan officer logged out',
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            response = success_response(message="Logged out successfully")
            clear_auth_cookies(response)
            return response
            
        except Exception as e:
            logger.error(f"Loan officer logout error: {str(e)}")
            response = success_response(message="Logged out successfully")
            clear_auth_cookies(response)
            return response
