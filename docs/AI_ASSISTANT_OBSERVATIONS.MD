# AI Assistant Module — Accuracy, Observations & Concerns

Date: 2026-07-26  
Scope: Static code review of `ai_assistant/` and related LLM/tooling behavior.

## Architecture Summary

The `ai_assistant` module provides an AI chatbot backed by Groq/Ollama with:
- **REST + SSE endpoints** for chat and streaming
- **Function calling** with 10 read-only MongoDB tools
- **Privacy controls** for user context building
- **Rate limiting**, **content filtering**, and **consent enforcement**
- **Knowledge base** centralized in `knowledge_base.py` (v1.7)

## Strengths

1. Multi-provider LLM support (Groq cloud + Ollama local) via `.env` switch
2. Parallel tool execution using `ThreadPoolExecutor` for concurrent MongoDB queries
3. Privacy-aware context builder with field redaction (`password`, `otp`, `private_key`, etc.) and PII masking
4. Per-user sliding-window rate limiting with per-tool cost multipliers
5. Content filtering blocks credential collection, guarantees, and off-topic requests
6. Short-term caching on tool results (30s–1800s) to reduce DB load
7. Consent enforcement via `ConsentRequiredMixin` before AI feature access
8. Streaming support via SSE (`chat_stream`, `chat_with_tools_stream`)
9. Bilingual support (English/Tagalog) with language prefix injection
10. Read-only tool contract — no mutations via chatbot
 11. Cache invalidation hook (`invalidate_user_tool_cache`) for data freshness
 12. Knowledge versioning and centralized system prompt source of truth
 13. Comprehensive test coverage for tool safety, context redaction, and streaming SSE behavior (58 new tests)

## Observations & Concerns

### 1. Large view file (RESOLVED)
- **Files**: `ai_assistant/views/chat_views.py` → split into `chat.py`, `streaming.py`, `history.py`, `auxiliary.py`
- **Observation**: Split 935-line `chat_views.py` into logical modules by endpoint concern. Shared mixins, renderers, and constants remain in `chat_views.py`. URL patterns and `__init__.py` re-exports updated.
- **Status**: Fixed. Each view class now has its own file, improving maintainability and test import isolation.

### 2. Missing tests (RESOLVED)
- **Files**: `tests/test_ai_tool_safety_integration.py`, `tests/test_ai_context_builder.py`, `tests/test_ai_streaming.py`
- **Observation**: Added 58 tests covering tool safety, context redaction, and streaming SSE behavior.
- **Status**: Fixed. Coverage now includes:
  - Tool executors, rate limiting boundaries, and cache invalidation
  - Context builder privacy controls (redaction, masking, helper functions)
  - Streaming endpoint validation, content filtering, and event formatting

### 3. Blocking I/O in LLM calls
- **Files**: `ai_assistant/services/llm_service.py`
- **Observation**: Uses `requests.post(...)` synchronously for all Groq/Ollama calls, including inside `ThreadPoolExecutor` tool execution.
- **Risk**: Under load, blocking HTTP calls can exhaust worker threads and reduce throughput.
- **Recommendation**: Consider `httpx`/`aiohttp` + ASGI deployment, or offload LLM calls to a background task queue (Celery/worker) for non-streaming paths.

### 4. Streaming endpoint correctness (RESOLVED)
- **Files**: `ai_assistant/views/chat_views.py`, `ai_assistant/services/llm_service.py`, `tests/test_ai_streaming.py`
- **Observation**: Added rigid SSE frame-parsing integration tests that verify exact `event: ...\ndata: ...\n\n` formatting, `text/event-stream` content type, and no middleware wrapping. Also verified `EventStreamRenderer` pass-through and `StreamingHttpResponse` headers (`Cache-Control`, `X-Accel-Buffering`).
- **Status**: Fixed. Frame formatting is now guarded by automated tests.

### 5. Rapid knowledge-base iteration
- **File**: `ai_assistant/services/knowledge_base.py`
- **Observation**: 7 version bumps in one day (v1.0 → v1.7 on 2026-06-06).
- **Risk**: Indicates initial misalignment with other modules (accounts, loans, profiles). Future edits may miss cross-module consistency.
- **Recommendation**: Schedule a knowledge-base alignment review with product/docs and lock a review-and-merge checklist for subsequent changes.

### 6. Tool safety inconsistency (RESOLVED)
- **Files**: `ai_assistant/services/tool_safety.py`, `ai_assistant/services/tools.py`
- **Observation**: All tool calls now flow through `safe_execute_tool`. `execute_tool()` delegates to `safe_execute_tool()` with rate limiting, validation, and auditing. The raw executor is now `_execute_tool_raw()`.
- **Status**: Fixed. Rate limiting is enforced for all tool execution paths.

### 7. Unsanitized LLM output (RESOLVED)
- **Files**: `ai_assistant/views/chat_views.py`, `accounts/utils/validation_utils.py`
- **Observation**: Added `escape_llm_output()` helper that HTML-escapes AI responses before saving to MongoDB and returning to clients. Applied to both streaming and non-streaming chat paths, including prohibited-content redirect responses and streamed token/error events.
- **Status**: Fixed. All LLM output now passes through `html.escape` after multiline sanitization.

### 8. Cross-app import coupling (RESOLVED)
- **Files**: `ai_assistant/services/tools.py`
- **Observation**: Replaced `from notifications.models.notification import get_db` with direct `settings.MONGODB` access. `notifications` collection name is inlined as `"notifications"`.
- **Status**: Fixed. `ai_assistant` no longer imports from the `notifications` app.

### 9. Renderer/middleware interaction
- **Files**: `ai_assistant/views/chat_views.py`, `config/middleware.py`
- **Observation**: `EventStreamRenderer` is declared in the view, but global DRF/Django middleware or renderer settings may buffer or parse responses.
- **Risk**: SSE may break in production if response buffering or JSON parsing is applied.
- **Recommendation**: Confirm `renderer_classes` is respected end-to-end and add a smoke test that validates real SSE behavior.

### 10. No tests for streaming or tool behavior (RESOLVED)
- **Files**: `tests/test_ai_tool_safety_integration.py`, `tests/test_ai_context_builder.py`, `tests/test_ai_streaming.py`
- **Observation**: Added 58 tests covering tool call/response loops, streaming generator behavior, and context/tool failure handling.
- **Status**: Fixed. Coverage now includes:
  - `execute_tool` JSON serialization and error handling
  - `chat_with_tools_stream` generator output
  - `get_context_for_intent()` intent selection
  - `check_prohibited_content()` routing in streaming path

## Summary

The `ai_assistant` module is well-structured and production-ready in concept. The primary remaining gaps are **blocking I/O at scale** (#3) and **knowledge-base review lock** (#5). Test coverage, unsanitized LLM output, tool safety inconsistency, cross-app import coupling, large view file, and streaming correctness verification have been resolved.