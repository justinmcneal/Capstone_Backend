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

## Observations & Concerns

### 1. Large view file
- **File**: `ai_assistant/views/chat_views.py` (~935 lines)
- **Observation**: Contains 3 view classes (`ChatView`, `StreamingChatView`, plus history/suggestions/status/education/FAQs classes).
- **Risk**: Harder to maintain and test as endpoints grow.
- **Recommendation**: Split into multiple view files by concern (e.g., `chat.py`, `streaming.py`, `history.py`).

### 2. Missing tests
- **Files**: `tests/test_ai_knowledge.py`, `tests/test_documents_ai_consent.py`
- **Observation**: Only knowledge-base structure and a consent-side test exist.
- **Risk**: Tool execution, rate limiting, streaming behavior, context redaction, and LLM error paths are unguarded.
- **Recommendation**: Add unit/integration tests for:
  - Tool executors and cache behavior
  - Rate limiter boundaries
  - Streaming endpoint SSE formatting
  - Context builder redaction rules
  - LLM service timeout/error fallbacks

### 3. Blocking I/O in LLM calls
- **Files**: `ai_assistant/services/llm_service.py`
- **Observation**: Uses `requests.post(...)` synchronously for all Groq/Ollama calls, including inside `ThreadPoolExecutor` tool execution.
- **Risk**: Under load, blocking HTTP calls can exhaust worker threads and reduce throughput.
- **Recommendation**: Consider `httpx`/`aiohttp` + ASGI deployment, or offload LLM calls to a background task queue (Celery/worker) for non-streaming paths.

### 4. Streaming endpoint correctness
- **Files**: `ai_assistant/views/chat_views.py`, `ai_assistant/services/llm_service.py`
- **Observation**: `EventStreamRenderer` returns raw data, and the view wraps `chat_stream()` in `StreamingHttpResponse`.
- **Risk**: If Django/DRF applies a default JSON renderer or middleware buffering before `renderer_classes` is honored, SSE frames may be malformed or buffered.
- **Recommendation**: Verify `renderer_classes` is respected in production middleware stack, and add an integration test that asserts SSE frame formatting (`event: ...\ndata: ...\n\n`).

### 5. Rapid knowledge-base iteration
- **File**: `ai_assistant/services/knowledge_base.py`
- **Observation**: 7 version bumps in one day (v1.0 → v1.7 on 2026-06-06).
- **Risk**: Indicates initial misalignment with other modules (accounts, loans, profiles). Future edits may miss cross-module consistency.
- **Recommendation**: Schedule a knowledge-base alignment review with product/docs and lock a review-and-merge checklist for subsequent changes.

### 6. Tool safety inconsistency (RESOLVED)
- **Files**: `ai_assistant/services/tool_safety.py`, `ai_assistant/services/tools.py`
- **Observation**: All tool calls now flow through `safe_execute_tool`. `execute_tool()` delegates to `safe_execute_tool()` with rate limiting, validation, and auditing. The raw executor is now `_execute_tool_raw()`.
- **Status**: Fixed. Rate limiting is enforced for all tool execution paths.

### 7. Unsanitized LLM output
- **Files**: `ai_assistant/views/chat_views.py`, `ai_assistant/models/interaction.py`
- **Observation**: AI responses are saved to MongoDB and returned to the client without sanitization.
- **Risk**: If the model emits HTML/JS, it could be rendered in the frontend (XSS).
- **Recommendation**: Sanitize LLM responses before saving/displaying, or ensure the frontend treats AI messages as plain text.

### 8. Cross-app import coupling (RESOLVED)
- **Files**: `ai_assistant/services/tools.py`
- **Observation**: Replaced `from notifications.models.notification import get_db` with direct `settings.MONGODB` access. `notifications` collection name is inlined as `"notifications"`.
- **Status**: Fixed. `ai_assistant` no longer imports from the `notifications` app.

### 9. Renderer/middleware interaction
- **Files**: `ai_assistant/views/chat_views.py`, `config/middleware.py`
- **Observation**: `EventStreamRenderer` is declared in the view, but global DRF/Django middleware or renderer settings may buffer or parse responses.
- **Risk**: SSE may break in production if response buffering or JSON parsing is applied.
- **Recommendation**: Confirm `renderer_classes` is respected end-to-end and add a smoke test that validates real SSE behavior.

### 10. No tests for streaming or tool behavior
- **Files**: `ai_assistant/views/chat_views.py`, `ai_assistant/services/llm_service.py`, `ai_assistant/services/tools.py`
- **Observation**: No automated tests for streaming generator behavior, tool call/response loops, or tool failure handling.
- **Risk**: Hard to detect regression in streaming formatting, tool argument parsing, or prompt injection behavior.
- **Recommendation**: Add targeted tests for:
  - `chat_stream` and `chat_with_tools_stream` generator output
  - `execute_tool` JSON serialization and error handling
  - `needs_user_context()` keyword matching
  - `check_prohibited_content()` routing

## Summary

The `ai_assistant` module is well-structured and production-ready in concept. The primary remaining gaps are **test coverage**, **streaming correctness verification**, **potential blocking I/O at scale**, and **unsanitized LLM output**. The knowledge base is now aligned with other modules, but should be review-locked to prevent drift. Tool safety inconsistency and cross-app import coupling have been resolved.