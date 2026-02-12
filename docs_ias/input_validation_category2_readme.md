## Category 2: Input Validation Review (Backend-Wide)

Scope: `accounts`, `profiles`, `documents`, `loans`, `analytics`, `ai_assistant`, `config`

### Summary Status
1. All inputs validated server-side: `Partial`
1. Parameterized SQL queries: `N/A (MongoDB backend, no SQL layer used)`
1. XSS protection (context-aware escaping): `Partial`
1. File upload validation (type + size): `Implemented (for current document upload path)`
1. API schema validation: `Partial`
1. NoSQL injection protection: `Partial`
1. CSRF tokens enabled: `Partial (middleware enabled; JWT API setup does not strongly enforce CSRF per endpoint)`

---

## Quick Manual Test Cases (Copy/Paste)

Assumptions:
1. API base URL: `http://localhost:8000`
1. You already have a valid customer access token as `ACCESS_TOKEN`
1. Replace placeholders before running

### TC-01: Serializer validation works (positive control) Done
```bash
curl -i -X POST http://localhost:8000/api/auth/signup/ \
  -H "Content-Type: application/json" \
  -d '{"first_name":"","last_name":"User","email":"bad","password":"123","password_confirm":"321"}'
```
Expected:
1. `400` with field-level validation errors.

### TC-02: Ad-hoc endpoint validation inconsistency check 
```bash
curl -i "http://localhost:8000/api/analytics/audit-logs/?page=not_a_number" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```
Expected:
1. If endpoint is fully schema-validated, it should return clean `400`.
1. In current state, behavior may be inconsistent (often server-side exception path), confirming `Partial`.

500 internal server error

### TC-03: File upload type+size validation
```bash
curl -i -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -F "document_type=valid_id" \
  -F "file=@/path/to/invalid.txt;type=text/plain"
```
Expected:
1. `400` with invalid file type message.

Done

### TC-04: XSS pattern blocking on protected field
```bash
curl -i -X POST http://localhost:8000/api/auth/signup/ \
  -H "Content-Type: application/json" \
  -d '{"first_name":"<script>alert(1)</script>","last_name":"User","email":"xss@example.com","password":"StrongPass123!","password_confirm":"StrongPass123!"}'
```
Expected:
1. `400` with validation message indicating malicious input/pattern detection.

DONE

### TC-05: NoSQL pattern blocking on protected field
```bash
curl -i -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"{\"$ne\":null}","password":"anything"}'
```
Expected:
1. `400` validation error from sanitizer/serializer path.

### TC-06: SQL usage sanity check
```bash
rg -n "\\bSELECT\\b|\\bINSERT\\b|\\bUPDATE\\b|\\bDELETE\\b|execute\\(|cursor\\." accounts profiles documents loans analytics ai_assistant config -S
```
Expected:
1. No real SQL execution usage in backend business code.

**TC-06 Result:** ✅ Matches expected

- Hits for `DELETE` are endpoint docstrings/comments (HTTP method names), not SQL statements.
- Hits for `cursor` are Mongo/PyMongo cursor operations (`sort`, `limit`), not SQL DB cursor execution.
- No `execute(...)`, raw SQL queries, or SQL statement usage (`SELECT/INSERT/UPDATE/DELETE` as DB commands) found in business code.

**Conclusion:** No real SQL execution usage was identified; this remains consistent with MongoDB-backed architecture.


### TC-07: CSRF behavior with JWT APIs
```bash
curl -i -X POST http://localhost:8000/api/auth/logout/ \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"refresh":"YOUR_REFRESH_TOKEN"}'
```
Expected:
1. Request is handled by JWT flow (no strict CSRF token requirement in typical bearer usage path).
1. Confirms middleware is enabled but CSRF is not the primary gate for these token-auth APIs.

INFO 2026-02-12 14:36:31,148 Blacklisted access token
INFO 2026-02-12 14:36:31,203 Blacklisted refresh token
INFO 2026-02-12 14:36:31,203 User logged out from IP 127.0.0.1
[12/Feb/2026 14:36:31] "POST /api/auth/logout/ HTTP/1.1" 200 56

---

## 1) All Inputs Validated Server-Side

Status: `Partial`

Why:
1. Many endpoints validate using serializers.
1. Many other endpoints parse `request.data` and query params manually with ad-hoc checks.
1. Some endpoints cast query params directly with `int(...)` and no serializer-backed schema.

Evidence (validated with serializers):
1. `accounts/views/auth_views.py`
1. `accounts/views/password_views.py`
1. `profiles/views/profile_views.py`
1. `documents/views/document_views.py`
1. `loans/views/admin_views.py`
1. `loans/views/officer_views.py` (review flow)

Evidence (manual/ad-hoc parsing):
1. `ai_assistant/views/chat_views.py` (`message`, `limit`, `language`)
1. `loans/views/customer_views.py` (`PreQualifyView`)
1. `accounts/views/admin_views.py` (`AdminLoginView`, loan-officer creation fields)
1. `accounts/views/loan_officer_views.py` (`LoanOfficerLoginView`)
1. `documents/views/document_views.py` (`RequestReuploadView`)
1. `analytics/views/admin_dashboard.py` (query params pagination/filtering)

How to test:
1. Send invalid type values to serializer-backed endpoints (expect 400 with structured errors).
1. Send malformed values to ad-hoc endpoints, e.g. non-numeric `page` in endpoints using `int(...)`.

Correct result criteria:
1. Serializer-backed endpoints consistently return `400` with field errors.
1. Ad-hoc endpoints may return inconsistent errors; this confirms `Partial`, not full implementation.

---

## 2) Parameterized SQL Queries

Status: `N/A (effectively satisfied by architecture)`

Why:
1. Backend uses MongoDB (`PyMongo`), not SQL ORM queries.
1. No raw SQL usage found (`SELECT`, `INSERT`, `cursor.execute`, etc.).

Evidence:
1. `config/settings.py` (`django.db.backends.dummy`, MongoDB via `MongoClient`)
1. Model/query usage in:
1. `accounts/models/*.py`
1. `loans/models/*.py`
1. `documents/models/*.py`
1. `analytics/models/*.py`

How to test:
1. Run search:
```bash
rg -n "\\bSELECT\\b|\\bINSERT\\b|\\bUPDATE\\b|\\bDELETE\\b|execute\\(|cursor\\." accounts profiles documents loans analytics ai_assistant config -S
```

Correct result criteria:
1. No SQL execution statements are present.

---

## 3) XSS Protection (Context-Aware Escaping)

Status: `Partial`

Why:
1. There is server-side sanitization/pattern blocking for some fields (`sanitize_text_input`).
1. It is not applied across all serializers/views.
1. It is pattern-based sanitization, not full context-aware output escaping strategy.

Evidence:
1. `accounts/utils/input_sanitizer.py` (XSS and NoSQL pattern checks)
1. Sanitizer usage in:
1. `accounts/serializers/auth_serializers.py`
1. `documents/serializers/document_serializers.py`
1. Limited/no usage in many other serializers and views:
1. `profiles/serializers/profile_serializers.py`
1. `loans/views/*.py`
1. `ai_assistant/views/chat_views.py`

How to test:
1. Send `<script>alert(1)</script>` in signup fields protected by sanitizer.
1. Send script payload in endpoints not using sanitizer (e.g. some free-text fields in loans/officer flows).

Correct result criteria:
1. Protected endpoints reject malicious payload with validation error.
1. Unprotected endpoints may accept payload as plain text, confirming `Partial`.

---

## 4) File Upload Validation (Type + Size)

Status: `Implemented` (for document upload endpoint)

Why:
1. Upload endpoint checks file presence, MIME type allowlist, and max size.

Evidence:
1. `documents/views/document_views.py` (`DocumentUploadView`)
1. `documents/serializers/document_serializers.py` (`validate_uploaded_file`)
1. `documents/models/document.py` (`ALLOWED_MIME_TYPES`, `MAX_FILE_SIZE`)

How to test:
1. Upload valid file: `image/jpeg` or `application/pdf` under 10MB.
1. Upload invalid MIME type (e.g. `.exe`, `text/plain`).
1. Upload file larger than 10MB.

Correct result criteria:
1. Valid file returns success (`201`).
1. Invalid type/size returns `400` with clear error.

---

## 5) API Schema Validation

Status: `Partial`

Why:
1. Many endpoints use DRF serializers (good schema validation).
1. Many endpoints still use manual extraction from `request.data` or query params without serializer schema.
1. No global OpenAPI/schema enforcement tooling present.

Evidence (schema validation present):
1. `accounts/serializers/*.py`
1. `profiles/serializers/profile_serializers.py`
1. `loans/serializers/loan_serializers.py`
1. `documents/serializers/document_serializers.py`

Evidence (manual parsing still used):
1. `accounts/views/admin_views.py`
1. `accounts/views/loan_officer_views.py`
1. `ai_assistant/views/chat_views.py`
1. `loans/views/customer_views.py` (`PreQualifyView`)
1. `loans/views/officer_views.py` (several flows)

How to test:
1. On serializer-backed endpoints, send wrong field types/missing required fields.
1. On manual endpoints, send malformed types and observe behavior consistency.

Correct result criteria:
1. Serializer-backed endpoints reliably return structured `400` errors.
1. Manual endpoints show inconsistent validation behavior, confirming `Partial`.

---

## 6) NoSQL Injection Protection

Status: `Partial`

Why:
1. Pattern-based NoSQL injection blocking exists in `sanitize_text_input`.
1. Protection is only used in selected serializers.
1. Several query-building paths use direct user input and regex filtering without centralized sanitization.

Evidence:
1. `accounts/utils/input_sanitizer.py` (`NOSQL_INJECTION_PATTERNS`)
1. Protected fields in:
1. `accounts/serializers/auth_serializers.py`
1. `documents/serializers/document_serializers.py`
1. Query-building/manual search examples:
1. `loans/views/officer_views.py`
1. `documents/views/document_views.py`
1. `accounts/views/admin_views.py`

How to test:
1. Send payloads like `{"email":"{\"$ne\":null}"}` to sanitized auth fields.
1. Send search strings containing operator-like patterns in query-param search endpoints.

Correct result criteria:
1. Sanitized endpoints block suspicious patterns with validation errors.
1. Other endpoints may still process input; this confirms `Partial`.

---

## 7) CSRF Tokens Enabled

Status: `Partial`

Why:
1. Django `CsrfViewMiddleware` is enabled globally.
1. API auth uses JWT bearer tokens (`CustomJWTAuthentication`) and not session auth by default.
1. In this API style, CSRF is not consistently an active control on token-based endpoints.

Evidence:
1. `config/settings.py` includes:
1. `django.middleware.csrf.CsrfViewMiddleware`
1. REST auth class set to:
1. `accounts.authentication.CustomJWTAuthentication`
1. No `SessionAuthentication` configured in default DRF auth classes.

How to test:
1. Send POST to a JWT endpoint without CSRF token but with valid bearer token.
1. Send POST without bearer token (should fail auth, but not necessarily as CSRF failure).

Correct result criteria:
1. Middleware is present in settings.
1. Endpoint behavior reflects JWT auth flow, not strict CSRF-token gate across API requests.

---

## Overall Verdict for Category 2

Category 2 is `Partially Implemented`.

Strong points:
1. Serializer-based validation is used in many critical endpoints.
1. File upload type/size checks are implemented.
1. Basic input sanitizer exists for XSS/NoSQL patterns.

Main gaps:
1. Validation is not uniform across all endpoints.
1. No centralized schema enforcement for every request path.
1. XSS/NoSQL protections are not consistently applied across apps.
1. CSRF is enabled in middleware but not a strong practical control for JWT API flows.

---

## Recommended Next Steps (Short)

1. Require serializers for every write endpoint (`POST`, `PUT`, `PATCH`) and structured query-param validation.
1. Add shared validation utilities for pagination/search params to avoid ad-hoc `int(...)` parsing.
1. Expand sanitizer usage (or stricter field validators) beyond auth/document serializers.
1. Review regex search paths and standardize safe escaping and limits.
1. Decide CSRF strategy explicitly for frontend auth mode (cookie/session vs pure bearer).
