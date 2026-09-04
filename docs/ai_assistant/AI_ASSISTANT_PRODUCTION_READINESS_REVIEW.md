# AI Assistant Module Documentation and Status

Last updated: 2026-08-28

## Overview

The AI Assistant is the authenticated, customer-facing conversational service
for MSME Pathways. It provides English and Tagalog chat, server-sent event
(SSE) streaming, customer-owned conversation history, service status,
conversation suggestions, loan education, and FAQs under `/api/ai/`.

The assistant can retrieve a limited set of the authenticated customer's
profile, document, loan, repayment, payment, product, dashboard, and
notification information through ten fixed read-only tools. It cannot approve
loans, change application state, make payments, alter documents, or mutate data
owned by another domain module. There are no loan-officer or administrator AI
endpoints.

This project uses PyMongo directly for AI persistence. Django ORM migrations
are not part of this module's database lifecycle; MongoDB collections,
validators, and indexes are managed through the project's bootstrap and AI
operational tooling.

## Current Status

**Module implementation status: Complete for the approved controlled-assistant
baseline**

**Production deployment status: Ready for production-environment validation**

The application controls, APIs, persistence, privacy lifecycle, safety
boundaries, controlled bilingual quality baseline, automated tests, and
operational tooling are implemented. Production approval remains conditional
on validating those controls in the selected deployment topology.

| Area | Status | Summary |
| --- | --- | --- |
| Customer APIs | Implemented | Nine authenticated customer operations cover chat, SSE chat, history, suggestions, status, education, and FAQs. |
| Provider integration | Implemented; topology-gated | Groq and Ollama use one bounded provider interface with readiness, timeout, circuit, and stable-error controls. |
| Customer context | Implemented | Ten allowlisted, read-only tools derive customer ownership from the authenticated session. |
| Persistence | Implemented | Encrypted exchanges, idempotency leases, signed cursor history, retention metadata, validators, and indexes are available. |
| Privacy lifecycle | Implemented | Current consent, retention, legal hold, export, deletion, and held-record pseudonymization are integrated. |
| Streaming | Implemented; deployment proof pending | SSE completion, error, disconnect, upstream cleanup, and single-terminal-event behavior have local coverage. |
| Quality controls | Implemented | The approved controlled English/Tagalog system benchmark passes 18/18; raw-model limitations remain documented. |
| Observability | Implemented; deployment proof pending | Low-cardinality metrics, alert rules, a Grafana dashboard, correlation IDs, and metadata-only tool audits are present. |
| Local automated validation | Passing | Focused AI suite: 226 passed on 2026-08-28. Latest full repository suite: 1,363 passed and 55 opt-in tests skipped. |
| Deployment validation | Pending | Final MongoDB, deployed Redis workers, HTTPS proxy/SSE load, monitoring, alert delivery, recovery, and smoke evidence remain. |

## Module Responsibilities

### Customer conversation

- Accept authenticated English (`en`) and Tagalog (`tl`) messages.
- Maintain customer-owned conversations using UUID conversation identifiers.
- Supply up to ten recent persisted messages to the provider for conversation
  continuity.
- Return either a normal JSON response or an incremental SSE response.
- Detect prohibited or sensitive requests and return controlled policy
  responses without relying on provider generation.
- Use reviewed deterministic guidance for stable workflows where unconstrained
  model generation is unnecessary or insufficiently reliable.

### Provider orchestration

- Select and configure the supported Ollama or Groq provider through one
  service boundary.
- Validate provider/model configuration and expose bounded readiness details.
- Enforce connection/read timeouts, safe readiness retries, circuit breaking,
  output-token limits, tool-round limits, and provider concurrency.
- Translate provider failures into stable public API codes without returning
  provider bodies, credentials, hosts, or raw exception details.
- Keep paid or stateful chat requests from being automatically retried.
- Release provider and concurrency resources when a stream completes, fails,
  or the client disconnects.

### Customer-scoped tools

The backend, not the model, supplies the trusted customer identifier to every
tool. The registry contains only the following read operations:

| Tool | Responsibility and bound |
| --- | --- |
| `get_profile_status` | Profile completion and missing-field state. |
| `get_document_status` | Customer document types and review state. |
| `get_loan_status` | Recent application and loan lifecycle state. |
| `get_repayment_schedule` | Installment, balance, progress, overdue, and penalty state. |
| `get_next_payment_due` | The next unpaid installment and due date. |
| `get_payment_history` | Up to 20 recent customer payments. |
| `get_loan_products` | Bounded active-product terms and requirements. |
| `get_application_readiness` | Profile and document blockers. |
| `get_customer_dashboard` | Customer-scoped aggregate counts. |
| `get_notification_status` | Unread count and five recent notifications. |

Tool execution is subject to per-request call/round bounds and shared
minute/hour cost budgets. Attempts consume budget before validation or
execution so invalid and failed calls cannot bypass the limit.

### Conversation persistence and history

- Store user and assistant records in `ai_interactions` as one logical
  exchange.
- Use a MongoDB transaction when the target supports transactions and a
  repeatable pair-upsert fallback for offline development environments.
- Store idempotency state in `ai_chat_requests`; completed requests replay,
  active duplicates and conflicting key reuse return HTTP 409, and stale leases
  can be reconciled without inventing missing AI content.
- Support signed keyset cursors for scalable history retrieval while retaining
  bounded page-number pagination for compatibility.
- Support encrypted-content search using keyed blind tokens instead of
  plaintext search fields.

### Privacy and account lifecycle

- Require current data and AI consent before chat, streaming chat, history
  retrieval, or history deletion.
- Encrypt message, response, and legal-hold reason fields with the shared
  versioned field-encryption lifecycle when a field key is configured.
- Assign schema version, retention policy, expiry, hold, and encryption-key
  metadata to new interactions.
- Expire eligible interactions in bounded batches while excluding legal holds.
- Include a bounded, allowlisted, decrypted AI-history shape in customer data
  export.
- Delete ordinary AI data during final account deletion and pseudonymize held
  evidence that cannot yet be removed.
- Store AI tool audit records in `ai_activity_events` using a blind customer
  subject and metadata only.

### Knowledge and quality governance

- Maintain centralized system instructions, English/Tagalog static guidance,
  prohibited-content handling, and deterministic workflow responses.
- Evaluate a versioned 18-case synthetic bilingual set across accuracy,
  groundedness, language, safety, privacy, adversarial behavior, category
  thresholds, and critical failures.
- Bind evaluation reports to the dataset hash, dataset version, provider, and
  model so unrelated or stale evidence cannot satisfy the release gate.
- Record whether each evaluated response came from a policy rule,
  deterministic guidance, or the configured provider.

### Observability and incident control

- Propagate one request ID through the API, provider, tools, persistence, logs,
  and tool audit.
- Emit low-cardinality Prometheus metrics for request/provider/tool outcomes,
  latency, tokens, active streams, budget rejection, audit failure, and
  persistence failure without message or customer content labels.
- Supply Prometheus alert rules and an importable Grafana dashboard.
- Provide `AI_ASSISTANT_ENABLED` as an operational kill switch. When disabled,
  chat and streaming return HTTP 503 `AI_ASSISTANT_DISABLED`, status reports a
  disabled state, and authenticated static educational content remains usable.

## API Status

All paths below are relative to `/api/ai/`. Every operation requires a valid
customer access token and rejects non-customer roles.

| Method and path | Consent | Status | Behavior |
| --- | --- | --- | --- |
| `POST chat/` | Current data and AI consent | Implemented | Returns a complete response, conversation/model metadata, response timing, and request ID. |
| `POST chat/stream/` | Current data and AI consent | Implemented | Streams `tool_call`, `tool_result`, `token`, and one terminal `done` or `error` event. |
| `GET history/` | Current data and AI consent | Implemented | Returns owner-scoped history using bounded offset or signed cursor pagination and optional blind-token search. |
| `DELETE history/` | Current data and AI consent | Implemented | Deletes ordinary customer history while preserving legal-held evidence under lifecycle policy. |
| `GET suggestions/` | Authentication | Implemented | Returns cached English or Tagalog conversation starters. |
| `GET status/` | Authentication | Implemented | Returns configured provider/model availability, reachability, authentication, degradation, and circuit state from a bounded probe. |
| `GET education/` | Authentication | Implemented | Lists cached education topic identifiers and titles. |
| `GET education/<topic>/` | Authentication | Implemented | Returns cached topic content or HTTP 404. |
| `GET faqs/` | Authentication | Implemented | Returns cached static FAQs and a count. |

Chat and stream requests accept `message`, optional `language`, and optional
`conversation_id`. Clients should also send a UUID `Idempotency-Key`. Messages,
request bodies, search strings, page numbers, languages, conversation IDs, and
idempotency keys are validated and bounded before provider work.

Common response behavior includes:

- HTTP 400 for malformed fields or invalid bounds;
- HTTP 401 for missing or invalid authentication;
- HTTP 403 `CONSENT_REQUIRED` for a stale or missing current consent grant;
- HTTP 409 for an active duplicate or conflicting idempotency-key reuse;
- HTTP 413 for excessive byte or request size;
- HTTP 429 for chat or tool-budget limits; and
- HTTP 503 for a disabled assistant, unavailable provider, provider saturation,
  timeout, or open circuit.

## Security and Privacy Features

### Identity, authorization, and consent

- `CustomJWTAuthentication`, `IsAuthenticated`, and the shared customer
  access-control boundary protect every endpoint.
- Customer ownership is always derived from the authenticated token.
- Conversation and tool queries cannot accept a caller-selected customer ID.
- Personal-data and history operations require consent under the current policy
  version and hash.
- No AI endpoint grants officer/admin visibility into customer conversations.

### Input, output, and prompt safety

- Character, UTF-8 byte, whole-request, language, UUID, and history bounds are
  enforced before execution.
- Provider output is sanitized and escaped once for persistence; streaming
  tokens are escaped for transport.
- The response-control layer rejects internal prompt names, unsupported tool
  claims, unapproved interface controls, delivery guarantees, obvious language
  mismatch, and other known unsafe response patterns.
- Prohibited, credential-seeking, approval-decision, privacy, and adversarial
  intents use controlled responses.
- Clients must still render assistant responses as untrusted text, never as
  trusted HTML.

### Provider data boundary

With current customer consent, a provider call may receive the sanitized
question, up to ten recent interactions, the system instructions, fixed tool
schemas, and allowlisted fields returned by a selected tool. The application
contract excludes passwords, OTPs, private/API keys, uploaded file bytes,
document filenames, bank-account numbers, unrelated customer records, and raw
audit/provider error data.

The recorded provider approval covers private self-hosted Ollama on a
loopback/private network. It is conditional on preventing unintended cloud
egress and complying with the [Ollama Privacy Policy](https://ollama.com/privacy),
[Ollama Terms](https://ollama.com/terms), and
[Llama 3.1 Community License](https://github.com/meta-llama/llama-models/blob/main/models/llama_3_1/LICENSE),
including applicable attribution. Ollama Cloud, Groq, another model, or a
different network topology requires a new privacy, contractual, and quality
review before release.

### Storage and audit protection

- Sensitive interaction fields use versioned application-level encryption.
- Search uses HMAC blind tokens and records the active search-key identifier.
- `ai_interactions`, `ai_chat_requests`, and `ai_activity_events` have schema,
  ownership, uniqueness, recovery, and retention indexes/validators.
- Tool audits contain the blind subject, request ID, fixed tool name, outcome,
  duration, cost, and timestamps—not prompts, responses, parameters, raw
  customer IDs, provider bodies, or error text.
- Default interaction retention is 365 days and default tool-audit retention is
  90 days; deployment owners must approve the configured values.

## AI Quality Status

The approved production baseline is a controlled assistant, not an unrestricted
claim that the underlying model is fully accurate.

The original raw Ollama `llama3.1` benchmark passed 3/18 cases. After prompt,
safety-boundary, and generation-control improvements, the raw-model rerun
passed 13/18 cases (72.2% overall and 100% of critical cases). The remaining raw
failures involved platform guidance, one Tagalog repayment response, and
bilingual guidance quality. Those raw reports remain failing evidence and must
not be represented as a passing raw-model evaluation.

The customer-visible system then assigned reviewed deterministic guidance to
stable workflows and retained hard policy responses for high-risk requests.
The unchanged controlled benchmark passed 18/18 cases: 10 policy-controlled
responses, 8 deterministic-guidance responses, and no provider-generated
responses. This is the approved local quality artifact. Uncontrolled long-tail
generation remains subject to monitoring and may benefit from a stronger
bilingual model in the future.

Retrieval-augmented generation (RAG) is not currently required. It should be
introduced only when an approved knowledge corpus outgrows the versioned
prompt, FAQ, and deterministic-guidance approach, because RAG adds ingestion,
freshness, authorization, privacy, and citation responsibilities.

## Operational Notes

### MongoDB and lifecycle operations

| Command | Purpose |
| --- | --- |
| `ai_interaction_inventory` | Report legacy ownership, plaintext, missing lifecycle metadata, and stale search-key state. |
| `backfill_ai_interactions` | Dry-run or apply encryption and lifecycle metadata to legacy interactions. |
| `reconcile_ai_chat_requests` | Inventory and safely reconcile stale request leases or partial pairs without provider calls. |
| `manage_ai_legal_hold` | Set or release an interaction legal hold. |
| `collect_ai_quality_responses` | Collect approved synthetic responses from the selected provider. |
| `evaluate_ai_quality` | Validate and score reviewed synthetic assessments. |
| `ai_release_check` | Run read-only, fail-closed repository, quality, configuration, and deployment-evidence checks. |

Inventory and backfill are dry-run-first. Before applying a backfill, use an
approved target copy, review the inventory and dry-run output, take a verified
backup, apply the change, and repeat inventory. Previous field keys must remain
available until ciphertext rotation and blind-token rebuilding are verified.

The `ai_assistant.enforce_retention` Celery task removes expired, non-held
records in bounded batches. Retention scheduling, worker health, and failure
alerting must be verified in the deployed Celery topology.

### Runtime configuration

Configuration includes the provider/model and base URL or credential,
assistant kill switch, chat throttle, message/request/history bounds, output
tokens, tool rounds/calls and budgets, provider concurrency, timeouts, retry,
circuit settings, retention policy, and release-evidence flags. Invalid numeric
or rate formats fail during settings loading.

The current `100/hour` chat throttle is the accepted development/testing value.
It is not an application-code gap, but it must be reviewed against provider
cost, worker capacity, abuse risk, and expected traffic before production.

Do not store provider credentials, encryption keys, quality response artifacts,
or deployment evidence in source control. Use the deployment secret manager
and approved private evidence storage.

### Monitoring and incident response

- Scrape the backend metrics endpoint with Prometheus and import the supplied
  Grafana dashboard and alert rules.
- Generate authenticated synthetic AI API traffic before concluding that AI
  time series are absent or broken.
- Test alert firing and recovery through the real notification route.
- Use `AI_ASSISTANT_ENABLED=False` as the provider/AI incident kill switch and
  restart workers so the setting takes effect.
- Correlate client-visible `request_id` values with protected logs and metadata
  audit events; do not expose raw provider failures to clients.

## Client Notes

- The customer mobile client is the intended consumer; no officer/admin AI
  interface is required by the current API.
- Send a UUID `Idempotency-Key` for chat and stream requests. Reuse it only when
  retrying the same logical request. A completed replay includes
  `replayed=true`; different content with the same key returns HTTP 409.
- Use `pagination=cursor` for new history integrations and treat
  `next_cursor` as opaque. Bounded page-number pagination remains for older
  clients.
- Render every assistant response as plain/untrusted text.
- SSE clients must handle `tool_call`, `tool_result`, `token`, `done`, and
  `error`. HTTP 200 only means the stream opened; success requires exactly one
  `done` event and no later event.
- Tokens received before a terminal `error` or disconnect are incomplete
  display-only content. The backend does not persist that partial assistant
  reply.
- Stop loading on `done`, `error`, 401, 403, 409, 429, 503, or disconnect. Do
  not create an automatic duplicate stream with a new idempotency key.
- Treat `AI_ASSISTANT_DISABLED` as a temporary maintenance/incident state and
  avoid tight retry loops.
- A `CONSENT_REQUIRED` response includes the current policy metadata needed to
  send the customer through consent renewal.

## Validation Evidence

Current repository evidence:

- Focused AI regression suite: **226 passed** on 2026-08-28.
- Latest full repository suite: **1,363 passed and 55 opt-in integration tests
  skipped** on 2026-08-28.
- Opt-in tests remain skipped unless an approved real MongoDB, Redis, provider,
  proxy/load, privacy, monitoring, or recovery environment is supplied.

Dated environment exercises retained as supporting evidence:

- Owner-designated database inventory/backfill on 2026-08-14 found zero AI
  records and zero findings; request reconciliation found no stale or partial
  exchanges.
- An isolated real-Mongo gate passed two validator, index, encrypted-write, and
  query-plan tests; temporary collections were removed.
- Two independent clients and two processes passed the development Redis atomic
  state/TTL probe; probe keys were removed.
- The configured local Ollama `llama3.1` provider passed the synthetic basic
  chat/stream contract probe.
- An encrypted test-cluster backup restored 28 collections and 106 documents
  with no count mismatch. A field-key rotation changed 18 protected fields
  across five records and strict verification reported no failure; temporary
  evidence resources were removed.
- Local Prometheus reported one healthy target and eight loaded rules, and
  local Grafana 13.1.3 reported a healthy database.

These exercises establish that the tooling works in the tested environments.
They do not replace final evidence from the actual production topology.

## Remaining Gaps and Release Conditions

No known repository implementation stage remains for the approved controlled
baseline. The following are deployment or final-release conditions:

1. Immediately before release, repeat inventory and backfill dry-run against
   the target database, review intervening records, verify encryption, and
   retain approved backup evidence.
2. Verify target MongoDB validators, indexes, transactions, uniqueness, TTLs,
   encrypted writes, and representative query plans in an isolated deployment
   test database.
3. Prove atomic tool-budget and cache behavior across the deployed Redis service
   and multiple backend workers.
4. Exercise tool calls, incremental SSE delivery, proxy buffering, timeouts,
   disconnect propagation, cleanup, and expected load through deployed HTTPS.
5. Scrape authenticated synthetic AI traffic in deployed Prometheus, inspect
   the Grafana dashboard, and prove alert firing/recovery through the real route.
6. Confirm the provider/model/network topology still matches its privacy,
   contract, egress, license, and quality approval; re-review any change.
7. Repeat backup/restore, key rotation, provider failure, kill-switch, incident,
   and rollback rehearsals in the selected deployment topology.
8. Review the production chat throttle and all capacity/cost limits.
9. Store the passing quality report in approved evidence storage, bind it with
   `AI_ASSISTANT_QUALITY_REPORT_PATH`, run the final authenticated smoke test,
   and pass `ai_release_check` with deployment evidence enabled.

Until these conditions pass, the accurate status is **application-complete and
awaiting production-environment validation**, not fully production-approved.

## Review Boundaries

This document verifies repository implementation, API contracts, local
automated behavior, and the dated exercises above. It does not certify future
provider terms, independent human model evaluation, financial-advice
suitability, live customer data, production secret management, cloud egress,
network/IAM policy, production MongoDB or Redis configuration, reverse-proxy
behavior, deployed load, alert delivery, backup restorability, staffing,
incident ownership, or service-level objectives.

Accounts owns authentication, consent, session/account lifecycle, and shared
field keys. Profiles, Documents, Loans, Notifications, and Analytics own their
source records and business semantics. The AI Assistant may summarize only the
allowlisted customer-scoped data supplied by those modules and must not make
loan decisions or mutate their records.

This document describes the backend contract. Client usability, accessibility,
offline behavior, and mobile presentation require separate client validation.

## Related Documentation

- `docs/AI_ASSISTANT_TESTING_GUIDE.md` — API examples, test commands, quality
  workflow, deployment probes, smoke tests, and troubleshooting.
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  consent, account lifecycle, and shared encryption contracts.
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile source data
  and customer cleanup behavior.
- `docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` — document source,
  privacy, and lifecycle behavior.
- `docs/ANALYTICS_PRODUCTION_READINESS_REVIEW.md` — metrics, monitoring, and
  shared audit boundaries.
