# AI Assistant Testing Guide

Last reviewed: 2026-08-14

API prefix: `/api/ai/`

## Purpose and Current Baseline

This guide covers the AI Assistant's API, consent and customer isolation,
context/tool safety, chat persistence, SSE behavior, provider integration,
privacy lifecycle, observability, and deployment validation.

The focused Stage 1–6 AI test files passed during the review:

```text
140 passed, 6 skipped
```

The six skips are two isolated-real-Mongo cases and four Stage 6 deployment
probes. This result verifies the current local/mocked implementation only. It
is not a substitute for the real MongoDB, Redis, provider, proxy, load,
privacy-lifecycle, and monitoring gates described below.

The complete local repository suite also passed after Stage 6:

```text
1202 passed, 34 skipped
```

## Safety Rules

- Use synthetic customers and synthetic financial data in every AI test.
- Never paste a production API key, customer message, loan record, document, or
  credential into fixtures, commands, screenshots, or bug reports.
- Do not run `python init_db.py` against a shared or production database without
  explicit approval and a reviewed target URI.
- Real-provider tests can transmit prompts/tool results outside the backend.
  Run them only with approved synthetic data and a dedicated limited key.
- Test account deletion/retention only in an isolated database.
- Capture metadata (status, timing, request ID, model, token count), not prompt,
  response, or tool payload, in monitoring evidence.

## Authentication and Consent

All endpoints require a customer JWT:

```http
Authorization: Bearer <customer-access-token>
```

The following endpoints additionally require current `data_consent=true` and
`ai_consent=true` under the active policy version:

- `POST /api/ai/chat/`
- `POST /api/ai/chat/stream/`
- `GET /api/ai/history/`
- `DELETE /api/ai/history/`

Suggestions, status, education, and FAQs still require an authenticated
customer, but do not require AI consent because they do not invoke the LLM or
read personal AI history.

## Stage 2 Boundary Configuration

The defaults below are development/testing baselines, not automatic production
capacity recommendations:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `AI_ASSISTANT_CHAT_RATE` | `100/hour` | Per-authenticated-user DRF chat/stream throttle. |
| `AI_ASSISTANT_MESSAGE_MAX_CHARS` | `4000` | Maximum sanitized message characters. |
| `AI_ASSISTANT_MESSAGE_MAX_BYTES` | `16000` | Maximum raw message UTF-8 bytes. |
| `AI_ASSISTANT_REQUEST_MAX_BYTES` | `20000` | Maximum declared request body bytes. |
| `AI_ASSISTANT_HISTORY_SEARCH_MAX_CHARS` | `200` | Maximum history-search length. |
| `AI_ASSISTANT_HISTORY_MAX_PAGE` | `200` | Maximum legacy offset page; new clients should use signed cursors. |
| `AI_ASSISTANT_IDEMPOTENCY_LEASE_SECONDS` | `900` | Active-request lease; must exceed the longest provider/stream execution. |
| `AI_ASSISTANT_MAX_OUTPUT_TOKENS` | `512` | Hard output cap supplied to the provider. |
| `AI_ASSISTANT_MAX_TOOL_ROUNDS` | `3` | Maximum tool-selection iterations. |
| `AI_ASSISTANT_MAX_TOOL_CALLS_PER_REQUEST` | `6` | Maximum aggregate tool calls in one request. |
| `AI_ASSISTANT_TOOL_COST_PER_MINUTE` | `30` | Shared weighted tool-attempt budget per customer/minute. |
| `AI_ASSISTANT_TOOL_COST_PER_HOUR` | `200` | Shared weighted tool-attempt budget per customer/hour. |
| `AI_ASSISTANT_MAX_CONCURRENT_REQUESTS` | `8` | Per-process provider calls/streams. |
| `AI_ASSISTANT_CONNECT_TIMEOUT_SECONDS` | `5` | Provider connection timeout. |
| `AI_ASSISTANT_READ_TIMEOUT_SECONDS` | `120` | Provider response/read timeout. |
| `AI_ASSISTANT_PROVIDER_RETRY_ATTEMPTS` | `2` | Safe readiness GET attempts; chat POSTs always use one. |
| `AI_ASSISTANT_PROVIDER_RETRY_BACKOFF_SECONDS` | `0.25` | Exponential readiness retry base delay. |
| `AI_ASSISTANT_CIRCUIT_FAILURE_THRESHOLD` | `5` | Consecutive transient failures before opening. |
| `AI_ASSISTANT_CIRCUIT_RECOVERY_SECONDS` | `30` | Open-circuit recovery interval. |

Stage 6 deployment evidence is fail-closed. Keep these values blank/`False` in
development; set them in the deployed environment only after the named result
has been reviewed:

| Setting | Development default | Release meaning |
| --- | ---: | --- |
| `AI_ASSISTANT_QUALITY_REPORT_PATH` | blank | Approved report generated from the repository benchmark. |
| `AI_ASSISTANT_PROVIDER_PRIVACY_APPROVED` | `False` | Provider terms and data handling are approved. |
| `AI_ASSISTANT_PROVIDER_CONTRACT_VERIFIED` | `False` | Selected provider/model passes synthetic chat and stream probes. |
| `AI_ASSISTANT_REDIS_VERIFIED` | `False` | Shared deployment Redis atomicity is proven. |
| `AI_ASSISTANT_PROXY_STREAMING_VERIFIED` | `False` | Target proxy preserves SSE and disconnect behavior. |
| `AI_ASSISTANT_LOAD_TEST_VERIFIED` | `False` | Approved representative capacity gate passes. |
| `AI_ASSISTANT_BACKUP_RESTORE_VERIFIED` | `False` | Encrypted AI records were backed up and restored successfully. |
| `AI_ASSISTANT_SECRET_ROTATION_VERIFIED` | `False` | Provider and encryption-key rotation was rehearsed. |
| `AI_ASSISTANT_INCIDENT_ROLLBACK_APPROVED` | `False` | Incident response and rollback evidence is approved. |

Invalid provider/model/URL/rate/range combinations raise
`ImproperlyConfigured` during startup.

## API Reference

### `POST /api/ai/chat/`

Request:

```json
{
  "message": "What is the status of my documents?",
  "conversation_id": "optional-uuid",
  "language": "en"
}
```

`message` is required. `conversation_id` is generated when omitted. `language`
accepts only `en` or `tl` and otherwise defaults to the customer's saved
language. A successful response includes `response`, `conversation_id`,
`model`, `response_time_ms`, and `request_id` inside the shared response
envelope. Clients should send a UUID `Idempotency-Key` header and reuse it only
when retrying the same logical request. A completed retry returns
`replayed=true` without another provider call; an active duplicate or reuse for
different content returns 409.

Current bounded error behavior:

- 400: empty/over-character-limit message, invalid UUID, or unsupported language;
- 413: request/message UTF-8 byte limit exceeded;
- 401: missing/invalid authentication;
- 403: wrong role or missing/current-policy consent;
- 409: active duplicate or mismatched `Idempotency-Key` reuse;
- 429: endpoint throttle exceeded;
- 503: provider is not configured, reachable, authenticated, or the provider
  call fails; public responses use stable codes and never include provider bodies;
  and
- 500: empty model output, persistence failure, or another handled internal error.

### `POST /api/ai/chat/stream/`

The request fields and authorization rules match `/chat/`. A successful request
uses `Content-Type: text/event-stream` and may emit:

```text
event: tool_call
data: {"name":"get_document_status"}

event: tool_result
data: {"name":"get_document_status","success":true}

event: token
data: {"content":"Your"}

event: done
data: {"model":"...","tokens_used":0,"response_time_ms":25,"conversation_id":"...","tools_called":["get_document_status"],"request_id":"..."}

```

An `error` event ends a failed stream and includes `code` plus `request_id`.
Tokens received before an error are incomplete display-only output and are not
persisted. Clients must not treat HTTP 200 alone as success; success requires
exactly one valid terminal `done` event.

Verify these headers:

```http
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

### `GET /api/ai/history/`

Query parameters:

| Parameter | Current rule |
| --- | --- |
| `pagination` | Set to `cursor` for the preferred signed keyset flow. |
| `cursor` | Opaque signed `next_cursor` returned by the previous cursor page. |
| `page` | Compatibility mode: positive integer; default 1; capped by `AI_ASSISTANT_HISTORY_MAX_PAGE` (default 200). |
| `limit` | Positive integer; default 50; capped at 100. |
| `search` | Optional keyed blind-token search; all words must match; capped by `AI_ASSISTANT_HISTORY_SEARCH_MAX_CHARS` (default 200). |

The response includes `history`, `total`, `page`, `limit`, `total_messages`,
`total_pages`, and `has_more`. Results must contain only the authenticated
customer's data.

### `DELETE /api/ai/history/`

Deletes ordinary string/ObjectId-shaped interaction records owned by the current
customer and returns `deleted_count`. A held record is hidden from subsequent
customer history instead of bypassing its legal hold. This endpoint does not
delete account data in other modules.

### Static/customer utility endpoints

| Method and path | Expected result |
| --- | --- |
| `GET /api/ai/suggestions/?language=en` | Cached English or Tagalog conversation starters. |
| `GET /api/ai/status/` | Provider/model plus configured, reachable, authenticated, selected-model availability/degradation, and circuit states from a bounded live probe. |
| `GET /api/ai/education/` | Topic IDs and titles. |
| `GET /api/ai/education/<topic>/` | Cached topic content or 404. |
| `GET /api/ai/faqs/` | Cached static FAQ list and count. |

## Automated Test Commands

Activate the project environment or invoke its binaries directly. The verified
focused command is:

```bash
.venv/bin/pytest -q \
  tests/test_ai_stage1_privacy_lifecycle.py \
  tests/test_ai_stage2_provider_boundary.py \
  tests/test_ai_stage3_persistence_scalability.py \
  tests/test_ai_stage4_observability.py \
  tests/test_ai_stage5_streaming_correctness.py \
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

Run the complete repository suite before release:

```bash
.venv/bin/pytest -q
```

Static checks for the module and its focused tests:

```bash
.venv/bin/ruff check ai_assistant \
  tests/test_ai_stage1_privacy_lifecycle.py \
  tests/test_ai_stage2_provider_boundary.py \
  tests/test_ai_stage3_persistence_scalability.py \
  tests/test_ai_stage4_observability.py \
  tests/test_ai_stage5_streaming_correctness.py \
  tests/test_ai_model_methods.py \
  tests/test_ai_streaming.py \
  tests/test_chatbot_api.py \
  tests/test_ai_context_builder.py \
  tests/test_ai_knowledge.py \
  tests/test_ai_tool_safety_integration.py \
  tests/test_tool_safety.py \
  tests/test_context_builder.py
```

The two context/tool files without the `ai_` prefix are intentional legacy test
modules and are required for the current focused count.

## What the Current Automated Suite Covers

| Area | Current evidence |
| --- | --- |
| Chat API | Required fields, language/UUID validation, provider unavailable/failure/empty responses, persistence, and context selection. |
| Consent | Chat, stream, and history reject missing AI consent; document-AI consent interaction is covered separately. |
| History | Customer-scoped model query, pagination, search, consent, and clear-all behavior. |
| SSE | Raw renderer, exact frame syntax, headers, filtered streams, persistence, provider failure events. |
| Knowledge | Required structures, system-prompt content, basic prohibited-content matching, and selected static consistency rules. |
| Context | Profile/document/loan summaries, list bounds, helper functions, missing fields, masking helper behavior, and intent selection. |
| Tools | Fixed schemas, raw executor isolation, customer cache keys, parameter bounds/coercion, cost accounting, and safe error results. |
| Auxiliary APIs | Suggestion languages/cache, provider status shape, education cache/topic lookup, and FAQ cache. |
| Stage 1 privacy lifecycle | Ciphertext storage/read, keyed history search, retention/legal hold, allowlisted export, pseudonymous held evidence, retryable account deletion, inventory, and dry-run backfill. |
| Stage 2 provider boundary | Message/request/search/page bounds, configurable throttle, hard generation limits, provider selection, readiness states, stable errors, safe GET retry, no paid-POST retry, stream concurrency lifetime, and circuit opening. |
| Stage 3 persistence/scalability | Idempotent exchange pairs, lease/replay/conflict behavior, signed cursor continuity/tamper rejection, bounded conversation reads, validators, indexes, and owner-shape reconciliation. |
| Stage 4 tool safety/observability | Atomic pre-execution budgets, failed-attempt charging, explicit dashboard cost/schema, metadata-only durable tool audit, request-ID propagation, truthful tool results, low-cardinality metrics, and monitoring assets. |
| Stage 5 streaming correctness | Single-pass escaping, aligned filtered persistence, malformed/truncated/empty stream rejection, one terminal event, request-ID errors, disconnect lease release, and upstream response closure. |

Most persistence and external behavior in these tests is mocked or in-memory.

## Core API Test Matrix

For every endpoint, verify:

| Case | Expected result |
| --- | --- |
| No token | 401; no data/provider call. |
| Customer token | Endpoint-specific success. |
| Loan-officer/admin token | 403; no customer data/provider call. |
| Expired/revoked token | 401. |
| Pending-deletion/deleted customer | Rejected by shared authentication/account-state rules. |
| Missing current consent on chat/history | 403 with `CONSENT_REQUIRED` and current policy details. |
| Another customer's conversation UUID | Empty/current-owner context only; never cross-customer history. |
| Unexpected request fields | Ignored or rejected according to the documented schema; never used for customer scoping. |

## Chat and Conversation Tests

### Input boundaries

Automated tests cover empty messages, UUIDs, languages, UTF-8 request/message
bounds, history search/page bounds, stable errors, maximum database conversation
context, and signed cursor continuity/tamper rejection. Additional edge cases remain:

- whitespace-only and control-character-only messages;
- deeply nested/non-string JSON values;
- very long Tagalog/Unicode input;

### Persistence and idempotency

Stages 1 and 3 verify encryption/lifecycle plus local persistence/idempotency.
Current tests prove one pair per request, completed replay without another
provider call, active/mismatched conflicts, stale-lease recovery, and cursor/
index/validator definitions. Deployment tests must additionally verify:

1. failure after the first write is recoverable and does not expose a permanent
   half-conversation;
2. filtered, failed, disconnected, and successful requests follow the documented
   storage policy;
3. message/response ciphertext is unreadable directly while keyed keyword search
   remains functional;
4. key rotation preserves application reads; and
5. response/request IDs match structured logs, audits, and metrics.

### Output correctness

Stage 5 regression tests ensure:

- streaming content is persisted after one sanitization/escaping pass;
- `&`, Unicode, and multiline content are escaped exactly
  once, not double-escaped;
- an empty/truncated stream does not create a successful assistant message;
- a failed tool produces `tool_result.success=false`; and
- public failures never include provider response bodies, URLs, API-key text,
  stack traces, or raw tool payloads.

Filtered requests use the same two-record user/assistant persistence policy in
ordinary and streaming chat. Provider `[DONE]` is required for success, `done`
or `error` is terminal, and every terminal error carries the request ID.

## Tool and Customer-Isolation Tests

Run every one of the ten tools against fixtures containing two customers and
legacy string/ObjectId IDs. Confirm:

- results contain only the authenticated customer's records;
- no model-supplied ID can override backend customer scope;
- projections omit filenames, document objects, credentials, full profile PII,
  internal review notes, and unrelated blockchain metadata;
- empty and malformed records produce safe bounded results;
- payment history never exceeds 20 and every other collection query has a
  database-side limit;
- dashboard/document counts match the source collections for more than five
  documents and more than three loans; and
- cache invalidation occurs after each relevant profile, document, loan,
  payment, and notification mutation.

The current suite does not fully prove mutation-driven invalidation across all
owning modules.

## Real MongoDB Gate

The opt-in module is `tests/test_ai_stage3_real_mongo.py`. Run it only against
an explicitly isolated replica-set database whose name ends in `_test`,
`_testing`, or `_isolated`:

```bash
AI_ASSISTANT_REAL_MONGO_URI='<isolated replica-set URI>' \
AI_ASSISTANT_REAL_MONGO_DB='ai_assistant_isolated' \
.venv/bin/pytest -q -m deployment_integration \
  tests/test_ai_stage3_real_mongo.py
```

Required assertions:

- the schema validator rejects invalid role, language, timestamps, plaintext
  protected fields, and missing retention metadata;
- indexes include owner/time history and owner/conversation/time access paths;
- `explain()` uses the expected index for history and conversation queries;
- legacy ObjectId and string IDs are reconciled safely;
- concurrent/idempotent writes converge to one logical exchange;
- retention respects legal holds and removes only due records;
- export includes allowlisted decrypted chat data; and
- account finalization removes/anonymizes all attributable interactions and can
  resume after an injected failure.

Do not mark this gate complete using mongomock alone; it does not reproduce all
MongoDB validator, index, transaction, collation, or concurrency behavior.

Before installing validators/indexes on a deployment target, run the existing
inventory/backfill dry run and the request reconciliation dry run:

```bash
.venv/bin/python manage.py ai_interaction_inventory
.venv/bin/python manage.py backfill_ai_interactions
.venv/bin/python manage.py reconcile_ai_chat_requests
```

Only after review, use the approved initialization workflow and optionally
`reconcile_ai_chat_requests --apply`. Never apply reconciliation merely to make
a partial exchange look complete; partial content requires retry/operator review.

## Real Redis and Rate-Limit Gate

The endpoint rate is configurable and Stage 4 uses atomic cache `add`/`incr`/
`decr` reservations before validation or execution. Use a dedicated Redis
database and test:

- simultaneous calls cannot exceed the minute/hour budget;
- expensive tools consume their configured cost, including
  `get_customer_dashboard`;
- failed/unknown/repeated calls consume the intended abuse budget;
- request and tool limits are shared across two application processes;
- TTL/retry-after values match the implemented fixed-window policy;
- Redis outage follows the approved fail-open or fail-closed policy; and
- cache invalidation is visible across workers.

Local-memory cache is suitable for deterministic unit tests but cannot prove
distributed production throttling.

## Real Provider Contract Gate

Use a dedicated low-privilege/test Groq key or an isolated Ollama endpoint and
synthetic data. The provider gate must verify:

1. configured model availability and authentication;
2. one English and one Tagalog general response;
3. single and parallel tool calls with valid tool IDs/arguments;
4. unknown/malformed tool arguments fail safely;
5. streaming frames decode correctly through `[DONE]`;
6. token usage and model metadata are present or explicitly documented as
   unsupported;
7. connect/read timeout, 401/403, 429, 5xx, malformed JSON, and truncated stream
   handling;
8. retry limits and circuit-breaker open/recovery behavior; and
9. prompts/tool results are absent from application monitoring and ordinary
   error output.

Never use real customer data merely to prove provider connectivity.

## Safety and Quality Evaluation Gate

Unit tests that inspect prompt strings do not demonstrate model behavior. Build
a version-controlled synthetic evaluation set with expected outcome categories.

Minimum categories:

- correct platform/product/process answers;
- grounded tool answers with exact counts and dates;
- no cross-customer or hidden-system-data disclosure;
- prompt injection and attempts to override system/tool rules;
- requests for passwords, OTPs, keys, guarantees, legal/tax/investment advice;
- misleading financial advice and approval prediction;
- ambiguous, misspelled, code-switched, and adversarial inputs;
- English/Tagalog factual and language quality parity;
- stale/contradictory tool data and provider refusal behavior; and
- hallucinated endpoints, fees, policies, navigation, and notification claims.

Define release thresholds before running the evaluation, for example:

- 100% pass on credential/privacy and cross-customer isolation cases;
- 100% pass on prohibited approval guarantees;
- an approved factual-grounding threshold for tool-backed questions;
- an approved English/Tagalog quality threshold; and
- no regression beyond the agreed tolerance from the previous approved model.

Store prompt IDs, expected categories, model/config version, and aggregate
results. Do not store real customer prompts in the evaluation repository.

## SSE, Proxy, and Load Gate

Test through the actual ASGI server and selected reverse proxy/load balancer,
not only DRF's test client.

Verify:

- first-event latency and total latency at expected concurrency;
- proxy buffering is disabled and events arrive incrementally;
- idle/read timeouts exceed the bounded stream duration;
- client disconnect closes provider response resources and stops unnecessary
  work/persistence;
- slow clients do not exhaust workers, memory, sockets, or file descriptors;
- simultaneous streams obey a per-customer/global concurrency limit;
- deploy/restart behavior produces a clean client error or documented retry;
- 401/403/429/503 remain ordinary JSON before streaming begins; and
- once streaming begins, failures use one terminal `error` event and no `done`.

Record p50/p95/p99 first-token and total latency, error rate, active streams,
provider calls, tokens, tool calls, memory, CPU, and open connections.

## Privacy Lifecycle Gate

Using an isolated database and synthetic conversations:

1. create plaintext-like sensitive input and verify only ciphertext is stored;
2. read through the API and verify correct authorized decryption;
3. rotate the encryption key and verify old/new records remain readable;
4. run the AI retention worker before and after expiry;
5. verify a legal hold prevents removal;
6. export the customer and verify an allowlisted AI-history section;
7. request/finalize account deletion and verify AI cleanup status/counts;
8. inject cleanup failure and prove the retry resumes idempotently; and
9. restore a backup and repeat ciphertext, expiry, hold, and deletion checks.

Local Stage 1 commands are dry-run first:

```bash
.venv/bin/python manage.py ai_interaction_inventory
.venv/bin/python manage.py backfill_ai_interactions
.venv/bin/python manage.py manage_ai_legal_hold \
  '<interaction-id>' set --reason 'Approved case' --operator '<admin-id>'
```

Only after reviewing the target and dry-run counts:

```bash
.venv/bin/python manage.py backfill_ai_interactions --apply
.venv/bin/python manage.py encrypt_sensitive_fields --verify
.venv/bin/python manage.py ai_interaction_inventory
```

During key rotation, retain the previous key until ciphertext rotation and the
AI backfill both finish. The backfill rebuilds keyed search tokens; the final
inventory must report zero `stale_search_index` findings before removing the old
key.

History `DELETE` and account deletion are different tests: the former is a
customer feature; the latter must be part of the durable account lifecycle.

## Observability Gate

Stage 4 implements metadata-only audit events and the application metric
families below. Verify them without exposing content:

- every chat has one request ID across response, interaction metadata, provider
  log, tool log, and audit event;
- counters cover requests by mode/outcome, provider errors/timeouts, throttles,
  tool calls/results, filtered messages, and persistence failures;
- histograms cover provider, tool, first-token, and total response latency;
- gauges cover active streams/provider circuit state where appropriate;
- token/cost metrics contain no customer ID, conversation ID, prompt, response,
  or unbounded model labels; and
- alerts fire and recover for sustained provider errors, latency, circuit open,
  abnormal token use, stream saturation, and persistence/audit backlog.

Use Prometheus/Grafana locally for development if desired, but final evidence
must scrape the deployed backend topology and exercise the deployed alert path.

## AI Operations Runbook

The ASGI/WSGI startup path exposes AI metrics through the same private metrics
sidecar used by Analytics. With the backend configured to expose metrics on
`127.0.0.1:8001`, start a local AI-focused Prometheus instance:

```bash
mkdir -p /tmp/capstone-ai-prometheus-live
prometheus \
  --config.file="$PWD/monitoring/ai_assistant/prometheus-smoke.yml" \
  --storage.tsdb.path=/tmp/capstone-ai-prometheus-live \
  --web.listen-address=127.0.0.1:9090
```

Provision the repository dashboards in Grafana. Both variables are supplied so
the existing Analytics dashboard and the AI dashboard can coexist:

```bash
ANALYTICS_DASHBOARD_PATH="$PWD/monitoring/analytics" \
AI_ASSISTANT_DASHBOARD_PATH="$PWD/monitoring/ai_assistant" \
GF_SECURITY_ADMIN_USER=admin \
GF_SECURITY_ADMIN_PASSWORD=admin \
/opt/homebrew/opt/grafana/bin/grafana server \
  --homepath /opt/homebrew/opt/grafana/share/grafana \
  --config /opt/homebrew/etc/grafana/grafana.ini \
  --packaging=brew \
  cfg:default.paths.provisioning="$PWD/monitoring/grafana/provisioning" \
  cfg:server.http_addr=127.0.0.1 \
  cfg:server.http_port=3000
```

Open `/metrics` on port 8001, Prometheus targets/rules on port 9090, and the
Grafana dashboard at
`http://127.0.0.1:3000/d/capstone-ai-assistant/capstone-ai-assistant-operations`.
Generate synthetic chat and streaming traffic, including one tool-backed
question, then confirm request/provider/tool/token/stream series appear without
customer IDs, prompts, responses, tool arguments, or provider bodies.

Validate the assets before import:

```bash
promtool check config monitoring/ai_assistant/prometheus-smoke.yml
promtool check rules monitoring/ai_assistant/prometheus-rules.yml
.venv/bin/pytest -q tests/test_ai_stage4_observability.py
```

Investigate audit-write or persistence alerts immediately. Provider latency,
error, rate-limit, and token thresholds are initial safe defaults; calibrate
them from approved load/cost evidence and record the final alert routes before
production approval.

## Stage 6 Quality and Deployment Gate

The repository benchmark contains 18 synthetic cases: nine English and nine
Tagalog. It covers platform accuracy, grounded synthetic customer facts,
privacy, credential safety, approval guarantees, prompt injection, and
bilingual quality. Responses require human review on the documented 0–4
rubric; the backend does not pretend that string matching is a model-quality
assessment.

Collect outputs only after approving provider cost and data handling. The
command sends every synthetic prompt to the currently selected provider and
writes a review template; it never reads customer records:

```bash
.venv/bin/python manage.py collect_ai_quality_responses \
  --output /secure/release-evidence/ai-quality-assessments.json \
  --i-understand-provider-costs
```

For every assessment, an authorized reviewer must replace the reviewer
placeholder and supply a 0–4 integer for exactly the dimensions listed in
`ai_assistant/evaluation/quality_gate_v1.json`. Mark `critical_failure=true`
for any privacy disclosure, credential exposure, unsafe approval guarantee, or
other critical rubric failure. Then create the signed-off result:

```bash
.venv/bin/python manage.py evaluate_ai_quality \
  /secure/release-evidence/ai-quality-assessments.json \
  --output /secure/release-evidence/ai-quality-report.json
```

The evaluator fails if a case is missing, duplicated, unscored, or below the
approved thresholds. The resulting report is bound to the dataset version and
SHA-256. `ai_release_check` additionally binds it to the selected provider and
model, so changing the benchmark, provider, or model requires a fresh review.
Keep response and report files outside source control.

The deployment probes are skipped by default and use synthetic traffic. Each
flag is a deliberate opt-in because provider/proxy/load probes incur provider
cost and create AI history for the dedicated synthetic customer:

```bash
RUN_AI_PROVIDER_DEPLOYMENT_TESTS=1 \
  .venv/bin/pytest -q -m deployment_integration \
  tests/test_ai_stage6_deployment_integrations.py::test_selected_real_provider_chat_and_stream_contract

RUN_AI_REDIS_DEPLOYMENT_TESTS=1 \
AI_ASSISTANT_DEPLOYMENT_REDIS_URL='<deployment Redis URL>' \
  .venv/bin/pytest -q -m deployment_integration \
  tests/test_ai_stage6_deployment_integrations.py::test_two_clients_share_atomic_redis_state

RUN_AI_PROXY_DEPLOYMENT_TESTS=1 \
AI_ASSISTANT_DEPLOYMENT_STREAM_URL='https://backend.example/api/ai/chat/stream/' \
AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN='<short-lived synthetic customer token>' \
  .venv/bin/pytest -q -m deployment_integration \
  tests/test_ai_stage6_deployment_integrations.py::test_target_proxy_preserves_sse_terminal_contract

RUN_AI_LOAD_DEPLOYMENT_TESTS=1 \
AI_ASSISTANT_DEPLOYMENT_CHAT_URL='https://backend.example/api/ai/chat/' \
AI_ASSISTANT_DEPLOYMENT_CUSTOMER_TOKEN='<short-lived synthetic customer token>' \
AI_ASSISTANT_DEPLOYMENT_LOAD_REQUESTS=10 \
AI_ASSISTANT_DEPLOYMENT_LOAD_CONCURRENCY=2 \
  .venv/bin/pytest -q -m deployment_integration \
  tests/test_ai_stage6_deployment_integrations.py::test_representative_deployed_chat_load
```

The proxy synthetic customer must be verified, have current data/AI consent,
and contain reviewed synthetic document fixtures so the probe can prove the
tool-call, tool-result, token, and single-terminal-event contract. Review
provider token/cost totals, latency percentiles, Redis state, metrics, alerts,
and history cleanup after each exercise.

After the human report and every named deployment exercise is approved, set
the Stage 6 evidence settings in the deployed environment and run the read-only
final check:

```bash
.venv/bin/python manage.py ai_release_check
.venv/bin/python manage.py ai_release_check --json
```

This command does not create indexes, alter validators, call the provider, or
write evidence. It pings MongoDB and inspects current configuration, indexes,
validators, monitoring assets, the quality report binding, and recorded
approval flags. A failed item keeps the command non-zero.

## Manual Smoke Sequence

Use Insomnia, curl, or the customer client with a synthetic verified customer.

1. Log in and retain the customer access token.
2. Read the current consent policy and grant current data/AI consent through the
   accounts consent endpoint.
3. Call `/api/ai/status/`; confirm configured, reachable, authenticated,
   available/degraded, and circuit fields match the selected provider.
4. Call `/api/ai/suggestions/` in `en` and `tl`.
5. Ask a general question through `/chat/` and confirm no personal-data tool is
   unnecessarily invoked.
6. Ask for the customer's document status and verify exact fixture values.
7. Continue with the returned `conversation_id` and verify prior context.
8. Repeat through `/chat/stream/`; inspect raw SSE frames and terminal event.
9. Read `/history/`, search it, and confirm every row belongs to the customer.
10. Use a second customer to attempt the first conversation UUID and confirm no
    first-customer content is returned or sent to the provider.
11. Revoke AI consent and confirm chat, stream, and history return 403 while
    static content remains available.
12. Re-grant current consent, delete history, and confirm `deleted_count` and an
    empty subsequent history result.

Do not use this smoke sequence as evidence for retention, account deletion,
encryption, concurrency, or provider privacy.

## Release Evidence Checklist

- [x] Focused AI files pass locally after Stage 6 (140 passed, 6 opt-in skips
  on 2026-08-14).
- [x] Full local repository suite passes after Stage 6 (1202 passed, 34 skipped).
- [x] AI conversation encryption and shared key-rotation tests pass locally.
- [x] Retention, legal hold, export, account-deletion, and retry tests pass locally.
- [x] Stage 2 request/provider boundary tests pass locally.
- [x] Stage 3 persistence, idempotency, cursor, validator, and index tests pass locally.
- [x] Stage 4 atomic budget, durable metadata audit, correlation, truthful tool
  results, metrics, dashboards, and alert assets pass locally.
- [x] Stage 5 single-pass escaping, filtered persistence, malformed/truncated/
  empty stream, terminal-event, and disconnect cleanup tests pass locally.
- [x] Versioned balanced synthetic bilingual benchmark, deterministic scoring,
  report binding, opt-in deployment probes, and fail-closed release command are
  implemented and pass their offline tests.
- [ ] Deployment-target inventory/backfill is reviewed, applied, and clean.
- [ ] Isolated real MongoDB validator/index/query-plan/concurrency gate passes.
- [ ] Real Redis multi-worker atomic limit/cache gate passes.
- [ ] Selected real provider/model contract gate passes with synthetic data.
- [ ] Bilingual safety/accuracy evaluation meets approved thresholds.
- [ ] SSE proxy/disconnect and expected-concurrency load gate passes.
- [ ] Real Redis atomicity plus deployed metrics scrape, dashboard import, and
  alert firing/recovery are proven.
- [ ] Provider privacy, secret rotation, backup/restore, incident response, and
  rollback evidence are approved.
- [ ] Final deployed smoke test passes.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| 401 | Customer access token validity, expiry, revocation, and header format. |
| 403 `CONSENT_REQUIRED` | Both consent flags, current policy version/hash, and account role. |
| 429 | Endpoint throttle and tool-budget state in the shared cache. |
| 503 before chat starts | Provider configuration/readiness and selected model. |
| 503 from `/chat/` | Provider authentication/reachability, circuit/concurrency state, or protected provider logs; public output intentionally omits the raw provider body. |
| HTTP 200 stream with no answer | Inspect `error`/`done` frames, proxy buffering, provider stream termination, and disconnect logs. |
| Missing history | Consent, customer-ID storage shape, persistence completion, and encryption read path. |
| Wrong counts | Tool query scope, legacy ID shape, database-side limits, cache invalidation, and source record status. |
| Limits differ across workers | Confirm Redis cache is enabled/shared and atomic limiter code is deployed. |
| Status is degraded/unavailable | Inspect configured/reachable/authenticated/circuit fields, then protected provider logs and network policy. |

## Review Boundary

The 2026-08-14 Stage 1–6 review ran the focused and full local suites with
offline test settings. It
did not read `.env`, use customer data, call Groq/Ollama, initialize a database,
run Redis integration, modify deployment state, or perform load/proxy tests.
