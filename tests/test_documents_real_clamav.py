"""Explicitly opt-in proof against an isolated real ClamAV daemon."""

import os

import pytest

from documents.services.malware import ClamAVScanner, MalwareScanResult

REAL_CLAMAV_HOST = os.getenv("REAL_CLAMAV_TEST_HOST")
REAL_CLAMAV_ALLOW_SCAN = os.getenv("REAL_CLAMAV_TEST_ALLOW_SCAN") == "yes"


def _eicar_test_bytes():
    """Build the harmless industry-standard AV test marker only at runtime."""
    return b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + (
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )


@pytest.mark.real_clamav
def test_real_clamav_health_clean_and_detection(settings):
    """Prove readiness plus clean/detected verdicts without customer content."""
    if not REAL_CLAMAV_HOST or not REAL_CLAMAV_ALLOW_SCAN:
        pytest.skip(
            "REAL_CLAMAV_TEST_HOST and REAL_CLAMAV_TEST_ALLOW_SCAN=yes are required"
        )

    settings.DOCUMENT_MALWARE_SCAN_ENABLED = True
    settings.DOCUMENT_MALWARE_SCAN_REQUIRED = True
    settings.DOCUMENT_MALWARE_SCAN_HOST = REAL_CLAMAV_HOST
    settings.DOCUMENT_MALWARE_SCAN_PORT = int(
        os.getenv("REAL_CLAMAV_TEST_PORT") or "3310"
    )
    settings.DOCUMENT_MALWARE_SCAN_TIMEOUT_SECONDS = float(
        os.getenv("REAL_CLAMAV_TEST_TIMEOUT_SECONDS") or "10"
    )
    settings.DOCUMENT_MALWARE_SCAN_CHUNK_BYTES = 64 * 1024

    scanner = ClamAVScanner()
    test_marker = _eicar_test_bytes()
    assert len(test_marker) == 68

    assert scanner.health() == {
        "ready": True,
        "status": "available",
        "required": True,
    }
    assert scanner.scan_bytes(b"Capstone ClamAV deployment validation") == (
        MalwareScanResult(clean=True, status="clean")
    )
    assert scanner.scan_bytes(test_marker) == MalwareScanResult(
        clean=False,
        status="detected",
    )
