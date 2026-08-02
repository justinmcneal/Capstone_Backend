import json
import os

import pytest
from django.http import JsonResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIClient

from accounts.models import Customer
from accounts.utils.auth_cookies import apply_auth_token_transport
from accounts.utils.token_utils import TokenUtils
from config.middleware import CSRFSameSiteTokenMiddleware


@pytest.fixture(autouse=True)
def _ensure_pepper(monkeypatch):
    if not os.environ.get("SECRET_PEPPER"):
        monkeypatch.setenv("SECRET_PEPPER", "a" * 64)


@pytest.fixture
def tokens_factory():
    counter = 0

    def create_tokens():
        nonlocal counter
        counter += 1
        customer = Customer(
            first_name="CSRF",
            last_name="Transport",
            email=f"csrf-transport-{counter}@example.com",
            verified=True,
        )
        customer.set_password("Pass123!")
        customer.save()
        return TokenUtils.generate_jwt_tokens(customer)

    return create_tokens


def _login_customer(email):
    customer = Customer(
        first_name="Transport",
        last_name="Login",
        email=email,
        verified=True,
    )
    customer.set_password("Pass123!")
    customer.save()
    return customer


def _middleware_response(request):
    middleware = CSRFSameSiteTokenMiddleware(
        lambda _request: JsonResponse({"ok": True})
    )
    return middleware(request)


def _json(response):
    return json.loads(response.content)


def _request(path="/api/loans/", *, bearer=False, csrf_header=None):
    headers = {}
    if bearer:
        headers["HTTP_AUTHORIZATION"] = "Bearer explicit-api-token"
    if csrf_header is not None:
        headers["HTTP_X_CSRFTOKEN"] = csrf_header
    return RequestFactory().post(path, data={}, content_type="application/json", **headers)


def test_cookie_authenticated_unsafe_request_requires_csrf_cookie_and_header():
    request = _request()
    request.COOKIES["access_token"] = "ambient-cookie-token"
    response = _middleware_response(request)
    assert response.status_code == 403
    assert _json(response)["code"] == "csrf_token_missing"

    request = _request(csrf_header="header-token")
    request.COOKIES["access_token"] = "ambient-cookie-token"
    response = _middleware_response(request)
    assert response.status_code == 403
    assert _json(response)["code"] == "csrf_token_missing"


def test_cookie_authenticated_request_rejects_mismatch_and_accepts_match():
    cookie_token = "a" * 32
    request = _request(csrf_header="b" * 32)
    request.COOKIES.update(
        {"access_token": "ambient-cookie-token", "csrftoken": cookie_token}
    )
    response = _middleware_response(request)
    assert response.status_code == 403
    assert _json(response)["code"] == "csrf_token_invalid"

    request = _request(csrf_header=cookie_token)
    request.COOKIES.update(
        {"access_token": "ambient-cookie-token", "csrftoken": cookie_token}
    )
    assert _middleware_response(request).status_code == 200


def test_bearer_request_ignores_unrelated_access_cookie_csrf_state():
    request = _request(bearer=True)
    request.COOKIES["access_token"] = "stale-browser-cookie"
    assert _middleware_response(request).status_code == 200


def test_refresh_cookie_still_requires_csrf_when_bearer_header_is_present():
    request = _request(path="/api/auth/refresh-token/", bearer=True)
    request.COOKIES["refresh_token"] = "ambient-refresh-cookie"
    response = _middleware_response(request)
    assert response.status_code == 403
    assert _json(response)["code"] == "csrf_token_missing"


def test_safe_cookie_request_does_not_require_csrf():
    request = RequestFactory().get("/api/loans/")
    request.COOKIES["access_token"] = "ambient-cookie-token"
    assert _middleware_response(request).status_code == 200


@override_settings(
    AUTH_COOKIE_SECURE=True,
    AUTH_COOKIE_HTTPONLY=True,
    AUTH_COOKIE_SAMESITE="Strict",
    AUTH_ACCESS_COOKIE_PATH="/api/",
    AUTH_REFRESH_COOKIE_PATH="/api/auth/",
)
def test_cookie_transport_uses_narrow_paths_and_removes_json_tokens(tokens_factory):
    tokens = tokens_factory()
    response = Response(
        {"status": "success", "data": {"access": tokens["access"], "refresh": tokens["refresh"]}}
    )

    apply_auth_token_transport(
        response, tokens["access"], tokens["refresh"], "cookie"
    )

    assert "access" not in response.data["data"]
    assert "refresh" not in response.data["data"]
    assert response.cookies["access_token"]["path"] == "/api/"
    assert response.cookies["refresh_token"]["path"] == "/api/auth/"
    assert response.cookies["access_token"]["httponly"] is True
    assert response.cookies["refresh_token"]["secure"] is True
    assert response.cookies["refresh_token"]["samesite"] == "Strict"


def test_body_transport_retains_json_tokens_and_sets_no_cookies(tokens_factory):
    tokens = tokens_factory()
    response = Response({"status": "success", "data": dict(tokens)})

    apply_auth_token_transport(response, tokens["access"], tokens["refresh"], "body")

    assert response.data["data"] == tokens
    assert not response.cookies


@override_settings(SECURE_SSL_REDIRECT=False)
def test_login_body_transport_does_not_mix_in_auth_cookies():
    customer = _login_customer("body-login@example.com")
    response = APIClient().post(
        reverse("accounts:login"),
        {
            "email": customer.email,
            "password": "Pass123!",
            "token_transport": "body",
        },
        format="json",
    )

    assert response.status_code == 200
    assert "access" in response.json()["data"]
    assert "refresh" in response.json()["data"]
    assert "access_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@override_settings(SECURE_SSL_REDIRECT=False)
def test_login_cookie_transport_does_not_expose_tokens_in_json():
    customer = _login_customer("cookie-login@example.com")
    response = APIClient().post(
        reverse("accounts:login"),
        {
            "email": customer.email,
            "password": "Pass123!",
            "token_transport": "cookie",
        },
        format="json",
    )

    assert response.status_code == 200
    assert "access" not in response.json()["data"]
    assert "refresh" not in response.json()["data"]
    assert response.cookies["access_token"]["path"] == "/api/"
    assert response.cookies["refresh_token"]["path"] == "/api/auth/"


@override_settings(SECURE_SSL_REDIRECT=False)
def test_login_rejects_unknown_token_transport():
    customer = _login_customer("invalid-transport@example.com")
    response = APIClient().post(
        reverse("accounts:login"),
        {
            "email": customer.email,
            "password": "Pass123!",
            "token_transport": "hybrid",
        },
        format="json",
    )
    assert response.status_code == 400


@override_settings(SECURE_SSL_REDIRECT=False)
def test_cookie_refresh_fails_closed_then_succeeds_with_csrf_pair():
    customer = _login_customer("cookie-refresh@example.com")
    client = APIClient()
    login = client.post(
        reverse("accounts:login"),
        {
            "email": customer.email,
            "password": "Pass123!",
            "token_transport": "cookie",
        },
        format="json",
    )
    assert login.status_code == 200

    blocked = client.post(reverse("accounts:refresh-token"), {}, format="json")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "csrf_token_missing"

    csrf_response = client.get(reverse("accounts:csrf-token"))
    csrf_token = csrf_response.json()["data"]["csrf_token"]
    refreshed = client.post(
        reverse("accounts:refresh-token"),
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert refreshed.status_code == 200
    assert "access" not in refreshed.json()["data"]
    assert "refresh" not in refreshed.json()["data"]
    assert "access_token" in refreshed.cookies
    assert "refresh_token" in refreshed.cookies
