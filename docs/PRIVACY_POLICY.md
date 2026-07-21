# MSME Pathways Privacy Policy (Implementation-Aligned Draft)

**Status:** Draft for product-owner and privacy/legal approval
**Last reviewed against backend source:** 2026-07-21
**Applies to:** MSME Pathways customer mobile and web experiences, staff portals, and the Django API in this repository.

This policy describes the data processing implemented or supported by the current backend. It must be published only after the organisation supplies the controller name, business address, privacy contact, applicable retention periods, and the approved list of production providers. Those details are deliberately not invented here.

## 1. What we collect

We collect data that users submit or that is generated while they use the service.

| Category | Examples implemented in the backend | Why it is used |
| --- | --- | --- |
| Account and contact data | Name, email, phone number, language, role, and, for staff, employee ID and department | Create and secure accounts, communicate with users, and distinguish customers, loan officers, and administrators. |
| Identity, profile, and business data | Date of birth, gender, civil status, nationality, address, emergency contact, business details, registration number, income/expense information, and employee/dependent information | Complete a customer profile, assess application readiness, and support loan review. |
| Alternative credit data | Education, employment, housing, existing-credit, bank/e-wallet and utility-payment indicators, community information, and calculated risk category/score | Support pre-qualification and the application's AI-assisted credit/risk features. |
| Loan and payment data | Application, requested/approved/disbursed amount, term, purpose, decision and reviewer notes, repayment schedule, payment method, reference, amount, penalties, and disbursement reference | Process, administer, and audit loan applications and repayments. |
| Uploaded documents | Images or PDFs such as valid ID, selfie with ID, proof of address, business permit/photo, income proof, and supporting files; their metadata, review status, reviewer notes, and AI-analysis result | Verify identity, eligibility, documentation quality, and loan requirements. |
| Authentication and security data | Password hash, verification/reset OTP state, 2FA state and secret, backup codes, token hashes/revocation records, failed-login/lockout state, cookies, and device tokens | Authenticate users, prevent abuse, manage sessions, send push notifications, and protect accounts. We do not store a user's raw password. |
| Usage, audit, and consent data | IP address, timestamp, action, account email/role, related resource IDs, consent choices/version, notification history, and device platform | Maintain security, investigate events, provide operational analytics, document consent, and deliver notifications. |
| AI conversation data | Chat prompts, responses, conversation ID, language, model/provider, response time, token count, and limited account context requested by the assistant | Provide the optional loan-support chat feature and its conversation history. |
| Blockchain audit metadata (when enabled) | Transaction hash, block number, gas metadata, loan ID/action, and hashes of selected identifiers or free-text values | Provide an integrity/audit trail for loan and consent events. Blockchain syncing is disabled unless deployment configuration enables it. |

## 2. How we use data

We use the data above to:

- register, verify, authenticate, and secure accounts;
- create profiles, receive documents, assess loan readiness, process applications, administer disbursements and repayments, and allow authorised staff review;
- notify users about account, document, application, disbursement, and payment events by email, in-app notifications, WebSocket delivery, and, where a device token is registered, push notifications;
- maintain audit logs, detect suspicious activity, enforce rate limits and account lockouts, and improve reliability;
- provide the optional AI chat service after AI consent; and
- meet applicable legal, regulatory, dispute-resolution, fraud-prevention, and recordkeeping obligations once those obligations and retention periods are formally defined.

The application implements separate `data_consent` and `ai_consent` records. AI chat and history access are blocked without AI consent. Users can view and update consent through `/api/auth/consent/`. Notification preferences are separately stored for loan updates, payment reminders, and promotions.

## 3. Automated and AI-assisted processing

The service uses stored profile, business, alternative-credit, document, loan, and repayment information to calculate or present readiness, qualification, and risk-related information. The AI assistant can receive the user's prompt, up to six recent conversation entries, and limited, customer-scoped summaries or read-only tool results such as profile completion, document status, loan/payment status, repayment details, dashboard totals, and notification status.

The implementation excludes direct contact fields (including email, phone, mobile number, address, emergency-contact details, password, and authentication secrets) from the AI context builder. It does not make the AI result a final lending decision; authorised staff make application decisions. Users should not put passwords, OTPs, or other unnecessary sensitive information in chat messages.

AI processing requires separate opt-in (`ai_consent`). With the default `groq` provider, requests are sent to Groq's hosted API; a deployment can instead use an Ollama endpoint. The organisation must maintain the applicable processor agreement, provider privacy terms, data-location assessment, and approved model list before enabling a hosted provider in production.

## 4. When we share data

We do not sell personal data. We disclose or transmit it only as needed to operate the implementation:

- **Authorised organisation personnel:** loan officers can access customers in their assigned or permitted review scope; administrators have role and permission-controlled access to user management, analytics, and logs.
- **Infrastructure and storage providers:** MongoDB is the application database. Redis is used for Channels, Celery, and optional caching. The current runtime setting stores uploads on the backend's local media filesystem; the code also supports private Amazon S3-compatible storage when enabled and configured.
- **Communication providers:** configured SMTP infrastructure receives recipient email, message content, and necessary delivery data. Registered Firebase Cloud Messaging device tokens are used for push delivery when that capability is configured.
- **AI provider:** Groq or the deployment's Ollama endpoint receives the AI request content described above only when the AI feature is used with consent.
- **Blockchain network:** when blockchain sync is enabled, transaction and hashed audit metadata are written to the configured chain. Public-chain records can be publicly visible and are generally immutable. The backend, not the client apps, submits these transactions.
- **Authorities or other recipients:** only where required by law, to protect rights and safety, respond to a valid legal process, or in connection with an approved organisational transaction.

The production deployment inventory must identify the actual provider, hosting region, and cross-border transfer safeguards for MongoDB, SMTP, Redis, AI, S3, FCM, and any blockchain network.

## 5. Storage, safeguards, and retention

The backend uses MongoDB through PyMongo for application records. User uploads are currently configured for local storage under the backend media directory; S3 storage uses private-object defaults and time-limited presigned URLs when it is actually enabled. Redis may temporarily hold cache entries, Channels messages, and Celery task data.

Safeguards implemented in the backend include JWT authentication, HttpOnly secure cookies in production, CSRF checks for cookie-based unsafe API requests, HTTPS/HSTS production settings, role- and assignment-based access control, 2FA, login throttling/lockout, password hashing with bcrypt and a pepper, token hashing/expiry or revocation, selected-field Fernet encryption, security headers, and a NoSQL-operator payload guard.

These are safeguards, not a promise that every item is encrypted at the application-field level. The current field-encryption model protects selected fields only, and production configuration is necessary for HTTPS, secure cookies, encrypted storage, access restrictions, and provider controls to take effect.

The code has expiry indexes for refresh-token and blacklisted-token records. It does **not** define a comprehensive retention schedule or automated expiry for accounts, loan records, uploaded documents, AI conversations, audit logs, notifications, device tokens, or consent records. We will retain those records only for documented business, security, legal, and regulatory periods once adopted; the organisation must publish those periods before this policy is final.

## 6. Choices and requests

Users can update profile data, notification preferences, and consent through authenticated application functions. AI consent can be withdrawn; this stops access to AI endpoints, but does not by itself delete historical chat records. The API includes customer-scoped AI-history deletion support, and document removal is limited by application/document status and authorisation rules.

Subject to applicable law and recordkeeping requirements, users may request access, correction, deletion, restriction/objection, portability where applicable, or information about disclosures. Until the product owner supplies a working privacy contact and verification workflow, send requests through the application's official support channel. The final public policy must replace this sentence with the controller name, contact method, response timeframe, identity-verification process, and regulator/escalation information.

## 7. Security incidents and policy changes

We will investigate suspected unauthorised access, preserve relevant audit evidence, contain affected systems, and provide notices required by applicable law and contractual obligations. We may revise this policy when data practices or providers change; material changes must be versioned in the consent flow before relying on new consent.

## 8. Important implementation limitations requiring remediation

This policy is intentionally transparent about the following unresolved items:

1. No approved data-retention/deletion schedule, controller identity, privacy contact, request workflow, or production-provider/region inventory is present in the repository.
2. `config/settings.py` currently hardcodes local document storage even though S3 documentation describes a production path; public policy must not claim S3/KMS protection until the runtime selector and deployment controls are verified.
3. Application-level encryption is selective. Sensitive categories including AI conversations, audit/consent IP data, notifications, device tokens, much profile/financial data, and local uploaded files are not comprehensively covered by the model-level encryption lists.
4. The repository tracks `dump.rdb`, `media/`, `backups/`, and `logs/`. These locations can contain personal or operational data and must be removed from source control through an approved incident/remediation process, with history review and credential/data exposure assessment.
5. Hosted AI, email, push, database, storage, and blockchain transfers require documented processor terms, regions, access controls, and transfer assessments before production use.

## 9. Implementation references

This draft is based on `docs/AUTH_ACCESS_SECURITY_GUIDE.md`, `docs/DOCUMENTS_AND_CNN_GUIDE.md`, `docs/AI_ASSISTANT_TESTING_GUIDE.md`, `docs/DEPLOYMENT_AND_OPERATIONS_GUIDE.md`, `docs/BLOCKCHAIN_SYSTEM_DOCUMENTATION.md`, and the following implementation areas: `config/settings.py`, `config/middleware.py`, `accounts/`, `profiles/`, `loans/`, `documents/`, `ai_assistant/`, `notifications/`, and `analytics/`.
