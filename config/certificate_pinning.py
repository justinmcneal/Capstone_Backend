"""
Server-side certificate pinning endpoint.

Exposes the server certificate's SPKI SHA-256 hash so the frontend
can verify it during its pinning bootstrap. This is a public endpoint
(no auth required) that returns the pre-computed pin hash.
"""

import base64
import hashlib
import logging
import os

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("authentication")


def compute_server_pin():
    """
    Compute the SHA-256 SPKI pin of the server certificate.
    Returns a base64-encoded hash string, or None if cert not found.
    """
    cert_path = getattr(settings, "MTLS_SERVER_CERT_PATH", None)
    if not cert_path:
        return None

    if not os.path.isabs(cert_path):
        cert_path = os.path.join(settings.BASE_DIR, cert_path)

    if not os.path.isfile(cert_path):
        logger.warning("Server certificate not found at: %s", cert_path)
        return None

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        spki_der = cert.public_key().public_bytes(
            encoding=Encoding.DER,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
        digest = hashlib.sha256(spki_der).digest()
        return base64.b64encode(digest).decode("ascii")
    except Exception as exc:
        logger.error("Failed to compute server certificate pin: %s", exc)
        return None


# Module-level cache
_cached_pin = None


def get_server_pin():
    global _cached_pin
    if _cached_pin is None:
        _cached_pin = compute_server_pin()
    return _cached_pin


class ServerPinsView(APIView):
    """
    GET /api/auth/server-pins/

    Returns the server certificate's SPKI SHA-256 pin hash.
    The frontend uses this during bootstrap to verify the server identity
    and detect potential MITM attacks.

    Response:
        {
            "status": "success",
            "data": {
                "pins": ["sha256/BASE64_HASH"],
                "algorithm": "sha256",
                "expires": "2027-02-19T00:00:00Z"
            }
        }
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # No auth required for pin bootstrap

    def get(self, request):
        pin = get_server_pin()

        if not pin:
            return Response(
                {
                    "status": "error",
                    "message": "Server certificate pinning not configured",
                    "code": "pinning_not_configured",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Optionally read expiry from the cert
        expiry = self._get_cert_expiry()

        return Response(
            {
                "status": "success",
                "data": {
                    "pins": [f"sha256/{pin}"],
                    "algorithm": "sha256",
                    "expires": expiry,
                },
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_cert_expiry():
        """Get the server certificate's expiry date as ISO string."""
        cert_path = getattr(settings, "MTLS_SERVER_CERT_PATH", None)
        if not cert_path:
            return None

        if not os.path.isabs(cert_path):
            cert_path = os.path.join(settings.BASE_DIR, cert_path)

        try:
            from cryptography import x509

            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            return cert.not_valid_after_utc.isoformat()
        except Exception:
            return None
