"""
Mutual TLS (mTLS) Middleware for Django.

Validates client certificates presented during the TLS handshake.
When Gunicorn is configured with --cert-reqs=2 (CERT_REQUIRED), it
passes the client certificate via the WSGI environ dict. This middleware
reads the certificate, verifies it against the trusted CA, checks expiry,
and extracts the Common Name (CN) for downstream use.

Enable/disable via MTLS_ENABLED in settings.py (default: False).
"""

import logging
import os
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("authentication")


def _parse_pem_cert(pem_data):
    """Parse a PEM-encoded certificate string and return an x509.Certificate."""
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives.serialization import Encoding

    if isinstance(pem_data, str):
        pem_data = pem_data.encode("utf-8")

    # Gunicorn may URL-encode the PEM or pass it with different whitespace
    pem_data = pem_data.replace(b"\\n", b"\n").replace(b"%0A", b"\n")

    # Ensure proper PEM boundaries
    if b"-----BEGIN CERTIFICATE-----" not in pem_data:
        return None

    try:
        return cx509.load_pem_x509_certificate(pem_data)
    except Exception as exc:
        logger.warning("Failed to parse client certificate PEM: %s", exc)
        return None


def _load_ca_cert():
    """Load and cache the trusted CA certificate."""
    ca_path = getattr(settings, "MTLS_CA_CERT_PATH", None)
    if not ca_path:
        return None

    # Resolve relative paths against BASE_DIR
    if not os.path.isabs(ca_path):
        ca_path = os.path.join(settings.BASE_DIR, ca_path)

    if not os.path.isfile(ca_path):
        logger.error("MTLS_CA_CERT_PATH does not exist: %s", ca_path)
        return None

    try:
        from cryptography import x509 as cx509

        with open(ca_path, "rb") as f:
            return cx509.load_pem_x509_certificate(f.read())
    except Exception as exc:
        logger.error("Failed to load CA certificate: %s", exc)
        return None


# Module-level cache for the CA cert (loaded once per process)
_cached_ca_cert = None


def _get_ca_cert():
    global _cached_ca_cert
    if _cached_ca_cert is None:
        _cached_ca_cert = _load_ca_cert()
    return _cached_ca_cert


class MutualTLSMiddleware:
    """
    Middleware that enforces mutual TLS client certificate verification.

    Behaviour:
    - If MTLS_ENABLED is False (default), the middleware is a no-op.
    - Paths listed in MTLS_EXEMPT_PATHS are exempted (e.g. /api/health/).
    - Extracts the client certificate from WSGI environ or X-SSL-Client-Cert header.
    - Validates against the configured CA certificate.
    - Checks certificate expiry.
    - Sets request.mtls_client_cn with the client's Common Name on success.
    - Returns 403 JSON response on failure.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = getattr(settings, "MTLS_ENABLED", False)
        self.exempt_paths = getattr(settings, "MTLS_EXEMPT_PATHS", ["/api/health/"])

    def __call__(self, request):
        # Skip if mTLS is not enabled
        if not self.enabled:
            request.mtls_client_cn = None
            return self.get_response(request)

        # Skip exempt paths
        if any(request.path.startswith(p) for p in self.exempt_paths):
            request.mtls_client_cn = None
            return self.get_response(request)

        # Extract client certificate from request
        client_cert = self._extract_client_cert(request)
        if client_cert is None:
            logger.warning(
                "mTLS: No client certificate presented for %s %s from %s",
                request.method,
                request.path,
                request.META.get("REMOTE_ADDR", "unknown"),
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Client certificate required",
                    "code": "mtls_cert_missing",
                },
                status=403,
            )

        # Validate the client certificate
        error = self._validate_cert(client_cert)
        if error:
            logger.warning(
                "mTLS: Certificate validation failed for %s %s — %s",
                request.method,
                request.path,
                error,
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": f"Client certificate validation failed: {error}",
                    "code": "mtls_cert_invalid",
                },
                status=403,
            )

        # Extract Common Name
        from cryptography.x509.oid import NameOID

        cn_attrs = client_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cn = cn_attrs[0].value if cn_attrs else "unknown"
        request.mtls_client_cn = cn

        logger.info("mTLS: Authenticated client CN=%s for %s %s", cn, request.method, request.path)
        return self.get_response(request)

    def _extract_client_cert(self, request):
        """
        Extract the client certificate from the request.

        Gunicorn with --cert-reqs=2 places the raw DER cert in
        wsgi.environ['SSL_CLIENT_CERT']. Some reverse proxies pass it
        in the X-SSL-Client-Cert header instead.
        """
        # 1. Try WSGI environ (Gunicorn native TLS)
        pem = request.META.get("SSL_CLIENT_CERT") or request.META.get("wsgi.ssl_client_cert")
        if pem:
            return _parse_pem_cert(pem)

        # 2. Try X-SSL-Client-Cert header (reverse proxy)
        header_cert = request.META.get("HTTP_X_SSL_CLIENT_CERT")
        if header_cert:
            return _parse_pem_cert(header_cert)

        return None

    def _validate_cert(self, client_cert):
        """
        Validate the client certificate.

        Returns None on success, or an error message string on failure.
        """
        from cryptography.hazmat.primitives.asymmetric import padding

        # 1. Check expiry
        now = datetime.now(timezone.utc)
        if now < client_cert.not_valid_before_utc:
            return "Certificate is not yet valid"
        if now > client_cert.not_valid_after_utc:
            return "Certificate has expired"

        # 2. Verify the certificate was signed by our trusted CA
        ca_cert = _get_ca_cert()
        if ca_cert is None:
            return "Server CA certificate not configured"

        try:
            # Verify the client cert's signature using the CA's public key
            ca_cert.public_key().verify(
                client_cert.signature,
                client_cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                client_cert.signature_hash_algorithm,
            )
        except Exception:
            return "Certificate not signed by trusted CA"

        # 3. Verify the CA itself is the expected one (issuer match)
        if client_cert.issuer != ca_cert.subject:
            return "Certificate issuer does not match trusted CA"

        return None
