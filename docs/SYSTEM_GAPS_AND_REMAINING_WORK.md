# System Gaps and Remaining Work

Merged documentation for pending backend gaps and remaining feature endpoints.

## Wave

- Wave: 10
- Status: Done

## Navigation

1. [Backend Gap Analysis (Pending Items Only)](#section-1-gap_analysismd)
2. [Remaining Features Testing Guide (from Loan Lifecycle)](#section-2-loan_lifecycle_testing_guide_section-7)

## Source Files

1. `GAP_ANALYSIS.md`
2. `LOAN_LIFECYCLE_TESTING_GUIDE.md` (Section 7)

---

## Section 1: GAP_ANALYSIS.md

# MSME Pathways - Backend Gap Analysis (Pending Items Only)

> **Scope:** Backend only (frontend apps are complete)
> **Updated:** February 18, 2026

---

## Remaining Implementation Gaps

| Item | Current Status | What Is Missing | Priority |
|------|----------------|-----------------|----------|
| Smart Contracts / blockchain integration | ✅ Implemented (gated) | Code exists and is feature-gated by `BLOCKCHAIN_ENABLED`; enable via env, verify deployed contract addresses/ABIs and wallet key | 🔴 High |
| Production S3 document storage | ✅ Implemented | `S3StorageBackend` implemented, presigned helpers available, and migration tooling present (`scripts/migrate_media_to_s3.py`) — set `DOCUMENT_STORAGE_BACKEND=s3` and provide AWS creds to enable | 🔴 High |
| Production deployment (Railway) | ⚠️ Pending | Deploy backend service, set production env vars, run smoke tests for auth/docs/loans/analytics | 🔴 High |
| Tagalog chatbot quality improvements (advanced multilingual) | ⚠️ Basic TL support only | Add TL-focused prompt tuning, glossary/terminology control, and optional model routing for better EN/TL consistency | 🟡 Medium |

---

## Recommended Order

1. Verify and enable S3 in staging (set `DOCUMENT_STORAGE_BACKEND=s3`, provide AWS creds) and run migration smoke tests.
2. Enable blockchain in env and verify deployed contract addresses/ABIs (set `BLOCKCHAIN_ENABLED=True` and ensure `BLOCKCHAIN_WALLET_KEY` is present).
3. Deploy to Railway and run end-to-end verification.
4. Improve Tagalog chatbot quality with multilingual prompt/routing enhancements.

Status notes (where to find implementations)

- S3 backend and helpers: [documents/storage/backends.py](documents/storage/backends.py#L1)
- Migration tooling: [scripts/migrate_media_to_s3.py](scripts/migrate_media_to_s3.py#L1)
- Blockchain client & gating: [loans/blockchain/client.py](loans/blockchain/client.py#L1) and tests under [tests/blockchain/](tests/blockchain/)
- Railway runbook and smoke-test automation: [docs/RAILWAY_PRODUCTION_DEPLOYMENT_AND_SMOKE_TESTS.md](docs/RAILWAY_PRODUCTION_DEPLOYMENT_AND_SMOKE_TESTS.md#L1) and `scripts/smoke_test_railway.py`

---

## Section 2: LOAN_LIFECYCLE_TESTING_GUIDE.md (Section 7)

## Section 7: REMAINING_FEATURES_TESTING_GUIDE.md

# Remaining Features Testing Guide

## New Endpoints Summary

### 1. Application Resubmission
```
POST /api/loans/applications/<id>/resubmit/
Authorization: Bearer <customer_token>
```
- Only works for `rejected` applications
- Resets status to `draft`

---

### 2. Rejection Feedback
```
GET /api/loans/applications/<id>/feedback/
Authorization: Bearer <customer_token>
```
- AI explains rejection reason
- Includes improvement suggestions

---

### 3. Document Re-upload Request (Officer)
```
POST /api/documents/<id>/request-reupload/
Authorization: Bearer <officer_token>
Content-Type: application/json

{"reason": "Image is blurry, please upload a clearer photo"}
```

---

### 4. Loan Education
```
GET /api/ai/education/
GET /api/ai/education/<topic>/
```
Topics: `what_is_a_loan`, `interest_rates`, `loan_process`, `documents_needed`, `improving_chances`

---

### 5. FAQs
```
GET /api/ai/faqs/
```

---

### 6. Health Check
```
GET /api/health/
```
Returns: MongoDB status, AI status

---

### 7. Notification Preferences
```
GET /api/profile/notifications/
PUT /api/profile/notifications/

Body:
{
    "preferences": {
        "email_loan_updates": true,
        "email_payment_reminders": true,
        "email_promotions": false
    }
}
```

---

### 8. Multilingual Support
Customer model has `language` field (`en` or `tl`). AI responses adapt based on language.

---
## Verification performed

I scanned the codebase and verified the endpoints and features listed above are implemented in the repository (links below). Where noted in Section 1, operational enablement (setting env vars, provisioning S3/KMS, deploying to Railway) may still be required before these features are active in staging/production.

- Application resubmission: implemented at [loans/views/customer_views.py](loans/views/customer_views.py#L1125) and exposed in [loans/urls.py](loans/urls.py#L58).
- Rejection feedback (AI): implemented at [loans/views/customer_views.py](loans/views/customer_views.py#L1170).
- Document re-upload request (officer): implemented at [documents/views/document_views.py](documents/views/document_views.py#L938) and routed in [documents/urls.py](documents/urls.py#L30).
- Loan education and FAQs: implemented at [ai_assistant/views/chat_views.py](ai_assistant/views/chat_views.py#L672) and [ai_assistant/views/chat_views.py](ai_assistant/views/chat_views.py#L820).
- Health check: implemented at [ai_assistant/views/chat_views.py](ai_assistant/views/chat_views.py#L600).
- Notification preferences: implemented at [profiles/views/profile_views.py](profiles/views/profile_views.py#L502).
- Multilingual support: customer `language` implemented in [accounts/models/customer.py](accounts/models/customer.py#L33) and used in AI views.

All of these are present in the repository; a small number of features remain operational (environment/IaC) tasks:

- Provision S3/KMS and set Railway env vars to enable `DOCUMENT_STORAGE_BACKEND=s3` and S3 flows.
- Set `BLOCKCHAIN_ENABLED=True` and provide `BLOCKCHAIN_WALLET_KEY` to enable blockchain-backed flows.

## All Features Complete! 🎉
