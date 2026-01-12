# MSME Pathways - Complete API Reference

> **Base URL:** `http://localhost:8000`  
> **Version:** 1.0.0  
> **Last Updated:** January 2026

---

## Quick Reference

| Module | Endpoints | Auth Required |
|--------|-----------|---------------|
| [System](#system) | 1 | ❌ |
| [Authentication](#authentication) | 20 | Mixed |
| [Profiles](#profiles) | 5 | ✅ Customer |
| [Documents](#documents) | 6 | ✅ Mixed |
| [Loans](#loans) | 16 | ✅ Mixed |
| [AI Assistant](#ai-assistant) | 7 | ✅ Customer |
| [Analytics](#analytics) | 4 | ✅ Mixed |
| **Total** | **59 endpoints** | |

---

## Authentication Headers

```
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

---

## System

### Health Check
```
GET /api/health/
```
**Auth:** None  
**Response:** MongoDB status, AI status

---

## Authentication

### Customer Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/signup/` | Register new customer |
| `POST` | `/api/auth/verify-email/` | Verify email with OTP |
| `POST` | `/api/auth/resend-otp/` | Resend verification OTP |
| `POST` | `/api/auth/login/` | Customer login |
| `POST` | `/api/auth/logout/` | Logout (invalidate token) |
| `POST` | `/api/auth/refresh-token/` | Refresh JWT token |

### Password Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/forgot-password/` | Request password reset OTP |
| `POST` | `/api/auth/verify-reset-otp/` | Verify reset OTP |
| `POST` | `/api/auth/reset-password/` | Set new password |
| `POST` | `/api/auth/change-password/` | Change password (logged in) |

### Two-Factor Authentication (2FA)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/2fa/setup/` | Start 2FA setup (get QR code) |
| `POST` | `/api/auth/2fa/confirm/` | Confirm 2FA with TOTP code |
| `POST` | `/api/auth/2fa/verify/` | Verify 2FA during login |
| `POST` | `/api/auth/2fa/disable/` | Disable 2FA |
| `POST` | `/api/auth/2fa/backup-codes/` | Regenerate backup codes |
| `GET` | `/api/auth/2fa/status/` | Check 2FA status |

### Consent

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/consent/` | Get consent status |
| `POST` | `/api/auth/consent/` | Update consent |

### Loan Officer Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/loan-officer/login/` | Officer login |
| `POST` | `/api/auth/loan-officer/logout/` | Officer logout |

### Admin Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/admin/login/` | Admin login |
| `POST` | `/api/auth/admin/logout/` | Admin logout |

### Admin - User Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/admin/loan-officers/` | List all officers |
| `POST` | `/api/auth/admin/loan-officers/` | Create officer |
| `GET` | `/api/auth/admin/loan-officers/<id>/` | Get officer details |
| `PUT` | `/api/auth/admin/loan-officers/<id>/` | Update officer |
| `DELETE` | `/api/auth/admin/loan-officers/<id>/` | Deactivate officer |
| `GET` | `/api/auth/admin/admins/` | List all admins |
| `POST` | `/api/auth/admin/admins/` | Create admin |
| `GET` | `/api/auth/admin/admins/<id>/` | Get admin details |
| `PUT` | `/api/auth/admin/admins/<id>/permissions/` | Update permissions |

---

## Profiles

**Auth:** Customer JWT required

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/profile/` | Get personal profile |
| `PUT` | `/api/profile/` | Update personal profile |
| `GET` | `/api/profile/business/` | Get business profile |
| `PUT` | `/api/profile/business/` | Update business profile |
| `GET` | `/api/profile/alternative-data/` | Get alternative credit data |
| `PUT` | `/api/profile/alternative-data/` | Update alternative data |
| `GET` | `/api/profile/summary/` | Get complete profile summary |
| `GET` | `/api/profile/notifications/` | Get notification preferences |
| `PUT` | `/api/profile/notifications/` | Update notification preferences |

---

## Documents

### Customer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/upload/` | Upload document |
| `GET` | `/api/documents/` | List my documents |
| `GET` | `/api/documents/types/` | Get document types |
| `GET` | `/api/documents/<id>/` | Get document details |
| `DELETE` | `/api/documents/<id>/` | Delete document |

### Officer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/<id>/verify/` | Verify/reject document |
| `POST` | `/api/documents/<id>/request-reupload/` | Request re-upload |

---

## Loans

### Customer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/products/` | List loan products |
| `GET` | `/api/loans/products/<id>/` | Product details |
| `POST` | `/api/loans/pre-qualify/` | AI pre-qualification check |
| `POST` | `/api/loans/apply/` | Submit loan application |
| `GET` | `/api/loans/applications/` | List my applications |
| `GET` | `/api/loans/applications/<id>/` | Application details |
| `GET` | `/api/loans/applications/<id>/schedule/` | Get repayment schedule |
| `GET` | `/api/loans/applications/<id>/payments/` | Get payment history |
| `POST` | `/api/loans/applications/<id>/resubmit/` | Resubmit rejected app |
| `GET` | `/api/loans/applications/<id>/feedback/` | Get rejection feedback |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/admin/products/` | List all products |
| `POST` | `/api/loans/admin/products/` | Create product |
| `GET` | `/api/loans/admin/products/<id>/` | Product details |
| `PUT` | `/api/loans/admin/products/<id>/` | Update product |
| `DELETE` | `/api/loans/admin/products/<id>/` | Delete product |
| `POST` | `/api/loans/admin/applications/<id>/assign/` | Assign to officer |
| `GET` | `/api/loans/admin/officers/workload/` | View officer workloads |

### Loan Officer Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/loans/officer/applications/` | List assigned applications |
| `GET` | `/api/loans/officer/applications/<id>/` | Application detail |
| `POST` | `/api/loans/officer/applications/<id>/review/` | Approve/reject |
| `POST` | `/api/loans/officer/applications/<id>/disburse/` | Disburse loan |
| `POST` | `/api/loans/officer/payments/` | Record payment |

---

## AI Assistant

**Auth:** Customer JWT + AI Consent required

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ai/chat/` | Send message to AI |
| `GET` | `/api/ai/history/` | Get chat history |
| `DELETE` | `/api/ai/history/` | Clear chat history |
| `GET` | `/api/ai/suggestions/` | Get conversation starters |
| `GET` | `/api/ai/status/` | Check AI availability |
| `GET` | `/api/ai/education/` | List education topics |
| `GET` | `/api/ai/education/<topic>/` | Get topic content |
| `GET` | `/api/ai/faqs/` | Get FAQs |

---

## Analytics

### Admin Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/analytics/admin/` | System-wide statistics |
| `GET` | `/api/analytics/audit-logs/` | View audit logs |

### Officer Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/analytics/officer/` | Officer performance stats |

### Customer Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/analytics/customer/` | Personal loan statistics |

---

## Frontend Implementation Checklist

### Mobile/Web Screens Needed

#### Public (No Auth)
- [ ] Landing page
- [ ] Login screen
- [ ] Signup screen
- [ ] Email verification (OTP input)
- [ ] Forgot password flow

#### Customer App
- [ ] Dashboard (analytics)
- [ ] Profile management (3 sections)
- [ ] Document upload/list
- [ ] Loan products browsing
- [ ] Pre-qualification check
- [ ] Loan application form
- [ ] My applications list
- [ ] Application status details
- [ ] Repayment schedule view
- [ ] Payment history
- [ ] AI chat interface
- [ ] Settings (notifications, 2FA)

#### Officer Portal
- [ ] Dashboard
- [ ] Application queue
- [ ] Application review screen
- [ ] Document verification
- [ ] Disbursement form
- [ ] Payment recording

#### Admin Portal
- [ ] System dashboard
- [ ] User management (officers/admins)
- [ ] Product management
- [ ] Audit logs
- [ ] Officer workload view

---

## Response Format

All endpoints return:
```json
{
  "status": "success" | "error",
  "data": { ... },
  "message": "Human readable message",
  "errors": { ... }  // Only on error
}
```

---

## Status Codes

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
