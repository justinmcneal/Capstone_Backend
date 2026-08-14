# AI Assistant Production Readiness Review

Last updated: 2026-08-14

Scope: `ai_assistant/`, `/api/ai/`, AI interaction and request persistence,
customer-scoped read-only tools, Groq/Ollama provider boundaries, SSE delivery,
privacy lifecycle integration, PyMongo bootstrap, and AI-related automated tests
and documentation.

## Purpose and Status Definitions

This document is the evidence-based implementation and remediation plan for the
AI Assistant module. It distinguishes an endpoint being present from its data
being private, durable, bounded, observable, accurate, and operationally
supportable.

- **Complete**: implemented and covered by proportionate automated evidence.
- **Partial**: useful behavior exists, but important correctness, security,
  durability, scalability, quality, or operational work remains.
- **Not implemented**: no production implementation was found.
- **Deployment validation**: implemented code that still needs evidence from
  the selected MongoDB, Redis, provider, proxy, monitoring, and recovery
  environment.

The project uses PyMongo directly. Django ORM migrations are not part of the AI
Assistant persistence model. Unit tests using mocks, `mongomock`, or patched
providers do not prove real MongoDB transactions/query plans, shared Redis
behavior, external provider contracts, production SSE delivery, or model
quality.

## Executive Summary

The AI Assistant is **complete through Stage 5 at the application-code and local
automated-test level**. It is not yet ready for production approval because
bilingual quality evaluation and deployment validation remain.

Nine customer endpoints provide English/Tagalog chat, streaming chat, history,
provider status, suggestions, education, and FAQs. Chat can use ten fixed,
read-only, customer-scoped tools. Current AI/data consent is required whenever
personal data or conversation history is processed. No administrator or loan-
officer AI endpoint is registered.

Stages 1 through 5 added encrypted interaction content, keyed search, retention,
legal holds, export/deletion integration, validated request/provider limits,
stable provider failures, bounded provider concurrency, idempotency leases,
transaction-backed exchange persistence, signed cursor history, bounded domain
queries, MongoDB validators, production indexes, atomic tool budgets, durable
metadata-only tool audit, end-to-end correlation, metrics, dashboards, and
alerts. Streaming now fails closed for malformed/truncated providers, closes
upstream work on disconnect, persists content after exactly one escaping pass,
and emits one correlated terminal event. Stage 6 remains open.

Current local baseline:

- Focused Stage 1–5 AI suite: **217 passed** on 2026-08-14.
- Full repository suite: **1,194 passed and 30 opt-in integration tests skipped**
  on 2026-08-14.
- The skipped cases require explicitly approved real MongoDB, Redis, provider,
  proxy, load, privacy, or monitoring environments.
- The review did not read `.env`, inspect customer data, or call a live model.

## Verified Implemented Foundations

### API surface

All routes are registered under `/api/ai/` and require an authenticated
customer:

| Route | Consent boundary | Implementation status |
| --- | --- | --- |
| `POST chat/` | Current data and AI consent | Stage 4 complete; deployment monitoring proof remains |
| `POST chat/stream/` | Current data and AI consent | Stage 5 complete; proxy/load proof remains |
| `GET history/` | Current data and AI consent | Implemented with cursor and bounded offset modes |
| `DELETE history/` | Current data and AI consent | Implemented with legal-hold preservation |
| `GET suggestions/` | Authentication only | Implemented; static English/Tagalog content |
| `GET status/` | Authentication only | Implemented; deployment provider proof pending |
| `GET education/` | Authentication only | Implemented; static content |
| `GET education/<topic>/` | Authentication only | Implemented; static content or 404 |
| `GET faqs/` | Authentication only | Implemented; static content |

### Authentication, consent, and customer scope

- Views use `CustomJWTAuthentication`, `IsAuthenticated`, and the shared
  customer access-control boundary.
- Chat, streaming, history reads, and history deletion require current data and
  AI consent under the active policy version.
- The customer identity is derived from the authenticated session, never from
  model-supplied tool arguments.
- Conversation, interaction, profile, document, loan, payment, notification,
  and dashboard reads are owner-scoped.
- Conversation IDs and idempotency keys are UUIDs; language is restricted to
  `en` or `tl`.

### Chat and provider boundary

- Groq and Ollama are supported behind one validated service boundary.
- Provider, model, URL, rate, byte, character, token, tool, timeout, retry,
  circuit, and concurrency settings fail startup when invalid.
- Only idempotent readiness GET requests receive safe transient retries. Paid
  chat POST requests are not automatically retried.
- Readiness distinguishes configuration, reachability, authentication,
  selected-model availability/degradation, and circuit state.
- Public failures use stable codes and do not expose provider response bodies,
  hosts, credentials, or exception text.
- Streaming calls retain a provider concurrency slot until the response is
  consumed or closed.

### Tool-assisted customer context

The fixed tool registry is read-only. Tool implementations receive the trusted
customer ID from the backend and return bounded profile, document, loan,
repayment, payment, product, readiness, dashboard, or notification information.
Conversation context is limited to the latest six entries and selected source
queries use database-side limits and explicit projections.

| Tool | Current bounded result |
| --- | --- |
| `get_profile_status` | Completion and missing-field state |
| `get_document_status` | Current document types and review state |
| `get_loan_status` | Recent application and lifecycle state |
| `get_repayment_schedule` | Installments, balance, progress, overdue, and penalty state |
| `get_next_payment_due` | Next unpaid installment and due date |
| `get_payment_history` | Up to 20 recent payments |
| `get_loan_products` | Bounded active-product terms and requirements |
| `get_application_readiness` | Profile/document blockers |
| `get_customer_dashboard` | Customer aggregate counts |
| `get_notification_status` | Unread count and five recent notifications |

### Persistence and privacy lifecycle

- `message`, `response`, and legal-hold reason use shared versioned field
  encryption when a field key is configured.
- Keyed blind tokens support search without storing plaintext search content.
- New records receive schema, retention-policy, expiry, hold, and key metadata.
- Retention runs in bounded batches and excludes legal holds.
- Account export decrypts only an allowlisted bounded history shape.
- Final account deletion removes ordinary history and pseudonymizes held
  evidence, with resumable cleanup status/counts on the customer record.
- UUID idempotency leases prevent duplicate provider cost. Completed requests
  replay, active duplicates and mismatched reuse return HTTP 409, and stale or
  partial requests can be inventoried without fabricating content.
- User/assistant pairs use a transaction when supported and repeatable pair
  upserts in offline development.

### Persistence bootstrap

AI interaction/request validators enforce canonical string ownership, UUIDs,
roles, language, dates, numeric metadata, versioned ciphertext, and retention
shape. Bootstrap indexes cover owner/time keyset history, conversation history,
blind search, retention, exchange uniqueness, request uniqueness/recovery, and
request TTL. Legacy owner canonicalization and dry-run-first inventory/backfill
commands are available. Target replica-set transactions and query plans remain
a deployment release condition.

## Implemented Controls and Remaining Release Conditions

### 1. Data governance and account lifecycle

**Status: Complete at code and automated-test level; deployment backfill remains**

Stage 1 implemented encrypted interaction fields, keyed search, versioned
retention, bounded expiry cleanup, legal holds, account export, retryable final
account cleanup, and held-record pseudonymization. Inventory and backfill tools
are dry-run-first and report legacy ownership, plaintext, missing lifecycle
metadata, and stale search-key state.

Before deployment, run the count-only inventory against the target copy, review
the backfill dry run, take an approved backup, apply the backfill, verify field
encryption, and repeat the inventory. Previous keys must remain configured until
ciphertext rotation and blind-token rebuilding are complete.

### 2. Request, provider, and cost boundary

**Status: Complete at code and automated-test level; real-provider approval remains**

Stage 2 validates raw UTF-8 byte size, sanitized characters, history search and
page bounds, the current `100/hour` development chat rate, output tokens, tool
rounds, total tool calls, connect/read timeouts, safe readiness retry, circuit
behavior, and per-process provider concurrency. Bound violations return stable
HTTP 400, 413, 429, or 503 responses.

With current consent, the provider may receive the sanitized question, up to
six recent interactions, the system prompt, fixed tool schemas, and only the
documented tool-result fields. Passwords, OTPs, private/API keys, bank account
numbers, uploaded file bytes, document filenames, and unrelated customer data
are outside the application contract.

Production approval still requires organizational review of the chosen
provider's retention, training, subprocessors, data residency, deletion,
incident, and contractual terms, followed by a synthetic real-provider contract
test. The concurrency limit is per process and still needs multi-worker load
evidence.

### 3. Persistence consistency and query scalability

**Status: Complete at code and automated-test level; real-Mongo proof remains**

Stage 3 added owner-bound idempotency leases, completed-response replay,
transaction-backed exchange writes, repeatable development fallback, signed
keyset history, bounded legacy pagination, bounded conversation context, and
projected domain/tool queries. Validators and indexes enforce the new schemas
and uniqueness/lifecycle contracts. The reconciliation command inventories
stale leases and partial pairs without generating missing AI content.

Before deployment, run inventory/backfill first, install and verify validators
and indexes, then execute the opt-in real-Mongo validator, transaction, unique-
index, and `explain()` tests against an isolated replica-set database.

### 4. Tool safety, durable audit, and observability

**Status: Complete at code and automated-test level; deployment proof remains**

Stage 4 reserves fixed-window minute/hour tool cost with atomic cache operations
before validation/execution, so concurrent and failed attempts cannot bypass the
budget. The aggregate dashboard has an explicit cost/schema and SSE success is
derived from the actual safe-executor result. Redis keys use a keyed customer
fingerprint rather than a raw ID.

Each attempt writes a 90-day-default metadata-only event with a blind customer
subject, request ID, fixed tool name, outcome, duration, and cost. Prompts,
responses, parameters, error text, raw customer IDs, and provider bodies are not
stored. Correlation IDs reach chat, provider, tools, persistence, logs, and
audit. Low-cardinality metrics cover HTTP/provider/tool outcomes and latency,
budget rejections, tokens, active streams, and audit/persistence failures.
Prometheus rules and an importable Grafana dashboard are included.

Deployment must still prove shared Redis atomicity across processes, import the
rules/dashboard, calibrate thresholds, and exercise the real alert route. The
tool audit TTL must be approved against the deployment's security/compliance
retention policy.

### 5. Streaming and response correctness

**Status: Complete at code and automated-test level; proxy/load proof remains**

SSE framing, content type, cache control, anti-buffering headers, token events,
and exactly one terminal event have local coverage. Raw provider tokens are
accumulated and sanitized/escaped once for persistence, while each emitted token
is safely escaped for transport. Ordinary and streaming filtered requests both
persist the same user/assistant pair. Empty, malformed, truncated, and
unterminated streams emit a correlated error and do not persist partial content.
`tool_result.success` reflects the safe executor outcome.

Closing a client response closes the provider generator, which closes the
upstream HTTP response and releases its concurrency permit; an incomplete
request lease is marked failed for an intentional retry. Deployment must still
prove disconnect propagation, incremental delivery, buffering, timeouts,
resource limits, and concurrency behavior through the selected ASGI workers and
reverse proxy/load balancer.

### 6. Model quality and knowledge governance

**Status: Partial; release criteria are not yet defined**

The module has a centralized prompt, English/Tagalog static knowledge, simple
prohibited-content handling, and behavioral tests. It does not yet have a
versioned bilingual evaluation set, approved groundedness/safety thresholds,
adversarial prompt-injection and privacy-leak gates, or a feedback-driven quality
loop. The static knowledge base is manually maintained and is not automatically
checked against current routes, settings, products, policies, or client flows.

RAG is optional, not an automatic requirement. It should be introduced only if
an approved corpus outgrows the current versioned prompt/FAQ approach, because
it adds ingestion, freshness, authorization, privacy, and citation obligations.

### 7. Automated evidence and release environment

**Status: Local evidence complete through Stage 5; deployment evidence pending**

Local suites cover authentication, consent, owner isolation, lifecycle,
encryption/search, idempotency, bounded queries, provider boundary behavior,
context/tool validation, atomic in-process races, metadata audit, monitoring
asset structure, and SSE syntax. They do not prove real MongoDB
transactions/query plans, shared Redis atomicity, real Groq/Ollama behavior,
concurrent load, proxy streaming, provider secret rotation, monitoring/alerts,
backup/restore, incident response, or model quality thresholds.

## Remediation Plan

The stages below follow technical dependencies rather than an arbitrary stage
count.

### Stage 1 — Data governance and account lifecycle

**Status: Complete at code and automated-test level**

- [x] Encrypt AI interaction content and implement keyed search.
- [x] Add versioned retention, bounded cleanup, and legal holds.
- [x] Integrate bounded export and retryable account deletion/pseudonymization.
- [x] Provide dry-run-first inventory/backfill and lifecycle tests.
- [ ] Review and apply inventory/backfill against the selected deployment copy.

### Stage 2 — Request and provider boundary

**Status: Complete at code and automated-test level**

- [x] Validate request, history, rate, token, tool, timeout, and concurrency
  limits.
- [x] Add stable failures, truthful readiness, safe GET retry, circuit breaking,
  and streaming concurrency-slot ownership.
- [x] Document the outbound provider data contract.
- [ ] Approve provider privacy terms and prove the contract with synthetic data.

### Stage 3 — Persistence and query scalability

**Status: Complete at code and automated-test level**

- [x] Add UUID idempotency leases, replay, and conflict semantics.
- [x] Persist exchange pairs transactionally with repeatable development repair.
- [x] Add signed cursor history and bounded/projected context/tool queries.
- [x] Add validators, indexes, canonicalization, and reconciliation tooling.
- [ ] Execute the isolated real-Mongo transaction/index/query-plan gate.

### Stage 4 — Tool safety, audit, and observability

**Status: Complete at code and automated-test level**

- [x] Make shared tool budget accounting atomic and include failed attempts.
- [x] Correct the tool-cost registry and tool-result success contract.
- [x] Propagate one request ID across chat, provider, tools, persistence, logs,
  and durable metadata-only audit events.
- [x] Add Prometheus metrics, dashboards, alerts, and operational guidance.
- [ ] Prove multi-process Redis accounting and monitoring/alert operation in the
  selected deployment topology.

### Stage 5 — Streaming and response correctness

**Status: Complete at code and automated-test level**

- [x] Remove double escaping and align filtered-message persistence policy.
- [x] Test malformed/truncated streams, disconnects, upstream failures, and
  terminal-event semantics.
- [ ] Prove SSE buffering, timeout, and concurrency behavior through the target
  proxy and multi-worker deployment.

### Stage 6 — Model quality and deployment validation

**Status: Pending**

- [ ] Create a versioned English/Tagalog accuracy, groundedness, safety,
  privacy, and adversarial evaluation set with approved thresholds.
- [ ] Run real-provider chat/tool/stream/token and representative load gates
  using synthetic data.
- [ ] Rehearse provider/key failure, backup/restore, incident response, and
  rollback, then run the final deployment smoke gate.

## API and Client Impact Notes

- Existing paths remain stable; the current module has customer endpoints only.
- Chat clients should send a UUID `Idempotency-Key` and reuse it only for a
  retry of the same logical request. A replay sets `replayed=true`; active or
  mismatched reuse returns HTTP 409.
- New history clients should use `pagination=cursor` and treat `next_cursor` as
  opaque. Bounded page-number pagination remains for compatibility.
- Clients must treat assistant output as text, not trusted HTML.
- SSE clients must process `tool_call`, `tool_result`, `token`, `done`, and
  `error`; HTTP 200 alone does not prove a successful completed stream.
- Treat tokens received before a terminal `error` or disconnect as incomplete
  display-only text; the backend does not persist that partial assistant reply.
- Terminal stream errors include `request_id` for support correlation. A
  successful stream has exactly one `done` and no later events.
- Clients should stop loading on `done`, `error`, 401, 403, 409, 429, 503, or
  disconnect and must not automatically duplicate a stream without preserving
  the same idempotency key.
- Consent failures include current-policy metadata for the customer consent-
  renewal flow.

## Review Boundaries

This review verifies repository implementation and local automated behavior. It
does not certify provider legal/privacy terms, model accuracy or financial-
advice suitability, live customer data, production MongoDB/Redis controls,
secret-manager operation, network egress, reverse-proxy streaming, production
load, backup/restore, monitoring routes, staffing, or incident SLAs.

Accounts owns authentication, consent, session/account lifecycle, and shared
field keys. Profiles, Documents, Loans, Notifications, and Analytics own their
source records and business semantics. The AI Assistant may summarize only the
allowlisted customer-scoped data supplied by those modules and must not make
loan decisions or mutate their records.

## Release Gate

The AI Assistant is application-complete through Stage 5 but is **not production
ready yet**. Do not approve a production deployment until Stage 6 is
complete, the target inventory/backfill and real-Mongo/Redis/provider/proxy/load
gates pass, provider privacy terms are approved, bilingual safety/quality meets
versioned thresholds, and the final deployment smoke test succeeds.

The `100/hour` chat throttle is the explicitly accepted development/testing
value. It does not block continued implementation, but the deployed rate must
be reviewed against provider budget, worker capacity, abuse risk, and expected
traffic before release.

## Related Documentation

- `docs/AI_ASSISTANT_TESTING_GUIDE.md` — API behavior, configuration, test
  commands, and real-environment validation matrix
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  consent, account lifecycle, and encryption contracts
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile source and
  customer cleanup behavior
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document source,
  privacy, and lifecycle behavior
- `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` — operational metrics and
  shared audit boundaries
