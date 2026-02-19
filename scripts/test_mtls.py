#!/usr/bin/env python3
"""
mTLS Handshake Verification Script.

Tests the mutual TLS setup by making requests to the backend:
1. With valid client certificate  → expects 200
2. Without client certificate     → expects connection error or 403
3. Validates the server-pins endpoint

Prerequisites:
- Run `python scripts/generate_certs.py` first
- Start backend with mTLS: see Procfile `web-mtls` entry

Usage:
    python scripts/test_mtls.py [--host HOST] [--port PORT]
"""

import json
import os
import ssl
import sys
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS_DIR = os.path.join(BASE_DIR, "certs")

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8443

CA_CERT = os.path.join(CERTS_DIR, "ca.crt")
CLIENT_CERT = os.path.join(CERTS_DIR, "client.crt")
CLIENT_KEY = os.path.join(CERTS_DIR, "client.key")

PASS = "✓ PASS"
FAIL = "✗ FAIL"
SKIP = "⊘ SKIP"


def check_certs_exist():
    """Verify all required certificate files exist."""
    missing = []
    for path, name in [(CA_CERT, "ca.crt"), (CLIENT_CERT, "client.crt"), (CLIENT_KEY, "client.key")]:
        if not os.path.isfile(path):
            missing.append(name)
    return missing


def make_request(url, ssl_context=None):
    """Make an HTTPS request and return (status_code, body_dict)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        response = urllib.request.urlopen(req, context=ssl_context, timeout=10)
        body = json.loads(response.read().decode("utf-8"))
        return response.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"raw": str(e)}
        return e.code, body
    except (urllib.error.URLError, ssl.SSLError, ConnectionRefusedError, OSError) as e:
        return None, {"error": str(e)}


def test_health_with_client_cert(base_url):
    """Test 1: Health check WITH valid client certificate."""
    print("\n  Test 1: Health check with valid client cert")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(CA_CERT)
    ctx.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)

    status, body = make_request(f"{base_url}/api/health/", ctx)

    if status == 200:
        print(f"    {PASS} — Status {status}, response: {body.get('status', 'n/a')}")
        return True
    else:
        print(f"    {FAIL} — Expected 200, got {status}")
        print(f"           Response: {body}")
        return False


def test_health_without_client_cert(base_url):
    """Test 2: Health check WITHOUT client certificate (should fail at TLS level)."""
    print("\n  Test 2: Health check WITHOUT client cert")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(CA_CERT)
    # Deliberately NOT loading client cert

    status, body = make_request(f"{base_url}/api/health/", ctx)

    if status is None:
        # Connection-level error (TLS handshake rejection) — expected!
        print(f"    {PASS} — Connection rejected (no client cert): {body.get('error', '')[:80]}")
        return True
    elif status == 403:
        print(f"    {PASS} — Server returned 403 Forbidden (mTLS middleware)")
        return True
    else:
        print(f"    {FAIL} — Expected connection error or 403, got {status}")
        print(f"           Response: {body}")
        return False


def test_server_pins_endpoint(base_url):
    """Test 3: Server pins endpoint (should be accessible and return pin hashes)."""
    print("\n  Test 3: Server certificate pins endpoint")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(CA_CERT)
    ctx.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)

    status, body = make_request(f"{base_url}/api/auth/server-pins/", ctx)

    if status == 200 and body.get("status") == "success":
        pins = body.get("data", {}).get("pins", [])
        if pins:
            print(f"    {PASS} — Server pins: {pins}")
            return True
        else:
            print(f"    {FAIL} — Response OK but no pins returned")
            return False
    else:
        print(f"    {FAIL} — Expected 200+success, got {status}")
        print(f"           Response: {body}")
        return False


def test_api_without_cert_blocked(base_url):
    """Test 4: Regular API endpoint without client cert (should be blocked)."""
    print("\n  Test 4: Protected API without client cert")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(CA_CERT)

    status, body = make_request(f"{base_url}/api/auth/csrf-token/", ctx)

    if status is None or status == 403:
        msg = body.get('error', body.get('message', ''))[:80]
        print(f"    {PASS} — Request blocked: {msg}")
        return True
    else:
        print(f"    {FAIL} — Expected blocked, got {status}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test mTLS handshake")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    base_url = f"https://{args.host}:{args.port}"

    print("=" * 60)
    print("  mTLS Handshake Verification")
    print("=" * 60)
    print(f"\n  Target: {base_url}")
    print(f"  Certs:  {CERTS_DIR}")

    # Check prerequisites
    missing = check_certs_exist()
    if missing:
        print(f"\n  {FAIL} Missing certificate files: {', '.join(missing)}")
        print("  Run: python scripts/generate_certs.py")
        sys.exit(1)

    print(f"\n  {PASS} All certificate files found")

    # Run tests
    results = []
    results.append(("Health with client cert", test_health_with_client_cert(base_url)))
    results.append(("Health without client cert", test_health_without_client_cert(base_url)))
    results.append(("Server pins endpoint", test_server_pins_endpoint(base_url)))
    results.append(("Protected API without cert", test_api_without_cert_blocked(base_url)))

    # Summary
    passed = sum(1 for _, r in results if r)
    total = len(results)

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} tests passed")
    print("=" * 60)

    for name, result in results:
        icon = PASS if result else FAIL
        print(f"    {icon} {name}")

    print()

    if passed == total:
        print("  🎉 All mTLS tests passed! Your connection is secured.")
    else:
        print("  ⚠️  Some tests failed. Check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
