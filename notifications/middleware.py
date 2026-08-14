import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import parse_cookie
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.exceptions import TokenError

from accounts.authentication import CustomJWTAuthentication

logger = logging.getLogger("notifications")


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token, transport = self._get_token(scope)
        user = await self.get_user_from_token(token)

        # Query/subprotocol tokens are retained only for the customer mobile app.
        # Staff browser sessions must use the HttpOnly access cookie.
        if transport in {"query", "subprotocol"} and getattr(
            user, "role", None
        ) != "customer":
            user = AnonymousUser()

        scope["user"] = user
        scope["auth_transport"] = transport
        return await super().__call__(scope, receive, send)

    @classmethod
    def _get_token(cls, scope):
        query_token = cls._get_query_token(scope)
        if query_token:
            return query_token, "query"

        subprotocol_token = cls._get_subprotocol_token(scope)
        if subprotocol_token:
            return subprotocol_token, "subprotocol"

        cookie_token = cls._get_cookie_token(scope)
        if cookie_token:
            return cookie_token, "cookie"

        return None, None

    @staticmethod
    def _get_query_token(scope):
        query_string = scope.get("query_string", b"").decode()
        if query_string:
            try:
                parsed = parse_qs(query_string)
                tokens = parsed.get("token", [])
                if tokens:
                    return tokens[0]
            except ValueError:
                logger.debug("Failed to parse WebSocket query string", exc_info=True)
        return None

    @classmethod
    def _get_subprotocol_token(cls, scope):
        protocols = [str(item).strip() for item in scope.get("subprotocols", [])]
        if not protocols:
            header_value = cls._get_header(scope, b"sec-websocket-protocol")
            protocols = [item.strip() for item in header_value.split(",")]

        for protocol in protocols:
            if protocol.startswith("access_token|"):
                return protocol.partition("|")[2] or None

        if "access_token" not in protocols:
            return None

        return next(
            (protocol for protocol in protocols if protocol != "access_token"),
            None,
        )

    @classmethod
    def _get_cookie_token(cls, scope):
        raw_cookie = cls._get_header(scope, b"cookie")
        if not raw_cookie:
            return None
        cookie_name = getattr(settings, "AUTH_ACCESS_COOKIE_NAME", "access_token")
        return parse_cookie(raw_cookie).get(cookie_name)

    @staticmethod
    def _get_header(scope, header_name):
        values = [
            value.decode("latin1")
            for key, value in scope.get("headers", [])
            if key.lower() == header_name
        ]
        separator = "; " if header_name == b"cookie" else ","
        return separator.join(values)

    @database_sync_to_async
    def get_user_from_token(self, token):
        if not token:
            return AnonymousUser()

        try:
            authentication = CustomJWTAuthentication()
            user, _ = authentication.authenticate_raw_token(token)
            authentication.enforce_password_change(user)
            return user
        except (APIException, TokenError):
            logger.warning("WebSocket authentication failed")

        return AnonymousUser()
