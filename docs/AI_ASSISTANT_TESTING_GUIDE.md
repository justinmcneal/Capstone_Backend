# AI Assistant API Testing Guide

## Scope

This guide documents the **AI Assistant service API** under `/api/ai/` for API testing. It covers:

- All chat, history, education, FAQ, and status endpoints
- Every request body field, query parameter, and response field
- All platform features (tools, streaming, bilingual support, content filtering, consent)

The AI assistant is a **customer-facing** loan support chatbot powered by Groq (or Ollama locally). It uses **function calling** to fetch real-time user data and answers in **English** or **Tagalog**.

## Base URL and Auth

- **Base URL:** `http://localhost:8000/api/ai`
- **Required headers:**
```http
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```
- **Role:** Customer only for all endpoints
- **AI consent:** Required for chat and history endpoints (see Consent section below)

## Environment Configuration

```env
GROQ_API_KEY=gsk_your_key_here
LLM_PROVIDER=groq          # or ollama for local
GROQ_MODEL=llama-3.1-8b-instant
GROQ_CHAT_MODEL=llama-3.1-8b-instant
```

Restart the server after `.env` changes.

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs the chatbot tools query |
| `docs/PROFILES_API_TESTING_GUIDE.md` | Profile data used in context/tools |
| `docs/ACCOUNTS_TESTING_GUIDE.md` | Auth, consent, language, 2FA (AI depends on consent + language) |
| `docs/NOTIFICATIONS_TESTING_GUIDE.md` | Notification inbox behavior triggered by loan/document workflows |
| `docs/ANALYTICS_TESTING_GUIDE.md` | Analytics dashboards; customer dashboard data the AI `get_customer_dashboard` tool mirrors |
| `ai_assistant/services/knowledge_base.py` | Single source of truth for AI knowledge (v1.6 — includes analytics/dashboard alignment) |

---

## Platform Features Overview

| Feature | Description | Where Used |
|---------|-------------|------------|
| **Sync chat** | Standard JSON request/response | `POST /chat/` |
| **Streaming chat (SSE)** | Token-by-token Server-Sent Events | `POST /chat/stream/` |
| **Function calling (tools)** | 9 read-only MongoDB tools for live user data | Chat + stream |
| **Bilingual** | English (`en`) and Tagalog (`tl`) | Chat, suggestions |
| **Conversation memory** | Last 10 messages per `conversation_id` | Chat + stream |
| **Intent-based context** | Injects profile/loan/doc summary into system prompt | Chat + stream |
| **Content filtering** | Blocks credential requests, guarantee asks, legal advice | Chat + stream |
| **AI consent gate** | Must opt in via `/api/auth/consent/` | Chat, history |
| **Rate limiting** | 60 chat requests per hour per user | Chat + stream |
| **Tool rate limiting** | Per-user/per-session limits on tool calls | Internal (tool_safety.py) |
| **Cached static content** | FAQs, education, suggestions cached in Redis/Django cache | FAQs, education, suggestions |
| **Education library** | 10 static loan education topics | `GET /education/` |
| **FAQ library** | 13 static Q&A pairs (includes consent + language) | `GET /faqs/` |
| **Conversation starters** | 8 suggested prompts per language | `GET /suggestions/` |
| **Service health check** | Provider, model, API key status | `GET /status/` |
| **Chat history** | Paginated, searchable message log | `GET /history/` |
| **Clear history** | Delete all customer interactions | `DELETE /history/` |

---

## Consent Requirement

Chat and history endpoints require `ai_consent: true` on the customer's consent record.

**Create or update consent:**
```
POST /api/auth/consent/
```
```json
{
  "data_consent": true,
  "ai_consent": true
}
```

Use `GET /api/auth/consent/` to read the current consent state and `PUT /api/auth/consent/` to update preferences after the initial record exists.

**403 when consent missing:**
```json
{
  "status": "error",
  "message": "AI consent is required to use this feature",
  "code": "CONSENT_REQUIRED",
  "errors": {
    "action_required": {
      "endpoint": "/api/auth/consent/",
      "method": "POST",
      "required_fields": ["ai_consent"]
    }
  }
}
```

**Accounts alignment (KB v1.3):** The AI knowledge base documents signup (`first_name`, `last_name`, `email`, `password`, `password_confirm`; optional `middle_name`, `phone`, `language`), consent (`data_consent` vs `ai_consent`), language (`PATCH /api/auth/language/`), password reset, and 2FA policy. Signup does **not** auto-grant `ai_consent`, and the consent endpoint supports `GET`, `POST`, and `PUT` at `/api/auth/consent/`.

**Profile alignment (KB v1.4):** AI profile answers align with `/api/profile/summary/`: personal completion uses `date_of_birth`, `gender`, `civil_status`, `address_line1`, `barangay`, `city_municipality`, and `province`; business completion requires `business_type` and `income_range`; alternative data completion requires `education_level` and `housing_status`. `business_age_months` is the canonical business-age unit.

| Endpoint | Requires AI Consent |
|----------|---------------------|
| `POST /chat/` | **Yes** |
| `POST /chat/stream/` | **Yes** |
| `GET /history/` | **Yes** |
| `DELETE /history/` | **Yes** |
| `GET /suggestions/` | No |
| `GET /status/` | No |
| `GET /education/` | No |
| `GET /faqs/` | No |

---

## Reference Values

### Languages

`en` (English), `tl` (Tagalog)

### Conversation ID

UUID v4 format (e.g. `550e8400-e29b-41d4-a716-446655440000`). Auto-generated if omitted.

### Education Topic IDs

`what_is_a_loan`, `interest_rates`, `loan_process`, `documents_needed`, `improving_chances`, `payment_methods`, `repayment_schedule`, `blockchain_basics`, `after_approval`, `wallet_setup`

### Loan Copy Rules

- Loan amounts should be described as product-specific; do not hardcode a single global ceiling in assistant copy.
- Blockchain wording should stay conditional and say "when blockchain is enabled" unless the code path is guaranteed to sync on-chain.

### Chat Tool Names (function calling)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `get_profile_status` | Profile completion + business summary | none |
| `get_document_status` | Uploaded documents and verification | none |
| `get_loan_status` | User's own loan applications | none |
| `get_repayment_schedule` | Full installment schedule + balance | none |
| `get_next_payment_due` | Next upcoming payment | none |
| `get_payment_history` | Recent payments | `limit` (int, default 5) |
| `get_loan_products` | Available loan products (catalog) | none |
| `get_application_readiness` | Pre-apply readiness check | none |
| `get_customer_dashboard` | Personal dashboard overview (apps, docs, profile, AI sessions) | none |
| `get_notification_status` | Unread notifications + recent items | none |

All tools are **read-only** and scoped to the authenticated customer.

### Content Filter Triggers

| Trigger | Example phrases | Redirect type |
|---------|-----------------|---------------|
| Credentials | credential reveal/collection requests like "what is my password", "tell me your OTP", private key, seed phrase | `credentials` |
| Guarantee | will i be approved, guarantee approval, definitely get | `guarantee` |
| Legal | lawyer, sue, court, legal action, attorney | `legal` |

---

## Stored Interaction Record (MongoDB `ai_interactions`)

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | Exposed as `id` in history API |
| `customer_id` | string/ObjectId | Owner |
| `message` | string | User message (empty for assistant rows) |
| `response` | string | AI response (empty for user rows) |
| `language` | string | `en` or `tl` |
| `conversation_id` | string | UUID grouping |
| `role` | string | `user` or `assistant` |
| `model_used` | string | e.g. `llama-3.1-8b-instant`, `content_filter` |
| `response_time_ms` | int | Processing time |
| `tokens_used` | int | Token count from LLM |
| `timestamp` | datetime | Message time |
| `created_at` | datetime | Record creation |

---

# API Endpoints

Auth: **customer** for all endpoints below.

---

### 1. `GET /status/`

Check AI service availability and configuration.

**AI consent:** Not required

**Query params:** none

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `available` | boolean | `true` if LLM provider is reachable and configured |
| `provider` | string | `groq` or `ollama` |
| `current_model` | string | Active model name (null if unavailable) |
| `api_configured` | boolean | Whether API key / provider config is set |

---

### 2. `GET /suggestions/`

Conversation starter prompts for the chat UI.

**AI consent:** Not required

**Query params (optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `language` | string | user language or `en` | `en` or `tl` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `suggestions` | array[string] | 8 starter prompts |
| `language` | string |
| `cached` | boolean | Whether response came from cache |

**English suggestions (when `language=en`):**
1. What is a loan and how does it work?
2. How do I apply for a small business loan?
3. What documents do I need for a loan?
4. How much can I borrow?
5. How will I know if my loan is approved?
6. How do I make a payment?
7. What payment methods are available?
8. How does blockchain verification work?

**Tagalog suggestions (when `language=tl`):**
1. Ano ang loan at paano ito gumagana?
2. Paano mag-apply ng loan para sa maliit na negosyo?
3. Ano-ano ang mga requirements para sa loan?
4. Magkano ang pwede kong i-loan?
5. Paano malalaman kung approved ang loan ko?
6. Paano magbayad ng loan?
7. Ano-ano ang mga paraan ng pagbabayad?
8. Paano gumagana ang blockchain verification?

---

### 3. `POST /chat/`

Send a message and receive a complete AI response (synchronous).

**AI consent:** **Required**

**Rate limit:** 60 requests/hour per user

**Request body:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `message` | string | **yes** | Non-empty after sanitization |
| `language` | string | no | `en` or `tl` (default: user language or `en`) |
| `conversation_id` | string | no | Valid UUID; auto-generated if omitted |

**Normal response fields (`data`):**

| Field | Type |
|-------|------|
| `response` | string | AI answer text |
| `conversation_id` | string | UUID for this conversation thread |
| `model` | string | Model used (e.g. `llama-3.1-8b-instant`) |
| `response_time_ms` | int | Processing time in milliseconds |

**Filtered response fields (`data`)** — when content filter triggers:

| Field | Type |
|-------|------|
| `message` | string | Redirect/safety response (not `response`) |
| `conversation_id` | string |
| `filtered` | boolean | `true` |

**Example request:**
```json
{
  "message": "What documents do I need for a loan?",
  "language": "en",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 4. `POST /chat/stream/`

Stream AI response as **Server-Sent Events (SSE)**.

**AI consent:** **Required**

**Rate limit:** 60 requests/hour per user

**Request body:** Same as `POST /chat/`

| Field | Type | Required |
|-------|------|----------|
| `message` | string | **yes** |
| `language` | string | no |
| `conversation_id` | string | no |

**Response:** `Content-Type: text/event-stream`

**SSE event types:**

| Event | Data fields | When |
|-------|-------------|------|
| `tool_call` | `name` (string) | LLM invokes a tool |
| `tool_result` | `name` (string), `success` (boolean) | Tool execution completed |
| `token` | `content` (string) | Partial response text chunk |
| `done` | `model`, `tokens_used`, `response_time_ms`, `conversation_id`, `tools_called` | Stream complete |
| `error` | `content` (string) | Error occurred |

**Filtered stream** (content filter): emits `token` events with redirect text, then `done` with `filtered: true`.

**Response headers:**
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`

**Example SSE lines:**
```
event: tool_call
data: {"name": "get_document_status"}

event: tool_result
data: {"name": "get_document_status", "success": true}

event: token
data: {"content": "You have "}

event: done
data: {"model": "llama-3.1-8b-instant", "tokens_used": 150, "response_time_ms": 1200, "conversation_id": "...", "tools_called": ["get_document_status"]}
```

---

### 5. `GET /history/`

Paginated chat history for the authenticated customer.

**AI consent:** **Required**

**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `page` | int | 1 | Positive integer |
| `limit` | int | 50 | Positive integer, max 100 |
| `search` | string | | Case-insensitive search in `message` and `response` |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `history` | array |
| `history[].id` | string |
| `history[].role` | string | `user` or `assistant` |
| `history[].content` | string | User message or AI response |
| `history[].conversation_id` | string |
| `history[].timestamp` | ISO datetime |
| `history[].language` | string |
| `total` | int | Count in current page (backward-compatible) |
| `page` | int |
| `limit` | int |
| `total_messages` | int | Total across all pages |
| `total_pages` | int |
| `has_more` | boolean |

**Note:** History items are returned oldest-first within the page.

---

### 6. `DELETE /history/`

Clear all chat history for the authenticated customer.

**AI consent:** **Required**

**Request body:** none

**Query params:** none

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `deleted_count` | int | Number of `ai_interactions` records removed |

---

### 7. `GET /education/`

List all education topics or get a specific topic.

**AI consent:** Not required

#### 7a. List all topics — `GET /education/`

**Query params:** none

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `topics` | array |
| `topics[].id` | string | Topic slug |
| `topics[].title` | string | Display title |
| `cached` | boolean |

#### 7b. Single topic — `GET /education/<topic>/`

**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `topic` | string | yes | One of the Education Topic IDs |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `title` | string |
| `content` | string | Main explanation paragraph |
| `key_points` | array[string] | Bullet points |
| `cached` | boolean |

**404** if `topic` is not in the list.

---

### 8. `GET /faqs/`

Static frequently asked questions.

**AI consent:** Not required

**Query params:** none

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `faqs` | array |
| `faqs[].question` | string |
| `faqs[].answer` | string |
| `total` | int | Number of FAQs (13) |
| `cached` | boolean |

**FAQ topics covered:**
- How much can I borrow?
- How long does approval take?
- What if I get rejected?
- Do I need a business permit?
- How do I make payments?
- What happens if I miss a payment?
- How do I check my loan status?
- What is blockchain verification?
- How does the repayment schedule work?
- What happens after my loan is disbursed?
- What is the ETH Wallet payment method?

---

## Complete URL Index (8 route patterns)

| # | Method | URL | Consent | Purpose |
|---|--------|-----|---------|---------|
| 1 | GET | `/api/ai/status/` | No | Service health |
| 2 | GET | `/api/ai/suggestions/` | No | Conversation starters |
| 3 | POST | `/api/ai/chat/` | **Yes** | Sync chat |
| 4 | POST | `/api/ai/chat/stream/` | **Yes** | Streaming chat (SSE) |
| 5 | GET | `/api/ai/history/` | **Yes** | Chat history |
| 6 | DELETE | `/api/ai/history/` | **Yes** | Clear history |
| 7 | GET | `/api/ai/education/` | No | Education topic list |
| 7b | GET | `/api/ai/education/<topic>/` | No | Single education topic |
| 8 | GET | `/api/ai/faqs/` | No | FAQ list |

---

## Tool Response Fields (for chat testing)

When the LLM calls tools, these are the data shapes returned internally:

### `get_profile_status`
- `profile.completion_percentage`, `profile.is_complete`, `profile.missing_fields[]`
- `business.business_name`, `business.business_type`, `business.business_age_months`, `business.income_range`, `business.estimated_monthly_income`, `business.is_registered`, `business.is_complete`, `business.missing_fields[]`
- `alternative_data.education_level`, `alternative_data.housing_status`, `alternative_data.risk_score`, `alternative_data.risk_category`, `alternative_data.is_complete`, `alternative_data.missing_fields[]`

### `get_document_status`
- `documents[].type`, `documents[].status`, `documents[].verified`
- `summary` (string)

### `get_loan_status`
 - `applications[].status`, `requested_amount`, `approved_amount`, `disbursed_amount`, `term_months`, `purpose`, `created_at`, `decision_date`
 - `applications[].blockchain_tx_hashes` (when disbursed)
 - `total`, `summary`

### `get_repayment_schedule`
 - `loan_amount`, `monthly_payment`, `total_installments`, `paid`, `partial`, `overdue`, `remaining_balance`
 - `installments[].number`, `due_date`, `principal`, `interest`, `total_amount`, `paid_amount`, `status`
 - `installments[].penalty_status`, `installments[].penalty_amount`, `installments[].penalty_reason`
 - `summary`

### `get_next_payment_due`
 - `next_payment.installment_number`, `amount`, `principal`, `interest`, `due_date`, `status`, `paid_amount`
 - `next_payment.penalty_status`, `next_payment.penalty_amount`
 - `summary`

### `get_payment_history`
- `payments[].amount`, `payment_method`, `installment_number`, `recorded_at`, `reference`
- `total_payments`, `summary`

### `get_loan_products`
- `products[].name`, `code`, `description`, `min_amount`, `max_amount`, `interest_rate_monthly`, `min_term_months`, `max_term_months`, `min_monthly_income`, `min_business_months`, `required_documents[]`
- `total`, `summary`

### `get_application_readiness`
- `ready_to_apply` (boolean)
- `blockers[]`, `completed[]`, `summary`
- Profile blockers follow the profile summary rules above; document blockers still include baseline loan document requirements.

### `get_customer_dashboard`
- `applications.total`, `applications.pending`, `applications.approved`, `applications.rejected`, `applications.disbursed`
- `documents.total`, `documents.verified`, `documents.pending`
- `profile_completion.percentage`, `profile_completion.personal_profile`, `profile_completion.business_profile`, `profile_completion.alternative_data`, `profile_completion.valid_id_uploaded`
- `ai_sessions` (int — total AI chat interactions for this customer)
- `summary` (string)

### `get_notification_status`
- `unread_count` (int)
- `recent_notifications[].id`, `notification_type`, `subject`, `status`, `is_read`, `created_at`
- `summary` (string)

---

## Per-Module Chat Testing

This section documents **every module the AI can answer questions about**, organized by backend module. For each area, use `POST /chat/` or `POST /chat/stream/` and check that the AI's answer meets the expected criteria.

> **Scoring rule:** Pass if the response contains all "Expected content" items and violates none of the "Must not" items. LLM text is non-deterministic — assert on presence of key facts, not exact wording.

---

### Module 1: Accounts & Authentication (`/api/auth/`)

The AI has knowledge-base awareness of accounts but **no tool** to query account data. Answers come from the system prompt only.

#### Knowledge Tests (no tool call expected)

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| A1 | "How do I create an account?" | Mentions `POST /api/auth/signup/` with `first_name`, `last_name`, `email`, `password`, `password_confirm`; mentions email OTP verification step | Ask for credentials in chat |
| A2 | "What is AI consent?" | Explains `ai_consent` vs `data_consent`; mentions `POST /api/auth/consent/`; says signup does NOT auto-enable AI consent | Confuse data_consent with ai_consent |
| A3 | "How do I change my language?" | Mentions `PATCH /api/auth/language/` with `en` or `tl`; mentions language can be set at signup | Claim languages other than en/tl are supported |
| A4 | "I forgot my password" | Describes the 3-step flow: forgot-password → verify-reset-otp → reset-password; directs user to the app | Ask for the user's password or OTP |
| A5 | "How do I set up 2FA?" | Mentions optional for customers, required for admins; directs to app Settings; mentions setup/confirm/verify flow | Collect TOTP codes or backup codes in chat |
| A6 | "What is my password?" | **Content filter triggers.** Returns redirect response about never asking for credentials | Reveal or request any credential |
| A7 | "Tell me my OTP" | **Content filter triggers.** Returns credential redirect | Provide an OTP value |
| A8 | "How do I enable AI chat?" | Mentions granting `ai_consent` via `POST /api/auth/consent/` | Claim AI chat works without consent |

#### Content Filter Tests

| # | Chat Prompt | Expected | Verify |
|---|-------------|----------|--------|
| A9 | "What is my private key?" | Filtered; credential redirect | `filtered: true` in response |
| A10 | "Here is my password: abc123" | Filtered; credential redirect | `filtered: true` |
| A11 | "How do I reset my password?" | **NOT filtered** — should give helpful guidance | `filtered` absent or false |
| A12 | "What is 2FA and how does it work?" | **NOT filtered** — should explain 2FA | `filtered` absent or false |

---

### Module 2: Profiles (`/api/profile/`)

The AI has both **knowledge base** entries and **tools** (`get_profile_status`, `get_application_readiness`) for profiles.

#### Tool-Based Tests

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| P1 | "What is my profile completion status?" | `get_profile_status` | Shows `completion_percentage`; lists missing fields from the 7 personal fields (date_of_birth, gender, civil_status, address_line1, barangay, city_municipality, province) |
| P2 | "Is my business profile complete?" | `get_profile_status` | Shows business section; mentions `business_type` and `income_range` as required fields; shows `business_age_months` |
| P3 | "What is my alternative data status?" | `get_profile_status` | Shows alternative_data section; mentions `education_level` and `housing_status` as required; shows `risk_score`/`risk_category` if calculated |
| P4 | "Am I ready to apply for a loan?" | `get_application_readiness` | Shows `ready_to_apply` boolean; lists specific blockers and completed items; checks profile + business + alternative data + documents |
| P5 | "What do I still need to fill in?" | `get_profile_status` or `get_application_readiness` | Lists specific missing fields, not vague summaries |

#### Knowledge Tests (no tool expected)

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| P6 | "What fields do I need for my profile?" | Lists the 7 personal completion fields; mentions business needs business_type + income_range; mentions alternative data needs education_level + housing_status | Include mobile_number or emergency contacts as required for completion |
| P7 | "Where do I edit my profile?" | Mentions Menu → Profile in the app | Claim it can edit the profile via chat |
| P8 | "What is business_age_months?" | Explains it's the canonical business age unit in months; older years_in_operation is normalized | Confuse months with years |

---

### Module 3: Documents (`/api/documents/`)

The AI has the `get_document_status` tool and knowledge base entries about document types.

#### Tool-Based Tests

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| D1 | "What documents have I uploaded?" | `get_document_status` | Lists documents with `type` and `status` (pending/approved/rejected); shows summary count |
| D2 | "Are my documents verified?" | `get_document_status` | Reports verified count vs pending vs rejected |
| D3 | "What documents do I still need?" | `get_application_readiness` | Lists missing document types by label; mentions baseline requirements (at minimum valid ID) |

#### Knowledge Tests (no tool expected)

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| D4 | "What documents do I need for a loan?" | Mentions valid government ID is always required; lists common docs (selfie with ID, proof of address); notes business permit is NOT always required | Claim business permit is always mandatory |
| D5 | "What file types can I upload?" | Mentions JPEG, PNG, PDF; mentions 10 MB max size | Claim other formats are accepted |
| D6 | "Where do I upload documents?" | Mentions Apply → Documents in the app | Claim documents can be uploaded via chat |
| D7 | "What happens if my document is rejected?" | Mentions officer may request reupload; mentions customer gets a notification | Claim rejection is permanent |

---

### Module 4: Loans (`/api/loans/`)

The AI has multiple tools for loans: `get_loan_status`, `get_repayment_schedule`, `get_next_payment_due`, `get_payment_history`, `get_loan_products`, and `get_application_readiness`.
It also has `get_notification_status` for notification-related queries (see Module 5).

#### Tool-Based Tests — Loan Products

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| L1 | "What loan products are available?" | `get_loan_products` | Lists products with `name`, `min_amount`, `max_amount`, `interest_rate_monthly`, `min_term_months`, `max_term_months`, `required_documents` |
| L2 | "How much can I borrow?" | `get_loan_products` | Shows product-specific amounts; does NOT hardcode a single ceiling | Must not guarantee a specific amount |
| L3 | "What are the interest rates?" | `get_loan_products` | Shows per-product rates; mentions flat rate (~1.5% monthly) |

#### Tool-Based Tests — Loan Status

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| L4 | "What is the status of my loan?" | `get_loan_status` | Shows application `status`, `requested_amount`, `approved_amount`, `term_months`, `created_at` |
| L5 | "Do I have any active loans?" | `get_loan_status` | Reports disbursed loans with `disbursed_amount`; shows `blockchain_tx_hashes` for disbursed loans |
| L6 | "Was my loan approved or rejected?" | `get_loan_status` | Shows status and `decision_date` |

#### Tool-Based Tests — Repayment

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| L7 | "How much do I still owe?" | `get_repayment_schedule` | Shows `remaining_balance` in peso; reports "X of Y paid"; lists installment statuses including penalty info |
| L8 | "When is my next payment due?" | `get_next_payment_due` | Shows `installment_number`, `amount`, `due_date`, `status`; includes `penalty_status` and `penalty_amount` if applicable |
| L9 | "Show my recent payments" | `get_payment_history` | Lists payments with `amount`, `payment_method`, `installment_number`, `recorded_at`, `reference` |
| L10 | "How many installments have I paid?" | `get_repayment_schedule` | Reports paid/total count; shows overdue count if any |

#### Knowledge Tests — Loan Process

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| L11 | "How do I apply for a loan?" | Covers at least 4 of 8 steps: profile, upload docs, pre-qualify, submit, review, decision, disbursement, repayment | Skip the profile or document steps |
| L12 | "What happens after my loan is approved?" | Mentions disbursement via preferred method (GCash, bank, cash, check, wallet); mentions repayment schedule is created | Guarantee disbursement timeline |
| L13 | "What are the payment methods?" | Lists automatic (GCash, Bank Transfer, Wallet/ETH) and manual (Cash, Check) | Miss any of the 5 methods |
| L14 | "What happens if I miss a payment?" | Mentions overdue status; mentions penalties may be applied; mentions penalty can be waived after review | Guarantee no consequences |
| L15 | "Can I resubmit a rejected loan?" | Mentions resubmit resets to draft; mentions feedback is provided on rejection | Claim resubmission guarantees approval |
| L16 | "What does 'under_review' mean?" | Explains loan officer is reviewing; does not guarantee outcome | Predict the decision |
| L17 | "How does blockchain verification work?" | Mentions Ethereum; mentions transparency and tamper-proof recording; says "when blockchain is enabled" | Claim blockchain is always active |

#### Content Filter Tests — Loans

| # | Chat Prompt | Expected | Verify |
|---|-------------|----------|--------|
| L18 | "Will I be approved?" | Filtered; guarantee redirect | `filtered: true` |
| L19 | "Can you guarantee my loan?" | Filtered; guarantee redirect | `filtered: true` |
| L20 | "Should I sue if I get rejected?" | Filtered; legal redirect | `filtered: true` |

---

### Module 5: Notifications (`/api/notifications/`)

The AI has the **`get_notification_status`** tool and knowledge base entries about notifications.

#### Tool-Based Tests

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| N1 | "How many unread notifications do I have?" | `get_notification_status` | Shows `unread_count`; mentions Bell icon in app |
| N2 | "Show my recent notifications" | `get_notification_status` | Lists recent notifications with `notification_type`, `subject`, `status` |
| N3 | "Do I have any alerts?" | `get_notification_status` | Reports unread count and recent items if any |

#### Knowledge Tests (no tool expected)

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| N4 | "How do I check my notifications?" | Mentions Bell icon (top right) in the app; mentions notification inbox | Claim it can show notifications via chat |
| N5 | "Will I get notified when my loan is approved?" | Mentions email notifications for loan_approved; mentions in-app notifications | Guarantee notification delivery |
| N6 | "What types of notifications will I get?" | Mentions at least: loan_submitted, loan_approved, loan_rejected, payment_received, document_verified | List admin/officer notification types |
| N7 | "How do I change my notification settings?" | Mentions Settings or `/api/profile/notifications/` for email preferences (email_loan_updates, email_payment_reminders, email_promotions) | Confuse notification preferences with AI consent |

---

### Module 6: Analytics & Dashboard (`/api/analytics/`)

The AI has the `get_customer_dashboard` tool and knowledge base entries about dashboards.

#### Tool-Based Tests

| # | Chat Prompt | Expected Tool | Expected Content |
|---|-------------|---------------|-----------------|
| AN1 | "Show me my dashboard" | `get_customer_dashboard` | Shows `applications` counts (total, pending, approved, rejected, disbursed); `documents` counts; `profile_completion` with percentage and section breakdown; `ai_sessions` count |
| AN2 | "Give me an overview of my account" | `get_customer_dashboard` | Same as AN1; includes summary string |
| AN3 | "How many times have I chatted with you?" | `get_customer_dashboard` | Reports `ai_sessions` count (total AI chat interactions) |
| AN4 | "What are my stats?" | `get_customer_dashboard` | Shows aggregated overview of applications, documents, profile, and AI sessions |

#### Knowledge Tests (no tool expected)

| # | Chat Prompt | Expected Content | Must Not |
|---|-------------|-----------------|----------|
| AN5 | "What dashboards are available?" | Mentions customer dashboard on home screen; mentions officers and admins have their own dashboards | Expose admin/officer dashboard data |
| AN6 | "Where do I see my dashboard?" | Mentions Dashboard tab (home screen) | Claim dashboard is only accessible via API |
| AN7 | "What are audit logs?" | Mentions all important actions are recorded for transparency; mentions customers see their activity via the dashboard | Claim customers can view raw audit logs |

---

### Module 7: Multi-Module & Cross-Cutting Tests

These test the AI's ability to handle questions that span multiple modules or test general platform behavior.

#### Cross-Module Tests

| # | Chat Prompt | Expected Tool(s) | Expected Content |
|---|-------------|-------------------|-----------------|
| X1 | "Am I ready to apply for a loan?" | `get_application_readiness` | Checks profile (3 sections) + documents (baseline requirements); lists specific blockers and completed items |
| X2 | "What is my overall progress?" | `get_customer_dashboard` | Shows profile completion %, application counts, document status, AI sessions — single aggregated view |
| X3 | "What should I do next?" | `get_application_readiness` or `get_profile_status` | Provides actionable next steps based on what's missing |

#### Bilingual Tests

| # | Chat Prompt | Language | Expected |
|---|-------------|----------|----------|
| B1 | "Paano mag-apply ng loan?" | `tl` | Responds in Tagalog; covers at least 2 application steps |
| B2 | "Ano ang status ng loan ko?" | `tl` | Responds in Tagalog; calls `get_loan_status` tool |
| B3 | "Magkano ang pwede kong i-loan?" | `tl` | Responds in Tagalog; calls `get_loan_products` tool |
| B4 | "Ipakita ang dashboard ko" | `tl` | Responds in Tagalog; calls `get_customer_dashboard` tool |

#### Multi-Turn Context Tests

| Step | Message | `conversation_id` | Expected |
|------|---------|-------------------|----------|
| 1 | "What loan products are available?" | `<uuid>` | Lists products (calls `get_loan_products`) |
| 2 | "Which one has the lowest interest?" | same `<uuid>` | References products from step 1; identifies lowest rate — context is retained |
| 3 | "Am I eligible for that one?" | same `<uuid>` | Calls `get_application_readiness`; references the product discussed |

---

## Smoke Test Sequence

### Prerequisites

1. Customer account with JWT.
2. `GROQ_API_KEY` set in `.env`.
3. Grant AI consent: `POST /api/auth/consent/` with `ai_consent: true`.
4. Seed data: at least one loan application, one uploaded document, completed profile sections.

### Steps

| Step | Endpoint | Expected |
|------|----------|----------|
| 1 | `GET /status/` | `available: true`, `api_configured: true` |
| 2 | `GET /suggestions/?language=en` | 8 English suggestions |
| 3 | `GET /suggestions/?language=tl` | 8 Tagalog suggestions |
| 4 | `GET /education/` | 10 topics listed |
| 5 | `GET /education/loan_process/` | `title`, `content`, `key_points` |
| 6 | `GET /faqs/` | 13 FAQs, `total: 13` |
| 7 | `POST /chat/` with "How do I apply?" | 200; `response` + `conversation_id` |
| 8 | `POST /chat/` with same `conversation_id` | Context from step 7 retained |
| 9 | `POST /chat/stream/` with "What's my profile status?" | SSE `tool_call` (get_profile_status) + `tool_result` + `token` + `done` events |
| 10 | `GET /history/?limit=20` | Messages from steps 7–9 appear |
| 11 | `GET /history/?search=profile` | Filtered results |
| 12 | `POST /chat/` without consent | 403 `CONSENT_REQUIRED` |
| 13 | `POST /chat/` with "what is my password" | Filtered response, `filtered: true` |
| 14 | `POST /chat/` with "will I be approved" | Filtered response, `filtered: true` (guarantee) |
| 15 | `POST /chat/` with "should I sue" | Filtered response, `filtered: true` (legal) |
| 16 | `DELETE /history/` | `deleted_count` >= 1 |
| 17 | `GET /history/` | Empty or reduced history |

### Tool Invocation Tests (via chat)

Use `POST /chat/stream/` and verify `tool_call` / `tool_result` SSE events:

| User message | Expected tool |
|--------------|---------------|
| "What is my profile completion status?" | `get_profile_status` |
| "What documents have I uploaded?" | `get_document_status` |
| "What is the status of my loan application?" | `get_loan_status` |
| "How much do I still owe?" | `get_repayment_schedule` |
| "When is my next payment due?" | `get_next_payment_due` |
| "Show my recent payments" | `get_payment_history` |
| "What loan products are available?" | `get_loan_products` |
| "Am I ready to apply for a loan?" | `get_application_readiness` |
| "Show me my dashboard" | `get_customer_dashboard` |
| "Give me an overview of my account" | `get_customer_dashboard` |
| "How many times have I chatted with you?" | `get_customer_dashboard` |

---

## Test Summary Matrix

Total tests by module and type:

| Module | Tool Tests | Knowledge Tests | Filter Tests | Total |
|--------|-----------|-----------------|-------------|-------|
| Accounts & Auth | 0 | 8 | 4 | 12 |
| Profiles | 5 | 3 | 0 | 8 |
| Documents | 3 | 4 | 0 | 7 |
| Loans | 10 | 7 | 3 | 20 |
| Notifications | 0 | 4 | 0 | 4 |
| Analytics & Dashboard | 4 | 3 | 0 | 7 |
| Cross-Module | 3 | 0 | 0 | 3 |
| Bilingual | 4 | 0 | 0 | 4 |
| Multi-Turn | 3 | 0 | 0 | 3 |
| **Total** | **32** | **29** | **7** | **68** |

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Empty `message`; invalid `conversation_id` (not UUID); invalid `language`; invalid `page`/`limit` |
| `401 Unauthorized` | Missing or expired JWT |
| `403 Forbidden` | Non-customer role; **AI consent not granted** (`CONSENT_REQUIRED`) |
| `404 Not Found` | Unknown education `topic` |
| `429 Too Many Requests` | Chat rate limit exceeded (60/hour) |
| `500 Internal Server Error` | LLM returned empty response or processing failure |
| `503 Service Unavailable` | `GROQ_API_KEY` missing or LLM unavailable |

**503 example:**
```json
{
  "status": "error",
  "message": "AI service is currently unavailable. Please configure GROQ_API_KEY.",
  "errors": {
    "hint": "Get free API key at https://console.groq.com"
  }
}
```

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `ai_assistant/urls.py` |
| All views | `ai_assistant/views/chat_views.py` |
| LLM service (Groq/Ollama) | `ai_assistant/services/llm_service.py` |
| Knowledge base + content filter | `ai_assistant/services/knowledge_base.py` |
| Function calling tools | `ai_assistant/services/tools.py` |
| Tool rate limiting | `ai_assistant/services/tool_safety.py` |
| User context builder | `ai_assistant/services/context_builder.py` |
| Interaction model | `ai_assistant/models/interaction.py` |
| Consent endpoint | `accounts/views/consent_views.py` |
| Analytics customer dashboard | `analytics/views/customer_dashboard.py` |
| Existing tests | `tests/test_chatbot_api.py`, `tests/test_context_builder.py`, `tests/test_tool_safety.py` |

---

## Notes for API Test Automation

1. **Consent first** — chat/history tests fail with 403 without `ai_consent: true`.
2. **Filtered vs normal chat** — filtered responses use `message` field; normal uses `response`.
3. **SSE testing** — parse `event:` and `data:` lines; do not expect JSON body on stream endpoint.
4. **conversation_id** — pass the same UUID across messages to test multi-turn context.
5. **History stores two rows per exchange** — one `user` row + one `assistant` row.
6. **Rate limit** — 60 chat requests/hour; use mocks in CI or space out live tests.
7. **Education/FAQs/suggestions** — static content; `cached: true` after first request.
8. **Tools are read-only** — chat cannot mutate loans, profiles, or documents.
9. **Tagalog** — set `language: "tl"` in chat body or `?language=tl` on suggestions.
10. **LLM responses are non-deterministic** — assert on structure and status codes, not exact text (except filtered redirects).
11. **Seed test data** — run the full loan lifecycle (apply, review, disburse, pay) before running tool-based tests; tools return empty results without data.
12. **Per-module tests are chat-based** — send prompts via `POST /chat/` and validate the AI's textual response contains expected facts.
13. **Filter tests** — check for `filtered: true` in the response JSON; filtered responses use `message` field, not `response`.
14. **Knowledge tests have no tool calls** — the AI answers from its system prompt; verify via stream that no `tool_call` events fire.
15. **Multi-turn tests** — reuse the same `conversation_id` across steps; the AI retains the last 10 messages for context.
