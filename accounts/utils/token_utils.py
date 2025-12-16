import secrets
from datetime import datetime, timedelta
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from accounts.models import BlacklistedToken
from accounts.models import RefreshTokenEntry
from rest_framework_simplejwt.tokens import RefreshToken as JWT_RefreshToken
import hashlib
import logging

logger = logging.getLogger('authentication')


class TokenUtils:
    """Utility class for token operations with single-device enforcement"""
    
    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_jwt_tokens(customer, token_type='no_remember_me'):
        """
        Generate JWT access and refresh tokens for a customer with dynamic lifetimes.
        Invalidates all existing refresh tokens for this customer (single-device enforcement).
        
        Args:
            customer: Customer object
            token_type: 'remember_me', 'no_remember_me', or 'signup'
        
        Returns:
            dict with access and refresh tokens
        """
        lifetimes = settings.TOKEN_LIFETIMES.get(token_type, settings.TOKEN_LIFETIMES['no_remember_me'])
        
        # Single-device enforcement: Invalidate all existing refresh tokens for this customer
        existing_tokens = RefreshTokenEntry.objects(customer=str(customer.id))
        invalidated_count = existing_tokens.count()
        if invalidated_count > 0:
            existing_tokens.delete()
            logger.info(f"Invalidated {invalidated_count} existing refresh token(s) for {customer.email}")
        
        # Create refresh token
        refresh = RefreshToken()
        refresh['customer_id'] = str(customer.id)
        refresh['email'] = customer.email
        refresh['verified'] = customer.verified
        refresh['role'] = customer.role
        
        refresh.set_exp(lifetime=lifetimes['refresh'])
        
        access = refresh.access_token
        access.set_exp(lifetime=lifetimes['access'])
        
        # Store new refresh token hash in DB
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
    def blacklist_token(token, token_type='refresh'):
        """
        Add a token to the blacklist.
        
        Args:
            token: The token string
            token_type: 'access' or 'refresh'
        """
        try:
            if token_type == 'refresh':
                parsed_token = JWT_RefreshToken(token)
            else:
                # For access tokens, we just store their hash
                from rest_framework_simplejwt.tokens import AccessToken
                parsed_token = AccessToken(token)
            
            expires_at = datetime.fromtimestamp(parsed_token['exp'])
            
            BlacklistedToken.objects.create(
                token=TokenUtils._hash_token(token),
                token_type=token_type,
                expires_at=expires_at
            )
            
            # Remove from refresh token history if it's a refresh token
            if token_type == 'refresh':
                RefreshTokenEntry.objects(token_hash=TokenUtils._hash_token(token)).delete()
            
            logger.info(f"Blacklisted {token_type} token")
            return True
        except Exception as e:
            logger.error(f"Failed to blacklist token: {str(e)}")
            return False
    
    @staticmethod
    def blacklist_tokens_on_logout(access_token, refresh_token):
        """
        Blacklist both access and refresh tokens on logout.
        
        Args:
            access_token: The access token string
            refresh_token: The refresh token string
        """
        try:
            if access_token:
                TokenUtils.blacklist_token(access_token, token_type='access')
            if refresh_token:
                TokenUtils.blacklist_token(refresh_token, token_type='refresh')
            return True
        except Exception as e:
            logger.error(f"Failed to blacklist tokens on logout: {str(e)}")
            return False
        
    @staticmethod
    def is_token_blacklisted(token, token_type='refresh'):
        """Check if a token is blacklisted."""
        token_hash = TokenUtils._hash_token(token)
        return BlacklistedToken.objects(token=token_hash, token_type=token_type).first() is not None
    
    @staticmethod
    def is_refresh_token_valid(customer_id, token):
        """
        Check if the refresh token is valid for this customer.
        Used for single-device token validation.
        """
        token_hash = TokenUtils._hash_token(token)
        entry = RefreshTokenEntry.objects(
            customer=customer_id,
            token_hash=token_hash
        ).first()
        return entry is not None
