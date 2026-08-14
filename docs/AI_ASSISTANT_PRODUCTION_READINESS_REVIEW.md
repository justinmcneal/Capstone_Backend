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
automated behavior is strong: the Stage 1–3 focused suite has **200 passing
tests**, and the full local repository suite has **1,157 passing tests**.

Stage 1 data governance, Stage 2 request/provider boundaries, and Stage 3
persistence/query scalability are application-complete. Conversation content is encrypted when
a field key is configured, history search uses keyed blind tokens, new records
receive versioned retention metadata, legal holds and bounded cleanup exist,
account export includes allowlisted history, and final account deletion performs
resumable AI cleanup. Chat input, history search/page, rate, token, tool,
timeout, and concurrency policies are validated and configurable. Provider
configuration fails at startup when invalid; readiness checks authentication
and reachability; public failures are stable; and safe readiness retries,
circuit breaking, and concurrency slots are enforced. Signed cursor history,
bounded context/tool reads, idempotency leases, transaction-backed exchange
writes, validators, and production indexes are implemented. Production approval still
requires target backfill, provider/privacy approval, and real provider,
MongoDB, Redis, load, proxy, audit, and monitoring evidence.

| Area | Status | Summary |
| --- | --- | --- |
| Authentication and customer scoping | Implemented | Every endpoint requires JWT authentication and customer role checks. Conversation and tool data are scoped with the authenticated customer ID. |
| Consent | Implemented | Chat, streaming chat, and history require current data and AI consent. Static status, education, FAQ, and suggestion endpoints do not send personal data to an LLM. |
| Non-streaming chat | Stage 3 implemented; later hardening remains | Bounded tool chat uses UUID idempotency keys, active-request leases, completed-response replay, and consistent exchange persistence. Full provider/tool/audit correlation remains Stage 4. |
| Streaming chat | Implemented; hardening required | SSE framing and persistence are tested. Disconnect handling, proxy/load proof, error semantics, and a double-escaping defect remain. |
| Read-only customer tools | Implemented; hardening required | Ten customer-scoped tools are available. Rate limiting is non-atomic, one expensive tool is under-costed, and durable tool audit is missing. |
| Context minimization | Partial | Context builders limit list sizes and omit direct credentials, but the declared redaction/masking lists are not actually applied as a generic enforcement layer. |
| Conversation storage | Stage 3 implemented; deployment proof pending | Encryption/lifecycle controls, signed cursor pagination, bounded conversation reads, canonical owner shape, transaction-backed idempotent pairs, validators, and indexes are implemented. Target backfill and real-Mongo evidence remain. |
| Provider integration | Stage 2 implemented; deployment proof pending | Groq and Ollama use validated configuration, authenticated/reachable readiness states, stable errors, bounded timeouts, safe GET retries, a circuit breaker, and per-process concurrency slots. Real-provider contract and privacy approval remain. |
| Knowledge and response quality | Partial | A centralized prompt, simple prohibited-content checks, and many behavior tests exist. There is no versioned evaluation set, feedback loop, groundedness threshold, or adversarial safety gate. |
| Observability | Partial | Timing, model, token count, streaming request ID, and ordinary logs exist. Non-streaming correlation, Prometheus metrics, durable audit, dashboards, and alerts do not. |
| Local automated tests | Passing through Stage 3 | 200 focused tests and the full 1,157-test local suite pass; 30 opt-in integrations are skipped and real deployment behavior remains unproven. |
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
| `POST /api/ai/chat/` | Required | Stage 3 implemented; later hardening remains | Accepts optional UUID `Idempotency-Key`; duplicates replay without a second provider call, active duplicates return 409, and mismatched reuse returns 409. |
| `POST /api/ai/chat/stream/` | Required | Stage 3 implemented; later hardening remains | Uses the same idempotency contract and persists filtered/successful exchanges consistently; disconnect/proxy correctness remains Stage 5. |
| `GET /api/ai/history/` | Required | Stage 3 implemented | Owner-scoped signed keyset cursors are available with `pagination=cursor`; bounded page compatibility remains for existing clients. Search remains keyed and bounded. |
| `DELETE /api/ai/history/` | Required | Implemented | Deletes all interactions belonging to the authenticated customer. |
| `GET /api/ai/suggestions/` | Not required | Implemented | Static English/Tagalog suggestions cached by language. |
| `GET /api/ai/status/` | Not required | Implemented; deployment proof pending | Reports configured, reachable, authenticated, selected-model availability/degradation, and circuit state using a bounded provider probe. |
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

## Verified Stage 2: Request and Provider Boundary

Implemented application behavior:

- request/message UTF-8 bytes, sanitized characters, history search, and page
  number have validated configurable limits;
- chat rate defaults to `100/hour` for the current test policy and is no longer
  hard-coded in the throttle class;
- output token, tool-round, total tool-call, connect/read timeout, safe retry,
  circuit, and per-process provider-concurrency policies fail startup when
  invalid;
- only idempotent readiness GETs retry transient failures; paid chat POSTs do
  not automatically retry and create duplicate cost;
- streaming responses retain their concurrency slot until consumed or closed;
- status reports configuration, reachability, authentication, selected-model
  availability/degradation, and circuit state; and
- customer responses use stable error codes without raw provider bodies, URLs,
  credentials, or exception text.

### Outbound provider data contract

With current AI consent, the selected Groq/Ollama provider may receive the
sanitized customer question, up to six recent conversation entries, the system
prompt, fixed tool schemas, and only the result fields documented in the tool
catalog above. Depending on the question, those results can contain profile/
business completion state, document types/statuses, loan and repayment status,
payment dates/amounts, product data, readiness blockers, aggregate dashboard
counts, and notification status. Direct passwords, OTPs, API/private keys, bank
account numbers, uploaded document bytes, document filenames, and unrelated
customer records are outside the approved application contract.

This documents current code behavior; deployment approval still requires the
organization to approve the chosen provider's retention, training, subprocessors,
data-residency, deletion, incident, and contractual terms.

## Remaining Production-Blocking Gaps

### 1. Request, cost, and query bounds

**Stage 2 application boundary complete.** Chat requests enforce configured
UTF-8 byte and sanitized-character limits before filtering/provider work.
History search length and page number are bounded. Chat rate (currently
`100/hour` for testing), output tokens, tool rounds, total tool calls,
connect/read timeouts, and provider concurrency are validated settings. Bound
violations return stable 400, 413, or DRF 429 responses.

Stage 3 subsequently added signed keyset history, database-bounded conversation
context, and bounded/projected document, loan, repayment, payment, dashboard,
and notification tool reads. Legacy offset pages remain bounded only for client
compatibility. Deployment query-plan/load evidence remains open.

### 2. Provider boundary and failure behavior

**Stage 2 application boundary complete.** Invalid provider, model, URL, rate,
and numeric settings fail startup. Unknown runtime providers are rejected.
`/status/` distinguishes configured, reachable, authenticated, selected-model
availability, degradation, and circuit state. Provider bodies/details are protected-log-only;
customers receive stable error codes. Calls use bounded connect/read timeouts,
safe transient retries are limited to idempotent readiness GETs, paid chat POSTs
are never retried automatically, and circuit/concurrency controls cover normal
and streaming provider calls.

Deployment conditions still open: approve which minimized customer fields may
reach the selected provider and its retention/training/data-residency terms,
then run the real-provider chat/tool/streaming/timeout/token contract gate with
synthetic data. Per-process concurrency also requires deployment load evidence;
it is intentionally not represented as a distributed quota.

### 3. Durable audit, correlation, and monitoring

`ToolCallAuditor` writes ordinary log messages only. Its
`get_recent_calls()` method is an explicit placeholder returning an empty list.
There are no AI Prometheus counters/histograms or alert rules.

Both chat modes now create/accept a UUID request ID and return/store it for
completed/filtered exchanges. It is not yet propagated through every provider/
tool log or durable audit event, and failed attempts do not yet have the Stage 4
uniform audit record.

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

**Stage 3 application implementation complete.** UUID idempotency keys are
leased before provider work; completed exchanges replay without provider cost;
active duplicates and mismatched key reuse return 409. User/assistant records
use one transaction where MongoDB supports sessions and repeatable pair upserts
in offline development. A dry-run-first reconciliation command inventories
stale leases and partial pairs without fabricating content.

The interaction/request validators enforce canonical string ownership, UUIDs,
roles, languages, dates, numeric metadata, versioned ciphertext, and retention.
Indexes cover owner/time keyset history, owner/conversation/time, encrypted
search, retention, exchange uniqueness, request uniqueness/recovery, and request
TTL. Legacy backfill canonicalizes ObjectId owners and inventory reports legacy
shape. Conversation context and selected tool reads now use database-side limits
and minimal projections.

Deployment condition: run inventory/backfill first, then install/verify the
validators and indexes and execute the opt-in real-Mongo validator, transaction,
unique-index, and `explain()` gate against an isolated replica-set database.

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

**Application implementation complete.** Validated input/rate/token/tool/time/
concurrency limits, stable errors, truthful readiness states, safe retry/backoff,
circuit breaking, and local boundary tests are implemented. Provider privacy
approval and real-provider/load evidence remain deployment conditions.

### Stage 3: Persistence and query scalability

**Application implementation complete.** Schema validation, production indexes,
signed keyset pagination, bounded/projected queries, idempotency leases/replay,
transaction-backed pairs, retry reconciliation, and local tests are implemented.
The isolated real-Mongo proof remains a deployment gate.

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
- [x] Input, pagination, token, tool, timeout, rate, and concurrency limits are
  validated and documented.
- [x] Provider configuration fails safely and public errors disclose no provider
  internals.
- [x] MongoDB validators, indexes, idempotency, signed cursors, and bounded
  persistence/query behavior are implemented and locally tested.
- [ ] MongoDB validators/indexes/transactions/query plans and Redis atomic limits
  pass isolated real integration tests.
- [ ] Durable metadata-only audit, end-to-end correlation, metrics, dashboards,
  and actionable alerts are operational.
- [ ] Streaming correctness, disconnect, proxy, and load tests pass.
- [ ] A versioned bilingual safety/accuracy evaluation meets approved thresholds.
- [ ] The selected real provider/model passes chat, tool, streaming, timeout,
  and token-accounting contract tests.
- [ ] Provider privacy terms, secrets, backup/restore, incident response, and
  rollback evidence are reviewed for the deployment target.
- [x] The full local repository suite passes after Stage 3 (1,157 passed, 30 skipped).
- [ ] The final deployment smoke gate passes.

## Review Boundaries

This was an implementation review plus the focused local test run
listed above. The review did not read `.env`, inspect customer data, call a live
LLM, mutate a real MongoDB/Redis deployment, run load tests, or validate a
production proxy/cloud environment. Those are release conditions, not verified
facts.
