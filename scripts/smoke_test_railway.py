#!/usr/bin/env python3
"""Run a lightweight smoke test suite against a deployed Railway backend.

This script is intentionally dependency-light and can be run locally or from CI.
It expects either an existing access token or a login email/password pair.

Required environment variables:
  - SMOKE_BASE_URL: Base URL for the deployed backend, e.g. https://app.up.railway.app

Authentication options:
  - SMOKE_ACCESS_TOKEN: Use an existing JWT access token
  - or SMOKE_EMAIL + SMOKE_PASSWORD: Login and extract the access token

Optional environment variables:
  - SMOKE_DOCUMENT_TYPE: defaults to valid_id
  - SMOKE_TIMEOUT_SECONDS: defaults to 20
  - SMOKE_KEEP_DOCUMENT: set to 1 to skip delete step
  - SMOKE_RUN_NOTIFICATIONS: set to 1 to call notifications endpoints
  - SMOKE_RUN_LOANS: set to 1 to call loans endpoints
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAA=="
)


@dataclass
class SmokeConfig:
    base_url: str
    timeout: int = 20
    document_type: str = "valid_id"
    keep_document: bool = False
    run_notifications: bool = False
    run_loans: bool = True


class SmokeFailure(RuntimeError):
    pass


def _clean_base_url(value: str) -> str:
    return value.rstrip("/")


def _response_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception as exc:
        raise SmokeFailure(
            f"Expected JSON response from {response.url}, got status {response.status_code}"
        ) from exc


def _ensure_ok(response: requests.Response, expected_statuses=(200, 201)) -> Dict[str, Any]:
    if response.status_code not in expected_statuses:
        body = response.text[:1000]
        raise SmokeFailure(f"{response.request.method} {response.url} -> {response.status_code}: {body}")
    return _response_json(response)


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(session: requests.Session, config: SmokeConfig) -> str:
    token = os.getenv("SMOKE_ACCESS_TOKEN", "").strip()
    if token:
        return token

    email = os.getenv("SMOKE_EMAIL", "").strip()
    password = os.getenv("SMOKE_PASSWORD", "").strip()
    if not email or not password:
        raise SmokeFailure(
            "Set either SMOKE_ACCESS_TOKEN or both SMOKE_EMAIL and SMOKE_PASSWORD"
        )

    response = session.post(
        f"{config.base_url}/api/auth/login/",
        json={"email": email, "password": password},
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    data = payload.get("data") or {}
    token = data.get("access") or data.get("access_token")
    if not token:
        raise SmokeFailure(f"Login succeeded but no access token was returned: {payload}")
    return token


def check_health(session: requests.Session, config: SmokeConfig) -> None:
    response = session.get(f"{config.base_url}/api/health/", timeout=config.timeout)
    payload = _ensure_ok(response)
    print("health:", json.dumps(payload, sort_keys=True))


def check_ai_status(session: requests.Session, config: SmokeConfig, token: str) -> None:
    response = session.get(
        f"{config.base_url}/api/ai/status/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("ai_status:", json.dumps(payload, sort_keys=True))


def check_loans(session: requests.Session, config: SmokeConfig, token: str) -> None:
    response = session.get(
        f"{config.base_url}/api/loans/products/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("loans_products:", json.dumps(payload, sort_keys=True))


def upload_document(session: requests.Session, config: SmokeConfig, token: str) -> Dict[str, Any]:
    files = {"file": ("smoke-test.pdf", b"%PDF-1.4\n%EOF\n", "application/pdf")}
    data = {"document_type": config.document_type}
    response = session.post(
        f"{config.base_url}/api/documents/upload/",
        headers=_auth_headers(token),
        files=files,
        data=data,
        timeout=config.timeout,
    )
    payload = _ensure_ok(response, expected_statuses=(200, 201))
    data = payload.get("data") or {}
    document_id = data.get("id")
    if not document_id:
        raise SmokeFailure(f"Upload response missing document id: {payload}")
    print("upload:", json.dumps(payload, sort_keys=True))
    return payload


def list_documents(session: requests.Session, config: SmokeConfig, token: str) -> Dict[str, Any]:
    response = session.get(
        f"{config.base_url}/api/documents/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("documents_list:", json.dumps(payload, sort_keys=True))
    return payload


def get_document_detail(session: requests.Session, config: SmokeConfig, token: str, document_id: str) -> Dict[str, Any]:
    response = session.get(
        f"{config.base_url}/api/documents/{document_id}/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("document_detail:", json.dumps(payload, sort_keys=True))
    return payload


def delete_document(session: requests.Session, config: SmokeConfig, token: str, document_id: str) -> None:
    response = session.delete(
        f"{config.base_url}/api/documents/{document_id}/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("document_delete:", json.dumps(payload, sort_keys=True))


def check_notifications(session: requests.Session, config: SmokeConfig, token: str) -> None:
    response = session.get(
        f"{config.base_url}/api/notifications/unread-count/",
        headers=_auth_headers(token),
        timeout=config.timeout,
    )
    payload = _ensure_ok(response)
    print("notifications_unread:", json.dumps(payload, sort_keys=True))


def run_smoke(config: SmokeConfig) -> None:
    session = requests.Session()

    check_health(session, config)
    token = login(session, config)
    check_ai_status(session, config, token)

    if config.run_loans:
        check_loans(session, config, token)

    upload_payload = upload_document(session, config, token)
    document_data = upload_payload["data"]
    document_id = document_data["id"]

    list_payload = list_documents(session, config, token)
    documents = (list_payload.get("data") or {}).get("documents") or []
    if not any(str(item.get("id")) == str(document_id) for item in documents):
        raise SmokeFailure(f"Uploaded document {document_id} not present in list response")

    detail_payload = get_document_detail(session, config, token, document_id)
    detail_data = detail_payload.get("data") or {}
    if str(detail_data.get("id")) != str(document_id):
        raise SmokeFailure("Document detail returned mismatched id")

    if config.run_notifications:
        check_notifications(session, config, token)

    if not config.keep_document:
        delete_document(session, config, token, document_id)


def parse_args() -> SmokeConfig:
    parser = argparse.ArgumentParser(description="Run Railway smoke tests")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "").strip())
    parser.add_argument("--timeout", type=int, default=int(os.getenv("SMOKE_TIMEOUT_SECONDS", "20")))
    parser.add_argument("--document-type", default=os.getenv("SMOKE_DOCUMENT_TYPE", "valid_id"))
    parser.add_argument("--keep-document", action="store_true", default=os.getenv("SMOKE_KEEP_DOCUMENT", "0") == "1")
    parser.add_argument("--run-notifications", action="store_true", default=os.getenv("SMOKE_RUN_NOTIFICATIONS", "0") == "1")
    parser.add_argument("--no-loans", action="store_true", default=os.getenv("SMOKE_RUN_LOANS", "1") != "1")
    args = parser.parse_args()

    if not args.base_url:
        raise SmokeFailure("SMOKE_BASE_URL (or --base-url) is required")

    return SmokeConfig(
        base_url=_clean_base_url(args.base_url),
        timeout=args.timeout,
        document_type=args.document_type,
        keep_document=args.keep_document,
        run_notifications=args.run_notifications,
        run_loans=not args.no_loans,
    )


def main() -> int:
    try:
        config = parse_args()
        run_smoke(config)
        print("smoke: success")
        return 0
    except SmokeFailure as exc:
        print(f"smoke: failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("smoke: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"smoke: unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())