# Consent Management Documentation

> Privacy-first consent collection and enforcement for AI features in MSME Pathways

---

## Overview

As required by data privacy regulations and ethical AI practices, users must provide explicit consent before:
- Their data is collected and processed
- They interact with AI-powered features

```
┌─────────────────────────────────────────────────────────────┐
│                    CONSENT FLOW                              │
├─────────────────────────────────────────────────────────────┤
│ User Opens App → Language Selection → CONSENT COLLECTION    │
│                                            ↓                 │
│                                  [If Consent Given]          │
│                                            ↓                 │
│                                  AI Assistant Enabled        │
└─────────────────────────────────────────────────────────────┘
```

---

## Consent Types

### 1. Data Consent (`data_consent`)

**What it covers:**
- Collection of personal information (name, email, phone)
- Storage of uploaded documents
- Processing of alternative credit data
- Profile and behavior analytics

**Required for:**
- Account profile completion
- Document uploads
- Loan pre-qualification

---

### 2. AI Consent (`ai_consent`)

**What it covers:**
- Interaction with AI Financial Assistant
- AI-powered document analysis
- AI loan recommendations
- Chat history storage for AI improvement

**Required for:**
- Using the AI chatbot
- Receiving AI-generated loan recommendations
- Document analysis via CNN

---

## Consent Model

```python
class Consent:
    _id: ObjectId
    user_id: ObjectId           # Reference to Customer/LoanOfficer
    user_type: str              # 'customer' or 'loan_officer'
    data_consent: bool          # Consent to data collection
    ai_consent: bool            # Consent to AI interactions
    consent_date: datetime      # When consent was first given
    updated_at: datetime        # Last modification
    ip_address: str             # IP at time of consent (audit)
    consent_version: str        # Version of consent terms accepted
```

---

## API Endpoints

### Record Consent

```http
POST /api/auth/consent/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "data_consent": true,
    "ai_consent": true
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Consent recorded successfully",
    "data": {
        "data_consent": true,
        "ai_consent": true,
        "consent_date": "2024-01-15T10:30:00Z"
    }
}
```

---

### Get Consent Status

```http
GET /api/auth/consent/
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "data_consent": true,
        "ai_consent": true,
        "consent_date": "2024-01-15T10:30:00Z",
        "can_access_ai": true
    }
}
```

---

### Update Consent

```http
PUT /api/auth/consent/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "ai_consent": false
}
```

**Response:**
```json
{
    "status": "success",
    "message": "Consent updated successfully",
    "data": {
        "data_consent": true,
        "ai_consent": false,
        "updated_at": "2024-01-20T14:00:00Z",
        "can_access_ai": false
    }
}
```

---

## AI Feature Blocking

When `ai_consent` is `false` or not given, the following features are blocked:

| Feature | Blocked | Error Code |
|---------|---------|------------|
| AI Financial Assistant | ✅ | `CONSENT_REQUIRED` |
| Document AI Analysis | ✅ | `CONSENT_REQUIRED` |
| AI Loan Recommendations | ✅ | `CONSENT_REQUIRED` |
| Profile Viewing | ❌ | — |
| Manual Document Upload | ❌ | — |

### Error Response Example

```json
{
    "status": "error",
    "code": "CONSENT_REQUIRED",
    "message": "AI consent is required to use this feature",
    "action_required": {
        "endpoint": "/api/auth/consent/",
        "method": "POST",
        "required_fields": ["ai_consent"]
    }
}
```

---

## Consent Enforcement

The system enforces AI consent using a **view-level mixin** (`ConsentRequiredMixin`) applied to AI-related views:

```python
# ai_assistant/views/chat_views.py
class ConsentRequiredMixin:
    """Mixin to enforce AI consent before allowing AI features"""
    
    def check_ai_consent(self, request):
        """Check if user has given AI consent"""
        consent = Consent.find_by_user(customer_id, 'customer')
        
        if not consent or not consent.ai_consent:
            return False, error_response(
                message="AI consent is required to use this feature",
                errors={'code': 'CONSENT_REQUIRED', ...},
                status_code=403
            )
        return True, consent
```

**How it works:**

1. Each AI view inherits from `ConsentRequiredMixin`
2. Views call `check_ai_consent()` at the start of request handling
3. Returns `403 Forbidden` with `CONSENT_REQUIRED` code if not given
4. Consent can be updated at any time via `PUT /api/auth/consent/`

**Views protected by consent check:**
- `ChatView` — AI chat endpoint
- `ChatHistoryView` — Chat history retrieval
- `SuggestionsView` — Conversation starters

---

## Consent Withdrawal

Users can withdraw consent at any time:

- **Data Consent Withdrawal**: User must be informed that this may limit app functionality
- **AI Consent Withdrawal**: AI features immediately become unavailable
- **Full Withdrawal**: User may request account deletion

---

## Audit Trail

All consent actions are logged:

```json
{
    "event": "consent_updated",
    "user_id": "6789abc...",
    "user_type": "customer",
    "changes": {
        "ai_consent": {"from": true, "to": false}
    },
    "ip_address": "192.168.1.1",
    "timestamp": "2024-01-20T14:00:00Z"
}
```

---

## Language Selection Integration

Consent collection happens alongside language selection as per the system flowchart:

```
App Open → Language Selection → Consent Form → [Continue to App]
                                    ↓
                        Both displayed in selected language
```

Supported languages:
- `en` — English
- `tl` — Tagalog (Filipino)

---

## Legal Compliance

This consent system supports:

- **Data Privacy Act of 2012** (Philippines) — Explicit consent requirement
- **GDPR principles** — Right to withdraw, data minimization
- **Ethical AI practices** — Informed consent for AI interactions

---

## Related Documentation

- [User Roles](./ROLES.md) — Role-specific consent requirements
- [Authentication](./AUTHENTICATION.md) — Auth flow integration
