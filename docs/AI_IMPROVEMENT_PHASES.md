# AI Improvement Phases

This document outlines a phased plan to improve the AI assistant experience, accuracy, and performance over time.

## Current State (Baseline)

**AI Chat Endpoint:** `POST /api/ai/chat/`  
**Providers:** Groq (cloud) or Ollama (local)  
**Core Behavior:**  
- Uses a system prompt + recent conversation history  
- Optional dynamic user context from backend data  
- Supports tool calling via `chat_with_tools`  

**Known Gaps:**  
- Responses can be slow on local CPU models  
- Long prompts/history increase token usage  
- User context is always built (even when not needed)  
- Limited analytics for quality or latency

---

## Phase 1 — Performance & Latency Optimization

**Goal:** Make responses faster without changing user-visible functionality.  
**Priority:** 🔴 Critical

### 1.1 Model Optimization (Ollama)
- [ ] Use smaller/quantized models for faster CPU inference:
  - `llama3.1:8b-instruct-q4_0` — 4-bit quantized (~4GB, 3-5x faster)
  - `llama3.2:3b` — Smaller 3B model
  - `phi3:mini` — 3.8B, very fast on CPU
  - `gemma2:2b` — 2B, fastest option for CPU
- [ ] Document recommended models for CPU vs GPU deployments
- [ ] Add Ollama keep-alive/health-ping strategy to avoid cold starts

### 1.2 Response Streaming
- [x] Implement streaming responses via Server-Sent Events (SSE)
- [x] Update `/api/ai/chat/stream/` endpoint with SSE support
- [x] Update mobile app to consume streaming responses
- [x] Show typing indicator with progressive token display

### 1.3 Prompt & Token Optimization
- [x] Reduce history window (e.g., last 4–6 messages instead of 10)
- [x] Lower `max_tokens` for standard replies (e.g., 256–512)
- [x] Compress system prompt without losing meaning (~60% reduction achieved)
- [x] Only build user context when question requires it (intent detection)

### 1.4 Response Caching
- [x] Add Redis/in-memory cache for frequent queries
- [x] Cache FAQ responses (high TTL, 24 hours)
- [x] Cache loan products list (medium TTL, 30 minutes + invalidation on admin update)
- [x] Cache education content (high TTL, 24 hours)
- [x] Cache suggestions (12 hours, per language)
- [x] Add `cached` flag in API responses for debugging

**Cache TTL Configuration (in `config/settings.py`):**
```python
CACHE_TTL = {
    'faqs': 86400,        # 24 hours
    'education': 86400,   # 24 hours  
    'suggestions': 43200, # 12 hours
    'loan_products': 1800,# 30 minutes
    'ai_status': 60,      # 1 minute
}
```

### 1.5 Parallel Tool Execution
- [ ] Detect when multiple independent tools are requested
- [ ] Execute independent tools concurrently (e.g., profile + documents)
- [ ] Aggregate results before sending to LLM for final response

---

## Phase 2 — Knowledge Accuracy & Consistency

**Goal:** Reduce hallucinations and keep product details accurate.  
**Priority:** 🟠 High

### Tasks
- [ ] Centralize canonical platform facts in a single source of truth
- [ ] Add versioned “AI knowledge” document used in prompt injection
- [ ] Add automated tests for system prompt regressions
- [ ] Define a “do not answer / redirect” policy for unknowns

---

## Phase 3 — Context-Aware Personalization

**Goal:** Let the AI provide precise, user-specific answers.  
**Priority:** 🟡 Medium

### Tasks
- [ ] Normalize user context formatting and ensure safe redaction
- [ ] Add a context summarizer to keep prompts short
- [ ] Limit sensitive fields and enforce output rules
- [ ] Add “summarize only” mode for sensitive responses

---

## Phase 4 — Tool Calling & Action Support

**Goal:** Enable safe, structured backend actions and queries.  
**Priority:** 🟢 Low

### Tasks
- [ ] Expand tool schemas and validate parameters
- [ ] Add tool result caching for repeated queries
- [ ] Add safety policies for tool invocation frequency
- [ ] Add integration tests for tool calls and edge cases

---

## Phase 5 — Proactive Assistance

**Goal:** Make the assistant useful before users ask.  
**Priority:** 🔵 Future

### Tasks
- [ ] Add context-driven greetings and nudges
- [ ] Suggest next steps based on current user state
- [ ] Support notifications tied to repayment or approval events

---

## Phase 6 — Analytics & Continuous Improvement

**Goal:** Track quality, speed, and user satisfaction.  
**Priority:** 🔵 Future

### Tasks
- [ ] Log response times and token usage
- [ ] Add feedback capture (thumbs up/down)
- [ ] Track unanswered or low-confidence queries
- [ ] Build dashboard for trends and failure categories

---

## Implementation Priority (Recommended)

| Phase | Effort | Impact | Priority |
|------|--------|--------|----------|
| Phase 1 — Performance | Low–Medium | Very High | 🔴 Do First |
| Phase 2 — Accuracy | Medium | High | 🟠 Do Next |
| Phase 3 — Context | Medium | High | 🟡 Then |
| Phase 4 — Tools | High | Very High | 🟢 Plan |
| Phase 5 — Proactive | Medium | Medium | 🔵 Future |
| Phase 6 — Analytics | Medium | Medium | 🔵 Future |

---

## Phase 1 Quick Wins (Recommended Order)

| Task | Effort | Speed Gain | Notes |
|------|--------|------------|-------|
| Use quantized model (q4_0/3B) | 5 min | 3-5x | Change `OLLAMA_MODEL` in .env |
| Response streaming | 2-3 hrs | Perceived 10x | Users see tokens immediately |
| Response caching (FAQs) | 2-3 hrs | ∞ for cached | Redis or in-memory |
| Prompt compression | 1 hr | 20-30% | Reduce ~3000 tokens to ~2000 |
| Parallel tool execution | 2 hrs | 30-50% | For multi-tool queries |

---

## RAG Consideration

**Current Assessment:** RAG is **not recommended** at this stage because:
- Platform knowledge is already embedded in the system prompt
- Live data is fetched via tool calling (MongoDB)
- No large external document corpus to search

**When to Add RAG:**
- If you add 100+ FAQs or policy documents
- If you need to reference legal/compliance docs dynamically
- If users ask questions beyond the system prompt scope

**RAG Implementation (Future):**
- [ ] Set up vector database (Chroma, Pinecone, or pgvector)
- [ ] Embed and index FAQ/education/policy content
- [ ] Add retrieval step before LLM call
- [ ] Inject top-k relevant chunks into prompt

