from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from datetime import datetime, timedelta
from bson import ObjectId

from accounts.models import LoanOfficer
from accounts.utils.token_utils import TokenUtils
from accounts.utils.response_helpers import success_response, error_response
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
                return error_response(
                    message="Invalid credentials",
                    status_code=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if account is active
            if not officer.active:
                return error_response(
                    message="Account has been deactivated. Contact your administrator.",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Check lockout
            if officer.locked_until and officer.locked_until > datetime.utcnow():
                remaining = (officer.locked_until - datetime.utcnow()).seconds // 60
                return error_response(
                    message=f"Account is locked. Try again in {remaining} minutes.",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            
            # Verify password
            if not officer.check_password(password):
                # Increment failed attempts
                officer.failed_login_attempts += 1
                
                if officer.failed_login_attempts >= 5:
                    officer.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    officer.save()
                    return error_response(
                        message="Account locked due to too many failed attempts. Try again in 15 minutes.",
                        status_code=status.HTTP_403_FORBIDDEN
                    )
                
                officer.save()
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
                ip_address=request.META.get('REMOTE_ADDR', '')
            )
            
            return success_response(
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
            refresh_token = str(request.data.get('refresh_token') or '').strip()
            access_token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '').strip()
            
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
            
            return success_response(message="Logged out successfully")
            
        except Exception as e:
            logger.error(f"Loan officer logout error: {str(e)}")
            return success_response(message="Logged out successfully")
