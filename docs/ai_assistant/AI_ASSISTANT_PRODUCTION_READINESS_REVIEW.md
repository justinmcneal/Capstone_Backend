# AI Assistant Production Readiness Review

Last source review: 2026-08-15

Scope: backend `ai_assistant` HTTP/SSE routes, customer authorization and consent, provider communication, read-only tools, MongoDB persistence, privacy lifecycle, rate controls, observability, release checks, and focused automated tests.

## 1. Overview

The AI Assistant domain provides customer-facing loan education and account-aware guidance. It exposes non-streaming chat, Server-Sent Events (SSE) chat, owner-scoped history, conversation suggestions, provider status, static education topics, and FAQs. Chat may invoke a fixed set of backend read-only tools for the authenticated customer's profile, documents, applications, repayment, payment history, products, readiness, dashboard, and notifications.

Only authenticated customers are supported. No AI route for loan officers or administrators is registered. Current data and AI consent is required for chat, streaming, and history processing. Static suggestions, status, education, and FAQ routes require an authenticated customer but do not require AI consent.

This review is based primarily on current source and focused tests. Historical documentation is treated as supporting context, not proof of current deployment state. The current checkout demonstrates substantial application-level controls, but it does **not** by itself establish production readiness. The most important source-verified gaps are:

- the non-streaming filtered-response field does not match the normal chat contract or current mobile client;
- provider-generated streamed text bypasses the non-streaming response-validation boundary;
- interaction retention depends on a live Celery beat/worker path rather than a MongoDB TTL index;
- customer identifiers are written to several AI logs/cache keys;
- provider privacy, real MongoDB/Redis behavior, proxy streaming, monitoring, load, recovery, and release approval remain environment-dependent.

Evidence labels used below:

- **Source-verified**: directly supported by current implementation.
- **Test-verified**: exercised by the focused automated suite in this checkout.
- **Unverified operational concern**: requires selected infrastructure, credentials, traffic, or operator evidence not exercised by this review.

## 2. Current Architecture

The request path is:

```text
config/urls.py
  -> ai_assistant/urls.py
  -> ai_assistant/views/*
  -> request validation, authorization, consent, and throttling
  -> ai_assistant/services/*
  -> ai_assistant/models/* and customer-domain read models
  -> Groq or Ollama through the provider boundary
  -> JSON response or SSE stream
```

| Layer | Current responsibility | Primary evidence |
| --- | --- | --- |
| Root routing | Mounts the domain at `/api/ai/` | [`config/urls.py`](../../config/urls.py) |
| Domain routing | Registers chat, stream, history, suggestions, status, education, and FAQ routes | [`ai_assistant/urls.py`](../../ai_assistant/urls.py) |
| Views | Authentication, customer/consent gates, request/response shaping, throttling, SSE framing, persistence orchestration | [`views/chat.py`](../../ai_assistant/views/chat.py), [`views/streaming.py`](../../ai_assistant/views/streaming.py), [`views/history.py`](../../ai_assistant/views/history.py), [`views/auxiliary.py`](../../ai_assistant/views/auxiliary.py) |
| Validation | Message byte/character limits, UUID request IDs, UUID conversation IDs, `en`/`tl` language checks, history bounds | [`services/request_limits.py`](../../ai_assistant/services/request_limits.py) and the views |
| Prompt/knowledge | Versioned platform knowledge, system prompt, deterministic input policy checks | [`services/knowledge_base.py`](../../ai_assistant/services/knowledge_base.py) |
| Customer context | Builds bounded profile, document, loan, balance, and payment summaries | [`services/context_builder.py`](../../ai_assistant/services/context_builder.py) |
| Provider adapter | Selects Groq or Ollama, formats chat/tool requests, parses provider responses and streams | [`services/llm_service.py`](../../ai_assistant/services/llm_service.py) |
| Provider resilience | Connect/read timeouts, safe readiness retries, per-process concurrency guard and circuit breaker | [`services/provider_boundary.py`](../../ai_assistant/services/provider_boundary.py) |
| Tool boundary | Fixed schemas and read-only customer-scoped data functions | [`services/tools.py`](../../ai_assistant/services/tools.py) |
| Tool safety | Shared-cache budgets, parameter validation, metadata-only audit, generic failures | [`services/tool_safety.py`](../../ai_assistant/services/tool_safety.py) |
| Response control | Reviewed deterministic answers and non-streaming provider-output checks | [`services/response_controls.py`](../../ai_assistant/services/response_controls.py) |
| Persistence | Encrypted interactions/history and metadata-only tool activity | [`models/interaction.py`](../../ai_assistant/models/interaction.py), [`models/activity_event.py`](../../ai_assistant/models/activity_event.py) |
| Request idempotency | Lease, conflict, replay, failure, and request retention state | [`services/idempotency.py`](../../ai_assistant/services/idempotency.py) |
| Privacy lifecycle | Retention, export, deletion/pseudonymization, inventory, and backfill support | [`services/lifecycle.py`](../../ai_assistant/services/lifecycle.py) |
| Operations | Fail-closed read-only release report over configuration/evidence flags, indexes, validators, quality report, and monitoring assets | [`services/operations.py`](../../ai_assistant/services/operations.py), [`ai_release_check.py`](../../ai_assistant/management/commands/ai_release_check.py) |
| Observability | Low-cardinality Prometheus metrics plus alert/dashboard assets | [`metrics.py`](../../ai_assistant/metrics.py), [`monitoring/ai_assistant/`](../../monitoring/ai_assistant/) |

There is no `ai_assistant/serializers/` package in the current source. Validation and response shaping are implemented directly in views and small service helpers. This is an architectural fact, not evidence that DRF serializer validation is active for these routes.

## 3. Current API and Data Flow

### Exposed operations

The table uses each complete path exactly as registered by the root and domain URL configurations.

| Method | Path | Verified inputs | Verified output/behavior |
| --- | --- | --- | --- |
| `POST` | `/api/ai/chat/` | Required `message`; optional UUID `conversation_id`; optional `language` (`en`, `tl`); optional UUID `Idempotency-Key` header | Wrapped JSON containing the assistant response, conversation/model/timing/request metadata, or a stable error |
| `POST` | `/api/ai/chat/stream/` | Same chat body/header contract | SSE events: `tool_call`, `tool_result`, `token`, and exactly one `done` or `error` terminal event |
| `GET` | `/api/ai/history/` | `page`, `limit` (capped at 100), `search`; optional cursor mode through `cursor` or `pagination=cursor` | Owner-scoped messages, pagination metadata, and signed next cursor |
| `DELETE` | `/api/ai/history/` | No body | Deletes ordinary history and hides held records from customer history; returns `deleted_count` |
| `GET` | `/api/ai/suggestions/` | Optional `language` (`en`, `tl`) | Cached static conversation starters |
| `GET` | `/api/ai/status/` | No body | Provider, model, configuration, reachability, authentication, model availability, state, and circuit fields |
| `GET` | `/api/ai/education/` | No body | Cached education topic list |
| `GET` | `/api/ai/education/<topic>/` | Topic path value | Cached topic content or `404` |
| `GET` | `/api/ai/faqs/` | No body | Cached static FAQ list |

### Non-streaming chat flow

1. `CustomJWTAuthentication`, `IsAuthenticated`, `ChatRateThrottle`, customer role, and current data/AI consent are enforced.
2. The kill switch, request size/message rules, optional idempotency UUID, conversation UUID, and language are validated.
3. `ai_chat_requests` claims the request. Conflicting reuse and active duplicates return `409`; completed exchanges replay without another provider call.
4. At most ten owner-scoped conversation rows are loaded; the provider adapter sends at most the last six history messages.
5. The deterministic prohibited-content boundary may return a reviewed response before provider/tool access.
6. The selected provider is synchronously probed for readiness. When personal context is indicated, a bounded context summary is appended to the system prompt.
7. The provider may request only the fixed tool schemas. Tools receive the authenticated `customer_id`, not a model-supplied owner identifier.
8. Final non-streaming provider text passes `validate_provider_response()`, then is sanitized/escaped.
9. User and assistant rows are saved as one idempotent exchange, the request is marked complete, metrics/logs are emitted, and wrapped JSON is returned.

Normal success uses `data.response`. The filtered branch currently uses `data.message`; this is a verified contract inconsistency described in Section 9.

### Streaming flow

The pre-stream checks mirror normal chat. Tool rounds are completed through non-streaming provider calls; the final answer is then streamed. Each token is escaped before SSE emission, while raw chunks are accumulated and sanitized/escaped before persistence. Persistence occurs only after a provider `done` event with non-empty content. Malformed, truncated, empty, disconnected, or unterminated streams produce an error, mark the idempotency lease failed, close the upstream generator/response, and do not persist partial output.

The current Flutter customer app is a verified caller. Retrofit defines all JSON endpoints, while `LearnStreamingService` consumes `POST /ai/chat/stream/`. The mobile repository reads the non-streaming assistant text from `data.response`. Evidence: [`learn_api_service.dart`](../../../MSME-Pathways-Mobile/lib/data/datasources/remote/learn_api_service.dart), [`learn_streaming_service.dart`](../../../MSME-Pathways-Mobile/lib/data/datasources/remote/learn_streaming_service.dart), and [`learn_repository_impl.dart`](../../../MSME-Pathways-Mobile/lib/data/repositories/learn_repository_impl.dart).

## 4. Authentication, Authorization, and Ownership

**Source-verified controls:**

- Every registered AI view declares `CustomJWTAuthentication` and `IsAuthenticated`.
- Every view calls the shared customer-role boundary. Staff roles are not accepted merely because they possess a valid token.
- Custom authentication validates the live account, verification/active state, account state, session, token blacklist, and security version before constructing the authenticated user.
- Chat, stream, and history require current-policy `data_consent=true` and `ai_consent=true`; consent failures fail closed.
- Customer identity is derived from `request.user.customer_id` and is injected server-side into persistence and tools.
- Conversation history queries include both `conversation_id` and customer ownership. History list/delete operations are owner-scoped.
- Profile, document, application, repayment, payment, dashboard, and notification tool queries are built from the authenticated customer ID. Unknown tool names fail closed.
- Customer caches are separated by tool name and customer ID.

**Evidence:** [`accounts/authentication.py`](../../accounts/authentication.py), [`accounts/utils/access_control.py`](../../accounts/utils/access_control.py), [`accounts/services/consent_service.py`](../../accounts/services/consent_service.py), [`views/chat.py`](../../ai_assistant/views/chat.py), [`models/interaction.py`](../../ai_assistant/models/interaction.py), and [`services/tools.py`](../../ai_assistant/services/tools.py).

**Boundary:** static suggestions, status, education, and FAQs do not process stored conversation history and intentionally require authentication/customer role without AI consent. This review verified source enforcement and local tests; it did not perform a two-account staging isolation exercise or inspect deployed token/cookie behavior.

## 5. AI Safety, Privacy, and Security

### Implemented controls

- Message size is bounded by request bytes, message bytes, and sanitized character length. Conversation IDs and idempotency keys must be UUIDs; language is limited to English or Tagalog.
- The system prompt explicitly treats user/history/tool content as untrusted, forbids hidden-prompt disclosure and cross-customer access, and prohibits invented customer/financial facts.
- A deterministic input filter blocks recognized prompt-injection, cross-customer disclosure, credential collection/reveal, approval guarantees, and selected legal/profit requests before provider or tool calls.
- Stable high-confidence intents can use reviewed deterministic guidance without provider access.
- Non-streaming provider text is checked for raw tool names, unsupported tool claims, unapproved UI controls, delivery guarantees, and obvious language mismatch.
- Tool execution is a fixed read-only allowlist. Parameters are validated, per-request tool calls are capped, and shared-cache minute/hour cost budgets are reserved before validation/execution.
- Tool audits persist only a keyed subject, request ID, allowlisted tool name, outcome, duration, cost, and timestamps. Prompts, responses, parameters, raw customer IDs, and error text are excluded.
- Interaction `message`, `response`, and legal-hold reason use the shared field-encryption boundary. Production startup requires a valid encryption key, and strict decryption is part of the release gate.
- History search uses keyed HMAC tokens rather than plaintext search terms.
- Public provider failures are generic and do not include raw provider bodies or exception details.

### Data sent to a provider

With current consent, provider requests may include the sanitized user message, up to six recent conversation messages, system instructions, selected context, fixed tool schemas, and tool results. Depending on intent/tool use, source-verified provider-visible data may include business name/type/income, profile completion and risk category, document types/statuses, application amounts/status/purpose, repayment amounts/dates/penalties, recent payment references, dashboard counts, and notification subjects/statuses.

The implementation does not send passwords, OTPs, private keys, uploaded document bytes, storage paths, or document filenames through the reviewed context/tool shapes. Provider privacy/legal approval remains a release condition; the read-only release check records `AI_ASSISTANT_PROVIDER_PRIVACY_APPROVED` but does not itself validate a provider's retention, training, residency, egress, or subcontractor behavior.

### Source-verified safety/privacy concerns

- Streamed provider text is escaped but does not pass the non-streaming response validator before reaching the customer.
- The declared prohibited-topic list is broader than deterministic enforcement. Medical, political, investment, competitor, and general off-topic restrictions rely mainly on prompt compliance; the output validator does not enforce those categories.
- Raw customer IDs appear in AI stream-start, context-build, history-clear, and some failure logs; per-user tool cache keys also contain the raw ID.
- `ai_chat_requests.request_fingerprint` is an unkeyed SHA-256 digest of message, conversation value, and language. Common new-conversation prompts may be susceptible to offline dictionary matching by a database reader.

## 6. Reliability and Provider Resilience

**Source-verified behavior:**

- Exactly one provider is selected from validated settings: Groq or Ollama. There is no cross-provider automatic fallback.
- Default connect/read timeouts are 5/120 seconds and are bounded at startup.
- Only readiness `GET` requests receive bounded retry/backoff. Paid/non-idempotent chat `POST` calls are deliberately not retried.
- A per-process bounded semaphore rejects excess provider concurrency, and a per-process circuit opens after configured failures and recovers after a configured interval.
- Provider readiness distinguishes not configured, authentication failed, model unavailable, degraded, available, and circuit-open conditions.
- Chat failures return stable `503` codes such as `AI_PROVIDER_UNAVAILABLE`, `AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_BUSY`, or `AI_PROVIDER_CIRCUIT_OPEN` where classified.
- Idempotency leases prevent duplicate work when a caller reuses a stable UUID key. Stale/failed requests are reclaimable; complete exchanges replay.
- SSE parsing rejects malformed JSON/UTF-8 and missing provider terminal markers. Application streaming rejects empty/incomplete streams, emits a correlated terminal error, closes upstream resources, and avoids partial persistence.
- `AI_ASSISTANT_ENABLED=False` prevents new chat/provider work and is surfaced by the status route.

**Limitations:**

- Provider concurrency and circuit state are local to each application process. Effective concurrency scales with worker count and one worker's open circuit does not protect another.
- Every chat and stream performs a live readiness request before the actual provider request. The status route also performs a live readiness request and has no explicit throttle or short-lived readiness cache.
- Stable idempotency requires the caller to send the same `Idempotency-Key` on retry. The current mobile chat and streaming services do not set that header, so backend-generated IDs cannot deduplicate a client retry after an ambiguous network failure.
- No deployment fallback answer is returned for provider outage beyond deterministic policy/guidance paths and stable service-unavailable errors.

## 7. Data Integrity and Persistence

| Collection | Purpose | Important verified controls |
| --- | --- | --- |
| `ai_interactions` | User and assistant history | Owner/conversation/request metadata; encrypted content; UTC timestamps; retention/legal-hold metadata; signed cursor/search indexes; unique request/role pair |
| `ai_chat_requests` | Idempotency lease and replay state | Owner/request unique key; fingerprint; processing/complete/failed state; lease/recovery index; TTL expiry |
| `ai_activity_events` | Metadata-only tool audit | Keyed owner subject; fixed tool/outcome enums; request correlation; duration/cost; TTL expiry |

User/assistant pairs use a MongoDB transaction when supported. The development/mongomock fallback uses repeatable `$setOnInsert` upserts that can repair an interrupted pair without duplicating rows. Validators and required indexes are defined and the release check inspects their presence; installation occurs through controlled database initialization and was not performed by this review.

New interactions default to a 365-day versioned retention period. A daily Celery task deletes bounded batches of expired, non-held interactions. Held rows survive retention, are hidden on customer history clear, and are pseudonymized during final account deletion. Account export uses a bounded allowlist. `ai_chat_requests` uses a TTL index aligned with interaction retention; `ai_activity_events` defaults to a 90-day TTL.

Timestamps are timezone-aware UTC at write time and history returns ISO-8601 strings. Customer IDs support legacy `ObjectId` and string reads; new exchange writes canonicalize to string.

No AI feedback endpoint, feedback model, or feedback collection was found. Tool audit is present, but there is no separate append-only audit of every chat decision beyond interaction/request metadata and ordinary logs/metrics.

## 8. Performance, Scalability, and Operations

### Implemented behavior

- Chat request rate defaults to 100 per customer per hour through DRF and the configured shared cache in production.
- Tool cost defaults to 30 per minute and 200 per hour per customer, with weighted expensive tools and atomic cache increments.
- Per-request output tokens, tool rounds, and total tool calls are capped.
- Multiple tool calls may execute concurrently with at most four local threads; total provider requests are separately bounded per process.
- Static suggestions, education, and FAQ responses are cached. Selected owner-scoped tool results use 30-60 second caches; loan products use a shared 30-minute cache.
- Conversation loading is bounded. History supports signed keyset pagination and capped offset pages/search length. Tool queries use limits/projections in many high-volume paths.
- SSE disables response caching and requests reverse-proxy buffering be disabled with `X-Accel-Buffering: no`.
- Metrics cover request/provider/tool outcomes and latency, tool-budget rejection, tokens, active streams, and audit/persistence failures. Prometheus rules and a Grafana dashboard are present.
- A read-only release command fails closed unless configuration, encryption, shared cache, MongoDB indexes/validators, quality evidence, monitoring assets, provider/privacy attestations, proxy/Redis/load/recovery checks, and rollback approval are all recorded.

### Operational boundaries

- Prometheus metrics and the optional metrics HTTP server default to disabled. Asset presence does not prove deployed scrape, dashboard import, alert delivery, or on-call response.
- The configured `ai_assistant` logger has no dedicated handler/formatter in `LOGGING`; common `request_id`, provider, tool, timing, and outcome values are supplied as `extra` fields but the configured simple formatter prints only level/time/message.
- No live first-token metric is implemented, despite first-token latency being a meaningful SSE signal.
- Celery scheduling is required for `ai_interactions` retention. The release check verifies configuration/evidence flags but does not directly verify recent successful retention-task execution.
- The sync HTTP provider client and sync `StreamingHttpResponse` keep a worker/thread and upstream socket active for each stream. Slow-client, worker, socket, memory, and file-descriptor behavior requires production-like load validation.
- Cache atomicity is shared only when all workers use the same Redis cache. Development in-memory cache evidence cannot establish multi-worker enforcement.

## 9. Production Readiness Assessment

Priority definitions: **P0/Critical** blocks use immediately; **P1/High** blocks production approval; **P2/Medium** requires mitigation or explicit risk acceptance; **P3/Low** is hardening/documentation work.

### Source-verified findings

| Area | Current behavior and evidence | Production impact | Priority | Recommended remediation |
| --- | --- | --- | --- | --- |
| Correctness / API contract | Normal chat returns `data.response`, but the deterministic filtered branch returns `data.message`. The current mobile repository reads only `data.response`, while the backend test explicitly expects `message`. Evidence: [`views/chat.py`](../../ai_assistant/views/chat.py), [`test_chatbot_api.py`](../../tests/test_chatbot_api.py), [`learn_repository_impl.dart`](../../../MSME-Pathways-Mobile/lib/data/repositories/learn_repository_impl.dart). | A prohibited non-streaming request can display an empty assistant message in the verified client despite a successful backend response. | **P1 / High** | Standardize every successful chat branch on the documented `response` field (or version the contract), then add backend-client contract coverage for filtered, replayed, controlled, and provider responses. |
| AI safety | Non-streaming provider text passes `validate_provider_response()`. Streaming sends escaped provider tokens directly and persists their concatenation without that semantic validation. Evidence: [`services/llm_service.py`](../../ai_assistant/services/llm_service.py), [`views/streaming.py`](../../ai_assistant/views/streaming.py), [`services/response_controls.py`](../../ai_assistant/services/response_controls.py). | Raw streamed output can expose internal tool names, unsupported tool claims, wrong-language text, delivery guarantees, or other content that non-streaming chat would replace. | **P1 / High** | Add a streaming-compatible moderation/validation design: buffer before release for high-risk paths, incrementally abort on enforceable violations, or route controlled intents away from raw streaming; add parity tests. |
| Privacy / retention | `ai_interactions` has a retention query index but no TTL index because legal holds require conditional deletion. Expiry depends on the daily Celery task. Evidence: [`models/interaction.py`](../../ai_assistant/models/interaction.py), [`tasks.py`](../../ai_assistant/tasks.py), [`config/celery.py`](../../config/celery.py). | A stopped/misconfigured beat or worker can retain customer conversations beyond policy without automatic database expiry. | **P1 / High** | Monitor task freshness/deletion counts, alert on overdue runs/backlog, include scheduler/worker health in the release gate, and rehearse failure recovery. Preserve legal-hold semantics. |
| Safety policy coverage | `PROHIBITED_TOPICS` names financial, competitor, legal, investment, political, and medical categories, but deterministic input filtering covers only a subset; the output validator also checks a narrower set. Evidence: [`services/knowledge_base.py`](../../ai_assistant/services/knowledge_base.py), [`services/response_controls.py`](../../ai_assistant/services/response_controls.py). | Long-tail provider responses rely on prompt compliance for several declared safety categories. | **P2 / Medium** | Make the executable policy match the declared policy, define category-specific expected behavior, and add bilingual adversarial/output tests for every prohibited category. |
| Privacy / logging | Stream start, context build/failure, history clear, consent failure, and cache invalidation paths can log raw customer IDs; owner-scoped tool cache keys contain the raw ID. Evidence: [`views/streaming.py`](../../ai_assistant/views/streaming.py), [`views/history.py`](../../ai_assistant/views/history.py), [`services/context_builder.py`](../../ai_assistant/services/context_builder.py), [`services/tools.py`](../../ai_assistant/services/tools.py). | Logs/cache metadata can create unnecessary linkable customer identifiers and widen operator exposure. | **P2 / Medium** | Use request IDs and keyed subject digests, remove raw identifiers from routine messages/cache names where practical, and enforce structured redaction/retention/access controls. |
| Privacy / persistence | The idempotency fingerprint is plain SHA-256 over message, conversation value, and language. Evidence: [`services/idempotency.py`](../../ai_assistant/services/idempotency.py). | Common prompts—especially new conversations with an empty supplied conversation value—may be testable through offline dictionary matching if request metadata is exposed. | **P2 / Medium** | Use a keyed HMAC/domain-separated digest with rotation support, or fingerprint only non-content request identity while preserving conflict detection. |
| Reliability / performance | Each chat/stream first calls provider readiness, then calls chat; `/status/` also performs provider I/O without an explicit throttle or readiness cache. Evidence: [`views/chat.py`](../../ai_assistant/views/chat.py), [`views/streaming.py`](../../ai_assistant/views/streaming.py), [`views/auxiliary.py`](../../ai_assistant/views/auxiliary.py), [`services/llm_service.py`](../../ai_assistant/services/llm_service.py). | Extra provider requests add latency and can amplify outages, model-list rate limits, or status polling into avoidable load. | **P2 / Medium** | Cache readiness briefly, separate liveness from provider diagnostics, throttle the diagnostic route, and let the actual bounded chat request remain authoritative for request-time failure. |
| Reliability / capacity | Circuit and semaphore state are process-local. Evidence: module-global [`provider_session`](../../ai_assistant/services/provider_boundary.py). | Total provider concurrency equals per-process limit multiplied by worker count; failure isolation/circuit behavior differs between workers. | **P2 / Medium** | Define worker-aware capacity, validate under the target topology, and use shared provider budgeting/circuit state if aggregate protection is required. |
| Reliability / client retries | Backend idempotency works only with a stable caller key; the verified mobile JSON/SSE callers do not set `Idempotency-Key`. Evidence: [`services/request_limits.py`](../../ai_assistant/services/request_limits.py), [`learn_api_service.dart`](../../../MSME-Pathways-Mobile/lib/data/datasources/remote/learn_api_service.dart), [`learn_streaming_service.dart`](../../../MSME-Pathways-Mobile/lib/data/datasources/remote/learn_streaming_service.dart). | A retry after a timeout/disconnect can create another paid provider call and another exchange because the server-generated key is unknown to the client. | **P2 / Medium** | Generate and retain a UUID per user send attempt in the client, reuse it for safe retries, and test ambiguous network outcomes. |
| Observability | AI metrics/rules/dashboard exist, but metrics default off; AI log `extra` fields are not included by the configured simple formatter and no dedicated AI logger is configured. Evidence: [`metrics.py`](../../ai_assistant/metrics.py), [`config/settings.py`](../../config/settings.py), [`monitoring/ai_assistant/`](../../monitoring/ai_assistant/). | Correlation and alert assets may not be visible in an actual incident even though source emits them. | **P2 / Medium** | Enable and scrape metrics in the selected environment, route/test alerts, add structured AI log formatting with correlation fields, and validate privacy-safe log output. |
| Documentation / schema inventory | Workspace schema documentation lists `ai_interactions` but not the source-verified `ai_chat_requests` and `ai_activity_events` collections. Evidence: [`DATABASE_SCHEMA.md`](../../../docs/DATABASE_SCHEMA.md) versus the models/services above. | Operators reviewing only the schema map may omit TTL/index/backup/privacy checks for two AI collections. | **P3 / Low** | Update the workspace schema map in a separately scoped documentation change. |

### Verified strengths

| Area | Current behavior | Evidence level |
| --- | --- | --- |
| Authentication and ownership | Customer-only live-session authentication; current consent on personal AI flows; owner-scoped history/tools | Source-verified and focused-test coverage |
| Persistence correctness | Idempotent exchange pairs, transaction when available, repairable upsert fallback, signed cursor pagination, validators/index definitions | Source-verified and local mongomock/unit coverage; real MongoDB skipped in this run |
| Privacy lifecycle | Production-required encryption, keyed search, retention metadata, legal hold, export and deletion/pseudonymization | Source-verified and focused-test coverage |
| Tool security | Fixed read-only allowlist, trusted customer ID, bounds, atomic cost budgets, metadata-only audit | Source-verified and focused-test coverage |
| Provider failure handling | Bounded timeouts, readiness-only retry, circuit/concurrency controls, generic errors, no automatic paid-POST retry | Source-verified and focused-test coverage |
| Streaming correctness | Exact SSE framing, terminal-event enforcement, incomplete/empty failure behavior, upstream close on disconnect, no partial persistence | Source-verified and focused-test coverage |
| Release governance | Synthetic quality gate, opt-in deployment probes, and fail-closed read-only release check | Source-verified; external evidence not rerun here |

### Unverified deployment concerns

These are not asserted defects in source; they are release evidence that this review did not establish:

- selected Groq/Ollama contract, model availability, privacy terms, data residency, retention/training behavior, network egress, and credential rotation;
- target MongoDB validators, indexes, transactions, query plans, backup/restore, legal-hold operations, and current inventory/backfill state;
- shared Redis atomicity across real application workers and cache eviction/failure behavior;
- reverse-proxy incremental SSE delivery, buffering, idle timeout, disconnect propagation, and CORS/CSRF behavior through the deployed path;
- expected/peak load, slow-client resource use, provider quota/cost, and worker/socket/file-descriptor capacity;
- live Prometheus scrape, dashboard provisioning, alert firing/recovery/routing, log ingestion/redaction, and on-call ownership;
- Celery beat/worker health, retention-task freshness/backlog, incident kill-switch restart procedure, and rollback approval;
- production/staging mobile end-to-end behavior, including filtered JSON display and stable idempotency keys.

## 10. Existing Tests and Verification Coverage

Fresh local command on 2026-08-15:

```powershell
$aiTests = Get-ChildItem -LiteralPath 'tests' -File -Filter 'test_ai_*.py' |
  Sort-Object Name | ForEach-Object { $_.FullName }
$extraTests = @(
  'tests\test_chatbot_api.py',
  'tests\test_context_builder.py',
  'tests\test_tool_safety.py',
  'tests\test_documents_ai_consent.py'
)
.\venv\Scripts\python.exe -m pytest -q @aiTests @extraTests
```

Result: **242 passed, 7 skipped, 62 warnings**. The seven skips are explicitly opt-in real MongoDB (2) and provider/Redis/proxy/load deployment probes (5). The warnings were dependency deprecations and did not fail the suite.

| Test group | What it proves in this checkout |
| --- | --- |
| [`test_chatbot_api.py`](../../tests/test_chatbot_api.py), [`test_ai_streaming.py`](../../tests/test_ai_streaming.py) | Route/view validation, consent, filtering, status/static content, history, JSON/SSE success and error shapes, persistence orchestration |
| [`test_ai_knowledge.py`](../../tests/test_ai_knowledge.py), [`test_ai_provider_safety_boundary.py`](../../tests/test_ai_provider_safety_boundary.py), [`test_ai_response_controls.py`](../../tests/test_ai_response_controls.py) | Prompt policy content, deterministic prohibited/controlled responses, non-streaming provider-response replacement |
| [`test_ai_context_builder.py`](../../tests/test_ai_context_builder.py), [`test_context_builder.py`](../../tests/test_context_builder.py) | Context selection, summarization, bounds, and helper behavior |
| [`test_ai_stage1_privacy_lifecycle.py`](../../tests/test_ai_stage1_privacy_lifecycle.py) | Encryption, blind search, retention/legal hold, export, deletion/pseudonymization, inventory/backfill behavior |
| [`test_ai_stage2_provider_boundary.py`](../../tests/test_ai_stage2_provider_boundary.py) | Request limits, throttle configuration, provider validation/readiness, timeout/retry/circuit/concurrency behavior, generic failures |
| [`test_ai_stage3_persistence_scalability.py`](../../tests/test_ai_stage3_persistence_scalability.py), [`test_ai_model_methods.py`](../../tests/test_ai_model_methods.py) | Idempotent exchange, lease/replay, signed cursor, bounded conversation query, index/validator shape, owner filters |
| [`test_ai_stage4_observability.py`](../../tests/test_ai_stage4_observability.py), [`test_tool_safety.py`](../../tests/test_tool_safety.py), [`test_ai_tool_safety_integration.py`](../../tests/test_ai_tool_safety_integration.py) | Atomic budgets, parameter bounds, safe execution, metadata-only audit, metric-label normalization, monitoring asset structure |
| [`test_ai_stage5_streaming_correctness.py`](../../tests/test_ai_stage5_streaming_correctness.py) | Malformed/truncated/empty/incomplete/disconnect handling, terminal events, escaping/persistence, request correlation |
| [`test_ai_stage6_quality_release.py`](../../tests/test_ai_stage6_quality_release.py) | Offline synthetic evaluation/report binding and fail-closed release-check logic |
| [`test_documents_ai_consent.py`](../../tests/test_documents_ai_consent.py) | AI consent boundary for document AI behavior and consent reporting |

Important paths without current automated proof:

- parity between non-streaming filtered responses and the mobile client's expected field;
- semantic output validation/moderation of provider-generated streamed text;
- live Celery retention execution/freshness and backlog alerting;
- dedicated structured AI logging/redaction behavior;
- provider privacy/data-handling guarantees;
- real multi-worker Redis/provider capacity and circuit behavior;
- staging/production SSE proxy and mobile end-to-end behavior.

The focused pass does **not** claim live-provider, live-Redis, real-MongoDB, SSE proxy, load, deployment, alert-route, backup/restore, or production validation. The skipped tests are executable probes, not completed evidence.

## 11. Production Validation Checklist

### Authorization and data isolation

- [ ] In staging, verify anonymous, expired/revoked-session, staff-role, inactive, unverified, and forced-password-change requests are rejected as designed.
- [ ] With two synthetic customers, verify conversation ID reuse, history search/cursor, clear-history, every tool, caches, and notifications never cross owners.
- [ ] Revoke current AI consent and verify chat, stream, and history fail closed while intended static customer content remains available.
- [ ] Confirm the deployed web/mobile authentication transport and CSRF behavior without exposing tokens or cookies in evidence.

### Safety and privacy

- [ ] Resolve the non-streaming filtered-response field mismatch and add client contract proof.
- [ ] Establish streaming response-control parity and run bilingual adversarial tests through the actual SSE endpoint.
- [ ] Review the exact provider-visible context/tool fields against the approved privacy notice, data-processing terms, residency, retention/training, and egress policy. **Requires selected provider/privacy approval and real credentials.**
- [ ] Verify no prompts, responses, tool arguments, provider bodies, credentials, raw customer IDs, or sensitive financial/profile data appear in deployed logs, metrics labels, traces, or cache keys.
- [ ] Verify encryption, strict decryption, search-key rotation, legal holds, account export, history clearing, final deletion, and pseudonymization on an isolated production-like database.

### Provider and failure behavior

- [ ] Verify selected model readiness, normal chat, tool chat, streaming, malformed/truncated stream, timeout, authentication failure, quota/429, circuit open/recovery, and kill switch. **Requires real provider credentials or approved private provider infrastructure.**
- [ ] Confirm paid provider POSTs are not duplicated on ambiguous client retries; use stable client idempotency keys.
- [ ] Validate worker-count-aware provider concurrency and aggregate quotas under representative traffic.

### Streaming and performance

- [ ] Through the target ASGI server and reverse proxy, confirm content type, incremental delivery, no buffering, exactly one terminal event, idle/read timeouts, and upstream cancellation after client disconnect. **Requires staging proxy/infrastructure.**
- [ ] Load test normal chat, tool-heavy chat, slow SSE clients, status polling, and provider degradation at expected and peak concurrency. **Requires production-like traffic and approved cost limits.**
- [ ] Measure first-token, total latency, memory, CPU, sockets/file descriptors, provider tokens/cost, cache hit rate, and MongoDB query plans.

### Persistence and operations

- [ ] Run the read-only inventory and review dry runs before any approved index/validator/backfill operation.
- [ ] Verify all required indexes and validators on `ai_interactions`, `ai_chat_requests`, and `ai_activity_events` in the target database. **Requires isolated/approved MongoDB access.**
- [ ] Verify daily retention execution, deletion counts, legal-hold exclusion, task freshness alerting, and recovery from a stopped beat/worker.
- [ ] Rehearse encrypted backup/restore, key rotation, provider credential rotation, incident disable/restart, rollback, and evidence cleanup. **Requires staging operations and owner approval.**

### Monitoring and release gate

- [ ] Enable/scrape AI metrics, import the dashboard/rules, generate synthetic API traffic, and verify every alert fires, routes, acknowledges, and recovers. **Requires monitoring infrastructure.**
- [ ] Confirm structured correlation from HTTP request through provider/tool/audit/persistence without sensitive content.
- [ ] Generate and approve the provider/model-bound quality report using synthetic data only.
- [ ] Set evidence flags only after the corresponding artifact is reviewed; then run `python manage.py ai_release_check` in the selected release environment.
- [ ] Record rollback authority, on-call owner, provider outage behavior, retention owner, and final production approval.

## 12. Important Source Files

| File | Responsibility |
| --- | --- |
| [`config/urls.py`](../../config/urls.py) | Root `/api/ai/` mount |
| [`ai_assistant/urls.py`](../../ai_assistant/urls.py) | Authoritative AI endpoint registry |
| [`views/chat.py`](../../ai_assistant/views/chat.py) | Non-streaming request orchestration |
| [`views/streaming.py`](../../ai_assistant/views/streaming.py) | SSE request orchestration and persistence |
| [`views/history.py`](../../ai_assistant/views/history.py) | Owner-scoped history list/search/cursor/delete |
| [`views/auxiliary.py`](../../ai_assistant/views/auxiliary.py) | Suggestions, provider status, education, FAQs |
| [`services/request_limits.py`](../../ai_assistant/services/request_limits.py) | Message/request and idempotency UUID validation |
| [`services/knowledge_base.py`](../../ai_assistant/services/knowledge_base.py) | System prompt, static knowledge, prohibited-input policy |
| [`services/context_builder.py`](../../ai_assistant/services/context_builder.py) | Bounded customer context summaries |
| [`services/llm_service.py`](../../ai_assistant/services/llm_service.py) | Groq/Ollama adapter, tool rounds, provider parsing |
| [`services/provider_boundary.py`](../../ai_assistant/services/provider_boundary.py) | Timeouts, retry policy, circuit, concurrency slots |
| [`services/response_controls.py`](../../ai_assistant/services/response_controls.py) | Deterministic guidance and non-streaming output validation |
| [`services/tools.py`](../../ai_assistant/services/tools.py) | Tool schemas and read-only owner-scoped queries |
| [`services/tool_safety.py`](../../ai_assistant/services/tool_safety.py) | Tool validation, budgets, audit, safe errors |
| [`services/idempotency.py`](../../ai_assistant/services/idempotency.py) | Request lease, replay, conflict, recovery state |
| [`models/interaction.py`](../../ai_assistant/models/interaction.py) | Encrypted history, search, cursor, exchange, indexes/validator |
| [`models/activity_event.py`](../../ai_assistant/models/activity_event.py) | Metadata-only tool audit and TTL |
| [`services/lifecycle.py`](../../ai_assistant/services/lifecycle.py) | Retention, export, deletion, inventory/backfill |
| [`services/operations.py`](../../ai_assistant/services/operations.py) | Read-only release readiness aggregation |
| [`metrics.py`](../../ai_assistant/metrics.py) | AI Prometheus instruments |
| [`tasks.py`](../../ai_assistant/tasks.py), [`config/celery.py`](../../config/celery.py) | Daily interaction-retention execution/schedule |
| [`init_db.py`](../../init_db.py) | Controlled creation of AI indexes/validators; state-changing and not run in this review |
| [`tests/test_chatbot_api.py`](../../tests/test_chatbot_api.py) and [`tests/test_ai_stage1_privacy_lifecycle.py`](../../tests/test_ai_stage1_privacy_lifecycle.py) through [`tests/test_ai_stage6_quality_release.py`](../../tests/test_ai_stage6_quality_release.py) | Focused behavior and release-control evidence |

## 13. Known Limitations and Open Risks

- The current checkout is not sufficient evidence to approve production deployment.
- Non-streaming filtered responses are incompatible with the verified mobile response mapper.
- Streaming output does not receive the semantic validation used by non-streaming output.
- Several declared prohibited topics rely on model/system-prompt compliance.
- Conversation retention depends on successful recurring background work.
- Raw customer IDs are present in selected log/cache metadata paths.
- Idempotency metadata uses an unkeyed content-derived fingerprint.
- The selected provider is a single dependency; no automatic provider failover exists.
- Provider circuit/concurrency protection is per process, and status/readiness adds synchronous provider traffic.
- The current mobile client does not supply a stable idempotency key for chat retries.
- Metrics, dashboards, alerts, structured log correlation, Celery freshness, and release attestations are implemented or represented in source but not verified against a deployed environment in this review.
- Real MongoDB, shared Redis, provider, proxy, load, recovery, and production-like mobile evidence is intentionally unverified.
- No AI feedback API/persistence path was found.

## 14. Related Documentation

- Workspace architecture: [`docs/CODEBASE_MAP.md`](../../../docs/CODEBASE_MAP.md)
- Workspace endpoint inventory: [`docs/API_MAP.md`](../../../docs/API_MAP.md)
- Workspace persistence inventory: [`docs/DATABASE_SCHEMA.md`](../../../docs/DATABASE_SCHEMA.md)
- Dated workspace status: [`docs/CURRENT_STATE.md`](../../../docs/CURRENT_STATE.md)
- Existing AI implementation/release history: [`docs/AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md`](../AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md)
- AI testing, deployment probes, and runbook: [`docs/AI_ASSISTANT_TESTING_GUIDE.md`](../AI_ASSISTANT_TESTING_GUIDE.md)
- Consent/privacy policy referenced by the consent service: [`docs/feats/PRIVACY_POLICY.md`](../feats/PRIVACY_POLICY.md)
- Monitoring assets: [`monitoring/ai_assistant/`](../../monitoring/ai_assistant/)

Historical documents may contain earlier local or owner-reported evidence. Reverify any drift-prone or deployment-specific claim before using it for a release decision.
