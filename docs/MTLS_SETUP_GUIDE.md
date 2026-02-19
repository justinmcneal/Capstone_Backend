# mTLS (Mutual TLS) + Certificate Pinning — Setup Guide

This guide explains how to enable **mutual TLS authentication** and **certificate pinning** for the MSME Pathways application.

## What is mTLS?

Standard TLS (HTTPS) only verifies the **server's** identity. Mutual TLS (mTLS) goes further — **both** the server and client must present valid certificates signed by a trusted Certificate Authority (CA). This prevents unauthorized clients from connecting to your API.

## What is Certificate Pinning?

Certificate pinning ensures the frontend only communicates with a server presenting a **specific, pre-known certificate**. Even if an attacker somehow obtains a valid TLS certificate, the pinned hash won't match, blocking the connection.

---

## Prerequisites

- Python 3.8+
- `cryptography` Python package: `pip install cryptography>=41.0.0`
- Node.js 18+ (for the frontend)

---

## Step 1: Generate Certificates

From the `Capstone_Backend` directory:

```bash
python scripts/generate_certs.py
```

This creates 6 files in `certs/`:

| File | Purpose |
|------|---------|
| `ca.key` | Root CA private key |
| `ca.crt` | Root CA certificate |
| `server.key` | Server private key |
| `server.crt` | Server certificate (SAN: localhost, 127.0.0.1) |
| `client.key` | Client private key |
| `client.crt` | Client certificate (CN: capstone-web-client) |

The script also prints the **SPKI SHA-256 pin hash** — copy this for Step 3.

> ⚠️ **Never commit** the `certs/` directory to version control. It's already in `.gitignore`.

---

## Step 2: Configure the Backend

### 2a. Environment Variables

Add to your `.env` file:

```env
MTLS_ENABLED=True
MTLS_CA_CERT_PATH=certs/ca.crt
MTLS_SERVER_CERT_PATH=certs/server.crt
```

### 2b. Start with mTLS

Instead of the regular server, use the mTLS Gunicorn profile:

```bash
# Regular (no mTLS)
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2

# With mTLS (port 8443)
gunicorn config.wsgi:application \
  --bind 0.0.0.0:8443 \
  --workers 2 \
  --certfile=certs/server.crt \
  --keyfile=certs/server.key \
  --ca-certs=certs/ca.crt \
  --cert-reqs=2
```

The `--cert-reqs=2` flag means **CERT_REQUIRED** — every client must present a valid certificate signed by the CA.

### 2c. Verify with curl

```bash
# This should work (client cert provided):
curl --cert certs/client.crt --key certs/client.key \
     --cacert certs/ca.crt \
     https://localhost:8443/api/health/

# This should FAIL (no client cert):
curl --cacert certs/ca.crt https://localhost:8443/api/health/
```

---

## Step 3: Configure the Frontend

### 3a. Environment Variables

Add to `Capstone-Web/.env`:

```env
VITE_API_URL=https://localhost:8443
VITE_SERVER_CERT_PIN=sha256/PASTE_THE_HASH_FROM_STEP_1
```

### 3b. How It Works

1. **Vite dev server** automatically detects certs in `../Capstone_Backend/certs/` and starts with HTTPS + client certificate
2. **Certificate pinning** validates the server's SPKI hash on the first API request
3. If the pin doesn't match, **all API requests are blocked** with a `CERTIFICATE_PIN_MISMATCH` error

### 3c. Start the Frontend

```bash
cd Capstone-Web
npm run dev
```

If certs exist, Vite will serve on `https://localhost:5173`. Open the browser console — you should see:
```
[Certificate Pinning] ✓ Server certificate pin verified successfully.
```

---

## Step 4: Test the mTLS Handshake

Run the verification script:

```bash
cd Capstone_Backend
python scripts/test_mtls.py
```

---

## Architecture Overview

```
┌──────────────────┐          mTLS           ┌──────────────────┐
│                  │◄═══════════════════════►│                  │
│  React Frontend  │  Client Cert + Server   │  Django Backend  │
│  (Vite + HTTPS)  │  Cert verified both     │  (Gunicorn TLS)  │
│                  │  directions              │                  │
└────────┬─────────┘                         └────────┬─────────┘
         │                                            │
         │  Pin Validation                            │  mTLS Middleware
         │  (SPKI SHA-256)                            │  (config/mtls.py)
         │                                            │
    ┌────▼─────────┐                         ┌────────▼─────────┐
    │ certificat-  │                         │  Trusted CA      │
    │ ePinning.ts  │                         │  (ca.crt)        │
    └──────────────┘                         └──────────────────┘
```

### Middleware Chain

```
Request → SecurityHeaders → MutualTLS → Session → CORS → CSRF → Auth → View
                              ↓
                    Verify client cert
                    against CA cert
                              ↓
                    403 if invalid/missing
```

---

## Production Notes

> [!IMPORTANT]
> In production (e.g., Railway), TLS termination is typically handled by the reverse proxy/load balancer, not Gunicorn directly. In that case:
> 
> 1. Configure the reverse proxy (Nginx, Cloudflare, etc.) to require client certs
> 2. The proxy passes the client cert via `X-SSL-Client-Cert` header
> 3. The Django `MutualTLSMiddleware` reads from this header automatically
> 4. Set `MTLS_ENABLED=True` in production environment

---

## Certificate Rotation

When certificates expire (default: 1 year for server/client, 10 years for CA):

1. Re-run `python scripts/generate_certs.py`
2. Update `VITE_SERVER_CERT_PIN` in the frontend `.env` with the new hash
3. Restart both backend and frontend
4. For zero-downtime rotation, configure **two pins** in `VITE_SERVER_CERT_PIN` (comma-separated): old and new

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `SSL: CERTIFICATE_VERIFY_FAILED` | Add `--cacert certs/ca.crt` to curl, or trust the CA in your OS |
| `CERTIFICATE_PIN_MISMATCH` in browser | Re-generate certs and update `VITE_SERVER_CERT_PIN` |
| `Client certificate required` (403) | Ensure Vite is loading the client cert from `../Capstone_Backend/certs/` |
| Backend starts but no mTLS | Check `MTLS_ENABLED=True` in `.env` |
| Vite starts with HTTP instead of HTTPS | Ensure cert files exist at `../Capstone_Backend/certs/` |
