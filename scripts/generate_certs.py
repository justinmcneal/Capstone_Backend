#!/usr/bin/env python3
"""
Generate self-signed CA, server, and client certificates for mTLS.

Usage:
    python scripts/generate_certs.py

Output (in certs/ directory):
    ca.key, ca.crt          — Root Certificate Authority
    server.key, server.crt  — Server certificate (signed by CA)
    client.key, client.crt  — Client certificate (signed by CA)

Also prints the SHA-256 SPKI pin hash for certificate pinning.
"""

import os
import sys
import base64
import hashlib
from datetime import datetime, timedelta, timezone

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("ERROR: 'cryptography' package is required.")
    print("Install it with:  pip install cryptography>=41.0.0")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CERTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "certs")
KEY_SIZE = 4096
CA_VALIDITY_DAYS = 3650      # 10 years
SERVER_VALIDITY_DAYS = 365   # 1 year
CLIENT_VALIDITY_DAYS = 365   # 1 year

CA_CN = "MSME Pathways Root CA"
SERVER_CN = "localhost"
CLIENT_CN = "capstone-web-client"

# SANs for the server certificate are built inside generate_server_cert()


def _generate_key() -> rsa.RSAPrivateKey:
    """Generate a new RSA private key."""
    return rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)


def _write_key(key: rsa.RSAPrivateKey, path: str) -> None:
    """Write a private key to PEM file."""
    with open(path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"  ✓ {os.path.basename(path)}")


def _write_cert(cert: x509.Certificate, path: str) -> None:
    """Write a certificate to PEM file."""
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"  ✓ {os.path.basename(path)}")


def _build_subject(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PH"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MSME Pathways"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def generate_ca(certs_dir: str):
    """Generate the Root CA key + self-signed certificate."""
    print("\n[1/3] Generating Root CA ...")
    key = _generate_key()
    subject = issuer = _build_subject(CA_CN)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=CA_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    _write_key(key, os.path.join(certs_dir, "ca.key"))
    _write_cert(cert, os.path.join(certs_dir, "ca.crt"))
    return key, cert


def generate_server_cert(certs_dir: str, ca_key, ca_cert):
    """Generate server key + certificate signed by the CA."""
    print("\n[2/3] Generating Server Certificate ...")
    import ipaddress

    key = _generate_key()
    subject = _build_subject(SERVER_CN)

    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName("host.docker.internal"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        x509.IPAddress(ipaddress.IPv6Address("::1")),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=SERVER_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, key_cert_sign=False, crl_sign=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_key(key, os.path.join(certs_dir, "server.key"))
    _write_cert(cert, os.path.join(certs_dir, "server.crt"))
    return key, cert


def generate_client_cert(certs_dir: str, ca_key, ca_cert):
    """Generate client key + certificate signed by the CA."""
    print("\n[3/3] Generating Client Certificate ...")
    key = _generate_key()
    subject = _build_subject(CLIENT_CN)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=CLIENT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, key_cert_sign=False, crl_sign=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_key(key, os.path.join(certs_dir, "client.key"))
    _write_cert(cert, os.path.join(certs_dir, "client.crt"))
    return key, cert


def compute_spki_pin(cert: x509.Certificate) -> str:
    """
    Compute the SPKI SHA-256 pin (RFC 7469 format) of a certificate.
    
    This is the base64-encoded SHA-256 hash of the DER-encoded
    Subject Public Key Info (SPKI) — the same format used by
    HTTP Public-Key-Pinning and browser certificate pinning.
    """
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(spki_der).digest()
    return base64.b64encode(digest).decode("ascii")


def main():
    print("=" * 60)
    print("  mTLS Certificate Generator — MSME Pathways")
    print("=" * 60)

    os.makedirs(CERTS_DIR, exist_ok=True)

    # 1. Root CA
    ca_key, ca_cert = generate_ca(CERTS_DIR)

    # 2. Server certificate
    _server_key, server_cert = generate_server_cert(CERTS_DIR, ca_key, ca_cert)

    # 3. Client certificate
    _client_key, client_cert = generate_client_cert(CERTS_DIR, ca_key, ca_cert)

    # 4. Compute SPKI pin for certificate pinning
    server_pin = compute_spki_pin(server_cert)
    ca_pin = compute_spki_pin(ca_cert)

    print("\n" + "=" * 60)
    print("  All certificates generated successfully!")
    print("=" * 60)
    print(f"\n  Output directory: {CERTS_DIR}")
    print(f"\n  Server SPKI Pin (SHA-256):")
    print(f"    sha256/{server_pin}")
    print(f"\n  CA SPKI Pin (SHA-256):")
    print(f"    sha256/{ca_pin}")
    print(f"\n  Add to frontend .env:")
    print(f"    VITE_SERVER_CERT_PIN=sha256/{server_pin}")
    print(f"\n  Test with curl:")
    print(f"    curl --cert certs/client.crt --key certs/client.key \\")
    print(f"         --cacert certs/ca.crt https://localhost:8443/api/health/")
    print()


if __name__ == "__main__":
    main()
