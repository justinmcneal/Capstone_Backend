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
| Smart Contracts / blockchain integration | ⚠️ Implemented but disabled by default | Enable via env and verify deployed contract addresses/ABIs | 🔴 High |
| Production S3 document storage | ❌ Not implemented | Implement real `S3StorageBackend` (upload/delete/get_url), env-based backend switch, and migration path from local `media/` to S3 | 🔴 High |
| Production deployment (Railway) | ⚠️ Pending | Deploy backend service, set production env vars, run smoke tests for auth/docs/loans/analytics | 🔴 High |
| Tagalog chatbot quality improvements (advanced multilingual) | ⚠️ Basic TL support only | Add TL-focused prompt tuning, glossary/terminology control, and optional model routing for better EN/TL consistency | 🟡 Medium |

---

## Recommended Order

1. Enable blockchain in env, verify contracts/ABIs, and add missing on-chain flows.
2. Implement S3 storage backend and switch production storage to S3.
3. Deploy to Railway and run end-to-end verification.
4. Improve Tagalog chatbot quality with multilingual prompt/routing enhancements.

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

## All Features Complete! 🎉
