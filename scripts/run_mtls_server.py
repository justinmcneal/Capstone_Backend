#!/usr/bin/env python3
"""
Windows-compatible mTLS Development Server.

Gunicorn doesn't work on Windows (requires fcntl). This script wraps
Django's WSGI app with Python's built-in ssl module to provide:
  - HTTPS with the server certificate
  - Client certificate verification (mTLS)

Usage:
    python scripts/run_mtls_server.py

The server runs on https://localhost:8443 by default.
"""

import os
import socket
import ssl
import sys
import traceback
from http.server import HTTPServer
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

# Add the project root to Python path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Cert paths
CERTS_DIR = os.path.join(BASE_DIR, "certs")
SERVER_CERT = os.path.join(CERTS_DIR, "server.crt")
SERVER_KEY = os.path.join(CERTS_DIR, "server.key")
CA_CERT = os.path.join(CERTS_DIR, "ca.crt")

HOST = "0.0.0.0"
PORT = 8443


def check_certs():
    """Verify certificate files exist."""
    missing = []
    for path, name in [(SERVER_CERT, "server.crt"), (SERVER_KEY, "server.key"), (CA_CERT, "ca.crt")]:
        if not os.path.isfile(path):
            missing.append(name)
    if missing:
        print(f"\n  ERROR: Missing certificate files: {', '.join(missing)}")
        print(f"  Run first: python scripts/generate_certs.py\n")
        sys.exit(1)


def create_ssl_context():
    """Create SSL context with mTLS (mutual TLS) configuration."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=SERVER_CERT, keyfile=SERVER_KEY)
    ctx.load_verify_locations(cafile=CA_CERT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers('HIGH:!aNULL:!MD5:!RC4')
    return ctx


class MTLSWSGIServer(WSGIServer):
    """
    WSGI server that wraps each accepted connection with SSL individually.

    This avoids wrapping the listener socket (which breaks select() on Windows).
    Instead, SSL is applied per-connection after accept().
    """

    allow_reuse_address = True
    request_queue_size = 10

    def __init__(self, server_address, handler_class, ssl_context):
        super().__init__(server_address, handler_class)
        self.ssl_context = ssl_context

    def get_request(self):
        """Accept a connection, then wrap it with SSL (mTLS handshake)."""
        client_socket, addr = self.socket.accept()
        try:
            ssl_socket = self.ssl_context.wrap_socket(client_socket, server_side=True)
            return ssl_socket, addr
        except ssl.SSLError as e:
            # Client didn't present a valid cert — reject at TLS level
            sys.stderr.write(
                f"  \033[93m[TLS REJECTED]\033[0m {addr[0]}:{addr[1]} — {e.reason or e}\n"
            )
            client_socket.close()
            raise

    def handle_error(self, request, client_address):
        """Suppress noisy SSL errors from rejected clients."""
        exc_type = sys.exc_info()[0]
        if exc_type is ssl.SSLError or exc_type is ConnectionResetError:
            # Already logged in get_request() — don't double-print
            pass
        else:
            sys.stderr.write(
                f"  \033[91m[ERROR]\033[0m {client_address}: {sys.exc_info()[1]}\n"
            )


class MTLSRequestHandler(WSGIRequestHandler):
    """Request handler with client cert extraction and clean logging."""

    def get_environ(self):
        env = super().get_environ()
        env['wsgi.url_scheme'] = 'https'

        # Extract client certificate info from the SSL socket
        try:
            if hasattr(self.request, 'getpeercert'):
                peer_cert = self.request.getpeercert()
                if peer_cert:
                    for field in peer_cert.get('subject', ()):
                        for key, value in field:
                            if key == 'commonName':
                                env['SSL_CLIENT_CN'] = value

                    # PEM-encode the client cert for the middleware
                    peer_cert_der = self.request.getpeercert(binary_form=True)
                    if peer_cert_der:
                        import base64
                        pem = (
                            b"-----BEGIN CERTIFICATE-----\n" +
                            base64.encodebytes(peer_cert_der) +
                            b"-----END CERTIFICATE-----\n"
                        )
                        env['SSL_CLIENT_CERT'] = pem.decode('utf-8')
        except Exception as e:
            sys.stderr.write(f"  Warning: cert extraction failed: {e}\n")

        return env

    def log_message(self, format, *args):
        """Concise colored log output."""
        status = str(args[1]) if len(args) > 1 else ""
        if status.startswith("2"):
            color = "\033[92m"
        elif status.startswith("4"):
            color = "\033[93m"
        elif status.startswith("5"):
            color = "\033[91m"
        else:
            color = "\033[0m"
        reset = "\033[0m"

        cn = "unknown"
        try:
            if hasattr(self.request, 'getpeercert'):
                cert = self.request.getpeercert()
                if cert:
                    for field in cert.get('subject', ()):
                        for key, value in field:
                            if key == 'commonName':
                                cn = value
        except Exception:
            pass

        sys.stderr.write(f"  {color}[{status}]{reset} {args[0]} (client: {cn})\n")
        sys.stderr.flush()


def main():
    check_certs()

    print("=" * 60)
    print("  mTLS Development Server (Windows-compatible)")
    print("=" * 60)

    # Load Django
    print("\n  Loading Django...", flush=True)
    import django
    django.setup()
    from django.core.wsgi import get_wsgi_application
    wsgi_app = get_wsgi_application()
    print("  Django loaded successfully.", flush=True)

    # Create SSL context
    ssl_context = create_ssl_context()

    # Create the mTLS WSGI server (SSL per-connection, not on listener)
    server = MTLSWSGIServer((HOST, PORT), MTLSRequestHandler, ssl_context)
    server.set_app(wsgi_app)

    print(f"\n  Listening on: https://localhost:{PORT}")
    print(f"  Server cert:  {SERVER_CERT}")
    print(f"  CA cert:      {CA_CERT}")
    print(f"  Client cert required: YES (mTLS enforced)")
    print(f"\n  Test with:")
    print(f"    python scripts/demo_mtls.py   (interactive demo)")
    print(f"    python scripts/test_mtls.py   (automated tests)")
    print(f"\n  Press Ctrl+C to stop.\n", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        server.server_close()
        print("\n  Server stopped.")


if __name__ == "__main__":
    main()
