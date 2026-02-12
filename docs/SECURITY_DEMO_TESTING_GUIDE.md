# Security Demo Testing Guide

This guide validates security controls end-to-end using the real backend API and `scripts/security_demo_cli.py`.

## 1. Prerequisites

1. Set environment values in `.env`:
   - `MONGODB_URI`
   - `MONGODB_NAME`
   - `DOCUMENT_ENCRYPTION_KEY` (required)
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Start backend:
```bash
python manage.py runserver
```

## 2. Run Demo Harness

```bash
python scripts/security_demo_cli.py
```

Use the menu in this order for full proof coverage:

1. `Customer Signup`
2. `Verify Signup OTP (optional but recommended for new users)`
3. `Customer Login`
4. `Upload Document (valid_id)`
5. `View/Preview Document`
6. `Run Input Sanitization Test (XSS + NoSQL)`
7. `Run Unauthorized Access Test`
8. `Export Security Logs to JSON`

## 3. Sample Inputs

### Normal Inputs

- Signup:
  - `first_name`: `Alice`
  - `last_name`: `Rivera`
  - `email`: `alice.demo@example.com`
  - `password`: `SecurePass123!`
- Login:
  - `email`: `alice.demo@example.com`
  - `password`: `SecurePass123!`
- Upload:
  - file: real `.jpg`, `.png`, or `.pdf`
  - `document_type`: fixed to `valid_id` in harness
  - `description`: `Government ID upload`

### Malicious Inputs

- XSS payload (signup):
  - `first_name`: `<script>alert('xss')</script>`
- NoSQL payload (signup):
  - `last_name`: `{"$ne":""}`

## 4. Expected Behavior

### Signup/Login (Hashing)

- Signup succeeds for valid input.
- Login succeeds only when password is correct.
- Backend logs include:
  - `password_hashing_triggered`
  - `password_hash_verification`

### Input Sanitization

- XSS payload is rejected with validation error.
- NoSQL-style payload is blocked/rejected.
- Backend logs include:
  - `input_sanitization_blocked`

### Secure Upload Encryption at Rest

- Upload succeeds for allowed file types.
- File is encrypted with `AES-256-GCM` before being persisted.
- Backend logs include:
  - `document_upload_request_received`
  - `document_authorization_check`
  - `document_encryption_triggered`
  - `document_upload_completed`

### Decryption on Authorized Access

- Owner (or authorized officer/admin) can preview.
- Backend decrypts only at read time.
- Optional download is available via `?download=true` on preview endpoint.
- Backend logs include:
  - `document_view_request_received`
  - `document_authorization_check` (allowed/blocked)
  - `document_decryption_triggered`
  - `document_preview_streamed`

### Unauthorized Access Blocking

- Non-owner access attempt is denied (`403` or `404`).
- Backend logs include:
  - `document_access_blocked`

## 5. Evidence File

The harness exports a presentation-ready JSON file:

- Path pattern: `logs/security_demo_evidence_YYYYMMDD_HHMMSS.json`
- Source log stream: `logs/security_events.jsonl`

Security logging rule: raw passwords, OTPs, tokens, encryption keys, and file bytes are never written to this evidence log.

## 6. Web Preview Verification

Loan Officer UI now uses authenticated preview streaming instead of direct file links:

1. Open `Capstone-Web` and login as a loan officer.
2. Go to `Documents` or open an application detail page.
3. Click the eye icon on any uploaded document.
4. Expected behavior:
   - Backend endpoint: `/api/documents/<document_id>/preview/`
   - Authorization is validated server-side.
   - File is decrypted only for the request and streamed inline for browser preview.
