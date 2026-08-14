# AI Assistant Testing Guide

Last reviewed: 2026-08-14

API prefix: `/api/ai/`

## Purpose and Current Baseline

This guide covers the AI Assistant's API, consent and customer isolation,
context/tool safety, chat persistence, SSE behavior, provider integration,
privacy lifecycle, observability, and deployment validation.

The focused offline suite passed during the review:

```text
176 passed in 1.21 seconds
```

That result verifies the current local/mocked implementation only. It is not a
substitute for the real MongoDB, Redis, provider, proxy, load, privacy-lifecycle,
and monitoring gates described below.

The complete local repository suite also passed after Stage 1:

```text
1133 passed, 28 skipped, 1 warning in 51.29 seconds
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
`model`, and `response_time_ms` inside the shared response envelope.

Current error behavior:

- 400: empty message, invalid UUID, or unsupported language;
- 401: missing/invalid authentication;
- 403: wrong role or missing/current-policy consent;
- 429: endpoint throttle exceeded;
- 503: provider is not configured/available before the call; and
- 500: provider call failure, empty model output, or handled processing error.

Production hardening must add a documented message-size response and normalize
upstream failures without returning provider details.

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
data: {"model":"...","tokens_used":0,"response_time_ms":25,"conversation_id":"...","tools_called":["get_document_status"]}

```

An `error` event ends a failed stream. Clients must not treat an HTTP 200 alone
as success; success requires a valid terminal `done` event.

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
| `page` | Positive integer; default 1. No current maximum. |
| `limit` | Positive integer; default 50; capped at 100. |
| `search` | Optional case-insensitive keyword search backed by keyed blind tokens. All supplied words must match; no current input-length bound. |

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
| `GET /api/ai/status/` | Provider, selected model, configured/available flags. Groq availability currently checks key presence only. |
| `GET /api/ai/education/` | Topic IDs and titles. |
| `GET /api/ai/education/<topic>/` | Cached topic content or 404. |
| `GET /api/ai/faqs/` | Cached static FAQ list and count. |

## Automated Test Commands

Activate the project environment or invoke its binaries directly. The verified
focused command is:

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

Run the complete repository suite before release:

```bash
.venv/bin/pytest -q
```

Static checks for the module and its focused tests:

```bash
.venv/bin/ruff check ai_assistant \
  tests/test_ai_stage1_privacy_lifecycle.py \
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

Existing tests cover empty messages, UUIDs, and languages. Add tests before
production for:

- maximum accepted UTF-8 bytes and characters;
- whitespace-only and control-character-only messages;
- deeply nested/non-string JSON values;
- very long Tagalog/Unicode input;
- maximum conversation-history size enforced by the database query;
- bounded search text and maximum page/cursor; and
- stable 400/413 errors without reflecting sensitive input.

### Persistence and idempotency

Stage 1 verifies encryption and lifecycle behavior locally. Later persistence
stages must additionally verify:

1. one logical request creates exactly one user and one assistant record;
2. an identical idempotency key never calls the provider or writes twice;
3. failure after the first write is recoverable and does not expose a permanent
   half-conversation;
4. filtered, failed, disconnected, and successful requests follow the documented
   storage policy;
5. message/response ciphertext is unreadable directly while keyed keyword search
   remains functional;
6. key rotation preserves application reads; and
7. response/request IDs match structured logs, audits, and metrics.

### Output correctness

Add regression tests ensuring:

- non-streaming and streaming responses persist the same decoded text;
- `<`, `>`, `&`, quotes, Unicode, and multiline content are escaped exactly
  once, not double-escaped;
- an empty/truncated stream does not create a successful assistant message;
- a failed tool produces `tool_result.success=false`; and
- public failures never include provider response bodies, URLs, API-key text,
  stack traces, or raw tool payloads.

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

This gate does not yet have an opt-in test module. Implement it as part of the
persistence/lifecycle stage and run it only against an isolated database.

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

## Real Redis and Rate-Limit Gate

After the limiter is made atomic/configurable, use a dedicated Redis database
and test:

- simultaneous calls cannot exceed the minute/hour budget;
- expensive tools consume their configured cost, including
  `get_customer_dashboard`;
- failed/unknown/repeated calls consume the intended abuse budget;
- request and tool limits are shared across two application processes;
- TTL/retry-after values match the implemented fixed/sliding-window policy;
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

After AI metrics/audit are implemented, verify without exposing content:

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

## Manual Smoke Sequence

Use Insomnia, curl, or the customer client with a synthetic verified customer.

1. Log in and retain the customer access token.
2. Read the current consent policy and grant current data/AI consent through the
   accounts consent endpoint.
3. Call `/api/ai/status/`; treat it as configuration information until real
   upstream readiness is implemented.
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

- [x] Stage 1-focused offline suite passes (176 tests on 2026-08-14).
- [x] Full local repository suite passes after Stage 1 (1133 passed, 28 skipped).
- [x] AI conversation encryption and shared key-rotation tests pass locally.
- [x] Retention, legal hold, export, account-deletion, and retry tests pass locally.
- [ ] Deployment-target inventory/backfill is reviewed, applied, and clean.
- [ ] Isolated real MongoDB validator/index/query-plan/concurrency gate passes.
- [ ] Real Redis multi-worker atomic limit/cache gate passes.
- [ ] Selected real provider/model contract gate passes with synthetic data.
- [ ] Bilingual safety/accuracy evaluation meets approved thresholds.
- [ ] SSE proxy/disconnect and expected-concurrency load gate passes.
- [ ] Correlation, durable audit, metrics, dashboards, and alerts are proven.
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
| 500 from `/chat/` | Protected provider logs, malformed response, tool error, or persistence failure; do not expose the raw provider body. |
| HTTP 200 stream with no answer | Inspect `error`/`done` frames, proxy buffering, provider stream termination, and disconnect logs. |
| Missing history | Consent, customer-ID storage shape, persistence completion, and encryption read path. |
| Wrong counts | Tool query scope, legacy ID shape, database-side limits, cache invalidation, and source record status. |
| Limits differ across workers | Confirm Redis cache is enabled/shared and atomic limiter code is deployed. |
| Status says available but calls fail | Current Groq status checks key presence only; verify upstream authentication/model manually until readiness is hardened. |

## Review Boundary

The 2026-08-14 review ran the focused local suite with offline test settings. It
did not read `.env`, use customer data, call Groq/Ollama, initialize a database,
run Redis integration, modify deployment state, or perform load/proxy tests.
