# MSME Pathways - Complete API Reference

> **Base URL:** `http://localhost:8000`  
> **Version:** 1.0.0  
> **Last Updated:** February 20, 2026

---

## Quick Reference

Counts below are based on backend route definitions in `config/urls.py` and module `urls.py` files.

| Module | URL Paths | Method Entries | Auth Required |
|--------|-----------|----------------|---------------|
| [System](#system) | 1 | 1 | ❌ |
| [Authentication](#authentication) | 27 | 35 | Mixed |
| [Profiles](#profiles) | 5 | 9 | ✅ Customer |
| [Documents](#documents) | 6 | 7 | ✅ Mixed |
| [Loans](#loans) | 28 | 31 | ✅ Mixed |
| [AI Assistant](#ai-assistant) | 7 | 8 | ✅ Customer |
| [Analytics](#analytics) | 6 | 6 | ✅ Mixed |
| [Notifications](#notifications) | 4 | 4 | ✅ Mixed |
| **Total** | **84** | **101** | |

---

## Authentication Headers

```http
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

---

## System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health/` | Health check (MongoDB/AI status) |

---

## Authentication

### Customer Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/csrf-token/` | Get CSRF token |
| `POST` | `/api/auth/signup/` | Register customer |
| `POST` | `/api/auth/verify-email/` | Verify email OTP |
| `POST` | `/api/auth/resend-otp/` | Resend verification OTP |
| `POST` | `/api/auth/login/` | Customer login |
| `POST` | `/api/auth/logout/` | Customer logout |
| `POST` | `/api/auth/refresh-token/` | Refresh JWT token |

### Password Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/forgot-password/` | Request password reset OTP |
| `POST` | `/api/auth/verify-reset-otp/` | Verify reset OTP |
| `POST` | `/api/auth/reset-password/` | Reset password |
| `POST` | `/api/auth/change-password/` | Change password |

### Two-Factor Authentication (2FA)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/2fa/setup/` | Start 2FA setup |
| `POST` | `/api/auth/2fa/confirm/` | Confirm 2FA setup |
| `POST` | `/api/auth/2fa/verify/` | Verify 2FA code |
| `POST` | `/api/auth/2fa/disable/` | Disable 2FA |
| `POST` | `/api/auth/2fa/backup-codes/` | Regenerate backup codes |
| `GET` | `/api/auth/2fa/status/` | Get 2FA status |

### Consent

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/consent/` | Get consent status |
| `POST` | `/api/auth/consent/` | Record consent |
| `PUT` | `/api/auth/consent/` | Update consent |

### Loan Officer Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/loan-officer/login/` | Loan officer login |
| `POST` | `/api/auth/loan-officer/logout/` | Loan officer logout |

### Admin Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/admin/login/` | Admin login |
| `POST` | `/api/auth/admin/logout/` | Admin logout |

### Admin - Loan Officer Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/admin/loan-officers/` | List loan officers |
| `POST` | `/api/auth/admin/loan-officers/` | Create loan officer |
| `GET` | `/api/auth/admin/loan-officers/<str:officer_id>/` | Get loan officer detail |
| `PUT` | `/api/auth/admin/loan-officers/<str:officer_id>/` | Update loan officer |
| `DELETE` | `/api/auth/admin/loan-officers/<str:officer_id>/` | Deactivate loan officer |

### Admin - Admin Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/admin/admins/` | List admins |
| `POST` | `/api/auth/admin/admins/` | Create admin |
| `GET` | `/api/auth/admin/admins/<str:admin_id>/` | Get admin detail |
| `PUT` | `/api/auth/admin/admins/<str:admin_id>/` | Update admin |
| `DELETE` | `/api/auth/admin/admins/<str:admin_id>/` | Deactivate admin |
| `PUT` | `/api/auth/admin/admins/<str:admin_id>/permissions/` | Update admin permissions |

---

## Profiles

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/profile/` | Get personal profile |
| `PUT` | `/api/profile/` | Update personal profile |
| `GET` | `/api/profile/business/` | Get business profile |
| `PUT` | `/api/profile/business/` | Update business profile |
| `GET` | `/api/profile/alternative-data/` | Get alternative credit data |
| `PUT` | `/api/profile/alternative-data/` | Update alternative credit data |
| `GET` | `/api/profile/summary/` | Get profile summary |
| `GET` | `/api/profile/notifications/` | Get notification preferences |
| `PUT` | `/api/profile/notifications/` | Update notification preferences |

---

## Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/upload/` | Upload document |
| `GET` | `/api/documents/` | List documents |
| `GET` | `/api/documents/types/` | List allowed document types |
| `GET` | `/api/documents/<str:document_id>/` | Get document detail |
| `DELETE` | `/api/documents/<str:document_id>/` | Delete document |
| `PUT` | `/api/documents/<str:document_id>/verify/` | Verify/reject document |
| `POST` | `/api/documents/<str:document_id>/request-reupload/` | Request document re-upload |

---

## Loans

### Customer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/products/` | List loan products |
| `GET` | `/api/loans/products/<str:product_id>/` | Get product detail |
| `POST` | `/api/loans/pre-qualify/` | Run pre-qualification |
| `POST` | `/api/loans/apply/` | Submit loan application |
| `GET` | `/api/loans/applications/` | List my applications |
| `GET` | `/api/loans/applications/<str:application_id>/` | Get application detail |
| `GET` | `/api/loans/applications/<str:application_id>/schedule/` | Get repayment schedule |
| `GET` | `/api/loans/applications/<str:application_id>/payments/` | Get payment history |
| `POST` | `/api/loans/applications/<str:application_id>/resubmit/` | Resubmit rejected application |
| `GET` | `/api/loans/applications/<str:application_id>/feedback/` | Get rejection feedback |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/admin/products/` | List all products |
| `POST` | `/api/loans/admin/products/` | Create product |
| `GET` | `/api/loans/admin/products/<str:product_id>/` | Get product detail |
| `PUT` | `/api/loans/admin/products/<str:product_id>/` | Update product |
| `DELETE` | `/api/loans/admin/products/<str:product_id>/` | Delete/deactivate product |
| `POST` | `/api/loans/admin/applications/<str:application_id>/assign/` | Assign application to officer |
| `POST` | `/api/loans/admin/applications/<str:application_id>/reassign/` | Reassign application |
| `GET` | `/api/loans/admin/officers/workload/` | View officer workload |

### Loan Officer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/officer/applications/` | List officer applications |
| `GET` | `/api/loans/officer/applications/<str:application_id>/` | Get officer application detail |
| `POST` | `/api/loans/officer/applications/<str:application_id>/notes/` | Add application notes |
| `POST` | `/api/loans/officer/applications/<str:application_id>/request-missing-documents/` | Request missing documents |
| `PUT` | `/api/loans/officer/applications/<str:application_id>/review/` | Approve/reject application |
| `POST` | `/api/loans/officer/applications/<str:application_id>/disburse/` | Disburse approved loan |
| `POST` | `/api/loans/officer/payments/` | Record payment |
| `GET` | `/api/loans/officer/payments/search/` | Search payments |
| `GET` | `/api/loans/officer/active-loans/` | List active/disbursed loans |
| `GET` | `/api/loans/officer/applications/<str:application_id>/schedule/` | Get repayment schedule (officer view) |
| `POST` | `/api/loans/officer/applications/<str:application_id>/penalties/apply/` | Apply installment penalty |
| `POST` | `/api/loans/officer/applications/<str:application_id>/penalties/waive/` | Waive installment penalty |
| `GET` | `/api/loans/officer/applications/<str:application_id>/payments/` | Get payment history (officer view) |

---

## AI Assistant

**Auth:** Customer JWT + AI consent required

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ai/chat/` | Send message to AI |
| `GET` | `/api/ai/history/` | Get chat history |
| `DELETE` | `/api/ai/history/` | Clear chat history |
| `GET` | `/api/ai/suggestions/` | Get chat suggestions |
| `GET` | `/api/ai/status/` | Get AI service status |
| `GET` | `/api/ai/education/` | List education topics |
| `GET` | `/api/ai/education/<str:topic>/` | Get specific education topic |
| `GET` | `/api/ai/faqs/` | Get FAQs |

---

## Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/analytics/admin/` | Admin dashboard metrics |
| `GET` | `/api/analytics/audit-logs/` | List audit logs |
| `GET` | `/api/analytics/audit-logs/users/` | List users present in audit logs |
| `GET` | `/api/analytics/audit-logs/<str:log_id>/` | Get audit log detail |
| `GET` | `/api/analytics/officer/` | Officer dashboard metrics |
| `GET` | `/api/analytics/customer/` | Customer dashboard metrics |

---

## Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/notifications/` | List notifications |
| `GET` | `/api/notifications/unread-count/` | Get unread notification count |
| `POST` | `/api/notifications/mark-all-read/` | Mark all notifications as read |
| `POST` | `/api/notifications/<str:notification_id>/read/` | Mark one notification as read |

---

## Response Format

All endpoints return:

```json
{
  "status": "success" | "error",
  "data": { ... },
  "message": "Human readable message",
  "errors": { ... }
}
```

---

## Common Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Server Error |
| 503 | Service Unavailable |
