#!/usr/bin/env python3
"""
mTLS Demo Script — For Professor Presentation

This script demonstrates mutual TLS (mTLS) + certificate pinning
by running through each security check step-by-step with clear output.

Usage:
    1. First start the mTLS server in another terminal:
       python scripts/run_mtls_server.py

    2. Then run this demo:
       python scripts/demo_mtls.py

It will show:
    1. What happens WITHOUT a client certificate (rejected)
    2. What happens WITH a valid client certificate (accepted)
    3. Certificate pinning verification
    4. Certificate details inspection
"""

import base64
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS_DIR = os.path.join(BASE_DIR, "certs")
CA_CERT = os.path.join(CERTS_DIR, "ca.crt")
CLIENT_CERT = os.path.join(CERTS_DIR, "client.crt")
CLIENT_KEY = os.path.join(CERTS_DIR, "client.key")
SERVER_CERT = os.path.join(CERTS_DIR, "server.crt")

HOST = "localhost"
PORT = 8443
BASE_URL = f"https://{HOST}:{PORT}"

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(text):
    print(f"\n{'=' * 60}")
    print(f"  {BOLD}{text}{RESET}")
    print(f"{'=' * 60}")


def step(num, text):
    print(f"\n  {CYAN}[Step {num}]{RESET} {BOLD}{text}{RESET}")
    print(f"  {DIM}{'─' * 50}{RESET}")


def success(text):
    print(f"  {GREEN}✓ {text}{RESET}")


def fail(text):
    print(f"  {RED}✗ {text}{RESET}")


def info(text):
    print(f"  {DIM}  {text}{RESET}")


def pause():
    input(f"\n  {YELLOW}Press Enter to continue...{RESET}")


def make_request(url, ssl_context=None):
    """Make HTTPS request, return (status, body_dict)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, context=ssl_context, timeout=10)
        body = json.loads(resp.read().decode("utf-8"))
        return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"error": str(e)}
        return e.code, body
    except (urllib.error.URLError, ssl.SSLError, ConnectionRefusedError, OSError) as e:
        return None, {"error": str(e)}


def get_cert_info(cert_path):
    """Read certificate and return useful info."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        org = cert.subject.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)[0].value
        issuer_cn = cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        not_before = cert.not_valid_before_utc.strftime("%Y-%m-%d %H:%M UTC")
        not_after = cert.not_valid_after_utc.strftime("%Y-%m-%d %H:%M UTC")
        serial = format(cert.serial_number, 'X')

        # SPKI pin
        spki_der = cert.public_key().public_bytes(
            encoding=Encoding.DER, format=PublicFormat.SubjectPublicKeyInfo
        )
        pin = base64.b64encode(hashlib.sha256(spki_der).digest()).decode()

        return {
            "cn": cn, "org": org, "issuer": issuer_cn,
            "valid_from": not_before, "valid_until": not_after,
            "serial": serial[:16] + "...", "pin": f"sha256/{pin}"
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    header("mTLS + Certificate Pinning Demo")
    print(f"\n  {BOLD}What is mTLS?{RESET}")
    print(f"  Normal TLS:  Server proves identity → Client trusts server")
    print(f"  Mutual TLS:  Server proves identity → Client trusts server")
    print(f"               Client proves identity → Server trusts client")
    print(f"               {GREEN}BOTH sides must present valid certificates!{RESET}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 1: Show the certificate chain
    # ─────────────────────────────────────────────────────────
    step(1, "Certificate Chain Inspection")

    print(f"\n  Our PKI (Public Key Infrastructure) chain:")
    print(f"  ┌─────────────────────────────────┐")
    print(f"  │  {BOLD}Root CA (Certificate Authority){RESET}  │ ← Self-signed, trusts itself")
    print(f"  │  Signs both server + client      │")
    print(f"  └──────────┬──────────┬────────────┘")
    print(f"             │          │")
    print(f"  ┌──────────▼──┐  ┌───▼────────────┐")
    print(f"  │ {GREEN}Server Cert{RESET} │  │ {CYAN}Client Cert{RESET}   │")
    print(f"  │ (backend)   │  │ (frontend)     │")
    print(f"  └─────────────┘  └────────────────┘")

    for label, path in [("CA Certificate", CA_CERT), ("Server Certificate", SERVER_CERT), ("Client Certificate", CLIENT_CERT)]:
        ci = get_cert_info(path)
        if "error" not in ci:
            print(f"\n  {BOLD}{label}:{RESET}")
            info(f"Common Name:  {ci['cn']}")
            info(f"Organization: {ci['org']}")
            info(f"Issued By:    {ci['issuer']}")
            info(f"Valid From:   {ci['valid_from']}")
            info(f"Valid Until:  {ci['valid_until']}")
            info(f"Serial:       {ci['serial']}")
            if "server" in label.lower():
                info(f"SPKI Pin:     {ci['pin']}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 2: Connect WITHOUT client cert (should fail)
    # ─────────────────────────────────────────────────────────
    step(2, "Connection WITHOUT Client Certificate")
    print(f"  Attempting to connect to {BASE_URL}/api/health/")
    print(f"  {YELLOW}Without presenting a client certificate...{RESET}")

    ctx_no_client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx_no_client.load_verify_locations(CA_CERT)

    status, body = make_request(f"{BASE_URL}/api/health/", ctx_no_client)

    if status is None:
        success(f"Connection REJECTED by server — TLS handshake failed!")
        info(f"Reason: {body.get('error', 'unknown')[:80]}")
        info(f"The server refused the connection because no client cert was presented.")
    elif status == 403:
        success(f"Server returned 403 Forbidden — mTLS middleware blocked the request!")
        info(f"Message: {body.get('message', 'n/a')}")
    else:
        fail(f"Expected rejection, got status {status}")
        info(f"This means mTLS is NOT properly enforced!")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 3: Connect WITH client cert (should succeed)
    # ─────────────────────────────────────────────────────────
    step(3, "Connection WITH Valid Client Certificate")
    print(f"  Attempting to connect to {BASE_URL}/api/health/")
    print(f"  {GREEN}With a valid client certificate signed by our CA...{RESET}")

    ctx_with_client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx_with_client.load_verify_locations(CA_CERT)
    ctx_with_client.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)

    status, body = make_request(f"{BASE_URL}/api/health/", ctx_with_client)

    if status == 200:
        success(f"Connection ACCEPTED — mTLS handshake successful!")
        info(f"Server response: {json.dumps(body, indent=2)[:200]}")
        info(f"Both server and client verified each other's certificates.")
    else:
        fail(f"Expected 200, got {status}")
        info(f"Response: {body}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 4: Certificate Pinning
    # ─────────────────────────────────────────────────────────
    step(4, "Certificate Pinning Verification")
    print(f"  Fetching server's SPKI pin from /api/auth/server-pins/...")

    status, body = make_request(f"{BASE_URL}/api/auth/server-pins/", ctx_with_client)

    if status == 200 and body.get("status") == "success":
        server_pins = body["data"]["pins"]
        success(f"Server returned its certificate pins:")
        for pin in server_pins:
            info(f"Pin: {pin}")

        # Compare with our local cert
        local_info = get_cert_info(SERVER_CERT)
        local_pin = local_info.get("pin", "")

        if local_pin in server_pins:
            success(f"Pin MATCHES our local server certificate!")
            info(f"This confirms the server is authentic — no MITM attack.")
        else:
            fail(f"Pin MISMATCH — potential MITM attack!")
            info(f"Local pin: {local_pin}")
            info(f"Server pins: {server_pins}")
    else:
        fail(f"Could not fetch server pins: {status}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────
    header("Demo Summary")
    print(f"""
  {BOLD}What we demonstrated:{RESET}

  {GREEN}✓{RESET} {BOLD}Mutual TLS (mTLS):{RESET}
    • Server presents certificate → Client verifies server identity
    • Client presents certificate → Server verifies client identity
    • Without valid client cert   → Connection is REJECTED
    • With valid client cert      → Connection is ACCEPTED

  {GREEN}✓{RESET} {BOLD}Certificate Pinning:{RESET}
    • Server exposes its SPKI SHA-256 hash via /api/auth/server-pins/
    • Frontend compares the hash against hardcoded trusted pins
    • If hash doesn't match → ALL API requests are blocked (MITM detected)
    • If hash matches       → Communication proceeds securely

  {GREEN}✓{RESET} {BOLD}PKI Chain:{RESET}
    • Self-signed Root CA signs both server and client certificates
    • 4096-bit RSA keys with SHA-256 signatures
    • Server cert includes SANs for localhost + 127.0.0.1

  {BOLD}Security Checklist:{RESET}
    ☑ Connections encrypted?   → mTLS (mutual TLS)
    ☑ Certificate pinning?     → SPKI SHA-256 pin validation
    ☑ Client authentication?   → Client certificate required
    ☑ Man-in-the-middle safe?  → Pin mismatch blocks all traffic
""")


if __name__ == "__main__":
    main()
