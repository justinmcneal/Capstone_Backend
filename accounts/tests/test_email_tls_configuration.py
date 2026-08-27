import os

import certifi


def test_email_tls_has_a_default_ca_bundle():
    """The SMTP backend can verify public TLS certificates by default."""
    assert os.environ.get("SSL_CERT_FILE") == certifi.where()
