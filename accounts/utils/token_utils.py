import secrets
from datetime import datetime, timedelta
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from accounts.models import BlacklistedToken
from accounts.models import RefreshTokenEntry
from rest_framework_simplejwt.tokens import RefreshToken as JWT_RefreshToken
import hashlib


class TokenUtils:
    """Utility class for token operations"""
    
    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_jwt_tokens(customer, token_type='no_remember_me'):
        """
        Generate JWT access and refresh tokens for a customer with dynamic lifetimes
        
        Args:
            customer: Customer object
            token_type: 'remember_me', 'no_remember_me', or 'signup'
        
        Returns:
            dict with access and refresh tokens
        """
        lifetimes = settings.TOKEN_LIFETIMES.get(token_type, settings.TOKEN_LIFETIMES['no_remember_me'])
        
        # Create refresh token
        refresh = RefreshToken()
        refresh['customer_id'] = str(customer.id)
        refresh['email'] = customer.email
        refresh['verified'] = customer.verified
        
        refresh.set_exp(lifetime=lifetimes['refresh'])
        
        access = refresh.access_token
        access.set_exp(lifetime=lifetimes['access'])
        
        # Store refresh token hash in DB
        RefreshTokenEntry.objects.create(
            customer=str(customer.id),
            token_hash=TokenUtils._hash_token(str(refresh)),
            issued_at=datetime.utcnow(),
            expires_at=datetime.fromtimestamp(refresh['exp'])
        )
        
        return {
            'access': str(access),
            'refresh': str(refresh)
        }
    
    @staticmethod
    def blacklist_token(refresh_token):
        """Add refresh token to blacklist"""
        try:
            token = JWT_RefreshToken(refresh_token)
            expires_at = datetime.fromtimestamp(token['exp'])
            
            BlacklistedToken.objects.create(
                token=refresh_token,
                expires_at=expires_at
            )
            # Remove from refresh token history
            RefreshTokenEntry.objects(token_hash=TokenUtils._hash_token(refresh_token)).delete()
            return True
        except Exception as e:
            return False
        
    @staticmethod
    def is_token_blacklisted(refresh_token):
        return BlacklistedToken.objects(token=refresh_token).first() is not None
