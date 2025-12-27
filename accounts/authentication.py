from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from accounts.utils.token_utils import TokenUtils
import logging

logger = logging.getLogger('authentication')


class AuthenticatedUser:
    """
    User object representing an authenticated user.
    
    Supports three user types:
    - customer: MSME microentrepreneurs
    - loan_officer: Bank/microfinance staff
    - admin: System administrators
    """
    
    def __init__(self, customer_id, email, verified, role='customer'):
        self.customer_id = customer_id  # User ID (works for all user types)
        self.email = email
        self.verified = verified
        self.role = role
        self.is_authenticated = True
        self.is_active = True
    
    def __str__(self):
        role_display = self.role.replace('_', ' ').title()
        return f"{role_display}: {self.email}"
    
    def get(self, key, default=None):
        return getattr(self, key, default)
    
    @property
    def user_id(self):
        """Alias for customer_id for clearer semantics"""
        return self.customer_id
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    @property
    def is_loan_officer(self):
        return self.role == 'loan_officer'
    
    @property
    def is_customer(self):
        return self.role == 'customer'


class CustomJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that checks for blacklisted access tokens.
    """
    
    def authenticate(self, request):
        """
        Authenticate the request and check if token is blacklisted.
        """
        header = self.get_header(request)
        if header is None:
            return None
        
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None
        
        # Check if access token is blacklisted
        if TokenUtils.is_token_blacklisted(raw_token.decode(), token_type='access'):
            logger.warning(f"Attempt to use blacklisted access token")
            raise AuthenticationFailed('Token has been revoked')
        
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
    
    def get_user(self, validated_token):
        """
        Get user object from validated token claims.
        """
        try:
            customer_id = validated_token.get('customer_id')
            email = validated_token.get('email')
            verified = validated_token.get('verified')
            role = validated_token.get('role', 'customer')
            
            if not customer_id:
                raise InvalidToken('Token contained no recognizable user identification')
            
            return AuthenticatedUser(
                customer_id=customer_id,
                email=email,
                verified=verified,
                role=role
            )
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')

