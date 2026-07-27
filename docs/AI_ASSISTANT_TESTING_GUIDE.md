# AI Assistant API Testing Guide

## Scope
AI Assistant handles chat, streaming chat, chat history, conversation suggestions, AI service status, loan education content, and FAQs. It depends on `accounts/` for authentication, consent, and access control.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/ai`
- Protected endpoints require:
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```
- Customer-only endpoints require a customer token with `ai_consent=true`, except where noted.
- Streaming endpoints return `text/event-stream`.

## URL Reference

### Chat

1. `POST /chat/`
- Auth: authenticated customer with AI consent
- Request fields:
  - `message` required
  - `conversation_id` optional (UUID; generated if omitted)
  - `language` optional (`en` or `tl`, default `en`)
- Key response fields: `response`, `conversation_id`, `model`, `response_time_ms`
- Notes:
  - Prohibited content returns `filtered: true` with a redirect message.
  - Empty/missing message returns 400.
  - Invalid `conversation_id` or `language` returns 400.

2. `POST /chat/stream/`
- Auth: authenticated customer with AI consent
- Request fields:
  - `message` required
  - `conversation_id` optional (UUID; generated if omitted)
  - `language` optional (`en` or `tl`, default `en`)
- Key response fields: SSE events (`tool_call`, `tool_result`, `token`, `done`, `error`)
- Notes:
  - Prohibited content returns a minimal SSE stream with `event: token` and `event: done`.
  - Unavailable LLM returns 503.
  - Streamed token content is HTML-escaped.

### Chat History

3. `GET /history/`
- Auth: authenticated customer with AI consent
- Request fields: none required
- Query params:
  - `page` optional (positive integer, default 1)
  - `limit` optional (positive integer, default 50, max 100)
  - `search` optional (text filter)
- Key response fields: `history`, `total`, `page`, `limit`, `total_messages`, `total_pages`, `has_more`

4. `DELETE /history/`
- Auth: authenticated customer with AI consent
- Request fields: none required
- Key response fields: `deleted_count`

### Suggestions

5. `GET /suggestions/`
- Auth: authenticated customer (AI consent not required)
- Request fields: none required
- Query params:
  - `language` optional (`en` or `tl`, default en)
- Key response fields: `suggestions`, `language`, `cached`
- Notes:
  - Responses are cached per language.

### Status

6. `GET /status/`
- Auth: authenticated customer (AI consent not required)
- Request fields: none required
- Key response fields: `available`, `provider`, `current_model`, `api_configured`

### Education

7. `GET /education/`
- Auth: authenticated customer (AI consent not required)
- Request fields: none required
- Key response fields: `topics`, `cached`
- Notes:
  - Returns list of available topic IDs and titles.

8. `GET /education/<topic>/`
- Auth: authenticated customer (AI consent not required)
- Request fields: none required
- Key response fields: `title`, `content`, `key_points`, `cached`
- Notes:
  - Invalid topic returns 404.
  - Responses are cached per topic.

### FAQs

9. `GET /faqs/`
- Auth: authenticated customer (AI consent not required)
- Request fields: none required
- Key response fields: `faqs`, `total`, `cached`
- Notes:
  - Responses are cached.

## Smoke Test Sequence

1. Ensure a customer exists with `ai_consent=true` via `POST /api/auth/consent/`.
2. `POST /api/ai/chat/` with a simple message (`Hello`) and verify a non-empty `response`.
3. `POST /api/ai/chat/stream/` with a simple message and verify SSE frames (`event: token`, `event: done`).
4. `GET /api/ai/history/` and confirm the chat interaction appears.
5. `GET /api/ai/suggestions/` for both `language=en` and `language=tl`.
6. `GET /api/ai/status/` and confirm provider/model fields are present.
7. `GET /api/ai/education/` and `GET /api/ai/education/what_is_a_loan/`.
8. `GET /api/ai/faqs/`.
9. `DELETE /api/ai/history/` and confirm `deleted_count` matches history length.

## Common Errors

1. `400 Bad Request`
- Missing `message` on chat/stream endpoints.
- Invalid `conversation_id` format.
- Invalid `language` value.
- Invalid pagination params on history.

2. `401 Unauthorized`
- Missing or invalid access token.

3. `403 Forbidden`
- Customer without `ai_consent=true` accessing chat/stream/history.

4. `404 Not Found`
- Invalid education topic slug.

5. `429 Too Many Requests`
- Chat rate limit exceeded (`ChatRateThrottle`).

6. `503 Service Unavailable`
- LLM provider unavailable or not configured.

## Notes

- Chat and streaming chat enforce consent via `ConsentRequiredMixin`; status, education, FAQs, and suggestions do not.
- SSE streams set `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- Tool calls are read-only and scoped to the authenticated customer.
- History search uses case-insensitive regex on `message` and `response`.
- If language is omitted, chat defaults to the customer's saved language preference.
