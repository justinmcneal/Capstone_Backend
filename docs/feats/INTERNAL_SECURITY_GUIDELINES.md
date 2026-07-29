# MSME Pathways Internal Security Guidelines

**Status:** Mandatory engineering and operations baseline
**Last reviewed:** 2026-07-21
**System:** Django/DRF + PyMongo/MongoDB API, Django Channels/Daphne, Redis/Channels/Celery, local or S3 document storage, SMTP/FCM notifications, optional Groq/Ollama AI, and feature-gated Web3 blockchain sync.

These guidelines are specific to the implementation in this repository. They complement, and do not replace, an approved incident-response plan, data-retention schedule, vendor register, and legal/privacy review.

## 1. Data classification and handling rules

Treat all customer, officer, and administrator data as confidential. Treat the following as **restricted**: uploaded IDs and PDFs; address/contact data; credentials, JWTs, OTPs, 2FA seeds and backup codes; payment/disbursement references; alternative credit/risk data; AI messages; audit logs/IP addresses; FCM device tokens; MongoDB/Redis exports; S3 objects; and blockchain wallet keys.

- Do not read, print, attach, commit, paste into tickets, or use real restricted data in tests. Use synthetic fixtures.
- Do not log request bodies, tokens, passwords, OTPs, document bytes, AI prompts/responses, or full emails/phone numbers. Keep log fields to event type, pseudonymous/record ID where necessary, outcome, and timestamp.
- Preserve the repository instruction that `.env`, `media/`, `backups/`, `logs/`, `dump.rdb`, uploads, wallet material, Firebase credentials, and cloud credentials are sensitive. Use `.env.example` for configuration discussion.
- Use the smallest data projection and shortest cache TTL that the feature needs. Redis is not a durable source of truth and must not be used for unrestricted sensitive-data caching.

## 2. Identity, authentication, and session controls

The API's supported authentication is custom JWT Bearer authentication with an HttpOnly cookie fallback. Preserve this model unless a security design review approves a replacement.

- Keep access and refresh tokens out of URL parameters, logs, client storage that is unnecessary, analytics, and error messages. Set browser tokens only through `accounts/utils/auth_cookies.py`.
- Keep `AUTH_COOKIE_HTTPONLY=True`, `AUTH_COOKIE_SECURE=True`, and secure session/CSRF cookies in production. For cross-site browser deployment, explicitly set the approved `SameSite=None`, exact CORS origins, and exact CSRF trusted origins; test CSRF-protected writes.
- Preserve custom refresh-token hashing, blacklist checks, expiry indexes, logout revocation, customer single-device handling, and the configured role-specific lifetimes. Do not bypass `CustomJWTAuthentication`.
- Use the existing bcrypt-plus-pepper password routines; never implement password comparison, reversible password storage, or password logging. Keep the pepper and Django secret key in the secret manager/environment only.
- Preserve django-axes lockout, customer cooldown, DRF throttles, OTP expiry/resend/attempt controls, and mandatory 2FA for administrators. Any new privileged role needs 2FA and comparable throttling before release.

## 3. Authorisation and tenant isolation

The roles are customer, loan officer, administrator, and super administrator. Use `accounts/utils/access_control.py` rather than hand-rolled role comparisons.

- Default all API endpoints to authenticated access; make a public endpoint explicit and rate-limited.
- Enforce ownership for customer-owned profiles, documents, loans, payments, notifications, device tokens, and AI history. Return the existing concealed `404` behaviour when revealing the resource would leak its existence.
- For officers, use assignment/customer-scope checks. An officer must not access data belonging to an application assigned to another officer.
- For administrators, require both an admin role and the minimum named permission (`view_logs`, `view_analytics`, `manage_users`, etc.). Reserve super-admin-only operations for exceptional system administration.
- Apply the same permission checks to REST, WebSocket, background-job, export, presigned-upload/download, and blockchain-status paths. Do not trust a client-supplied user ID, role, document path, S3 key, or loan ID.

## 4. Data protection and storage

- Production must fail closed when `FIELD_ENCRYPTION_KEY` is absent or invalid, as `config/settings.py` currently requires. Rotate the Fernet key only with a tested decrypt/re-encrypt migration and recovery plan.
- Extend field-level protection deliberately: model-level Fernet protection is selective, not blanket encryption. Before adding a sensitive field, decide whether it needs field encryption, hashing, tokenisation, or only a protected relationship/ID, and add regression tests.
- Keep MongoDB private to the application network, use encrypted connections, least-privilege database accounts, backups with access controls, and tested restoration procedures. Never use MongoDB's query operators from untrusted input.
- Retain the NoSQL injection middleware and serializer validation. Query by trusted server-side identifiers; escape/validate searches; project only required fields. Do not turn client JSON into a PyMongo filter or update document.
- The current setting is `DOCUMENT_STORAGE_BACKEND = 'local'`. Local uploads must be on encrypted, non-public storage outside source control, with OS-level access control, secure backup, malware/format checks, and a deletion process. Do not expose a directory listing or construct a file path from client input.
- If S3 is enabled, use a private bucket, service-specific least-privilege IAM, SSE-KMS, short presigned URLs, key-prefix ownership validation, CloudTrail/access logging, lifecycle retention rules, and a staging migration test. Do not enable a custom public domain unless a security review proves it cannot expose documents.
- Store FCM device tokens and email-delivery records as restricted data; revoke/deactivate device tokens on logout/device removal and establish a retention period.

## 5. Secure application coding

- Use DRF serializers and existing response helpers for input validation and error handling. Validate allowed document type, MIME type, size (currently 10 MB), and server-detected content; never trust the filename or MIME type supplied by a client.
- Keep uploaded files out of templates and never render them inline without a reviewed content-disposition and content-type policy. Scan/validate PDFs and images before downstream processing.
- Preserve CSRF double-submit validation for unsafe `/api/` requests that use cookies. Bearer-token clients must continue to work without a CSRF cookie.
- Keep `SecurityHeadersMiddleware`, the API-first CSP, frame denial, `nosniff`, referrer policy, and production HTTPS/HSTS configuration. Do not enable `CORS_ALLOW_ALL_ORIGINS` in production.
- Do not return stack traces, provider errors, internal notes, raw audit details, or database exception text to users. Avoid error messages that distinguish whether an email/account exists.
- Keep background-task payloads minimal and JSON serialisable. Tasks that change loan status, send communications, access documents, or sync the blockchain must re-check authorisation/state server-side and be idempotent.

## 6. AI, notifications, and blockchain

- AI endpoints require customer authentication and `ai_consent`. Preserve the consent check for chat, streaming, and history endpoints; do not treat general account consent as permission to send data to an LLM.
- Keep the AI context builder's exclusion list for direct contact and secret fields. Tool calls must remain read-only and scoped to the authenticated customer; do not add admin/officer cross-customer tools without a separate security review.
- Limit history supplied to the model (the implementation currently uses the most recent six entries), avoid sending raw documents or unneeded PII, and do not put sensitive values in prompts, tool schemas, or logs. Review the provider, model, endpoint, contractual terms, retention, and region before changing `LLM_PROVIDER`.
- Use SMTP with TLS and minimal email content. Do not place full IDs, payment references, authentication secrets, or sensitive rejection/medical/financial details in email subject lines. Respect stored notification preferences.
- Authenticate WebSocket connections and authorise each per-user notification group. A notification group name must be derived from the authenticated identity, not a request parameter.
- Keep `BLOCKCHAIN_ENABLED=False` until the transaction design, deployed addresses, service wallet protection, chain/network choice, and public-data consequences are approved. Write only hashed/minimised data on-chain; a hash can still be personal data when linkable. Never store a private key in code, logs, backups, or a client app.

## 7. Secrets, deployment, and operations

- Keep `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, MongoDB URI, SMTP credentials, AWS credentials, Groq key, Firebase credentials, and blockchain wallet key in the deployment secret store/environment. Rotate on suspected exposure and remove obsolete credentials.
- Use `DEBUG=False`, an explicit `ALLOWED_HOSTS` allowlist, HTTPS redirect, HSTS, secure cookies, strict CORS/CSRF origin lists, and non-public MongoDB/Redis endpoints in production. Perform a production settings review for every release.
- Pin or constrain dependencies deliberately, run dependency/security scanning in CI, and promptly assess Django, PyMongo, boto3, Web3, Channels, Redis, cryptography, and Firebase advisories.
- Do not perform database migrations/initialisation, storage migration, backup/restore, deployment, Celery operations, or blockchain transactions without approved change control and a rollback plan.
- Monitor authentication failures/lockouts, privilege changes, document access failures, S3 403/404 trends, queue failures, unexpected blockchain attempts, and suspicious audit patterns without recording secret material.
- For a suspected incident: contain access, preserve minimal evidence, rotate affected credentials, assess data scope, notify the designated incident/privacy owners, and document remediation. Do not delete logs or alter evidence to hide an event.

## 8. Required verification before release

- Run `pytest -q` and relevant endpoint tests using synthetic data.
- Test customer ownership, officer assignment boundaries, admin permission boundaries, disabled-account access, token revocation, cookie/CSRF flows, lockout/OTP/2FA, document download/delete/re-upload, AI consent withdrawal, and WebSocket user isolation.
- Test production settings with no secrets printed: missing encryption key must fail, HTTPS/cookie flags must be enabled, CORS/CSRF allowlists must be exact, and S3 mode (if used) must be private and presigned.
- Review `git status --short`, tracked-file changes, and secret scanning before merge. A security-sensitive code change requires a second reviewer.

## 9. Current gaps and required remediation

| Priority | Finding and evidence | Required action |
| --- | --- | --- |
| Critical | `dump.rdb`, `media/`, `backups/`, and `logs/` are tracked by Git. These locations are expressly classified as sensitive in `AGENTS.md`; they may contain Redis, upload, backup, or authentication information. Their contents were not inspected for this review. | Treat as a potential data/secret exposure. Stop further commits, perform an approved data/secret incident assessment, remove sensitive artifacts and, where necessary, rewrite repository history under change control; rotate any exposed secrets. |
| High | `config/settings.py` hardcodes local document storage, while `docs/SYSTEM_GAPS_AND_REMAINING_WORK.md` describes S3 as enabled by environment. This is an implementation/documentation conflict. | Make storage selection configuration-driven, validate S3 settings at startup, enable private/KMS-protected S3 only after staging tests, and update all docs/policy to the verified runtime state. |
| High | Field encryption is selective. Many sensitive records (for example AI interactions, audit and consent IP data, notifications/device tokens, alternative-credit data, payment data, and local files) are outside the model encryption lists. | Complete a data inventory and threat model; encrypt or minimise each restricted field, use provider-side encryption and access controls, and test key-loss/rotation handling. |
| High | There is no comprehensive retention, deletion, backup-purge, legal-hold, or subject-request workflow. Only token collections visibly have expiry indexes. | Adopt retention periods by collection/provider; implement scheduled deletion and backup expiry; define account/document/AI deletion semantics and evidence of completion. |
| High | The policy/controller contact, privacy-request workflow, vendor/region register, processor agreements, and cross-border transfer assessment are absent from the repository. Hosted Groq, SMTP, FCM, MongoDB, S3, and blockchain can process or receive data. | Assign data owners; maintain an approved vendor and transfer register; publish a verified privacy contact and request process before public launch. |
| Medium | `CORS_ALLOW_ALL_ORIGINS` can be enabled by environment despite credentialed CORS. | Remove or hard-block this option in production and add a deployment test that rejects wildcard credentialed origins. |
| Medium | The policy/implementation does not establish an explicit retention or revocation lifecycle for FCM tokens, notification records, and unencrypted backup-code representation. | Define lifecycle and cryptographic handling, implement deletion/deactivation, and add tests. |
| Medium | Existing deployment documentation contains historical contradictions about local versus S3 storage and may be read as an assurance of controls not active in runtime. | Make `docs/DEPLOYMENT_AND_OPERATIONS_GUIDE.md`, `docs/PRODUCTION_S3.md`, `docs/SYSTEM_GAPS_AND_REMAINING_WORK.md`, and deployment settings agree; label future work clearly. |

## 10. Source basis

Reviewed sources include `docs/AUTH_ACCESS_SECURITY_GUIDE.md`, `docs/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md`, `docs/DEPLOYMENT_AND_OPERATIONS_GUIDE.md`, `docs/PRODUCTION_S3.md`, `docs/AI_ASSISTANT_TESTING_GUIDE.md`, `docs/DOCUMENTS_AND_CNN_GUIDE.md`, `docs/BLOCKCHAIN_SYSTEM_DOCUMENTATION.md`, `config/settings.py`, `config/middleware.py`, `config/field_encryption.py`, and the domain code under `accounts/`, `profiles/`, `loans/`, `documents/`, `ai_assistant/`, `notifications/`, and `analytics/`.
