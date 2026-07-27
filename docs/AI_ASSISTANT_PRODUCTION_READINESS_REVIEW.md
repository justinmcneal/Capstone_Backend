# AI Assistant Production Readiness Review

Date: 2026-07-27  
Scope: Static code review of `ai_assistant/` and related AI/LLM/tooling behavior.

## Executive Summary

The `ai_assistant` module provides a Groq/Ollama-backed chatbot with function calling, SSE streaming, privacy-aware context building, rate limiting, and content filtering. All concerns from the initial accuracy/observations review have been resolved or locked via inline guards. The module remains dependent on shared `accounts/` auth/consent/access-control infrastructure and does not introduce separate middleware or monitoring. Remaining items are minor: index/bootstrap coverage for AI collections, and absence of request correlation/tracing for LLM calls.

## High Priority Findings

1. Session-pooled HTTP calls replace unbuffered `requests` usage.
   - `ai_assistant/services/llm_service.py` now uses a module-level `requests.Session()` for all Groq/Ollama HTTP calls.
   - Risk: reduced TCP handshake overhead and connection reuse under moderate load. **Status: MITIGATED.**

2. Output sanitization is applied uniformly.
   - `escape_llm_output()` wraps every AI-generated string before persistence (`AIInteraction`) and client response.
   - Applied to non-streaming chat, prohibited-content redirects, streamed token events, and streamed error events.
   - Risk: LLM-emitted markup/JS is neutralized before rendering. **Status: MITIGATED.**

3. Tool safety is centralized and enforced.
   - `execute_tool()` routes through `safe_execute_tool()` with rate limiting, validation, and auditing. Raw DB access is isolated in `_execute_tool_raw()`.
   - Risk: tool abuse or invalid parameters are caught before DB queries. **Status: MITIGATED.**

4. SSE frame formatting is guarded by automated tests.
   - Strict frame-parsing tests verify exact `event: ...\ndata: ...\n\n` structure, `text/event-stream` content type, and no middleware wrapping.
   - Risk: middleware/renderer changes that corrupt SSE will be caught by tests. **Status: MITIGATED.**

5. Knowledge-base lock is inline in the source file.
   - `ai_assistant/services/knowledge_base.py` contains a review checklist before edits.
   - Risk: rapid drift between knowledge base and actual API contracts is reduced. **Status: LOCKED.**

## Medium Priority Findings

1. View file size is resolved via module split.
   - `chat_views.py` was split into `chat.py`, `streaming.py`, `history.py`, and `auxiliary.py`. Shared mixins/renderers/constants remain in `chat_views.py`.
   - Status: **DONE.**

2. Test coverage is comprehensive.
   - `tests/test_ai_tool_safety_integration.py` (277 lines)
   - `tests/test_ai_context_builder.py` (414 lines)
   - `tests/test_ai_streaming.py` (196 lines)
   - `tests/test_chatbot_api.py` (671 lines)
   - `tests/test_ai_knowledge.py` (209 lines)
   - `tests/test_documents_ai_consent.py` (180 lines)
   - Status: **DONE.**

3. Cross-app import coupling is removed.
   - `ai_assistant/services/tools.py` no longer imports from `notifications`. Direct `settings.MONGODB` access is used.
   - Status: **DONE.**

4. Blocking I/O improvement is in place.
   - Module-level `requests.Session()` provides connection pooling without architectural changes.
   - Status: **DONE.**

## Current Strengths

1. Shared auth infrastructure.
   - Reuses `accounts/` JWT auth, consent checks (`ConsentRequiredMixin`), RBAC/ABAC (`AccessControlMixin`), and throttling (`ChatRateThrottle`).
   - Files: `accounts/authentication.py`, `accounts/utils/access_control.py`, `accounts/utils/throttles.py`, `accounts/services/consent_service.py`.

2. Privacy-aware context builder.
   - `context_builder.py` redacts sensitive fields, masks PII, and summarizes data to minimize tokens.
   - Fields: `REDACTED_FIELDS`, `MASKED_FIELDS`, `MAX_DOCUMENTS`, `MAX_APPLICATIONS`, `MAX_PAYMENTS`.

3. Tool caching and invalidation.
   - Short-term caching on tool results (30s–1800s) via Django cache. `invalidate_user_tool_cache()` clears stale data after user mutations (e.g., document upload).

4. Bilingual support with language prefix injection.
   - Tagalog language prefix `[Please respond in Tagalog/Filipino]` is prepended when `language='tl'`.
   - `ALLOWED_LANGUAGES = {'en', 'tl'}` enforced in views.

5. Read-only tool contract.
   - All 10 tools query MongoDB only; no mutations via chatbot.

## Implementation Gaps Since Last Review

- `ai_assistant/views/chat_views.py` was split into 5 files for maintainability.
- 58 new tests added for tool safety, context redaction, streaming SSE behavior, and frame formatting.
- `escape_llm_output()` added to `accounts/utils/validation_utils.py`.
- `requests.Session()` pooling added to `ai_assistant/services/llm_service.py`.
- Knowledge-base review checklist added inline in `ai_assistant/services/knowledge_base.py`.

## Production Readiness Checklist

- [x] Session-pooled HTTP for LLM provider calls.
- [x] HTML-escape all LLM output before persistence and client response.
- [x] Enforce tool call safety through `safe_execute_tool()` with rate limiting and validation.
- [x] Verify SSE frame formatting with automated tests.
- [x] Lock knowledge-base changes behind inline review checklist.
- [x] Split large view file into logical modules.
- [x] Add comprehensive tests for tool safety, context redaction, streaming, and API behavior.
- [x] Remove cross-app import coupling (`notifications`).
- [ ] Create MongoDB indexes for `ai_interactions` collection on startup/bootstrap.
- [ ] Add request correlation/tracing IDs for LLM call debugging.

## Recommended Next Steps

1. Add `init_db.py` index bootstrap for AI collections.
   - `ai_assistant/models/interaction.py` defines `create_indexes()` but it is not invoked from `init_db.py`.
   - Add index creation for `ai_interactions` (customer_id, conversation_id, timestamp, compound).

2. Add request correlation IDs for LLM streaming paths.
   - Generate a request/call ID at the start of `StreamingChatView.post()` and attach it to log entries and `AIInteraction` metadata.
   - Improves debuggability when tracing slow or failed LLM calls.

3. Add automated tests for `AIInteraction` model methods.
   - Current tests exercise views/services; direct model tests for `find_by_customer_paginated`, `find_by_conversation`, and `delete_by_customer` would close the remaining coverage gap.

## Future Roadmap

1. **Proactive Assistance**
   - Context-driven greetings and nudges based on user state
   - Next-step suggestions tied to incomplete profiles or pending documents
   - Notifications tied to repayment or approval events

2. **Analytics & Continuous Improvement**
   - Log response times and token usage
   - Capture feedback (thumbs up/down)
   - Track unanswered or low-confidence queries
   - Build a dashboard for trends and failure categories

3. **RAG Consideration**
   - Current assessment: RAG is **not recommended** at this stage
   - Reasons: platform knowledge is already embedded in the system prompt; live data is fetched via tool calling; no large external document corpus to search
   - When to add: if FAQ/policy content exceeds ~100 documents, legal/compliance docs need dynamic reference, or questions exceed current prompt scope
   - If pursued later: vector database (Chroma, Pinecone, pgvector) → embed/index content → retrieve top-k chunks → inject into prompt

## Notes

- This review is code-level only (no live environment penetration testing).
- All 110 AI-related tests pass under `pytest -q`.
- The module depends on `accounts/` for authentication, consent, and access control; changes there may require corresponding AI review.
