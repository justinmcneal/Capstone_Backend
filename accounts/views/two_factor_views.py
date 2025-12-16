from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from accounts.services.two_factor_service import TwoFactorService
from accounts.services import AuthService
from accounts.utils.response_helpers import APIResponseHelper
from accounts.utils.throttles import TwoFactorRateThrottle
from accounts.utils.token_utils import TokenUtils
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
import logging

logger = logging.getLogger('authentication')


class Setup2FAView(APIView):
    """
    Initiate 2FA setup for authenticated customer.
    Returns secret and QR code provisioning URI.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            customer = AuthService.get_customer_by_id(request.user.customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            if customer.two_factor_enabled:
                return APIResponseHelper.error_response(
                    '2FA is already enabled for this account'
                )
            
            setup_data = TwoFactorService.setup_2fa(customer)
            
            logger.info(f"2FA setup initiated for {customer.email}")
            
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
        code = request.data.get('code')
        
        if not code:
            return APIResponseHelper.validation_error_response('Verification code is required')
        
        try:
            customer = AuthService.get_customer_by_id(request.user.customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            success, backup_codes = TwoFactorService.confirm_2fa_setup(customer, code)
            
            if not success:
                logger.warning(f"Invalid 2FA setup code for {customer.email}")
                return APIResponseHelper.error_response(
                    'Invalid verification code. Please try again.',
                    status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"2FA enabled for {customer.email}")
            
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
    """
    permission_classes = [AllowAny]
    throttle_classes = [TwoFactorRateThrottle]
    
    def post(self, request):
        temp_token = request.data.get('temp_token')
        code = request.data.get('code')
        use_backup = request.data.get('use_backup', False)
        
        if not temp_token or not code:
            return APIResponseHelper.validation_error_response(
                'Temporary token and verification code are required'
            )
        
        try:
            # Decode temp token to get customer ID
            token = RefreshToken(temp_token)
            customer_id = token.get('customer_id')
            
            if not customer_id:
                return APIResponseHelper.error_response(
                    'Invalid temporary token',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            customer = AuthService.get_customer_by_id(customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            # Verify 2FA code
            if use_backup:
                is_valid = TwoFactorService.use_backup_code(customer, code)
            else:
                is_valid = TwoFactorService.verify_totp(customer.two_factor_secret, code)
            
            if not is_valid:
                logger.warning(f"Invalid 2FA code for {customer.email}")
                return APIResponseHelper.error_response(
                    'Invalid verification code',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            # Generate full tokens after successful 2FA
            tokens = AuthService.create_customer_tokens(customer, token_type='no_remember_me')
            
            logger.info(f"2FA verified for {customer.email}")
            
            return APIResponseHelper.success_response(
                data={
                    'user': AuthService.serialize_customer_data(customer, include_last_name=True),
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
    Disable 2FA for authenticated customer.
    Requires password verification.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        password = request.data.get('password')
        
        if not password:
            return APIResponseHelper.validation_error_response('Password is required')
        
        try:
            customer = AuthService.get_customer_by_id(request.user.customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            if not customer.two_factor_enabled:
                return APIResponseHelper.error_response('2FA is not enabled')
            
            success = TwoFactorService.disable_2fa(customer, password)
            
            if not success:
                return APIResponseHelper.error_response(
                    'Invalid password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            logger.info(f"2FA disabled for {customer.email}")
            
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
        
        if not password:
            return APIResponseHelper.validation_error_response('Password is required')
        
        try:
            customer = AuthService.get_customer_by_id(request.user.customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            if not customer.two_factor_enabled:
                return APIResponseHelper.error_response('2FA is not enabled')
            
            backup_codes = TwoFactorService.regenerate_backup_codes(customer, password)
            
            if backup_codes is None:
                return APIResponseHelper.error_response(
                    'Invalid password',
                    status.HTTP_401_UNAUTHORIZED
                )
            
            logger.info(f"Backup codes regenerated for {customer.email}")
            
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
    Get 2FA status for authenticated customer.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            customer = AuthService.get_customer_by_id(request.user.customer_id)
            if not customer:
                return APIResponseHelper.error_response('Customer not found')
            
            return APIResponseHelper.success_response(
                data={
                    'two_factor_enabled': customer.two_factor_enabled,
                    'backup_codes_remaining': len(customer.backup_codes) if customer.backup_codes else 0
                }
            )
            
        except Exception as e:
            logger.error(f"2FA status error: {str(e)}")
            return APIResponseHelper.server_error_response('Failed to get 2FA status')
