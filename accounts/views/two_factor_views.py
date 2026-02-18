"""
Two-Factor Authentication (2FA) Views.

Unified views that support both Customer and LoanOfficer authentication.
"""
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from accounts.services.two_factor_service import TwoFactorService
from accounts.services import AuthService
from accounts.models import LoanOfficer, Admin
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.throttles import TwoFactorRateThrottle
from accounts.utils.token_utils import TokenUtils
from accounts.utils.user_detection import get_authenticated_user
from accounts.utils.validation_utils import parse_bool
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from bson import ObjectId
import logging

logger = logging.getLogger('authentication')


class Setup2FAView(APIView):
    """
    Initiate 2FA setup for authenticated user (Customer or LoanOfficer).
    Returns secret and QR code provisioning URI.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            user, user_type = get_authenticated_user(request)
            if not user:
                return APIResponseHelper.error_response('User not found')
            
            if user.two_factor_enabled:
                return APIResponseHelper.error_response(
                    '2FA is already enabled for this account'
                )
            
            setup_data = TwoFactorService.setup_2fa(user)
            
            logger.info(f"2FA setup initiated for {user.email} ({user_type})")
            
            return APIResponseHelper.success_response(
                data={
                    'provisioning_uri': setup_data['provisioning_uri'],
                    'manual_entry_key': setup_data['manual_entry_key'],
                    'message': 'Scan the QR code with your authenticator app, then verify with a code'
                },
                message='2FA setup initiated'
            )
            
        except Exception as e:
            logger.error(f"2FA setup error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to setup 2FA')


class Confirm2FASetupView(APIView):
    """
    Confirm 2FA setup by verifying the first TOTP code.
    Returns backup codes on success.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [TwoFactorRateThrottle]
    
    def post(self, request):
        code = str(request.data.get('code') or '').strip()
        
        if not code:
            return APIResponseHelper.validation_error_response('Verification code is required')
        if not code.isdigit() or len(code) != 6:
            return APIResponseHelper.validation_error_response(
                {'code': 'Verification code must be exactly 6 digits'}
            )
        
        try:
            user, user_type = get_authenticated_user(request)
            if not user:
                return APIResponseHelper.error_response('User not found')
            
            success, backup_codes = TwoFactorService.confirm_2fa_setup(user, code)
            
            if not success:
                logger.warning(f"Invalid 2FA setup code for {user.email} ({user_type})")
                return APIResponseHelper.error_response(
                    'Invalid verification code. Please try again.',
                    status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"2FA enabled for {user.email} ({user_type})")
            
            return APIResponseHelper.success_response(
                data={
                    'backup_codes': backup_codes,
                    'message': 'Save these backup codes securely. They can only be used once.'
                },
                message='2FA enabled successfully'
            )
            
        except Exception as e:
            logger.error(f"2FA confirmation error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to confirm 2FA setup')


class Verify2FAView(APIView):
    """
    Verify 2FA code during login flow.
    Called after password verification when 2FA is enabled.
    Supports both Customer and LoanOfficer.
    """
    permission_classes = [AllowAny]
    throttle_classes = [TwoFactorRateThrottle]
    
    def post(self, request):
        temp_token = str(request.data.get('temp_token') or '').strip()
        code = str(request.data.get('code') or '').strip()
        use_backup_raw = request.data.get('use_backup', False)
        use_backup_valid, use_backup, use_backup_error = parse_bool(use_backup_raw, 'use_backup')
        if not use_backup_valid:
            return APIResponseHelper.validation_error_response({'use_backup': use_backup_error})
        
        if not temp_token or not code:
            return APIResponseHelper.validation_error_response(
                'Temporary token and verification code are required'
            )
        if use_backup:
            if len(code) > 64:
                return APIResponseHelper.validation_error_response(
                    {'code': 'Backup code must be at most 64 characters'}
                )
        elif not code.isdigit() or len(code) != 6:
            return APIResponseHelper.validation_error_response(
                {'code': 'Verification code must be exactly 6 digits'}
            )
        
        try:
            # Decode temp token to get user ID and role
            token = RefreshToken(temp_token)
            user_id = token.get('customer_id')  # All users store ID in customer_id
            role = token.get('role', 'customer')
            
            if not user_id:
                return APIResponseHelper.error_response(
                    'Invalid temporary token',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            user = None
            user_type = None
            
            if role == 'loan_officer':
                user = LoanOfficer.find_one({'_id': ObjectId(user_id)})
                user_type = 'loan_officer'
            elif role == 'admin':
                user = Admin.find_one({'_id': ObjectId(user_id)})
                user_type = 'admin'
            else:
                user = AuthService.get_customer_by_id(user_id)
                user_type = 'customer'
            
            if not user:
                return APIResponseHelper.error_response(
                    'Invalid temporary token',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            # Verify 2FA code
            if use_backup:
                is_valid = TwoFactorService.use_backup_code(user, code)
            else:
                is_valid = TwoFactorService.verify_totp(user.two_factor_secret, code)
            
            if not is_valid:
                logger.warning(f"Invalid 2FA code for {user.email} ({user_type})")
                return APIResponseHelper.error_response(
                    'Invalid verification code',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            # Generate full tokens after successful 2FA
            if user_type == 'customer':
                tokens = AuthService.create_customer_tokens(user, token_type='no_remember_me')
                user_data = AuthService.serialize_customer_data(user, include_last_name=True)
            elif user_type == 'admin':
                # Admin tokens
                tokens = TokenUtils.generate_tokens(
                    user_id=user.id,
                    email=user.email,
                    verified=True,
                    role='admin',
                    refresh_token_days=1
                )
                user_data = {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'full_name': user.full_name,
                    'role': 'admin',
                    'permissions': user.permissions if not user.super_admin else ['*'],
                    'super_admin': user.super_admin
                }
            else:
                # Loan Officer tokens
                tokens = TokenUtils.generate_tokens(
                    user_id=user.id,
                    email=user.email,
                    verified=user.verified,
                    role='loan_officer',
                    refresh_token_days=1
                )
                user_data = {
                    'id': user.id,
                    'email': user.email,
                    'full_name': user.full_name,
                    'department': user.department,
                    'employee_id': user.employee_id,
                    'role': 'loan_officer'
                }
            
            logger.info(f"2FA verified for {user.email} ({user_type})")
            
            return APIResponseHelper.success_response(
                data={
                    'user': user_data,
                    'access': tokens['access'],
                    'refresh': tokens['refresh']
                },
                message='2FA verification successful'
            )
            
        except TokenError:
            return APIResponseHelper.error_response(
                'Invalid or expired temporary token',
                status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            logger.error(f"2FA verification error: {str(e)}")
            return APIResponseHelper.server_error_response('2FA verification failed')


class Disable2FAView(APIView):
    """
    Disable 2FA for authenticated user.
    Requires password verification.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        password = request.data.get('password')
        if password is None:
            password = ''
        if not isinstance(password, str):
            return APIResponseHelper.validation_error_response(
                {'password': 'Password must be a string'}
            )
        
        if not password:
            return APIResponseHelper.validation_error_response('Password is required')
        
        try:
            user, user_type = get_authenticated_user(request)
            if not user:
                return APIResponseHelper.error_response('User not found')
            
            if not user.two_factor_enabled:
                return APIResponseHelper.error_response('2FA is not enabled')
            
            success = TwoFactorService.disable_2fa(user, password)
            
            if not success:
                return APIResponseHelper.error_response(
                    'Invalid password',
                    status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"2FA disabled for {user.email} ({user_type})")
            
            return APIResponseHelper.success_response(
                message='2FA disabled successfully'
            )
            
        except Exception as e:
            logger.error(f"2FA disable error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to disable 2FA')


class RegenerateBackupCodesView(APIView):
    """
    Regenerate 2FA backup codes.
    Requires password verification.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        password = request.data.get('password')
        if password is None:
            password = ''
        if not isinstance(password, str):
            return APIResponseHelper.validation_error_response(
                {'password': 'Password must be a string'}
            )
        
        if not password:
            return APIResponseHelper.validation_error_response('Password is required')
        
        try:
            user, user_type = get_authenticated_user(request)
            if not user:
                return APIResponseHelper.error_response('User not found')
            
            if not user.two_factor_enabled:
                return APIResponseHelper.error_response('2FA is not enabled')
            
            backup_codes = TwoFactorService.regenerate_backup_codes(user, password)
            
            if backup_codes is None:
                return APIResponseHelper.error_response(
                    'Invalid password',
                    status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"Backup codes regenerated for {user.email} ({user_type})")
            
            return APIResponseHelper.success_response(
                data={
                    'backup_codes': backup_codes,
                    'message': 'Previous backup codes are now invalid. Save these new codes securely.'
                },
                message='Backup codes regenerated successfully'
            )
            
        except Exception as e:
            logger.error(f"Backup code regeneration error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to regenerate backup codes')


class Get2FAStatusView(APIView):
    """
    Get 2FA status for authenticated user.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            user, user_type = get_authenticated_user(request)
            if not user:
                return APIResponseHelper.error_response('User not found')
            
            return APIResponseHelper.success_response(
                data={
                    'two_factor_enabled': user.two_factor_enabled,
                    'backup_codes_remaining': len(user.backup_codes) if user.backup_codes else 0
                }
            )
            
        except Exception as e:
            logger.error(f"2FA status error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to get 2FA status')
