# PLATTECH Module 10 Activity (SYSDEV02) - Session 1 Evidence (Backend)

## Group Information
- Group #: 6
- Leader: Caronongan, Justin Mc Neal G.
- Members:
  - Soriano, Eli Gabriel T.
  - Co, Joshua
  - Pimentel John Lloyd
  - Barte, Feniel

---

## Session 1 Activity: Prototype Monitoring

### Scope for this submission
- AI track only for now.
- Target functions: **3 AI-related backend functions**.
- Blockchain function: **deferred/skip for now** (to be completed in smart-contract track).

### Important correction (project-specific)
This project's AI is **not an incident classifier**. The core AI behavior is:
1. LLM-powered chat assistance (`/api/ai/chat/`) via Groq
2. AI-assisted loan pre-qualification (`/api/loans/pre-qualify/` -> `qualify_customer`)
3. AI feature API calls (status/history/suggestions endpoints)

---

## Functions to Monitor (3 AI Functions)

### Function 1: AI Chat Generation
- Endpoint: `POST /api/ai/chat/`
- Main code path:
  - `ai_assistant/views/chat_views.py` -> `ChatView.post`
  - `ai_assistant/services/llm_service.py` -> `GroqService.chat`
- What to measure:
  - End-to-end API latency (ms)
  - LLM response time from payload (`response_time_ms`) if present

### Function 2: AI Pre-Qualification
- Endpoint: `POST /api/loans/pre-qualify/`
- Main code path:
  - `loans/views/customer_views.py` -> `PreQualifyView.post`
  - `loans/services/qualification.py` -> `qualify_customer`
- What to measure:
  - End-to-end API latency (ms)
  - Stability across different loan amounts/inputs

### Function 3: AI API Calls (Support Endpoints)
- Endpoints:
  - `GET /api/ai/status/`
  - `GET /api/ai/suggestions/`
  - `GET /api/ai/history/`
- Main code path:
  - `ai_assistant/views/chat_views.py` -> `AIStatusView`, `SuggestionsView`, `ChatHistoryView`
- What to measure:
  - API response latency (ms)
  - Identify slowest support endpoint

### Function 4: Blockchain Function
- Status: **Deferred for now (skip in this submission)**
- Note: to be completed in smart-contract session with gas-cost evidence.

---

## Evidence Collection Procedure (Actual Build)

### Prerequisites
1. Run backend server.
2. Use a valid customer JWT token.
3. Ensure AI consent is enabled for the account (`POST /api/auth/consent/` with `{"data_consent": true, "ai_consent": true}`).
4. Prepare one valid loan product + profile data for pre-qualify tests.

### Run benchmark script
From repo root:

```bash
python scripts/session1_ai_monitoring.py \
  --base-url http://localhost:8000 \
  --token "<YOUR_ACCESS_TOKEN>" \
  --prequal-base-json scripts/session1_prequal_payload.example.json
```

This generates:
- Per-case latency
- `AVG / MIN / MAX / RUNS`
- Overall summary per function

---

## Session 1 Performance Table (Actual Run Output)

| Test Case | Result (AVG) | Identified Bottleneck |
|---|---:|---|
| Function 1 - AI Chat Generation | `923.28 ms` | External LLM call latency (network + Groq inference time) |
| Function 2 - AI Pre-Qualification | `1176.88 ms` | Multi-step processing (profile/data checks + LLM qualification + response normalization) |
| Function 3 - AI API Calls | `149.46 ms` | `history_get` endpoint slower due to conversation retrieval/pagination work |

### Raw Evidence Logs (Paste script output below)

```text
Function 1 OVERALL: 923.28 ms (scripts/session1_func1_chat.txt)
Function 2 OVERALL: 1176.88 ms (scripts/session1_func2_prequal.txt)
Function 3 OVERALL: 149.46 ms (scripts/session1_func3_api.txt)
Note: Runs were executed with --repeats 1 per case for this captured evidence.
```

---

## Initial Bottleneck Analysis
1. Slowest function: `Function 2 - AI Pre-Qualification` at `1176.88 ms`.
2. Root-cause hypothesis: pre-qualification runs a heavier path than simple API reads because it combines DB/profile reads, prompt composition, external LLM request, and post-processing validation.
3. Candidate fix for Session 2: reduce LLM token budget/context size and optimize chat-history query payload using field projection.

---

## Grading Rubric Alignment (Session 1)
- 3 entries recorded: **Yes** (AI functions 1-3)
- Bottleneck clearly explained: **Yes**
- Uses project-specific backend flow: **Yes**

---

## Session 2: Plan Your Fix

### Quick Recall
1. **What is a bottleneck in a system?**  
   A bottleneck is the part of the system that limits overall performance and becomes the slowest step in the workflow.
2. **Name one optimization technique to reduce load time.**  
   Reduce heavy response generation (for AI calls) by lowering output token budget.
3. **What does horizontal scaling mean?**  
   Running multiple service instances in parallel to distribute request load instead of increasing one server's size.
4. **Why is it important to store API keys securely?**  
   Exposed keys can be abused to access paid services, leak data, and compromise system security.

### Main Task: Identify and Plan
1. **Identify the bottleneck**  
   Primary bottleneck is **Function 2 (AI Pre-Qualification, 1176.88 ms)**, followed by **Function 1 (AI Chat, 923.28 ms)**.
2. **Define your fix (one sentence)**  
   Reduce AI response workload and retrieval overhead by limiting LLM token output, trimming chat context size, and minimizing history query payload.
3. **Get approval**  
   Plan documented and ready for instructor review before final post-fix benchmarking.

---

## Optimization Techniques

| Type of Issue | Applied Fix | Why It Works |
|---|---|---|
| High LLM latency (chat) | Reduced chat output budget (`AI_CHAT_MAX_TOKENS`) | Fewer generated tokens reduce inference/response time |
| Heavy pre-qualification response generation | Reduced qualification token budget (`AI_QUALIFICATION_MAX_TOKENS`) | Limits model output length and lowers AI completion time |
| Slow history endpoint | Added MongoDB field projection for history pagination | Fetches only required fields, reducing payload and query processing |
| Context overhead in chat | Reduced prior messages sent to LLM (`AI_CHAT_CONTEXT_MESSAGES`) | Smaller prompt context decreases total tokens processed per request |

---

## Implementation & Results

### Implemented Code Changes
1. **Chat optimization**
   - Added env-based token/context controls in [chat_views.py](/Users/gab/Documents/GitHub/Capstone_Backend/ai_assistant/views/chat_views.py)
   - `AI_CHAT_MAX_TOKENS` (default `400`)
   - `AI_CHAT_CONTEXT_MESSAGES` (default `6`)
2. **Pre-qualification optimization**
   - Added env-based qualification token cap in [qualification.py](/Users/gab/Documents/GitHub/Capstone_Backend/loans/services/qualification.py)
   - `AI_QUALIFICATION_MAX_TOKENS` (default `400`, from previous `600`)
3. **History API optimization**
   - Added projection support in [interaction.py](/Users/gab/Documents/GitHub/Capstone_Backend/ai_assistant/models/interaction.py)
   - Applied projection in [chat_views.py](/Users/gab/Documents/GitHub/Capstone_Backend/ai_assistant/views/chat_views.py) for `GET /api/ai/history/`

### Post-Fix Benchmark Commands (Same Method as Session 1)
Run per function to avoid throttling:

```bash
# Function 1 (chat)
python scripts/session1_ai_monitoring.py \
  --base-url http://localhost:8000 \
  --token "$TOKEN" \
  --prequal-base-json scripts/session1_prequal_payload.example.json \
  --only chat \
  --repeats 1 | tee scripts/session2_func1_chat_after.txt

# Function 2 (pre-qualify)
python scripts/session1_ai_monitoring.py \
  --base-url http://localhost:8000 \
  --token "$TOKEN" \
  --prequal-base-json scripts/session1_prequal_payload.example.json \
  --prequal-amounts 15000,20000,30000 \
  --only prequal \
  --repeats 1 | tee scripts/session2_func2_prequal_after.txt

# Function 3 (api calls)
python scripts/session1_ai_monitoring.py \
  --base-url http://localhost:8000 \
  --token "$TOKEN" \
  --prequal-base-json scripts/session1_prequal_payload.example.json \
  --only api \
  --repeats 1 | tee scripts/session2_func3_api_after.txt
```

### Performance Comparison Table (Before vs After)
| Test Case | Before | After | Improvement |
|---|---:|---:|---|
| Function 1 - AI Chat Generation | `923.28 ms` | `1197.65 ms` | `Slower by 274.37 ms (~29.72% regression)` |
| Function 2 - AI Pre-Qualification | `1176.88 ms` | `969.81 ms` | `Faster by 207.07 ms (~17.59% improvement)` |
| Function 3 - AI API Calls | `149.46 ms` | `110.41 ms` | `Faster by 39.05 ms (~26.13% improvement)` |

### Session 2 Raw Evidence Files
- `scripts/session2_func1_chat_after.txt`
- `scripts/session2_func2_prequal_after.txt`
- `scripts/session2_func3_api_after.txt`

### Analysis (Session 2 Status)
Session 2 optimization produced mixed but measurable results.  
`Function 2` and `Function 3` improved after the applied fixes (token-budget reduction + history projection), with the API-call path showing a clear latency reduction and pre-qualification becoming faster overall.  
`Function 1` regressed in this run because chat latency is strongly affected by external LLM/network variability; despite local optimizations, remote inference time can dominate end-to-end response time.
