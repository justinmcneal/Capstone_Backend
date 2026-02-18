from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


def _cookie_max_age_from_token(token: str, token_cls) -> int:
    parsed = token_cls(token)
    exp = int(parsed["exp"])
    iat = int(parsed.get("iat", exp))
    return max(exp - iat, 0)


def set_auth_cookies(response, access_token: str, refresh_token: str):
    access_name = getattr(settings, "AUTH_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    secure = getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG)
    httponly = getattr(settings, "AUTH_COOKIE_HTTPONLY", True)
    samesite = getattr(settings, "AUTH_COOKIE_SAMESITE", "Lax")
    path = getattr(settings, "AUTH_COOKIE_PATH", "/")

    access_max_age = _cookie_max_age_from_token(access_token, AccessToken)
    refresh_max_age = _cookie_max_age_from_token(refresh_token, RefreshToken)

    response.set_cookie(
        key=access_name,
        value=access_token,
        max_age=access_max_age,
        secure=secure,
        httponly=httponly,
        samesite=samesite,
        path=path,
    )
    response.set_cookie(
        key=refresh_name,
        value=refresh_token,
        max_age=refresh_max_age,
        secure=secure,
        httponly=httponly,
        samesite=samesite,
        path=path,
    )


def clear_auth_cookies(response):
    access_name = getattr(settings, "AUTH_ACCESS_COOKIE_NAME", "access_token")
    refresh_name = getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    path = getattr(settings, "AUTH_COOKIE_PATH", "/")

    response.delete_cookie(access_name, path=path)
    response.delete_cookie(refresh_name, path=path)


def get_refresh_token_from_request(request):
    refresh = request.data.get("refresh") or request.data.get("refresh_token")
    if refresh:
        return refresh

    refresh_name = getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    return request.COOKIES.get(refresh_name)


def get_access_token_from_request(request):
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    access_name = getattr(settings, "AUTH_ACCESS_COOKIE_NAME", "access_token")
    return request.COOKIES.get(access_name)
