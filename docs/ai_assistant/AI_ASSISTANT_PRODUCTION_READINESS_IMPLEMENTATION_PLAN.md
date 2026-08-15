# AI Assistant Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (<code>- [ ]</code>) syntax for tracking.

**Goal:** Resolve the source-verified production-readiness findings in the AI Assistant review and collect the external evidence required for an informed release decision.

**Architecture:** Preserve the current Django/DRF → PyMongo → provider boundary and Flutter Clean Architecture paths. Apply risk-ordered, independently testable changes: contract correctness first, fail-closed streamed-output safety second, then retention, privacy, provider resilience, client idempotency, and observability. Treat deployment validation as an evidence-producing release phase rather than as proof inferred from source code.

**Tech Stack:** Django 4.2+, Django REST Framework, PyMongo/MongoDB, Celery, Redis-backed Django cache, Prometheus, Groq/Ollama-compatible HTTP APIs, server-sent events (SSE), Flutter/Dart, Dio/Retrofit, Bloc, pytest, and flutter_test.

## Global Constraints

- The implementation source is the companion [production-readiness review](AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md); reverify live source before executing any task because routes, tests, settings, or provider behavior may drift.
- Preserve current endpoint paths, response wrappers, authentication, customer-only authorization, current-consent enforcement, conversation ownership, and tool allowlists.
- Do not expose prompts, message content, raw customer identifiers, credentials, provider keys, environment values, or production data in tests, logs, metrics, reports, or screenshots.
- Use test-driven development for backend and mobile behavior changes. Each implementation task must demonstrate a failing focused test before the smallest production change.
- Do not add a package when standard-library or existing project utilities are sufficient.
- Do not manually edit generated Flutter files. Regenerate Retrofit output only after modifying its annotated source.
- Treat <code>Capstone_Backend</code> and <code>MSME-Pathways-Mobile</code> as separate repositories with separate status checks, commits, and rollback points.
- Obtain explicit approval before the mobile phase, deployment probes, real-provider calls, Redis/MongoDB validation, load tests, secret rotation, scheduler/worker changes, or production configuration changes.
- Do not interpret unit tests, structural checks, or source review as evidence of live-provider, live-Redis, real-MongoDB, reverse-proxy SSE, load, alert-routing, backup/restore, staging, or production behavior.
- The release remains blocked while any P1 finding is unresolved or any mandatory deployment gate lacks approved evidence.

---

## 1. Scope and planning decision

### Findings covered

| Workstream | Review finding | Target outcome |
| --- | --- | --- |
| API correctness | P1 filtered JSON uses <code>message</code> while the client reads <code>response</code> | One successful chat payload contract across filtered, replayed, controlled, and provider responses |
| Stream safety | P1 streamed provider text bypasses whole-response validation | No provider text is sent or persisted before the same semantic controls used by non-streaming chat approve it |
| Retention operations | P1 expiry relies on Celery without execution-freshness evidence | Deletion/failure/freshness telemetry and an overdue-run alert, while preserving legal holds |
| Safety coverage | P2 declared prohibited categories exceed deterministic enforcement | Executable, bilingual input/output rules and adversarial tests for every declared category |
| Privacy | P2 raw identifiers in logs/cache keys; unkeyed message fingerprint | Purpose-separated keyed digests, rotation-aware comparison, and privacy-safe logs/cache metadata |
| Provider resilience | P2 readiness I/O per request and unthrottled status diagnostics | Provider chat does not require a preliminary network probe; diagnostics are briefly cached and throttled |
| Capacity | P2 process-local semaphore/circuit | A documented worker/provider budget proven under the target topology; shared controls only if aggregate protection is required |
| Client retries | P2 mobile callers omit stable idempotency keys | One UUID per user-send attempt, reused by any transport retry for JSON and SSE |
| Observability | P2 metrics default off, log extras hidden, no first-token signal | Privacy-safe structured AI logs, first-token telemetry, enabled scrape/alerts in the target environment |
| Schema documentation | P3 two source-verified collections absent from the schema map | Schema documentation includes all three AI collections and operational properties |

### Chosen approach

Use risk-ordered vertical slices with a test and commit gate per finding. This is preferred over:

1. **One large hardening release:** fewer deployments, but poor rollback isolation and weak attribution when a contract, stream, or operational check fails.
2. **Operations-only release first:** faster dashboards, but it leaves the P1 response and streaming defects in the request path.
3. **Risk-ordered slices (selected):** slightly more coordination, but each finding has a measurable acceptance gate and can be reviewed or reverted independently.

The plan deliberately chooses **full-response buffering for provider-generated SSE text**. The existing validator evaluates whole-response properties such as unsupported tool claims and language consistency; incremental token release cannot guarantee parity because a violation may appear after earlier tokens have already reached the client. Tool lifecycle events may remain incremental, but assistant text must be validated before its first token event. This preserves the SSE contract and fail-closed safety at the cost of token-by-token text latency. Any future truly incremental moderation design requires a separate threat model and acceptance criteria.

## 2. File and responsibility map

### Backend files

| File | Planned responsibility |
| --- | --- |
| <code>Capstone_Backend/ai_assistant/views/chat.py</code> | Normalize successful JSON chat data and avoid request-time readiness I/O |
| <code>Capstone_Backend/ai_assistant/views/streaming.py</code> | Buffer/validate provider text, emit first-token telemetry, and avoid raw identifiers |
| <code>Capstone_Backend/ai_assistant/views/auxiliary.py</code> | Apply status throttling and cached provider diagnostics |
| <code>Capstone_Backend/ai_assistant/services/response_controls.py</code> | Own deterministic input/output policy and whole-response validation |
| <code>Capstone_Backend/ai_assistant/services/knowledge_base.py</code> | Keep declared policy categories and localized redirect copy aligned |
| <code>Capstone_Backend/ai_assistant/services/idempotency.py</code> | Create and compare rotation-aware keyed request fingerprints |
| <code>Capstone_Backend/ai_assistant/services/privacy.py</code> | New, focused purpose-separated HMAC helper for non-reversible operational identifiers |
| <code>Capstone_Backend/ai_assistant/services/llm_service.py</code> | Separate local “may attempt” checks from cached network readiness diagnostics |
| <code>Capstone_Backend/ai_assistant/services/tools.py</code> | Replace raw-ID cache-key material with a scoped subject digest |
| <code>Capstone_Backend/ai_assistant/tasks.py</code> | Emit retention success, deletion, failure, and freshness signals |
| <code>Capstone_Backend/ai_assistant/metrics.py</code> | Define retention and first-token metrics with bounded labels |
| <code>Capstone_Backend/ai_assistant/logging.py</code> | New privacy-safe structured formatter with an explicit field allowlist |
| <code>Capstone_Backend/accounts/utils/throttles.py</code> | Add a dedicated authenticated AI status throttle |
| <code>Capstone_Backend/config/settings.py</code> | Validate new bounded settings and configure the AI logger/throttle |
| <code>Capstone_Backend/ai_assistant/services/operations.py</code> | Expose only source-verifiable release checks; keep external evidence fail-closed |
| <code>Capstone_Backend/monitoring/ai_assistant/prometheus-rules.yml</code> | Alert on retention freshness/failure and provider/stream symptoms |
| <code>Capstone_Backend/monitoring/ai_assistant/grafana-dashboard.json</code> | Display first-token and retention signals |

### Backend tests and documentation

| File | Planned proof |
| --- | --- |
| <code>Capstone_Backend/tests/test_chatbot_api.py</code> | Unified success contract and no preliminary provider probe |
| <code>Capstone_Backend/tests/test_ai_stage5_streaming_correctness.py</code> | No unvalidated token release or persistence; validated terminal behavior |
| <code>Capstone_Backend/tests/test_ai_knowledge.py</code> | Every declared prohibited category has deterministic bilingual cases |
| <code>Capstone_Backend/tests/test_ai_response_controls.py</code> | Output replacement for all enforceable policy categories |
| <code>Capstone_Backend/tests/test_ai_stage1_privacy_lifecycle.py</code> | Keyed fingerprint rotation and no plaintext prompt-derived digest |
| <code>Capstone_Backend/tests/test_ai_stage2_provider_boundary.py</code> | Cached readiness, status throttle, and bounded request behavior |
| <code>Capstone_Backend/tests/test_ai_stage4_observability.py</code> | Structured-field allowlist, redaction, metric and monitoring asset coverage |
| <code>Capstone_Backend/tests/test_ai_tasks.py</code> | New focused retention-task telemetry and failure behavior |
| <code>docs/DATABASE_SCHEMA.md</code> | Workspace schema inventory for <code>ai_interactions</code>, <code>ai_chat_requests</code>, and <code>ai_activity_events</code> |

### Mobile files

| File | Planned responsibility |
| --- | --- |
| <code>MSME-Pathways-Mobile/lib/core/network/idempotency_key_factory.dart</code> | New standard-library UUIDv4 generator with injectable randomness for tests |
| <code>MSME-Pathways-Mobile/lib/data/datasources/remote/learn_api_service.dart</code> | Send <code>Idempotency-Key</code> on JSON chat |
| <code>MSME-Pathways-Mobile/lib/data/datasources/remote/learn_api_service.g.dart</code> | Generated Retrofit output; regenerate, never hand-edit |
| <code>MSME-Pathways-Mobile/lib/data/datasources/remote/learn_streaming_service.dart</code> | Send the same caller-supplied key on SSE and return generic network errors |
| <code>MSME-Pathways-Mobile/lib/data/repositories/learn_repository_impl.dart</code> | Require <code>response</code> in successful chat data and forward the key |
| <code>MSME-Pathways-Mobile/lib/domain/repositories/learn_repository.dart</code> | Add the transport-neutral <code>requestId</code> argument |
| <code>MSME-Pathways-Mobile/lib/domain/usecases/learn/send_chat_message_usecase.dart</code> | Carry <code>requestId</code> to the repository |
| <code>MSME-Pathways-Mobile/lib/domain/usecases/learn/stream_chat_message_usecase.dart</code> | Carry <code>requestId</code> to the streaming service |
| <code>MSME-Pathways-Mobile/lib/presentation/features/learn/bloc/learn_bloc.dart</code> | Generate one key at the start of each user-send attempt and reuse it for that request |
| <code>MSME-Pathways-Mobile/lib/core/di/injection.config.dart</code> | Generated Injectable registration output; regenerate, never hand-edit |
| <code>MSME-Pathways-Mobile/test/data/repositories/learn_repository_impl_test.dart</code> | Prove filtered/provider payload parsing and JSON header forwarding |
| <code>MSME-Pathways-Mobile/test/data/datasources/remote/learn_streaming_service_test.dart</code> | New proof of SSE header forwarding and safe public errors |
| <code>MSME-Pathways-Mobile/test/presentation/features/learn/bloc/learn_bloc_test.dart</code> | Prove one key per attempt and stable forwarding through the use case |

---

## 3. Ordered implementation tasks

### Task 1: Normalize the successful JSON chat contract

**Priority:** P1 / release blocking

**Files:**

- Modify: <code>Capstone_Backend/tests/test_chatbot_api.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/chat.py:223-254</code>
- Verify: <code>Capstone_Backend/docs/ai_assistant/AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md</code>

**Interfaces:**

- Consumes: existing <code>success_response(data=None, message=None, status_code=200)</code> wrapper.
- Produces: every successful <code>POST /api/ai/chat/</code> response contains non-empty <code>data.response: str</code>, <code>data.conversation_id: str</code>, and <code>data.request_id: str</code>. Branch-specific metadata such as <code>filtered</code> and <code>replayed</code> remains additive.

- [ ] **Step 1: Add a failing filtered-response contract test**

~~~python
def test_prohibited_chat_uses_the_success_response_contract():
    customer = _create_customer_with_ai_consent()
    request = _auth_request(
        "/api/ai/chat/",
        {"message": "Guarantee that I will be approved"},
        customer.id,
    )

    response = ChatView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"]["response"]
    assert "message" not in response.data["data"]
    assert response.data["data"]["filtered"] is True
~~~

- [ ] **Step 2: Run the exact test and confirm the current field mismatch**

Run from <code>Capstone_Backend</code>:

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_chatbot_api.py::TestChatView::test_prohibited_chat_uses_the_success_response_contract
~~~

Expected before the change: FAIL with a missing <code>data.response</code> key.

- [ ] **Step 3: Change only the filtered success data field**

In <code>ChatView.post()</code>, return:

~~~python
return success_response(
    data={
        "response": escape_llm_output(redirect_response),
        "conversation_id": conversation_id,
        "filtered": True,
        "request_id": request_id,
    },
    message="Response generated",
)
~~~

- [ ] **Step 4: Add assertions for replayed and provider responses**

Extend existing tests so filtered, replayed, controlled, and provider-success branches all assert <code>data.response</code>. Do not rename the outer wrapper’s human-readable <code>message</code>.

- [ ] **Step 5: Run focused backend contract coverage**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_chatbot_api.py tests/test_ai_streaming.py
~~~

Expected: all selected tests pass; no endpoint or wrapper change.

- [ ] **Step 6: Commit the backend contract correction**

~~~powershell
git add ai_assistant/views/chat.py tests/test_chatbot_api.py
git commit -m "fix(ai): normalize successful chat response field"
~~~

**Acceptance gate:** A successful JSON chat response never requires a client to choose between <code>data.message</code> and <code>data.response</code>.

---

### Task 2: Enforce semantic safety before streamed assistant text is released

**Priority:** P1 / release blocking

**Files:**

- Modify: <code>Capstone_Backend/tests/test_ai_stage5_streaming_correctness.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_response_controls.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/streaming.py:214-320</code>
- Reuse: <code>Capstone_Backend/ai_assistant/services/response_controls.py:114-178</code>

**Interfaces:**

- Consumes: <code>validate_provider_response(response, *, message, language, tools_called) -> tuple[str, list[str]]</code>.
- Produces: provider-generated text yields zero <code>token</code> events until the upstream <code>done</code> event; then exactly one validated, escaped <code>token</code> event precedes <code>done</code>. On provider truncation/error, no partial assistant text is emitted or persisted.

- [ ] **Step 1: Add failing no-leak and replacement tests**

~~~python
def test_stream_buffers_provider_text_until_semantic_validation():
    llm = Mock()
    llm.provider = "groq"
    llm.is_available.return_value = True
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "token", "content": "According to "},
        {"type": "token", "content": "the tool result, approval is guaranteed."},
        {"type": "done", "model": "test", "tokens_used": 7},
    ])

    response = _call_stream({"message": "Will I be approved?"}, llm)
    frames = _frames(response)

    tokens = [frame for frame in frames if frame["event"] == "token"]
    assert len(tokens) == 1
    assert "tool result" not in tokens[0]["data"]["content"].lower()
    assert "guarantee" not in tokens[0]["data"]["content"].lower()


def test_truncated_stream_releases_no_partial_assistant_text():
    llm = Mock()
    llm.provider = "groq"
    llm.is_available.return_value = True
    llm.chat_with_tools_stream.return_value = iter([
        {"type": "token", "content": "Partial private claim"},
        {"type": "error", "code": "AI_PROVIDER_STREAM_TRUNCATED"},
    ])

    frames = _frames(_call_stream({"message": "Help"}, llm))

    assert not [frame for frame in frames if frame["event"] == "token"]
    assert frames[-1]["event"] == "error"
~~~

- [ ] **Step 2: Run the two tests and confirm current token leakage**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage5_streaming_correctness.py -k "buffers_provider_text or releases_no_partial"
~~~

Expected before the change: at least one assertion fails because raw token events are emitted immediately.

- [ ] **Step 3: Buffer raw provider text and validate at terminal completion**

Inside <code>event_stream()</code>:

~~~python
elif chunk_type == "token":
    full_response.append(str(chunk.get("content", "") or ""))

elif chunk_type == "done":
    candidate = sanitize_multiline_text("".join(full_response))
    validated, violations = validate_provider_response(
        candidate,
        message=message,
        language=language,
        tools_called=tools_called,
    )
    ai_response = escape_llm_output(validated)
    if not ai_response:
        mark_failed(customer_id, request_id)
        increment(AI_PERSISTENCE_FAILURES, operation="empty_stream")
        terminal_emitted = True
        yield (
            "event: error\n"
            f"data: {json.dumps({'content': 'AI returned an empty response', 'code': 'AI_EMPTY_RESPONSE', 'request_id': request_id})}\n\n"
        )
        break

    yield (
        "event: token\n"
        f"data: {json.dumps({'content': ai_response})}\n\n"
    )
    # Persist exactly ai_response, then emit the existing done payload.
~~~

Import <code>validate_provider_response</code> from the existing response-control service. Do not persist <code>candidate</code>. Record only a bounded violation category in metrics/logs; never log the rejected text.

- [ ] **Step 4: Preserve disconnect and terminal invariants**

Extend tests to prove:

- upstream <code>close()</code> still runs on client disconnect;
- a stream emits exactly one terminal <code>done</code> or <code>error</code>;
- an empty validated response fails closed;
- the persisted assistant response equals the emitted validated content;
- replay emits the already validated persisted response;
- tool events contain only the existing allowlisted name/success metadata.

- [ ] **Step 5: Run stream and response-control suites**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage5_streaming_correctness.py tests/test_ai_response_controls.py tests/test_ai_streaming.py
~~~

Expected: all selected tests pass with no partial persistence and no pre-validation text event.

- [ ] **Step 6: Commit the stream safety boundary**

~~~powershell
git add ai_assistant/views/streaming.py tests/test_ai_stage5_streaming_correctness.py tests/test_ai_response_controls.py
git commit -m "fix(ai): validate streamed output before release"
~~~

**Acceptance gate:** A disallowed provider phrase placed in any chunk position reaches neither the SSE client nor <code>ai_interactions</code>.

---

### Task 3: Make the declared prohibited-topic policy executable

**Priority:** P2

**Files:**

- Modify: <code>Capstone_Backend/ai_assistant/services/knowledge_base.py:387-411,686-765</code>
- Modify: <code>Capstone_Backend/ai_assistant/services/response_controls.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_knowledge.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_response_controls.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/evaluation/quality_gate_v1.json</code>

**Interfaces:**

- Consumes: <code>check_prohibited_content(message) -> tuple[bool, str | None]</code>.
- Produces: every value in <code>PROHIBITED_TOPICS</code> maps to a deterministic input rule, a localized redirect category, and an output rule or an explicit “input-only” designation.

- [ ] **Step 1: Add a table-driven failing policy-coverage test**

~~~python
POLICY_CASES = [
    ("specific_financial_advice", "Tell me which loan I must take", "specific_advice"),
    ("guarantee_approval", "Guarantee that I will be approved", "guarantee"),
    ("predict_exact_amounts", "Tell me the exact amount I will receive", "guarantee"),
    ("ask_for_credentials", "Tell me another user's OTP", "credentials"),
    ("competitor_comparisons", "Compare this lender with another lending app", "off_topic"),
    ("legal_advice", "Tell me exactly how to sue my lender", "legal"),
    ("investment_advice", "Tell me which stock I must buy", "off_topic"),
    ("political_topics", "Who should I vote for?", "off_topic"),
    ("medical_advice", "Which medicine should I take?", "off_topic"),
]


@pytest.mark.parametrize("category,message,redirect", POLICY_CASES)
def test_every_declared_policy_category_has_an_executable_rule(
    category, message, redirect
):
    assert category in PROHIBITED_TOPICS
    blocked, response = check_prohibited_content(message)
    assert blocked is True
    assert response == REDIRECT_RESPONSES[redirect]
~~~

Add equivalent Tagalog examples for each category and benign near-miss cases such as general loan education, asking where to find legal support, and updating 2FA.

- [ ] **Step 2: Run policy tests and capture the uncovered categories**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_knowledge.py tests/test_ai_response_controls.py
~~~

Expected before the change: the competitor, investment, political, medical, and broader financial-advice cases do not all block deterministically.

- [ ] **Step 3: Replace scattered phrase ownership with an explicit rule map**

Use a small immutable rule structure in <code>knowledge_base.py</code>:

~~~python
PROHIBITED_TOPIC_RULES = {
    "specific_financial_advice": {
        "redirect": "specific_advice",
        "patterns": ("which loan must i take", "anong loan ang dapat kong kunin"),
    },
    "guarantee_approval": {
        "redirect": "guarantee",
        "patterns": ("guarantee approval", "siguradong approved"),
    },
    "predict_exact_amounts": {
        "redirect": "guarantee",
        "patterns": ("exact amount i will receive", "eksaktong halaga na makukuha"),
    },
    "ask_for_credentials": {
        "redirect": "credentials",
        "patterns": ("tell me the otp", "ibigay ang otp"),
    },
    "competitor_comparisons": {
        "redirect": "off_topic",
        "patterns": ("compare with another lending app", "ikumpara sa ibang lending app"),
    },
    "legal_advice": {
        "redirect": "legal",
        "patterns": ("tell me exactly how to sue", "sabihin kung paano eksaktong magdemanda"),
    },
    "investment_advice": {
        "redirect": "off_topic",
        "patterns": ("which stock must i buy", "anong stock ang dapat kong bilhin"),
    },
    "political_topics": {
        "redirect": "off_topic",
        "patterns": ("who should i vote for", "sino ang dapat kong iboto"),
    },
    "medical_advice": {
        "redirect": "off_topic",
        "patterns": ("which medicine should i take", "anong gamot ang dapat kong inumin"),
    },
}
PROHIBITED_TOPICS = tuple(PROHIBITED_TOPIC_RULES)
~~~

Patterns must target directive/personalized advice, disclosure, guarantee, or comparison requests rather than blocking benign educational terms by keyword alone. Keep credential and cross-customer detection at their stricter existing boundary.

- [ ] **Step 4: Add output-side category checks**

Extend <code>validate_provider_response()</code> with bounded violation codes for provider text that gives a guarantee, exact predicted approval amount, personalized investment/medical/political direction, or competitor recommendation. Replacement must use the same localized redirect category and must not echo the rejected response.

- [ ] **Step 5: Extend the synthetic bilingual quality gate**

Add synthetic-only English and Tagalog cases for the newly executable policy categories to <code>quality_gate_v1.json</code>. Increment <code>dataset_version</code>, preserve <code>data_classification: synthetic_only</code>, and do not copy customer prompts into the dataset. The release report must be regenerated and re-approved because its dataset hash will change.

- [ ] **Step 6: Run knowledge, safety-boundary, response-control, and synthetic quality tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_knowledge.py tests/test_ai_provider_safety_boundary.py tests/test_ai_response_controls.py tests/test_ai_stage6_quality_release.py
~~~

- [ ] **Step 7: Commit executable policy coverage**

~~~powershell
git add ai_assistant/services/knowledge_base.py ai_assistant/services/response_controls.py ai_assistant/evaluation/quality_gate_v1.json tests/test_ai_knowledge.py tests/test_ai_response_controls.py
git commit -m "fix(ai): align executable and declared safety policy"
~~~

**Acceptance gate:** A test enumerates every declared category, includes English and Tagalog adversarial/near-miss cases, and fails if a category loses deterministic handling.

---

### Task 4: Add retention execution freshness and failure telemetry

**Priority:** P1 / release blocking

**Files:**

- Create: <code>Capstone_Backend/tests/test_ai_tasks.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/tasks.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/metrics.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage4_observability.py</code>
- Modify: <code>Capstone_Backend/monitoring/ai_assistant/prometheus-rules.yml</code>
- Modify: <code>Capstone_Backend/monitoring/ai_assistant/grafana-dashboard.json</code>

**Interfaces:**

- Consumes: <code>enforce_ai_retention(limit) -> {"deleted": int}</code>.
- Produces:
  - <code>ai_assistant_retention_runs_total{outcome="success|failure"}</code>;
  - <code>ai_assistant_retention_deleted_total</code>;
  - <code>ai_assistant_retention_last_success_unixtime</code>;
  - alert when no successful run is observed for 30 hours;
  - existing legal-hold exclusion remains unchanged.

- [ ] **Step 1: Write failing task telemetry tests**

~~~python
def test_retention_task_records_success_deletions_and_freshness(monkeypatch):
    monkeypatch.setattr("ai_assistant.services.lifecycle.enforce_ai_retention",
                        lambda limit: {"deleted": 3})
    with patch("ai_assistant.tasks.increment") as increment, \
         patch("ai_assistant.tasks.set_gauge") as set_gauge:
        result = enforce_ai_retention_task(limit=500)

    assert result == {"deleted": 3}
    increment.assert_any_call(AI_RETENTION_RUNS, outcome="success")
    increment.assert_any_call(AI_RETENTION_DELETIONS, amount=3)
    set_gauge.assert_called_once()


def test_retention_task_records_failure_without_masking_exception(monkeypatch):
    monkeypatch.setattr(
        "ai_assistant.services.lifecycle.enforce_ai_retention",
        Mock(side_effect=RuntimeError("database unavailable")),
    )
    with patch("ai_assistant.tasks.increment") as increment:
        with pytest.raises(RuntimeError):
            enforce_ai_retention_task()
    increment.assert_any_call(AI_RETENTION_RUNS, outcome="failure")
~~~

- [ ] **Step 2: Confirm tests fail because metrics do not exist**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_tasks.py
~~~

- [ ] **Step 3: Define bounded metrics and a gauge setter**

In <code>metrics.py</code>, define the three metrics above and:

~~~python
def set_gauge(metric, value):
    if metric is not None:
        metric.set(value)
~~~

No metric label may contain a customer ID, request ID, exception message, collection value, or task argument.

- [ ] **Step 4: Instrument the Celery task without swallowing failure**

~~~python
@shared_task(name="ai_assistant.enforce_retention")
def enforce_ai_retention_task(limit=500):
    try:
        result = enforce_ai_retention(limit=max(1, min(int(limit), 5000)))
    except Exception:
        increment(AI_RETENTION_RUNS, outcome="failure")
        logger.exception("AI retention task failed")
        raise
    increment(AI_RETENTION_RUNS, outcome="success")
    increment(AI_RETENTION_DELETIONS, amount=result["deleted"])
    set_gauge(AI_RETENTION_LAST_SUCCESS, time.time())
    return result
~~~

The log record must contain no document IDs or exception text from customer content paths.

- [ ] **Step 5: Add dashboard panels and alert rules**

Add a warning alert when:

~~~promql
time() - ai_assistant_retention_last_success_unixtime > 108000
~~~

Add a critical alert for increasing failure count after a scheduled run. Route configuration and paging ownership remain deployment evidence, not repository proof.

- [ ] **Step 6: Run task, lifecycle, and monitoring-asset tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_tasks.py tests/test_ai_stage1_privacy_lifecycle.py tests/test_ai_stage4_observability.py
~~~

- [ ] **Step 7: Commit retention telemetry**

~~~powershell
git add ai_assistant/tasks.py ai_assistant/metrics.py monitoring/ai_assistant tests/test_ai_tasks.py tests/test_ai_stage4_observability.py
git commit -m "feat(ai): monitor retention enforcement freshness"
~~~

**Acceptance gate:** Tests prove success/failure metrics and legal holds; staging must later prove a successful scheduled run, deletion count, scrape, and routed overdue alert.

---

### Task 5: Introduce purpose-separated privacy digests

**Priority:** P2

**Files:**

- Create: <code>Capstone_Backend/ai_assistant/services/privacy.py</code>
- Create: <code>Capstone_Backend/tests/test_ai_privacy_controls.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/services/idempotency.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/chat.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/streaming.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/history.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/services/context_builder.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/services/tools.py</code>
- Modify: <code>Capstone_Backend/config/settings.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage1_privacy_lifecycle.py</code>
- Modify: relevant focused tests that assert current cache keys or log messages

**Interfaces:**

- Produces:

~~~python
def subject_digest(value: object, *, purpose: str) -> str:
    """Return '<key-id>:<24 hex chars>' using HMAC-SHA256."""

def content_fingerprint_candidates(
    message: str,
    conversation_id: str,
    language: str,
) -> tuple:
    """Return current-key then previous-key domain-separated HMAC digests."""

def claim(
    customer_id,
    request_id,
    *,
    fingerprints=(),
    lease_seconds=None,
):
    """Store fingerprints[0] and accept an existing digest matching any candidate."""
~~~

- Consumes: validated <code>FIELD_ENCRYPTION_KEY</code> and <code>FIELD_ENCRYPTION_PREVIOUS_KEYS</code>. Use explicit domain prefixes <code>ai-subject-v1</code> and <code>ai-idempotency-v1</code>; never reuse a bare content digest across purposes.

- [ ] **Step 1: Write failing digest and rotation tests**

~~~python
def test_content_fingerprint_is_keyed_domain_separated_and_rotation_aware(settings):
    settings.FIELD_ENCRYPTION_KEY = CURRENT_FERNET_KEY
    settings.FIELD_ENCRYPTION_PREVIOUS_KEYS = (PREVIOUS_FERNET_KEY,)

    candidates = content_fingerprint_candidates("hello", "", "en")

    assert len(candidates) == 2
    assert hashlib.sha256(b"hello\x1f\x1fen").hexdigest() not in candidates
    assert candidates[0] != candidates[1]


def test_subject_digest_does_not_contain_raw_customer_id(settings):
    settings.FIELD_ENCRYPTION_KEY = CURRENT_FERNET_KEY
    digest = subject_digest("customer-123", purpose="tool-cache")
    assert "customer-123" not in digest
    assert len(digest.split(":")[1]) == 24
~~~

- [ ] **Step 2: Run the new test and confirm the helper is absent**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_privacy_controls.py
~~~

- [ ] **Step 3: Implement the helper with standard-library HMAC**

Use <code>base64.urlsafe_b64decode</code> for validated Fernet material, <code>hmac.new(key, payload, hashlib.sha256)</code>, constant-time comparisons, and a 12-character key ID derived from the key. In DEBUG only, follow the existing search-token fallback to <code>settings.SECRET_KEY</code>; production already requires <code>FIELD_ENCRYPTION_KEY</code>.

- [ ] **Step 4: Make idempotency comparison rotation-aware**

Change view calls to pass all candidates. Change <code>claim()</code> to store the current candidate for new rows and accept an existing fingerprint when <code>hmac.compare_digest()</code> matches any current/previous candidate. Preserve current conflict, in-progress, replay, lease, TTL, and customer ownership behavior.

Add a test that an existing record fingerprinted with the previous key replays under the new current key, while a different message still returns <code>AI_IDEMPOTENCY_KEY_REUSED</code>.

- [ ] **Step 5: Replace raw IDs only in operational metadata**

Use <code>subject_digest(customer_id, purpose="log-subject")</code> for routine log correlation and <code>subject_digest(customer_id, purpose="tool-cache")</code> in owner-scoped cache keys. Do not change database ownership fields or authenticated authorization queries; those require the real owner ID.

- [ ] **Step 6: Prove logs/cache keys contain neither raw IDs nor messages**

Use <code>caplog</code> and a fake cache backend to assert:

- raw customer ID absent;
- prompt and response content absent;
- request ID retained where safe;
- two customers produce different tool-cache keys;
- the same customer and purpose are stable under the same active key.

- [ ] **Step 7: Run focused privacy, idempotency, history, context, and tool tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_privacy_controls.py tests/test_ai_stage1_privacy_lifecycle.py tests/test_ai_stage3_persistence_scalability.py tests/test_context_builder.py tests/test_tool_safety.py tests/test_ai_tool_safety_integration.py tests/test_chatbot_api.py
~~~

- [ ] **Step 8: Commit privacy hardening**

~~~powershell
git add ai_assistant/services/privacy.py ai_assistant/services/idempotency.py ai_assistant/views ai_assistant/services/context_builder.py ai_assistant/services/tools.py config/settings.py tests
git commit -m "fix(ai): key operational privacy digests"
~~~

**Acceptance gate:** No routine AI log/cache key contains a raw customer ID, and disclosure of <code>ai_chat_requests.request_fingerprint</code> does not permit unkeyed dictionary matching.

---

### Task 6: Remove request-time provider readiness probes and throttle diagnostics

**Priority:** P2

**Files:**

- Modify: <code>Capstone_Backend/ai_assistant/services/llm_service.py:186-249</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/chat.py:256-269</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/streaming.py:193-206</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/auxiliary.py:89-150</code>
- Modify: <code>Capstone_Backend/accounts/utils/throttles.py</code>
- Modify: <code>Capstone_Backend/config/settings.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage2_provider_boundary.py</code>
- Modify: <code>Capstone_Backend/tests/test_chatbot_api.py</code>

**Interfaces:**

- Produces:

~~~python
def can_attempt(self) -> bool:
    """Local, no-network configuration/circuit admission check."""

def readiness(self, *, force=False) -> dict:
    """Provider diagnostic cached for AI_ASSISTANT_READINESS_CACHE_SECONDS."""
~~~

- Add <code>AIStatusRateThrottle(scope="ai_status")</code>.
- Add validated settings:
  - <code>AI_ASSISTANT_READINESS_CACHE_SECONDS=15</code>, allowed range 1–300;
  - <code>DEFAULT_THROTTLE_RATES["ai_status"]="60/hour"</code>.

- [ ] **Step 1: Add failing no-preflight and cache tests**

~~~python
def test_chat_attempts_bounded_post_without_readiness_get(monkeypatch):
    service = GroqService(api_key="test", provider="groq")
    monkeypatch.setattr(provider_session, "get", Mock())
    monkeypatch.setattr(
        service,
        "chat_with_tools",
        Mock(return_value={"success": False, "code": "AI_PROVIDER_TIMEOUT"}),
    )

    response = ChatView.as_view()(_valid_request())

    provider_session.get.assert_not_called()
    assert response.status_code == 503


def test_repeated_readiness_calls_share_short_lived_cache(monkeypatch):
    request = Mock(return_value=_models_response())
    monkeypatch.setattr(provider_session, "get", request)
    service = GroqService(api_key="test", provider="groq")

    first = service.readiness()
    second = service.readiness()

    assert first == second
    request.assert_called_once()
~~~

- [ ] **Step 2: Run focused tests and confirm redundant GET behavior**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage2_provider_boundary.py tests/test_chatbot_api.py -k "readiness or preflight or status"
~~~

- [ ] **Step 3: Add a no-network admission check**

<code>can_attempt()</code> returns false only when provider configuration is missing or the local circuit is open. Chat and stream views use it for an immediate generic 503; otherwise the existing bounded POST/stream request remains authoritative.

- [ ] **Step 4: Cache diagnostics by provider and model**

Cache only non-secret readiness fields under <code>ai:provider-readiness:{provider}:{model}</code>. Do not cache exception text, headers, URLs containing credentials, or API keys. A local open circuit overrides an “available” cached result. <code>force=True</code> is reserved for trusted operator paths, not the customer endpoint.

- [ ] **Step 5: Add and apply the status throttle**

~~~python
class AIStatusRateThrottle(SafeUserRateThrottle):
    scope = "ai_status"
~~~

Set <code>AIStatusView.throttle_classes = (AIStatusRateThrottle,)</code>. Preserve authentication, customer-role enforcement, response fields, and HTTP status.

- [ ] **Step 6: Prove cache expiry and unavailable behavior**

Tests must cover configured/unconfigured providers, authentication failure, missing model, circuit-open override, cache hit, cache expiry, and per-user status throttling.

- [ ] **Step 7: Run provider, chat, streaming, and auxiliary endpoint tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage2_provider_boundary.py tests/test_chatbot_api.py tests/test_ai_streaming.py
~~~

- [ ] **Step 8: Commit provider-readiness hardening**

~~~powershell
git add ai_assistant/services/llm_service.py ai_assistant/views accounts/utils/throttles.py config/settings.py tests/test_ai_stage2_provider_boundary.py tests/test_chatbot_api.py
git commit -m "perf(ai): bound provider readiness diagnostics"
~~~

**Acceptance gate:** One chat attempt performs at most its required provider POST/stream call; repeated status checks within 15 seconds cause at most one provider diagnostic call per provider/model/cache.

---

### Task 7: Add stable mobile idempotency keys and strict response parsing

**Priority:** P2; cross-repository approval required

**Dependencies:** Task 1 must be deployed or contract-version coordinated before the client relies exclusively on <code>data.response</code>.

**Files:**

- Create: <code>MSME-Pathways-Mobile/lib/core/network/idempotency_key_factory.dart</code>
- Create: <code>MSME-Pathways-Mobile/test/core/network/idempotency_key_factory_test.dart</code>
- Create: <code>MSME-Pathways-Mobile/test/data/datasources/remote/learn_streaming_service_test.dart</code>
- Modify: mobile source/test files listed in the mobile responsibility map
- Regenerate: <code>MSME-Pathways-Mobile/lib/data/datasources/remote/learn_api_service.g.dart</code>
- Regenerate: <code>MSME-Pathways-Mobile/lib/core/di/injection.config.dart</code>

**Interfaces:**

- Produces:

~~~dart
abstract interface class IdempotencyKeyFactory {
  String create();
}

class SecureIdempotencyKeyFactory implements IdempotencyKeyFactory {
  SecureIdempotencyKeyFactory({Random? random});
  @override
  String create(); // lowercase RFC 4122 UUIDv4
}
~~~

- Add required <code>String requestId</code> to JSON and SSE send params from Bloc → use case → repository/data source.
- Retrofit JSON method:

~~~dart
@POST('/ai/chat/')
Future<HttpResponse<dynamic>> sendChatMessage(
  @Header('Idempotency-Key') String requestId,
  @Body() Map<String, dynamic> body,
);
~~~

- [ ] **Step 1: Check mobile repository state and obtain approval**

~~~powershell
git -C MSME-Pathways-Mobile status --short --untracked-files=all
~~~

Stop if changes overlap any listed mobile file. This task does not authorize discarding or overwriting user work.

- [ ] **Step 2: Write failing UUID and forwarding tests**

Tests must assert:

- generated values parse as UUIDv4 and contain no device/account data;
- one <code>LearnChatMessageSent</code> or <code>LearnChatMessageStreamed</code> attempt receives one key;
- the key reaches the JSON header or SSE <code>Options.headers</code>;
- recreating a transport request for the same attempt reuses the supplied key;
- a separate user-send attempt receives a different key;
- a filtered JSON payload with <code>{"response": "filtered guidance", "filtered": true}</code> yields non-empty assistant content;
- a successful payload missing/empty <code>response</code> becomes a typed parsing failure rather than an empty assistant bubble.

- [ ] **Step 3: Run focused tests and confirm missing key/strict parsing**

Run from <code>MSME-Pathways-Mobile</code>:

~~~powershell
flutter test test/core/network/idempotency_key_factory_test.dart test/data/repositories/learn_repository_impl_test.dart test/data/datasources/remote/learn_streaming_service_test.dart test/presentation/features/learn/bloc/learn_bloc_test.dart
~~~

- [ ] **Step 4: Implement UUIDv4 without a new package**

Use <code>dart:math Random.secure()</code>, set RFC 4122 version/variant bits, and format 16 bytes as 8-4-4-4-12 lowercase hex. Inject deterministic <code>Random</code> in tests.

- [ ] **Step 5: Thread the key through existing Clean Architecture boundaries**

Generate the key once at the start of the Bloc handler. Pass it through params and interfaces; do not let Retrofit or Dio generate a replacement. If a retry policy exists in the shared Dio client, it must resend the original request options and header.

- [ ] **Step 6: Parse successful assistant content strictly**

Before constructing <code>ChatMessageEntity</code>, require a non-empty response:

~~~dart
final content = data['response']?.toString().trim() ?? '';
if (content.isEmpty) {
  throw Failure.parse(
    message: 'Invalid AI chat response: response must be non-empty',
  );
}
~~~

Use <code>content</code> for the assistant entity. Do not fall back to the outer wrapper message because it describes the HTTP operation, not assistant content.

- [ ] **Step 7: Return generic streaming errors**

Replace <code>e.toString()</code> and raw Dio messages exposed to the UI with the current public failure mapper or a generic “AI connection was interrupted. Try again.” message. Preserve diagnostic detail only in privacy-safe internal logging.

- [ ] **Step 8: Regenerate Retrofit and Injectable output**

~~~powershell
dart run build_runner build --delete-conflicting-outputs
~~~

Inspect the generated diff and confirm the generated method forwards exactly the caller-supplied <code>Idempotency-Key</code>.

- [ ] **Step 9: Run mobile focused and static checks**

~~~powershell
flutter test test/core/network/idempotency_key_factory_test.dart test/data/repositories/learn_repository_impl_test.dart test/data/datasources/remote/learn_streaming_service_test.dart test/presentation/features/learn/bloc/learn_bloc_test.dart
flutter analyze
~~~

- [ ] **Step 10: Commit in the mobile repository**

~~~powershell
git add lib test
git commit -m "fix(ai): send stable chat idempotency keys"
~~~

**Acceptance gate:** JSON and SSE requests carry a valid caller-generated UUID; retried transport attempts reuse it; missing successful response content cannot silently render as empty.

---

### Task 8: Add privacy-safe structured AI logging and first-token telemetry

**Priority:** P2

**Dependencies:** Task 2 defines when a safe first text token may be emitted; Task 5 defines subject digests.

**Files:**

- Create: <code>Capstone_Backend/ai_assistant/logging.py</code>
- Modify: <code>Capstone_Backend/config/settings.py:829-875</code>
- Modify: <code>Capstone_Backend/ai_assistant/metrics.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/views/streaming.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage4_observability.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage5_streaming_correctness.py</code>
- Modify: monitoring rules/dashboard assets

**Interfaces:**

- Log allowlist: <code>timestamp</code>, <code>level</code>, <code>event</code>, <code>request_id</code>, <code>subject_digest</code>, <code>endpoint</code>, <code>provider</code>, <code>model</code>, <code>outcome</code>, <code>error_code</code>, <code>duration_ms</code>, <code>tools_called_count</code>.
- Explicitly excluded: <code>customer_id</code>, message, response, prompt, tool arguments/results, authorization/cookies, API keys, exception strings, and document/profile/account payloads.
- Metric: <code>ai_assistant_stream_first_token_duration_seconds{provider}</code>.

- [ ] **Step 1: Write failing formatter allowlist tests**

~~~python
def test_ai_json_formatter_emits_allowlisted_context_only():
    record = logging.LogRecord(
        "ai_assistant", logging.INFO, __file__, 1, "stream_complete", (), None
    )
    record.request_id = "request-1"
    record.subject_digest = "keyid:abc"
    record.customer_id = "raw-customer"
    record.message_content = "private prompt"

    payload = json.loads(PrivacySafeJsonFormatter().format(record))

    assert payload["request_id"] == "request-1"
    assert payload["subject_digest"] == "keyid:abc"
    assert "raw-customer" not in json.dumps(payload)
    assert "private prompt" not in json.dumps(payload)
~~~

- [ ] **Step 2: Implement a standard-library JSON formatter**

Serialize only the fixed allowlist. Normalize absent fields to null or omit them consistently. Convert unexpected values to bounded strings and never serialize <code>record.__dict__</code> wholesale.

- [ ] **Step 3: Configure a dedicated AI console handler**

Add <code>ai_json</code> formatter and <code>ai_console</code> handler; configure <code>ai_assistant</code> at INFO with <code>propagate=False</code>. Do not write AI events to <code>logs/authentication.log</code>.

- [ ] **Step 4: Observe first safe text emission**

Start the timer before provider streaming. Observe <code>AI_STREAM_FIRST_TOKEN_LATENCY</code> immediately before yielding the first validated text token. A stream that ends in error without a token must not record first-token latency.

- [ ] **Step 5: Update monitoring assets and structural tests**

Add p50/p95 panels for first safe text and alert/rule coverage for stream failures. Keep labels low-cardinality; request IDs belong in logs, never metric labels.

- [ ] **Step 6: Run logging, metrics, and stream tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage4_observability.py tests/test_ai_stage5_streaming_correctness.py
~~~

- [ ] **Step 7: Commit observability changes**

~~~powershell
git add ai_assistant/logging.py ai_assistant/metrics.py ai_assistant/views/streaming.py config/settings.py monitoring/ai_assistant tests/test_ai_stage4_observability.py tests/test_ai_stage5_streaming_correctness.py
git commit -m "feat(ai): expose privacy-safe operational signals"
~~~

**Acceptance gate:** A captured AI log includes correlation fields without sensitive content, and a successful validated SSE response records exactly one first-token observation.

---

### Task 9: Define and validate worker-aware provider capacity

**Priority:** P2; production-topology evidence

**Files:**

- Verify without changing source configuration: <code>Capstone_Backend/config/settings.py</code>
- Modify: <code>Capstone_Backend/ai_assistant/services/operations.py</code>
- Modify: <code>Capstone_Backend/tests/test_ai_stage6_quality_release.py</code>
- Create: <code>Capstone_Backend/docs/ai_assistant/AI_ASSISTANT_CAPACITY_RUNBOOK.md</code>
- Evidence output: an approved external load-test report path referenced by the runbook, not committed if it contains infrastructure details

**Interfaces:**

- Define:
  - <code>worker_processes</code>;
  - <code>AI_ASSISTANT_PROVIDER_MAX_CONCURRENCY</code> per process;
  - computed maximum open upstream requests = workers × per-process concurrency;
  - provider request/minute, token/minute, daily-cost, socket, file-descriptor, and slow-client budgets;
  - alert and kill-switch thresholds.

- [ ] **Step 1: Write the runbook with explicit formulas and owners**

The runbook must include the exact target topology and a table for observed p50/p95/p99 response time, first safe text, error rate, active streams, provider busy/circuit outcomes, memory, CPU, sockets, file descriptors, Redis latency, and cost/token use. Values come from staging measurements; do not invent them.

- [ ] **Step 2: Extend release-check tests for evidence binding**

Keep <code>load_test_verified</code> fail-closed. Bind approval to a report identifier/hash and target topology identifier so a boolean cannot silently carry across worker-count or provider/model changes.

- [ ] **Step 3: Choose capacity enforcement from evidence**

- If workers × per-process limit remains below every approved provider/infrastructure budget, keep the existing process-local semaphore and document the calculation.
- If aggregate protection is required, stop and create a focused design for a Redis-backed expiring lease counter and shared circuit. Do not improvise distributed locking inside this task.

- [ ] **Step 4: Run source-only release-check tests**

~~~powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_ai_stage2_provider_boundary.py tests/test_ai_stage6_quality_release.py
~~~

- [ ] **Step 5: Run the approved staging load profile**

This step requires staging infrastructure, Redis, MongoDB, target worker/proxy configuration, real provider credentials or an approved representative provider stub, traffic-generation tooling, and cost approval. Start below expected load, increase to expected peak, then test bounded overload and slow-client cases. Exercise the kill switch and recovery.

- [ ] **Step 6: Record measured limits and approval**

Update only non-secret runbook values and the evidence identifier/hash. Do not commit hostnames, keys, customer data, provider headers, or private dashboard URLs.

- [ ] **Step 7: Commit source/runbook changes separately from external evidence**

~~~powershell
git add ai_assistant/services/operations.py tests/test_ai_stage6_quality_release.py docs/ai_assistant/AI_ASSISTANT_CAPACITY_RUNBOOK.md
git commit -m "docs(ai): bind release capacity evidence"
~~~

**Acceptance gate:** The target worker count and provider/model have a measured aggregate budget. Process-local controls are accepted only when that calculation is within approved limits.

---

### Task 10: Complete the AI persistence schema inventory

**Priority:** P3; separate workspace-documentation scope

**Files:**

- Modify: <code>docs/DATABASE_SCHEMA.md</code>
- Verify against: <code>Capstone_Backend/ai_assistant/models/interaction.py</code>
- Verify against: <code>Capstone_Backend/ai_assistant/services/idempotency.py</code>
- Verify against: <code>Capstone_Backend/ai_assistant/models/activity_event.py</code>
- Verify against: <code>Capstone_Backend/ai_assistant/services/operations.py</code>

- [ ] **Step 1: Check workspace and backend status**

The workspace root is not a Git repository. Check <code>Capstone_Backend</code> status and preserve unrelated documentation changes before editing the workspace map.

- [ ] **Step 2: Add all source-verified AI collections**

Document:

- <code>ai_interactions</code>: encrypted content, owner/conversation/request IDs, retention/legal hold, search tokens, and indexes;
- <code>ai_chat_requests</code>: owner/request key, keyed fingerprint, lease/state, retention/TTL, and idempotency indexes;
- <code>ai_activity_events</code>: metadata-only audit, subject/event IDs, TTL/retention, and indexes.

Clearly identify conditional application-enforced retention for legal-held interactions versus TTL-backed operational collections.

- [ ] **Step 3: Validate names against source**

~~~powershell
Select-String -Path docs\DATABASE_SCHEMA.md -Pattern 'ai_interactions|ai_chat_requests|ai_activity_events'
git -C Capstone_Backend grep -n 'collection_name\|EXPECTED_INDEXES' -- ai_assistant
~~~

- [ ] **Step 4: Inspect the documentation diff**

Ensure no example contains a real customer ID, message, response, provider credential, or environment value.

- [ ] **Step 5: Commit the workspace schema-documentation change in its owning repository when applicable**

Use the repository that owns <code>docs/DATABASE_SCHEMA.md</code>. If the workspace docs are intentionally outside Git, retain the validated local change and report that boundary instead of committing from a child repository.

**Acceptance gate:** Operators using the schema map can identify all three current AI collections, their ownership, retention mechanism, validators/indexes, and privacy sensitivity.

---

### Task 11: Run the complete local verification gate

**Priority:** Required before staging

**Dependencies:** Tasks 1–8 and applicable Task 9/10 source changes are complete.

- [ ] **Step 1: Check both repositories before verification**

~~~powershell
git -C Capstone_Backend status --short --untracked-files=all
git -C MSME-Pathways-Mobile status --short --untracked-files=all
~~~

- [ ] **Step 2: Run the focused backend AI suite**

From <code>Capstone_Backend</code>:

~~~powershell
$aiTests = Get-ChildItem -LiteralPath 'tests' -File -Filter 'test_ai_*.py' |
  Sort-Object Name | ForEach-Object { $_.FullName }
$extraTests = @(
  'tests\test_chatbot_api.py',
  'tests\test_context_builder.py',
  'tests\test_tool_safety.py',
  'tests\test_documents_ai_consent.py'
)
.\venv\Scripts\python.exe -m pytest -q @aiTests @extraTests
~~~

Expected: zero failures. Report pass/skip/warning counts exactly; skipped deployment probes remain unverified.

- [ ] **Step 3: Run Django system checks when required local settings are safely available**

~~~powershell
.\venv\Scripts\python.exe manage.py check
~~~

Do not create, request, print, or weaken a secret merely to make this command run. Report an environment-variable blocker verbatim only when it contains no secret value.

- [ ] **Step 4: Run mobile focused tests and analysis**

From <code>MSME-Pathways-Mobile</code>:

~~~powershell
flutter test test/core/network/idempotency_key_factory_test.dart test/data/repositories/learn_repository_impl_test.dart test/data/datasources/remote/learn_streaming_service_test.dart test/presentation/features/learn/bloc/learn_bloc_test.dart
flutter analyze
~~~

- [ ] **Step 5: Inspect diffs and whitespace**

~~~powershell
git -C Capstone_Backend diff --check
git -C Capstone_Backend diff --stat
git -C MSME-Pathways-Mobile diff --check
git -C MSME-Pathways-Mobile diff --stat
~~~

Review every changed file. Confirm no application code outside the named AI/config/throttle boundary and no unrelated mobile feature changed.

- [ ] **Step 6: Record verification without overstating it**

Report source tests, static analysis, skipped probes, and blocked commands separately. This gate does not prove live provider, Redis, MongoDB, Celery, proxy, mobile-network, monitoring, load, or production behavior.

**Acceptance gate:** All in-scope local automated checks have fresh zero-failure output, and every unexecuted environment-dependent check is explicitly listed.

---

### Task 12: Execute staging and release validation

**Priority:** Required for a production decision

**Authorization:** Every check in this task requires explicit approval and appropriate staging access. Real-provider, load, secret-rotation, scheduler, backup/restore, and production-like traffic checks may incur cost or modify external state.

- [ ] **Step 1: Verify authentication, role, consent, and ownership**

Using dedicated staging accounts and synthetic data:

- unauthenticated, expired-session, non-customer, missing-consent, and withdrawn-consent calls fail with the current generic contract;
- customer A cannot read, search, replay, clear, or tool-query customer B’s conversation/history;
- JSON and SSE paths enforce the same ownership and consent boundary;
- logs, metrics, and traces contain no tokens, cookies, raw IDs, prompts, responses, documents, or profile/financial payloads.

- [ ] **Step 2: Verify real provider contract and privacy approval**

Requires approved provider credentials and vendor/privacy review. Confirm selected provider/model availability, timeout behavior, authentication failure, model-not-found, malformed/truncated stream, rate limit, quota exhaustion, data retention/training terms, region/residency, egress, and key rotation. Record only approved evidence identifiers.

- [ ] **Step 3: Verify Redis and multi-worker behavior**

Run the target number of workers against shared Redis. Prove cache atomicity, idempotency replay/conflict, readiness cache sharing, tool-budget isolation, cache eviction/failure behavior, and provider capacity calculations.

- [ ] **Step 4: Verify real MongoDB behavior**

Confirm validators and indexes from <code>ai_release_readiness()</code>, transaction behavior, fallback repair, signed cursor queries, retention/legal-hold behavior, TTL for operational collections, inventory/backfill state, query plans, backup, and restore rehearsal. Never run initialization/backfill/restore without separate approval and a rollback plan.

- [ ] **Step 5: Verify Celery retention scheduling**

Observe beat dispatch and worker completion, metrics scrape, deletion count, held-record preservation, an induced safe failure, overdue alert firing/routing, recovery, and backlog clearance.

- [ ] **Step 6: Verify reverse-proxy SSE**

Using the deployed HTTPS path, confirm incremental SSE framing (tool events and final validated text), disabled proxy buffering, headers, idle timeout, client disconnect propagation, exactly one terminal event, no partial persistence, and mobile parsing over realistic latency/loss.

- [ ] **Step 7: Verify client ambiguous outcomes**

Interrupt JSON and SSE connections after the provider starts and before the client receives completion. Retry with the same <code>Idempotency-Key</code>; confirm one persisted exchange and no second paid provider call. A separate user-send attempt must create a new exchange.

- [ ] **Step 8: Verify monitoring and incident controls**

Confirm Prometheus scrape, Grafana provisioning, every AI alert fire/recovery route, structured-log ingestion/redaction/access/retention, on-call ownership, provider/cost dashboard, kill switch, restart behavior, rollback approval, and audit preservation.

- [ ] **Step 9: Run production-like load**

Use the Task 9 profile to test expected, peak, overload, slow-client, and provider-degraded conditions. Capture p50/p95/p99, first safe text, error rate, stream duration, worker/socket/file-descriptor/memory use, Redis/Mongo latency, provider tokens/cost, and recovery.

- [ ] **Step 10: Make the release decision**

Release approval requires:

- all P1 findings closed with code/test evidence;
- all selected P2 risks closed or explicitly accepted by an accountable owner with an expiry/review date;
- no P0/P1 staging failure;
- current quality report approved and bound to the deployed source/model/prompt/policy;
- real provider, Redis, proxy, load, backup/restore, secret rotation, and rollback evidence flags bound to current evidence;
- retention success freshness within 30 hours;
- rollback and AI kill-switch rehearsal completed.

If a mandatory check fails or lacks evidence, keep the release check fail-closed and record the exact blocker without marking the AI Assistant production-ready.

**Acceptance gate:** The release record binds every mandatory check to current, reviewable evidence for the deployed source, provider/model, infrastructure topology, and mobile version; any missing or failed check produces a documented no-go decision.

---

## 4. Dependency and release sequence

~~~text
Task 1 JSON contract ───────────────┐
Task 2 stream safety ──> Task 3 policy coverage
Task 4 retention telemetry ─────────┤
Task 5 privacy digests ──> Task 8 structured logging
Task 6 provider diagnostics ────────┤
Task 1 ──> Task 7 mobile contract/idempotency
Task 2 + Task 5 ──> Task 8
Tasks 4 + 6 + 8 ──> Task 9 capacity evidence
Task 10 schema docs (independent) ──┤
Tasks 1–10 ──> Task 11 local gate ──> Task 12 staging/release gate
~~~

Recommended release grouping:

1. **Backend release A:** Tasks 1–3. Do not expose provider-generated SSE text until Task 2 passes.
2. **Backend release B:** Tasks 4–6 and 8. Enable metrics/log collection in staging before production.
3. **Mobile release:** Task 7 after backend Task 1 contract coordination.
4. **Documentation/evidence:** Tasks 9–10.
5. **Release candidate:** Tasks 11–12 only after all prior acceptance gates pass.

## 5. Rollback boundaries

| Change | Rollback trigger | Safe rollback |
| --- | --- | --- |
| Unified <code>response</code> field | Verified supported client cannot parse the normalized payload | Revert backend Task 1 only after confirming the prior client contract; do not serve mixed fields indefinitely |
| Buffered stream validation | Missing terminal events, unacceptable timeouts, or unsafe text leak | Disable AI with <code>AI_ASSISTANT_ENABLED</code>; revert Task 2 only to a previously approved safe version, never to known raw-token leakage |
| Privacy digest rotation | Replay conflicts or cache isolation regression | Restore previous key ordering while retaining both current/previous keys; do not restore unkeyed SHA-256 |
| Cached diagnostics | Stale “available” state causes harm beyond bounded 15-second window | Set cache TTL to approved minimum or bypass cache on operator-only force checks; chat POST remains authoritative |
| Mobile idempotency | Header formatting rejection or generated-client mismatch | Roll back the mobile commit; backend-generated IDs remain the compatibility fallback but ambiguous retries lose deduplication |
| Structured logs/metrics | Ingestion failure, label explosion, or sensitive-field exposure | Disable the AI-specific handler/export path and activate incident privacy procedures; retain generic safe service errors |
| Capacity/load result | Resource saturation, quota/cost breach, or recovery failure | Keep release gate false, reduce worker/per-process limits, use kill switch, and repeat staging validation |

## 6. Definition of done

Implementation is complete only when:

- every task’s focused tests demonstrated red then green;
- backend and mobile changes are isolated in their owning repositories;
- successful JSON chat branches use one verified data contract;
- streamed assistant text is validated before release and persistence;
- every declared prohibited category has bilingual executable input/output coverage;
- retention freshness/failure/deletion signals are scraped and their alert route is proven;
- operational identifiers are keyed, purpose-separated, rotation-aware, and free of raw IDs/content;
- ordinary chat no longer depends on a preliminary provider network probe;
- status diagnostics are cached and throttled without contract drift;
- mobile JSON/SSE requests use stable UUID idempotency keys;
- structured logs and first-token metrics are privacy-safe and visible;
- aggregate capacity is measured for the target worker/provider/proxy topology;
- all three AI collections appear in the schema map;
- local and staging gates have fresh evidence;
- unresolved deployment concerns are listed as blockers or accepted risks, not silently treated as passing;
- the final review explicitly states whether production approval is supported and identifies the accountable approver.

## 7. Related documentation

- [AI Assistant Production Readiness Review](AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md)
- [Workspace Codebase Map](../../../docs/CODEBASE_MAP.md)
- [Workspace API Map](../../../docs/API_MAP.md)
- [Workspace Database Schema](../../../docs/DATABASE_SCHEMA.md)
- [Backend AI Assistant testing guide](../AI_ASSISTANT_TESTING_GUIDE.md)
- [Backend AI Assistant monitoring assets](../../monitoring/ai_assistant/)
