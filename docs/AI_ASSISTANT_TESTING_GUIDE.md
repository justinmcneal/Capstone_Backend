# AI Assistant API Testing Guide

Complete guide to test the AI chatbot endpoints.

---

## Setup

**Base URL:** `http://localhost:8000/api/ai`

**Requirements:**
1. Groq API key: Get free at https://console.groq.com
2. Set in `.env`: `GROQ_API_KEY=gsk_your_key_here`
3. No local installation needed - cloud-based!

**Headers:**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json
```

> ⚠️ **Requires AI consent.** Customer must have `ai_consent: true`.

---

## Endpoints

### 1. Check AI Status

```
GET /api/ai/status/
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "available": true,
        "provider": "groq",
        "current_model": "llama-3.1-8b-instant",
        "api_configured": true
    }
}
```

---

### 2. Get Suggestions

```
GET /api/ai/suggestions/
GET /api/ai/suggestions/?language=tl
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "suggestions": [
            "What is a loan and how does it work?",
            "How do I apply for a small business loan?",
            ...
        ],
        "language": "en"
    }
}
```

---

### 3. Send Chat Message

```
POST /api/ai/chat/
```

**Body:**
```json
{
    "message": "What documents do I need for a loan?",
    "language": "en",
    "conversation_id": "optional-uuid"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "response": "To apply for a loan, you'll need...",
        "conversation_id": "abc123...",
        "model": "llama3.2",
        "response_time_ms": 1234
    }
}
```

---

### 4. Get Chat History

```
GET /api/ai/history/
GET /api/ai/history/?limit=20
```

---

### 5. Clear Chat History

```
DELETE /api/ai/history/
```

---

## Testing Flow

1. **Get Groq API key:** Sign up free at https://console.groq.com
2. **Add to .env:** `GROQ_API_KEY=gsk_your_key_here`
3. **Restart server:** `python manage.py runserver`
4. **Login as customer** with AI consent
5. **Check status:** `GET /api/ai/status/`
6. **Get suggestions:** `GET /api/ai/suggestions/`
7. **Send message:** `POST /api/ai/chat/`

---

## Error Responses

### No AI Consent
```json
{
    "status": "error",
    "message": "AI consent is required to use this feature",
    "errors": {
        "code": "CONSENT_REQUIRED",
        "action_required": {
            "endpoint": "/api/auth/consent/",
            "method": "POST"
        }
    }
}
```

### API Key Not Configured
```json
{
    "status": "error",
    "message": "AI service is currently unavailable. Please configure GROQ_API_KEY.",
    "errors": {
        "hint": "Get free API key at https://console.groq.com"
    }
}
```
