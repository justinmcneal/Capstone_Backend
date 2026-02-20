# AI Assistant API Testing Guide

## Prerequisites
- Base URL: `http://localhost:8000/api/ai`
- `.env` contains `GROQ_API_KEY=gsk_your_key_here`
- Server restarted after `.env` changes (`python manage.py runserver`)
- Authenticated customer token
- Customer consent must include `ai_consent: true`

Headers:
```http
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

## Endpoint Reference
1. `GET /status/`
Returns service health (`available`, `provider`, `current_model`, `api_configured`).

2. `GET /suggestions/?language=en|tl`
Returns starter prompts for the requested language (`en` or `tl`).

3. `POST /chat/`
Sends a message to the assistant.
```json
{
  "message": "What documents do I need for a loan?",
  "language": "en",
  "conversation_id": "optional-uuid"
}
```
`message` is required. `conversation_id` must be a valid UUID when provided.

4. `GET /history/?page=1&limit=20&search=term`
Returns paginated chat history (`history`, `page`, `limit`, `total_messages`, `total_pages`, `has_more`).

5. `DELETE /history/`
Clears all customer chat history (`deleted_count`).

## Smoke Test Order
1. `GET /status/` and confirm `available: true` and `api_configured: true`.
2. `GET /suggestions/?language=en`.
3. `POST /chat/` with a sample message.
4. `GET /history/?limit=20` and confirm returned messages.
5. `DELETE /history/`, then re-run history check.

## Common Errors
1. `403 CONSENT_REQUIRED`
```json
{
  "status": "error",
  "message": "AI consent is required to use this feature",
  "errors": {
    "code": "CONSENT_REQUIRED",
    "action_required": {
      "endpoint": "/api/auth/consent/",
      "method": "POST",
      "required_fields": ["ai_consent"]
    }
  }
}
```

2. `503 Service Unavailable` (missing `GROQ_API_KEY`)
```json
{
  "status": "error",
  "message": "AI service is currently unavailable. Please configure GROQ_API_KEY.",
  "errors": {
    "hint": "Get free API key at https://console.groq.com"
  }
}
```
