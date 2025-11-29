from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class AuthenticatedUser:
    def __init__(self, customer_id, email, verified):
        self.customer_id = customer_id
        self.email = email
        self.verified = verified
        self.is_authenticated = True
        self.is_active = True
    
    def __str__(self):
        return f"Customer: {self.email}"
    
    def get(self, key, default=None):
        return getattr(self, key, default)


class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        try:
            customer_id = validated_token.get('customer_id')
            email = validated_token.get('email')
            verified = validated_token.get('verified')
            
            if not customer_id:
                raise InvalidToken('Token contained no recognizable user identification')
            
            # Return a user-like object that works with DRF permissions
            return AuthenticatedUser(
                customer_id=customer_id,
                email=email,
                verified=verified
            )
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')
