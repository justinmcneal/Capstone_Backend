from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from accounts.authentication import AuthenticatedUser
import logging

logger = logging.getLogger("notifications")


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = None
        query_string = scope.get("query_string", b"").decode()
        if query_string:
            try:
                parsed = parse_qs(query_string)
                tokens = parsed.get("token", [])
                if tokens:
                    token = tokens[0]
            except Exception:
                pass

        if not token:
            headers = dict(scope.get("headers", []))
            subprotocols = headers.get(b"sec-websocket-protocol", b"").decode()
            if "access_token" in subprotocols:
                parts = subprotocols.split(",")
                for part in parts:
                    part = part.strip()
                    if part and "|" not in part:
                        token = part
                        break

        scope["user"] = await self.get_user_from_token(token)
        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def get_user_from_token(self, token):
        if not token:
            return AnonymousUser()

        try:
            from rest_framework_simplejwt.tokens import AccessToken
            access_token = AccessToken(token)
            customer_id = access_token.get("customer_id")
            email = access_token.get("email")
            verified = access_token.get("verified")
            role = access_token.get("role", "customer")

            if customer_id:
                return AuthenticatedUser(
                    customer_id=customer_id, email=email, verified=verified, role=role
                )
        except Exception as e:
            logger.warning(f"JWT authentication failed: {e}")

        return AnonymousUser()