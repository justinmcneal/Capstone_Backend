# System Architecture Gap Analysis

## A. Executive summary

**Significantly outdated; confidence high for source structure, medium for runtime configuration.** The code is one modular Django/DRF ASGI application using PyMongo, not independently deployed services behind an implemented API gateway. Runtime secrets/configuration were not read; enabled provider status is **UNVERIFIED**.

## B. Current assessment

| Original component | Verdict | Evidence / correction |
|---|---|---|
| Mobile, Loan Officer web, Admin web | Valid | Flutter customer app; React has role-separated officer/admin routes. Kiosk is **UNVERIFIED**. |
| API Gateway | Incorrect | `config/urls.py` is Django route dispatch. Rename Django REST/ASGI API. |
| Auth, profile, documents, notifications | Valid but incomplete | `accounts`, `profiles`, `documents`, `notifications` apps add 2FA, consent, lifecycle, WebSockets, FCM/email, retention. |
| Loan Recommendation | Incorrect name | `loans` implements product, qualification, applications, assignment, disbursement, repayments, payments. |
| AI labels | Partially valid | Groq/Ollama LLM; rule-based risk score; conditional MobileNetV2 CNN. |
| Separate databases | Incorrect | One physical MongoDB database with logical collections; document bytes are separate object/local storage. |
| BPI | Unsupported | No BPI client, URL, SDK, adapter, or route exists. Remove. |

## C–F. Components and connections

| Finding | Severity | Evidence | Required architecture change |
|---|---|---|---|
| No BPI implementation | CRITICAL | Repository search | Remove `Loan → BPI`. |
| Modules shown as services/gateway | HIGH | `config/urls.py`, shared PyMongo models | Show modular Django backend and API edge, not microservices/gateway. |
| Redis/Celery/Channels omitted | HIGH | `config/settings.py`, `config/celery.py`, `notifications/consumer.py` | Add Redis, Celery workers/beat, authenticated WebSockets. |
| Storage/FCM/email/blockchain omitted | HIGH | `documents/storage/backends.py`, notification services, `loans/blockchain/` | Add conditional S3-compatible storage, FCM, SMTP, EVM RPC, CoinGecko, WalletConnect. |
| Data labels are physical DBs | HIGH | model `collection_name`s, Mongo-only settings | Show MongoDB logical collections, not separate DB servers. |
| NLP → profiler and assistant → analytics | MEDIUM | No matching pipeline | Remove; assistant safely reads selected domain data, analytics owns audit/reporting. |
| Alternative Data Profiler | MEDIUM | `profiles/services/risk_scoring.py` | Rename Alternative Data & informational rule-based risk scoring. |
| Document CNN | MEDIUM | `documents/services/analyzer.py` | Show quality checks plus optional approved CNN artifact. |
| Mobile notification parser expects `payload`; server emits `data` | HIGH | mobile `notification_streaming_service.dart`; `notifications/consumer.py` | Connection exists but contract is likely non-functional. |
| Mobile FCM registration omits `/api` | HIGH | mobile `push_notification_service.dart`; backend URLs | Token registration is likely non-functional under shown base URL convention. |

Validated original arrows: client → API, API → accounts/profiles/loans/documents/notifications/AI, profile → alternative data, documents → analysis (conditional), and analytics → audit logs are supported. Admin accesses logs through API, not directly. Loan → product catalog is supported but loans additionally own applications/payments/schedules. NLP → profiler, assistant → analytics, and loan → BPI are unsupported.

## G–I. Backend and client alignment

| Area | Actual flow |
|---|---|
| Backend | `accounts`, `profiles`, `loans`, `documents`, `ai_assistant`, `notifications`, `analytics`, and optional `loans.blockchain`; exposed by `/api/` in `config/urls.py`. |
| Mobile | Bearer JWT/refresh; `/api/auth`, profile, loans, documents, AI/SSE, customer analytics, notifications, and ETH wallet payment APIs. Hive/secure storage are client-local. |
| Officer web | Cookie JWT/CSRF; officer dashboard, applications/reviews, documents, profiles, payments/schedules, audit logs, notifications. |
| Admin web | Cookie JWT/CSRF; management, consent/audit, dashboard, products/workload/assignments, blockchain transaction view, notifications. |

Officer and admin remain distinct client types because their routes, permissions, and backend APIs differ (`Capstone-Web/src/app/router.tsx`).

## J. Data architecture

- **MongoDB:** identities/security; profiles/alternative data; products/applications/payments/schedules; documents; notifications/device tokens; AI interactions; audit logs; blockchain state.
- **Object/local storage:** document bytes; local development or private S3-compatible storage in production.
- **Redis:** Channels layer, Celery broker/result, cache and shared production security state.

## K. External integrations

| Integration | Status |
|---|---|
| Groq or Ollama | Implemented configurable LLM boundary; live selection **UNVERIFIED**. |
| Firebase FCM, SMTP, S3-compatible storage | Implemented conditional integrations; credentials/configuration **UNVERIFIED**. |
| EVM RPC/contracts, CoinGecko, WalletConnect/Reown | Implemented conditional blockchain/wallet flow; backend blockchain default is disabled. |
| BPI | Exclude: no implementation evidence. |

## L. AI architecture

- **Assistant:** consent-gated English/Tagalog chat, SSE, history, controlled tools, Groq/Ollama (`ai_assistant/`).
- **Risk score:** deterministic weighted, explainable, informational-only alternative-data score—not AI approval (`profiles/services/risk_scoring.py`).
- **Document analysis:** image quality checks; classifier only when an approved MobileNetV2 artifact is present; queued through Celery with consent (`documents/services/{analysis,analyzer,cnn_model}.py`).
- **Loan qualification:** consent-aware optional LLM call constrained by deterministic product requirements (`loans/services/qualification.py`).
- **Analytics:** dashboards/audit reporting, not an AI insight engine (`analytics/`).
