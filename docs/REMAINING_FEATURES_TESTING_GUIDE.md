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
