# AI Assistant API Testing Guide

Complete guide to test the AI chatbot endpoints.

---

## Setup

**Base URL:** `http://localhost:8000/api/ai`

**Requirements:**
1. Ollama installed: https://ollama.ai
2. Model downloaded: `ollama pull llama3.2`
3. Ollama running: `ollama serve`

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
        "current_model": "llama3.2",
        "available_models": ["llama3.2:latest"],
        "host": "http://localhost:11434"
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

1. **Install Ollama:** `brew install ollama` (Mac) or download from ollama.ai
2. **Pull model:** `ollama pull llama3.2`
3. **Start Ollama:** `ollama serve` (runs on port 11434)
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

### Ollama Not Running
```json
{
    "status": "error",
    "message": "AI service is currently unavailable. Please ensure Ollama is running.",
    "errors": {
        "hint": "Run: ollama run llama3.2"
    }
}
```
