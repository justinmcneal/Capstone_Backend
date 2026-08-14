# AI Assistant Production Readiness Review

Last reviewed: 2026-08-14

Module: `ai_assistant/`

API prefix: `/api/ai/`

## Current Status

**Module implementation status: Functional baseline implemented; production hardening remains**

**Production deployment status: Not ready for approval**

The module already provides authenticated English/Tagalog chat, tool-assisted
answers based on the current customer's data, SSE streaming, consent checks,
history, static education content, and a choice of Groq or Ollama. Its local
automated behavior is strong: the Stage 1 focused review suite completed with
**176 passing tests** on 2026-08-14.

Stage 1 data-governance code is complete: conversation content is encrypted when
a field key is configured, history search uses keyed blind tokens, new records
receive versioned retention metadata, legal holds and bounded cleanup exist,
account export includes allowlisted history, and final account deletion performs
resumable AI cleanup. Production approval still requires reviewing and applying
the dry-run legacy backfill against the target database. Tool auditing is not
durable, production metrics are absent, request/provider bounds are incomplete,
and real provider, MongoDB, Redis, load, and proxy behavior remain unproven.

| Area | Status | Summary |
| --- | --- | --- |
| Authentication and customer scoping | Implemented | Every endpoint requires JWT authentication and customer role checks. Conversation and tool data are scoped with the authenticated customer ID. |
| Consent | Implemented | Chat, streaming chat, and history require current data and AI consent. Static status, education, FAQ, and suggestion endpoints do not send personal data to an LLM. |
| Non-streaming chat | Implemented; hardening required | Tool calling, history context, content filtering, bilingual responses, and persistence work, but request limits, idempotency, full correlation, and provider error normalization remain. |
| Streaming chat | Implemented; hardening required | SSE framing and persistence are tested. Disconnect handling, proxy/load proof, error semantics, and a double-escaping defect remain. |
| Read-only customer tools | Implemented; hardening required | Ten customer-scoped tools are available. Rate limiting is non-atomic, one expensive tool is under-costed, and durable tool audit is missing. |
| Context minimization | Partial | Context builders limit list sizes and omit direct credentials, but the declared redaction/masking lists are not actually applied as a generic enforcement layer. |
| Conversation storage | Stage 1 implemented; deployment backfill pending | Message, response, and hold reason use versioned field encryption; keyed search tokens preserve keyword search; retention, legal holds, export, and resumable account cleanup are implemented. MongoDB schema validation and target backfill evidence remain. |
| Provider integration | Partial | Groq and Ollama are supported through an OpenAI-compatible interface. Configuration validation, truthful upstream readiness, resiliency, and real-provider contract tests remain. |
| Knowledge and response quality | Partial | A centralized prompt, simple prohibited-content checks, and many behavior tests exist. There is no versioned evaluation set, feedback loop, groundedness threshold, or adversarial safety gate. |
| Observability | Partial | Timing, model, token count, streaming request ID, and ordinary logs exist. Non-streaming correlation, Prometheus metrics, durable audit, dashboards, and alerts do not. |
| Local automated tests | Passing | 176 Stage 1-focused tests passed; external services and real MongoDB behavior remain unproven. |
| Deployment validation | Missing | No recorded real Groq/Ollama, MongoDB, Redis, concurrent-load, SSE proxy, secret rotation, or incident-response evidence exists. |

## Module Responsibilities

The AI Assistant module is responsible for:

- accepting authenticated customer questions;
- requiring current AI/data consent before personal AI processing;
- building bounded summaries of profile, document, loan, repayment, and account
  state;
- allowing the model to invoke a fixed set of read-only, customer-scoped tools;
- returning complete JSON responses or SSE events;
- storing and retrieving customer chat history;
- serving static suggestions, loan education, and FAQs; and
- selecting and calling either Groq or a configured Ollama service.

It is not responsible for loan decisions, document classification, account
authentication, consent persistence, or analytics authorization. Those remain
owned by their respective modules.

## Request Flow

1. `CustomJWTAuthentication` authenticates the request.
2. `AccessControlMixin` restricts access to customers.
3. Chat/history endpoints call `ConsentService.check_ai_consent()`.
4. The request is sanitized and its language/conversation ID is validated.
5. A keyword filter redirects a small set of credential, guarantee, and legal
   requests.
6. Relevant customer context and up to ten read-only tools are made available
   to the configured provider.
7. Tool arguments are validated and every query is scoped with the authenticated
   customer ID.
8. The response is sanitized/escaped and returned; completed conversations are
   written to `ai_interactions`.

## API Status

| Method and path | Consent | Status | Notes |
| --- | --- | --- | --- |
| `POST /api/ai/chat/` | Required | Implemented; hardening required | JSON chat with tool calling and stored history. |
| `POST /api/ai/chat/stream/` | Required | Implemented; hardening required | SSE events: `tool_call`, `tool_result`, `token`, `done`, and `error`. |
| `GET /api/ai/history/` | Required | Implemented; query hardening required | Owner-scoped offset pagination, limit capped at 100, optional encrypted keyword search using keyed blind tokens. |
| `DELETE /api/ai/history/` | Required | Implemented | Deletes all interactions belonging to the authenticated customer. |
| `GET /api/ai/suggestions/` | Not required | Implemented | Static English/Tagalog suggestions cached by language. |
| `GET /api/ai/status/` | Not required | Partial | For Groq, `available` currently means an API key exists; it does not prove the upstream service works. |
| `GET /api/ai/education/` | Not required | Implemented | Lists static education topics. |
| `GET /api/ai/education/<topic>/` | Not required | Implemented | Returns one cached topic or 404. |
| `GET /api/ai/faqs/` | Not required | Implemented | Returns cached static FAQs. |

No loan-officer or admin AI endpoints are currently registered.

## Implemented Tool Catalog

All tools are read-only and receive the authenticated customer ID from the
backend rather than from model arguments.

| Tool | Data returned |
| --- | --- |
| `get_profile_status` | Profile, business, and alternative-data completion and missing fields. |
| `get_document_status` | Customer document types and review status. |
| `get_loan_status` | The customer's recent applications and decision/disbursement state. |
| `get_repayment_schedule` | Installments, balance, payment progress, overdue and penalty state. |
| `get_next_payment_due` | The next unpaid installment and due date. |
| `get_payment_history` | Up to 20 recent customer payments. |
| `get_loan_products` | Active products, ranges, terms, rates, and requirements. |
| `get_application_readiness` | Profile/document blockers for the baseline application workflow. |
| `get_customer_dashboard` | Application, document, profile, and AI-interaction counts. |
| `get_notification_status` | Unread count and five recent customer notifications. |

## Verified Security and Privacy Controls

- Chat, stream, and history reject customers without current data and AI
  consent.
- The current policy version is enforced by the shared consent service, so a
  policy change can require re-consent.
- Customer identity is taken from the authenticated token, not accepted as a
  request/tool parameter.
- Conversation lookups include customer scope, which prevents a known UUID from
  exposing another customer's history.
- Tool names are mapped to a fixed executor table and tools perform reads only.
- Tool parameters are normalized; payment-history limits are clamped to 1–20.
- Conversation IDs must be UUIDs and language is restricted to `en` or `tl`.
- User input has tags/control characters removed and model output is HTML
  escaped before ordinary JSON delivery/persistence.
- The context builder avoids passwords, OTPs, private keys, bank-account
  numbers, and other direct credentials in its current summaries.
- Conversation history sent back to the provider is bounded to the latest six
  entries; view queries load the latest ten stored entries before that bound.
- Tool rounds are capped, and endpoint/tool rate limiters exist.
- SSE framing, content type, and anti-buffering headers are covered by tests.
- LLM API keys are read from settings and are not returned by the AI endpoints.
- `message`, `response`, and legal-hold reason participate in the shared
  versioned field-encryption and key-rotation tooling.
- New interactions receive a retention policy version and expiry; the daily
  bounded retention task excludes legal holds.
- Account export decrypts only an allowlisted history shape. Final account
  deletion removes ordinary history and pseudonymizes the owner of held records,
  with retry status/counts stored on the customer.
- Encryption-compatible keyword search stores only keyed word hashes, not
  plaintext search content.

These controls reduce risk but do not replace target-environment backfill proof,
provider governance, or adversarial model evaluation.

## Verified Stage 1: Data Governance and Account Lifecycle

Implemented application behavior:

- `AIInteraction.encrypted_fields` covers message, response, and hold reason and
  is included in the global encryption verify/rotation command.
- New records receive `interaction_schema_version=2`, retention policy/version,
  expiry, hold metadata, and keyed blind-search tokens.
- `ai_assistant.enforce_retention` deletes bounded batches of expired, non-held
  records daily.
- Dry-run-first inventory, legacy backfill, and legal-hold commands are present.
- Customer export includes bounded, allowlisted decrypted history without owner
  IDs or internal search tokens.
- Final account deletion records retryable AI cleanup attempts/counts, deletes
  non-held records, and moves held evidence to a pseudonymous owner.
- Customer history clearing deletes ordinary records and hides held evidence
  from subsequent customer history without bypassing the hold.
- Local tests cover ciphertext storage/read, encrypted search, retention/hold,
  export, string/ObjectId deletion, pseudonymization, cleanup retry, inventory,
  dry-run backfill, and command behavior.

Deployment condition still open: run the count-only inventory and review the
backfill dry run against the deployment target before applying it. Stage 3 will
add the MongoDB validator and isolated real-Mongo query/index proof.

## Remaining Production-Blocking Gaps

### 1. Request, cost, and query bounds

Chat messages have no explicit byte/character limit. History search has no
search-length bound and page has no maximum offset. `find_by_conversation()` loads the entire
conversation before Python slices it. Several tools load all matching records
and slice afterward.

`ChatRateThrottle` is hard-coded to `1000/hour`; it is not an environment-based
production cost policy and does not limit concurrent long-lived calls. One
request can perform multiple provider rounds with 120–180 second timeouts.

Required work:

- validate maximum request bytes/message characters and bounded history fields;
- bound conversation history in MongoDB and replace unrestricted offsets with
  a maximum offset or cursor pagination;
- use projections and database-side limits for tool queries;
- make chat rate, tool budgets, timeout, token, tool-round, and concurrency
  limits validated settings; and
- return a documented 400/413/429 response when a bound is exceeded.

### 2. Provider boundary and failure behavior

`LLM_PROVIDER`, model names, timeouts, and Ollama URL are not validated at
startup. Unknown provider values silently become Groq. Groq `is_available()`
only checks whether a key is non-empty, so `/status/` and `/api/health/` can
report availability for an invalid key or provider outage.

Provider error text can be returned to customers, provider calls have no retry
policy/circuit breaker, and the synchronous HTTP path can occupy request workers
for minutes. There is no approved-provider/data-processing checklist or real
provider contract test.

Required work:

- fail startup on invalid provider/model/URL/limit configuration;
- distinguish configured, reachable, authenticated, degraded, and unavailable;
- map upstream failures to stable public errors and keep detailed provider text
  only in protected logs;
- add bounded connect/read timeouts, limited retry/backoff for safe transient
  failures, a circuit breaker, and concurrency control;
- document which customer fields may leave the system and approve provider
  retention/training/data-residency terms; and
- prove the selected provider/model supports the required streaming and tool
  contract in the deployment environment.

### 3. Durable audit, correlation, and monitoring

`ToolCallAuditor` writes ordinary log messages only. Its
`get_recent_calls()` method is an explicit placeholder returning an empty list.
There are no AI Prometheus counters/histograms or alert rules.

Streaming creates a request ID and stores it on completed interactions, but
non-streaming chat does not. Request IDs are not returned consistently or
propagated through provider/tool logs. Failed and filtered attempts do not have
a uniform event record.

Required work:

- generate/accept a safe correlation ID for every chat mode and return it;
- propagate it to provider calls, tool calls, persistence, structured logs, and
  audit events;
- store durable metadata-only audit events without prompts, responses, tool
  payloads, or unnecessary customer PII;
- add request, error, timeout, active-stream, tool, token, and latency metrics;
- build dashboards and alerts for provider failure, latency, rate limiting,
  abnormal token/tool use, and persistence failures; and
- define log access and retention rules.

### 4. Persistence consistency and schema enforcement

User and assistant messages are two independent inserts. A failure between them
can leave a half-conversation. Client retries have no idempotency key and can
create duplicate provider charges/history. The collection has indexes but no
MongoDB validator.

The current index set lacks the natural history index
`(customer_id, timestamp desc)`. The existing
`(customer_id, conversation_id, timestamp)` index helps conversation lookup but
does not efficiently serve all customer history sorted only by time.

Required work:

- define an atomic/idempotent interaction write strategy and retry state;
- validate role, language, UUID, timestamps, token/latency types, encryption,
  and retention fields at the MongoDB boundary;
- add the owner/timestamp history index and verify query plans; and
- reconcile legacy customer-ID shapes before tightening validation/indexes.

## Correctness and Maintainability Findings

These should be fixed before final production validation:

1. Streaming escapes each token and then escapes the joined response again
   before persistence, which can store double-escaped entities.
2. Filtered non-streaming messages are persisted, while filtered streaming
   messages are not; the intended policy must be explicit and consistent.
3. SSE `tool_result.success` is always emitted as `true`, even when the tool
   returned a rate-limit or safe error payload.
4. `build_documents_summary()` reports the total across all documents but
   counts statuses only within the first five, which can produce contradictory
   summaries.
5. `REDACTED_FIELDS`, `MASKED_FIELDS`, `MAX_PAYMENTS`, and `MAX_INSTALLMENTS`
   are declarations rather than an enforced generic serialization boundary.
6. `get_customer_dashboard` is omitted from the tool-cost table and parameter
   schema, so an aggregation-heavy tool receives the default cost.
7. Tool rate limiting uses cache `get` followed by `set`, which is not atomic;
   concurrent requests can bypass the intended count. Only successful calls
   are recorded, so repeated failing calls are not fully budgeted.
8. Some direct dashboard/notification queries use only string customer IDs,
   while the interaction model supports legacy ObjectId and string forms. This
   can make tool answers incomplete during legacy-data transition.
9. The static knowledge base is manually maintained. Its checklist and unit
   tests help, but they do not automatically compare claims with registered
   routes, current settings, product configuration, or client navigation.
10. The shared module-level `requests.Session` and synchronous provider calls
    need concurrency/load proof; connection pooling alone does not make the I/O
    non-blocking.

## Test Status and Missing Evidence

The following command passed during this review:

```bash
.venv/bin/pytest -q \
  tests/test_ai_stage1_privacy_lifecycle.py \
  tests/test_ai_model_methods.py \
  tests/test_ai_streaming.py \
  tests/test_chatbot_api.py \
  tests/test_ai_context_builder.py \
  tests/test_ai_knowledge.py \
  tests/test_ai_tool_safety_integration.py \
  tests/test_tool_safety.py \
  tests/test_context_builder.py \
  tests/test_documents_ai_consent.py \
  accounts/tests/test_field_encryption_lifecycle.py
```

Focused result: **176 passed in 1.21 seconds**.

The complete repository suite also passed after Stage 1:

```text
1133 passed, 28 skipped, 1 warning in 51.29 seconds
```

The skipped cases are explicit deployment/integration tests. The warning is the
existing `websockets.legacy` deprecation warning.

The suite verifies local API behavior, consent, owner scoping, content helpers,
context formatting, cache behavior, tool validation, and SSE syntax. It does
not currently prove:

- target-database legacy backfill/reconciliation or real MongoDB lifecycle;
- real MongoDB validators, indexes, query plans, or concurrent writes;
- atomic Redis-backed tool/request rate limiting;
- real Groq/Ollama tool calling, token accounting, timeout, and streaming;
- malformed/truncated provider streams and customer disconnect behavior;
- multi-worker load, maximum latency, memory, file-descriptor, or connection
  behavior;
- SSE behavior through the selected reverse proxy/load balancer;
- prompt-injection, jailbreak, unsafe-advice, privacy-leak, hallucination, and
  English/Tagalog quality thresholds; or
- metrics, dashboards, alerts, provider secret rotation, backup/restore, and
  incident runbooks.

See `docs/AI_ASSISTANT_TESTING_GUIDE.md` for the required test matrix.

## Recommended Implementation Order

The sequence below is based on dependencies and risk; it is not an arbitrary
fixed number of stages.

### Stage 1: Data governance and account lifecycle

**Application implementation complete.** Conversation encryption, keyed search,
retention/legal holds, export/final deletion, dry-run inventory/backfill, retry
state, and lifecycle tests are implemented. Deployment inventory/backfill and
real-Mongo evidence remain release operations, not application-code gaps.

### Stage 2: Request and provider boundary

Add validated settings, input/token/tool/time/concurrency limits, stable public
errors, provider readiness states, retry/backoff, and circuit breaking.

### Stage 3: Persistence and query scalability

Add schema validation, appropriate indexes, database-side bounds/cursor
pagination, idempotency, and consistent two-message persistence. Verify against
isolated real MongoDB.

### Stage 4: Tool safety, audit, and observability

Make rate accounting atomic, correct tool costs/results, create metadata-only
durable audit events, add correlation IDs and Prometheus metrics, then provision
dashboards and alerts.

### Stage 5: Streaming and response correctness

Fix double escaping and filtered-history consistency; test disconnects,
truncated/malformed streams, proxy buffering, upstream errors, and multi-worker
stream limits.

### Stage 6: Model quality and deployment validation

Create a versioned English/Tagalog evaluation set, define safety/groundedness
release thresholds, run a real-provider contract test and load test, rehearse
key/provider failure and rollback, and collect final deployment evidence.

## Optional Product Improvements

These are useful but are not substitutes for the blockers above:

- thumbs-up/down feedback with reason categories and privacy-safe reporting;
- conversation list, single-conversation deletion, titles, and explicit “new
  conversation” behavior;
- citations or structured source labels for factual platform answers;
- cost dashboards and per-model budget controls;
- human escalation when confidence is low or policy/financial questions exceed
  the assistant's approved scope; and
- a curated RAG system only if the approved policy/FAQ corpus grows beyond what
  can be safely versioned in the prompt. RAG is not required for the current
  small static knowledge base and would introduce new ingestion, authorization,
  freshness, and citation obligations.

## Client Notes

- Customer clients need only the existing nine endpoints; no officer/admin
  client changes are required by the current API.
- Treat response text as text, not trusted HTML. Server escaping does not remove
  the client's responsibility to avoid unsafe HTML rendering.
- SSE clients must handle all five event types, reconnect intentionally rather
  than automatically duplicating a request, and stop UI loading state on
  `done`, `error`, HTTP 401/403/429/503, or disconnect.
- Clients should preserve `conversation_id`; future idempotency/correlation
  fields should be added without changing the meaning of that ID.
- Consent errors include the endpoint and current policy metadata needed to
  route the customer through consent renewal.

## Operational Notes

- Production must use Redis-backed shared caching if multiple application
  processes rely on common throttles and tool caches. Local-memory cache is
  process-local and is not an adequate distributed control.
- `python init_db.py` creates AI indexes, but it must be run with an approved
  bootstrap identity and reviewed against the target database. It currently
  creates indexes only; schema validation and target lifecycle evidence remain.
- Review AI legacy records without writing:

  ```bash
  .venv/bin/python manage.py ai_interaction_inventory
  .venv/bin/python manage.py backfill_ai_interactions
  ```

  After reviewing the dry run, apply and verify with approved deployment
  credentials:

  ```bash
  .venv/bin/python manage.py backfill_ai_interactions --apply
  .venv/bin/python manage.py encrypt_sensitive_fields --verify
  .venv/bin/python manage.py ai_interaction_inventory
  ```

  During key rotation, keep previous keys configured until both the global
  ciphertext rotation and AI backfill have completed. The AI backfill rebuilds
  blind-search tokens under the primary key; inventory reports stale search-key
  IDs before an old key is removed.
- Groq keys belong in the deployment secret manager and must be rotated and
  tested. An Ollama endpoint must be private, authenticated at the network
  boundary, and protected from arbitrary outbound access.
- Confirm the deployment proxy preserves `text/event-stream`, disables response
  buffering/compression where necessary, and permits a deliberately bounded
  stream duration.
- Backups containing `ai_interactions` inherit the same encryption, retention,
  restore-testing, and access-control obligations as the live collection.

## Release Conditions

Production approval requires all of the following:

- [x] Conversation encryption, blind search, retention/legal hold, export, and
  retryable account deletion are implemented and locally verified.
- [ ] Deployment-target AI inventory/backfill is reviewed, applied, and returns
  zero plaintext, missing-retention, or stale-search-index findings.
- [ ] Input, pagination, token, tool, timeout, rate, and concurrency limits are
  validated and documented.
- [ ] Provider configuration fails safely and public errors disclose no provider
  internals.
- [ ] MongoDB validators/indexes and Redis atomic limits pass isolated real
  integration tests.
- [ ] Durable metadata-only audit, end-to-end correlation, metrics, dashboards,
  and actionable alerts are operational.
- [ ] Streaming correctness, disconnect, proxy, and load tests pass.
- [ ] A versioned bilingual safety/accuracy evaluation meets approved thresholds.
- [ ] The selected real provider/model passes chat, tool, streaming, timeout,
  and token-accounting contract tests.
- [ ] Provider privacy terms, secrets, backup/restore, incident response, and
  rollback evidence are reviewed for the deployment target.
- [x] The full local repository suite passes after Stage 1.
- [ ] The final deployment smoke gate passes.

## Review Boundaries

This was an implementation review plus the focused local test run
listed above. The review did not read `.env`, inspect customer data, call a live
LLM, mutate a real MongoDB/Redis deployment, run load tests, or validate a
production proxy/cloud environment. Those are release conditions, not verified
facts.
