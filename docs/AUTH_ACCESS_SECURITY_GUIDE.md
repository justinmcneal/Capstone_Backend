# Auth Access Security Guide

Merged documentation for authentication, account testing, security controls, consent, and role-based access.

## Wave

- Wave: 1
- Status: Done

## Navigation

1. [Authentication System Documentation](#section-1-authenticationmd)
2. [API Testing Guide for Insomnia](#section-2-accounts_testing_guidemd)
3. [Security Features](#section-3-securitymd)
4. [Consent Management Documentation](#section-4-consentmd)
5. [User Roles Documentation](#section-5-rolesmd)

## Source Files

1. `AUTHENTICATION.md`
2. `ACCOUNTS_TESTING_GUIDE.md`
3. `SECURITY.md`
4. `CONSENT.md`
5. `ROLES.md`

---

## Section 1: AUTHENTICATION.md

### Authentication System Documentation

> A comprehensive guide to the authentication and security mechanisms implemented in the Capstone Backend.

---

## Table of Contents

1. [Overview](#overview)
2. [User Roles](#user-roles)
3. [Authentication Flow](#authentication-flow)
4. [Security Mechanisms](#security-mechanisms)
5. [API Endpoints](#api-endpoints)
6. [Production Best Practices](#production-best-practices)

---

## Overview

This authentication system provides enterprise-grade security for **three user types**, featuring:

- **Multi-user role support**: Customers, Loan Officers, and Admins
- **Email-verified registration** with OTP confirmation (customers)
- **Secure login** with rate limiting and account lockout
- **Two-Factor Authentication (2FA)** using TOTP (Time-based One-Time Password)
- **Token-based sessions** with automatic invalidation
- **Consent management** for data and AI feature access
- **Production-ready throttling** to prevent abuse

> **Related Documentation:**
> - [User Roles](#section-5-rolesmd) — Detailed role permissions and capabilities
> - [Consent Management](#section-4-consentmd) — Data and AI consent requirements

---

## Authentication Flow

### 1. Customer Registration (Sign Up)

```
Customer → Submits registration form → System validates data → Creates unverified account
    ↓
System sends OTP email → Customer enters OTP → Account verified → Tokens issued
```

**Flow Details:**

1. Customer provides: first name, last name, email, password
2. System validates:
   - Email format and uniqueness
   - Password strength (Django validators)
3. Account created with `verified = false`
4. 6-digit OTP sent to email (valid for 12 hours)
5. Customer must verify within 12 hours or account is auto-deleted
6. OTP resend allowed 2 times maximum

**Security Features:**
- Signup rate limit: 5 requests/hour per IP
- Unverified accounts auto-deleted after 12 hours
- OTP resend limit prevents abuse

---

### 2. Customer Login

```
Customer → Enters email/password → System checks lockout → Validates credentials
    ↓
[If 2FA disabled] → Tokens issued → Login complete
    ↓
[If 2FA enabled] → Temp token issued → Customer enters 2FA code → Tokens issued
```

**Flow Details:**

1. Customer submits email and password
2. System checks:
   - Account existence
   - Account lockout status
   - Rate limiting (30 second cooldown)
   - Email verification status
   - Password validity
3. On failed password:
   - Failed attempt recorded
   - After 5 failures: account locked for 15 minutes
4. On successful password:
   - Lockout counter reset
   - If 2FA enabled: temporary token issued for 2FA step
   - If 2FA disabled: full access/refresh tokens issued

**Remember Me Option:**
- Checked: Refresh token valid for 3 days
- Unchecked: Refresh token valid for 24 hours
- Access token always valid for 10 minutes

---

### 3. Two-Factor Authentication (2FA)

```
┌─────────────────────────────────────────────────────────────┐
│                    2FA SETUP FLOW                           │
├─────────────────────────────────────────────────────────────┤
│ 1. User requests 2FA setup (authenticated)                  │
│ 2. System generates TOTP secret                             │
│ 3. Returns QR code URI for authenticator app                │
│ 4. User scans QR with Google Authenticator/Authy            │
│ 5. User enters first code to confirm setup                  │
│ 6. System enables 2FA, returns 10 backup codes              │
└─────────────────────────────────────────────────────────────┘
```

**2FA Login Flow:**
1. User enters email/password (validated normally)
2. System returns `requires_2fa: true` + temporary token
3. User enters 6-digit code from authenticator app
4. System validates code against stored secret
5. On success: full tokens issued

**Backup Codes:**
- 10 one-time use codes generated on 2FA setup
- Format: `XXXX-XXXX` (8 alphanumeric characters)
- Each code can only be used once
- Users can regenerate codes (invalidates old ones)

---

### 4. Token Management

```
┌─────────────────────────────────────────────────────────────┐
│                   TOKEN LIFECYCLE                           │
├─────────────────────────────────────────────────────────────┤
│ ACCESS TOKEN (10 min)                                       │
│ ├── Used for API authentication                             │
│ ├── Short-lived for security                                │
│ └── Blacklisted on logout                                   │
│                                                             │
│ REFRESH TOKEN (24h or 3 days)                               │
│ ├── Used to get new access token                            │
│ ├── Single-device: new login invalidates old tokens         │
│ └── Blacklisted on logout                                   │
└─────────────────────────────────────────────────────────────┘
```

**Single-Device Enforcement:**
When a customer logs in on a new device:
1. All existing refresh tokens for that customer are invalidated
2. Only the newest session remains active
3. Previous sessions become invalid

---

### 5. Logout

```
Customer → Sends access + refresh tokens → Both tokens blacklisted → Session ended
```

Both access and refresh tokens are added to a blacklist to prevent reuse.

---

## Security Mechanisms

### Account Lockout Protection

| Parameter | Value | Description |
|-----------|-------|-------------|
| Max Attempts | 5 | Failed password attempts before lockout |
| Lockout Duration | 15 minutes | Time account remains locked |
| Auto-Unlock | Yes | Account unlocks automatically after duration |
| Admin Unlock | Yes | Admins can manually unlock accounts |

**Why This Matters:**
Prevents brute-force password attacks. Even if an attacker knows an email, they can only attempt 5 passwords before being locked out.

---

### Request Throttling (Rate Limiting)

| Endpoint | Rate Limit | Rationale |
|----------|------------|-----------|
| Sign Up | 5/hour | Prevents mass account creation |
| Login | 10/hour | Prevents credential stuffing |
| OTP Verification | 5/hour | Prevents OTP brute-forcing |
| OTP Resend | 3/hour | Prevents email spam |
| 2FA Verification | 5/hour | Prevents 2FA brute-forcing |
| Password Reset | 3/hour | Prevents email enumeration |

**Why This Matters:**
These limits are per-IP address. Attackers cannot flood endpoints even with automated tools.

---

### Token Security

| Feature | Implementation | Benefit |
|---------|----------------|---------|
| Token Hashing | SHA-256 | Tokens stored securely in database |
| Access Token Blacklist | Checked on every request | Prevents use after logout |
| Refresh Token Invalidation | Automatic on new login | Single-device sessions |
| Expiry Enforcement | JWT exp claim + DB TTL | Automatic cleanup |

---

### Password Security

- **Hashing**: bcrypt with automatic salting
- **Validation**: 
  - Minimum length requirements
  - Common password rejection
  - Similarity to user attributes check
  - Numeric-only password rejection

---

## API Endpoints

### Authentication

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/signup/` | Register new customer | No |
| POST | `/api/auth/verify-email/` | Verify email with OTP | No |
| POST | `/api/auth/resend-otp/` | Resend verification OTP | No |
| POST | `/api/auth/login/` | Customer login | No |
| POST | `/api/auth/logout/` | End session | No |
| POST | `/api/auth/refresh-token/` | Get new access token | No |

### Password Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/forgot-password/` | Request password reset | No |
| POST | `/api/auth/verify-reset-otp/` | Verify reset OTP | No |
| POST | `/api/auth/reset-password/` | Set new password | No |
| POST | `/api/auth/change-password/` | Change password | Yes |

### Two-Factor Authentication

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/2fa/setup/` | Start 2FA setup | Yes |
| POST | `/api/auth/2fa/confirm/` | Confirm 2FA with first code | Yes |
| POST | `/api/auth/2fa/verify/` | Verify 2FA during login | No (temp token) |
| POST | `/api/auth/2fa/disable/` | Disable 2FA | Yes |
| POST | `/api/auth/2fa/backup-codes/` | Regenerate backup codes | Yes |
| GET | `/api/auth/2fa/status/` | Get 2FA status | Yes |

### Consent Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/auth/consent/` | Get consent status | Yes |
| POST | `/api/auth/consent/` | Record initial consent | Yes |
| PUT | `/api/auth/consent/` | Update consent preferences | Yes |

### Loan Officer Authentication

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/loan-officer/login/` | Loan officer login | No |
| POST | `/api/auth/loan-officer/logout/` | End loan officer session | No |

### Admin Authentication & Management

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/admin/login/` | Admin login | No |
| POST | `/api/auth/admin/logout/` | End admin session | No |
| GET | `/api/auth/admin/loan-officers/` | List all loan officers | Admin |
| POST | `/api/auth/admin/loan-officers/` | Create new loan officer | Admin |
| GET | `/api/auth/admin/loan-officers/<id>/` | Get loan officer details | Admin |
| PUT | `/api/auth/admin/loan-officers/<id>/` | Update loan officer | Admin |
| DELETE | `/api/auth/admin/loan-officers/<id>/` | Deactivate loan officer | Admin |

---

## Production Best Practices

### Environment Configuration

```bash
# Required for security
DEBUG=False
SECRET_KEY=<strong-random-key>
ALLOWED_HOSTS=yourdomain.com

# Email configuration
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=<app-password>
```

### Recommended Actions

1. **Use HTTPS Only**: Configure SSL/TLS certificate
2. **Set Secure Cookies**: Enable `SECURE_SSL_REDIRECT`
3. **Monitor Logs**: Watch for lockout patterns indicating attacks
4. **Backup 2FA Secrets**: Securely store encryption keys
5. **Regular Updates**: Keep dependencies updated

### Assumptions

- MongoDB Atlas is used for data storage
- Redis is available for Celery task queue
- SMTP email service is configured
- Customers use modern authenticator apps for 2FA

### Limitations

1. Rate limiting is IP-based; may affect shared networks
2. 2FA requires smartphone with authenticator app
3. Account recovery requires email access
4. Session tokens cannot be transferred between devices

---

## Summary

This authentication system provides multiple layers of security:

1. **Registration**: Email verification prevents fake accounts
2. **Login**: Lockout + throttling prevents brute force
3. **Sessions**: Token blacklisting ensures logout effectiveness
4. **2FA**: Optional but recommended second factor
5. **Single-device**: Automatic session management

For questions or issues, consult the development team.

---

## Section 2: ACCOUNTS_TESTING_GUIDE.md

### API Testing Guide for Insomnia

Complete guide to test all authentication endpoints in Insomnia.

---

## Setup

**Base URL:** `http://localhost:8000/api/auth`

**Headers (for authenticated requests):**
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

---

## Creating Test Users

Before testing the API, you need to create the appropriate user accounts:

### 1. Create Admin (CLI - Required First)
```bash
# Activate virtual environment first
source venv/bin/activate

# Interactive mode
python manage.py create_admin

# Or with all options (super admin)
python manage.py create_admin --username admin --email admin@system.com --password AdminPass123! --super-admin
```

### 2. Create Loan Officer (API - Requires Admin)
Use the Admin token to create loan officers via API:
```
POST /api/auth/admin/loan-officers/
```

### 3. Create Customer (Self-Registration)
Customers register themselves via:
```
POST /api/auth/signup/
```

---

## Customer Authentication

### 1. Sign Up

```
POST /api/auth/signup/
```

**Body:**
```json
{
    "first_name": "Juan",
    "last_name": "Dela Cruz",
    "email": "juan@example.com",
    "password": "SecurePass123!",
    "password_confirm": "SecurePass123!",
    "phone": "09171234567",
    "language": "tl"
}
```

**Response (201):**
```json
{
    "status": "success",
    "message": "Account created. Please verify your email.",
    "data": {
        "email": "juan@example.com"
    }
}
```

---

### 2. Verify Email (OTP)

```
POST /api/auth/verify-email/
```

**Body:**
```json
{
    "email": "juan@example.com",
    "otp": "123456"
}
```

**Response (200):**
```json
{
    "status": "success",
    "message": "Email verified successfully",
    "data": {
        "access_token": "eyJ...",
        "refresh_token": "eyJ..."
    }
}
```

---

### 3. Resend OTP

```
POST /api/auth/resend-otp/
```

**Body:**
```json
{
    "email": "juan@example.com"
}
```

---

### 4. Customer Login

```
POST /api/auth/login/
```

**Body:**
```json
{
    "email": "juan@example.com",
    "password": "SecurePass123!",
    "remember_me": true
}
```

**Response (200):**
```json
{
    "status": "success",
    "data": {
        "access_token": "eyJ...",
        "refresh_token": "eyJ...",
        "user": {
            "id": "...",
            "email": "juan@example.com",
            "full_name": "Juan Dela Cruz"
        }
    }
}
```

**Response (if 2FA enabled):**
```json
{
    "status": "success",
    "data": {
        "requires_2fa": true,
        "temp_token": "eyJ..."
    }
}
```

---

### 5. Refresh Token

```
POST /api/auth/refresh-token/
```

**Body:**
```json
{
    "refresh": "eyJ..."
}
```

---

### 6. Logout

```
POST /api/auth/logout/
```

**Body:**
```json
{
    "refresh_token": "eyJ..."
}
```

**Headers:**
```
Authorization: Bearer <access_token>
```

---

## Password Management

### 7. Forgot Password

```
POST /api/auth/forgot-password/
```

**Body:**
```json
{
    "email": "juan@example.com"
}
```

---

### 8. Verify Reset OTP

```
POST /api/auth/verify-reset-otp/
```

**Body:**
```json
{
    "email": "juan@example.com",
    "otp": "123456"
}
```

---

### 9. Reset Password

```
POST /api/auth/reset-password/
```

**Body:**
```json
{
    "email": "juan@example.com",
    "otp": "123456",
    "new_password": "NewSecurePass123!",
    "confirm_password": "NewSecurePass123!"
}
```

---

### 10. Change Password (Authenticated)

```
POST /api/auth/change-password/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "old_password": "SecurePass123!",
    "new_password": "NewSecurePass123!",
    "confirm_password": "NewSecurePass123!"
}
```

---

## Two-Factor Authentication (2FA)

### 11. Setup 2FA

```
POST /api/auth/2fa/setup/
```

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
    "status": "success",
    "data": {
        "secret": "JBSWY3DPEHPK3PXP",
        "qr_uri": "otpauth://totp/..."
    }
}
```

---

### 12. Confirm 2FA Setup

```
POST /api/auth/2fa/confirm/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "code": "123456"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "backup_codes": ["XXXX-XXXX", "YYYY-YYYY", ...]
    }
}
```

---

### 13. Verify 2FA (During Login)

```
POST /api/auth/2fa/verify/
```

**Body:**
```json
{
    "temp_token": "eyJ...",
    "code": "123456"
}
```

---

### 14. Disable 2FA

```
POST /api/auth/2fa/disable/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "password": "SecurePass123!"
}
```

---

### 15. Get 2FA Status

```
GET /api/auth/2fa/status/
```

**Headers:** `Authorization: Bearer <access_token>`

---

### 16. Regenerate Backup Codes

```
POST /api/auth/2fa/backup-codes/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "password": "SecurePass123!"
}
```

---

## Consent Management

### 17. Get Consent Status

```
GET /api/auth/consent/
```

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
    "status": "success",
    "data": {
        "data_consent": false,
        "ai_consent": false,
        "consent_date": null,
        "can_access_ai": false
    }
}
```

---

### 18. Record Consent

```
POST /api/auth/consent/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "data_consent": true,
    "ai_consent": true
}
```

---

### 19. Update Consent

```
PUT /api/auth/consent/
```

**Headers:** `Authorization: Bearer <access_token>`

**Body:**
```json
{
    "ai_consent": false
}
```

---















## Loan Officer Authentication

### 20. Loan Officer Login

```
POST /api/auth/loan-officer/login/
```

**Body:**
```json
{
    "email": "officer@bank.com",
    "password": "TempPassword123!",
    "remember_me": false
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "access_token": "eyJ...",
        "refresh_token": "eyJ...",
        "user": {
            "id": "...",
            "email": "officer@bank.com",
            "full_name": "Maria Santos",
            "department": "Loan Processing",
            "employee_id": "EMP001",
            "role": "loan_officer"
        },
        "must_change_password": true
    }
}
```

---

### 21. Loan Officer Logout

```
POST /api/auth/loan-officer/logout/
```

**Body:**
```json
{
    "refresh_token": "eyJ..."
}
```

---

## Admin Authentication

### 22. Admin Login

```
POST /api/auth/admin/login/
```

**Body:**
```json
{
    "username": "admin",
    "password": "AdminSecure123!"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "access_token": "eyJ...",
        "refresh_token": "eyJ...",
        "user": {
            "id": "...",
            "username": "admin",
            "email": "admin@system.com",
            "role": "admin",
            "permissions": ["*"],
            "super_admin": true
        }
    }
}
```

---

### 23. Admin Logout

```
POST /api/auth/admin/logout/
```

**Body:**
```json
{
    "refresh_token": "eyJ..."
}
```













---

## Admin - Loan Officer Management

### 24. List Loan Officers

```
GET /api/auth/admin/loan-officers/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

**Query Params (optional):**
- `active=true` (default) or `active=false`
- `department=Loan Processing`

---

### 25. Create Loan Officer

```
POST /api/auth/admin/loan-officers/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

**Body:**
```json
{
    "employee_id": "EMP001",
    "first_name": "Maria",
    "last_name": "Santos",
    "email": "maria.santos@bank.com",
    "phone": "09181234567",
    "department": "Loan Processing"
}
```

**Response (201):**
```json
{
    "status": "success",
    "message": "Loan officer created successfully",
    "data": {
        "loan_officer": {
            "id": "...",
            "employee_id": "EMP001",
            "email": "maria.santos@bank.com",
            "full_name": "Maria Santos",
            "department": "Loan Processing"
        },
        "temporary_password": "xK9#mP2$qL5!",
        "message": "Send this temporary password to the loan officer securely."
    }
}
```

---

### 26. Get Loan Officer Details

```
GET /api/auth/admin/loan-officers/<officer_id>/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

---

### 27. Update Loan Officer

```
PUT /api/auth/admin/loan-officers/<officer_id>/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

**Body:**
```json
{
    "department": "Risk Assessment",
    "active": true
}
```

---

### 28. Deactivate Loan Officer

```
DELETE /api/auth/admin/loan-officers/<officer_id>/
```

**Headers:** `Authorization: Bearer <admin_access_token>`

---

## Admin - Admin Management (Super Admin Only)

> ⚠️ These endpoints require **Super Admin** access. Regular admins cannot manage other admins.

### 29. List Admins

```
GET /api/auth/admin/admins/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

**Query Params (optional):**
- `active=true` (default) or `active=false`

---

### 30. Create Admin

```
POST /api/auth/admin/admins/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

**Body:**
```json
{
    "username": "newadmin",
    "email": "newadmin@system.com",
    "first_name": "New",
    "last_name": "Admin",
    "super_admin": false,
    "permissions": ["create_loan_officer", "view_logs"]
}
```

**Response (201):**
```json
{
    "status": "success",
    "message": "Admin created successfully",
    "data": {
        "admin": {
            "id": "...",
            "username": "newadmin",
            "email": "newadmin@system.com",
            "full_name": "New Admin",
            "super_admin": false,
            "permissions": ["create_loan_officer", "view_logs"]
        },
        "temporary_password": "xK9#mP2$qL5!",
        "message": "Send this temporary password to the admin securely."
    }
}
```

**Available Permissions:**
- `create_loan_officer` - Can create loan officer accounts
- `manage_loan_officers` - Can edit/deactivate loan officers
- `manage_users` - Can lock/unlock user accounts
- `view_analytics` - Can access analytics
- `view_logs` - Can access audit logs
- `manage_system` - Can modify system settings

---

### 31. Get Admin Details

```
GET /api/auth/admin/admins/<admin_id>/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

---

### 32. Update Admin

```
PUT /api/auth/admin/admins/<admin_id>/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

**Body:**
```json
{
    "first_name": "Updated",
    "last_name": "Name",
    "active": true
}
```

---

### 33. Update Admin Permissions

```
PUT /api/auth/admin/admins/<admin_id>/permissions/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

**Body (grant specific permissions):**
```json
{
    "permissions": ["create_loan_officer", "manage_loan_officers", "view_analytics"]
}
```

**Body (make super admin):**
```json
{
    "super_admin": true
}
```

---

### 34. Deactivate Admin

```
DELETE /api/auth/admin/admins/<admin_id>/
```

**Headers:** `Authorization: Bearer <super_admin_access_token>`

---

## Error Responses

### 400 Bad Request
```json
{
    "status": "error",
    "message": "Invalid request data",
    "errors": {
        "email": ["This field is required"]
    }
}
```

### 401 Unauthorized
```json
{
    "status": "error",
    "message": "Invalid credentials"
}
```

### 403 Forbidden (Locked Account)
```json
{
    "status": "error",
    "message": "Account is locked. Try again in 15 minutes."
}
```

### 403 Forbidden (Consent Required)
```json
{
    "status": "error",
    "code": "CONSENT_REQUIRED",
    "message": "AI consent is required to use this feature",
    "errors": {
        "action_required": {
            "endpoint": "/api/auth/consent/",
            "method": "POST",
            "required_fields": ["ai_consent"]
        }
    }
}
```

---

## Testing Flow

1. **Customer Flow:**
   - Sign up → Verify email → Login → Record consent → Use features

2. **Admin Flow:**
   - Admin login → Create loan officer → Note temporary password

3. **Loan Officer Flow:**
   - Login with temp password → Change password

---

## Section 3: SECURITY.md

### Security Features

> Security mechanisms implemented in MSME Pathways Backend

---

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY LAYERS                           │
├─────────────────────────────────────────────────────────────┤
│  Rate Limiting     →  Prevent brute-force attacks           │
│  Account Lockout   →  Block after failed attempts           │
│  2FA (TOTP)        →  Two-factor authentication             │
│  JWT Tokens        →  Secure session management             │
│  Security Headers  →  XSS, CSRF, clickjacking protection    │
│  Password Hashing  →  bcrypt with salting                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Rate Limiting (Throttling)

Request throttling prevents API abuse and brute-force attacks.

| Endpoint | Rate Limit | Rationale |
|----------|------------|-----------|
| Sign Up | 5/hour per IP | Prevent mass account creation |
| Login | 10/hour per IP | Prevent credential stuffing |
| OTP Verification | 5/hour per IP | Prevent OTP brute-forcing |
| OTP Resend | 3/hour per IP | Prevent email spam |
| 2FA Verification | 5/hour per IP | Prevent 2FA brute-forcing |
| Password Reset | 3/hour per IP | Prevent email enumeration |

### Implementation

```python
# accounts/utils/throttles.py
class SignUpRateThrottle(SimpleRateThrottle):
    rate = '5/hour'
    scope = 'signup'

class LoginRateThrottle(SimpleRateThrottle):
    rate = '10/hour'
    scope = 'login'
```

---

## Account Lockout Protection

Automatic account lockout after repeated failed login attempts.

| Parameter | Value |
|-----------|-------|
| Max Attempts | 5 |
| Lockout Duration | 15 minutes |
| Auto-Unlock | Yes |

### Implementation

```python
# accounts/services/lockout_service.py
class LockoutService:
    MAX_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)
    
    @staticmethod
    def record_failed_attempt(customer):
        customer.failed_login_attempts += 1
        if customer.failed_login_attempts >= LockoutService.MAX_ATTEMPTS:
            customer.locked_until = datetime.utcnow() + LockoutService.LOCKOUT_DURATION
```

---

## Two-Factor Authentication (2FA)

TOTP-based 2FA using authenticator apps (Google Authenticator, Authy).

| Feature | Implementation |
|---------|----------------|
| Secret Generation | `pyotp.random_base32()` |
| QR Code | URI format for authenticator apps |
| Backup Codes | 10 one-time codes per user |
| Code Validation | 30-second time window |

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/2fa/setup/` | Start 2FA setup |
| `POST` | `/api/auth/2fa/confirm/` | Confirm with first code |
| `POST` | `/api/auth/2fa/verify/` | Verify during login |
| `POST` | `/api/auth/2fa/disable/` | Disable 2FA |
| `POST` | `/api/auth/2fa/backup-codes/` | Regenerate backup codes |
| `GET` | `/api/auth/2fa/status/` | Check 2FA status |

---

## JWT Token Security

Access and refresh tokens for session management.

| Token Type | Lifetime | Purpose |
|------------|----------|---------|
| Access Token | 10 minutes | API authentication |
| Refresh Token | 24 hours (or 3 days with "remember me") | Get new access token |

### Security Features

- **Token Blacklisting** — Tokens invalidated on logout
- **Single Device** — New login invalidates previous sessions
- **Token Hashing** — SHA-256 hashing for stored tokens

---

## Security Headers Middleware

Custom middleware adds security headers to all responses.

```python
# config/middleware.py
class SecurityHeadersMiddleware:
    def __call__(self, request):
        response = self.get_response(request)
        
        # Prevent clickjacking
        response['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # XSS protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # HTTPS enforcement (production only)
        response['Strict-Transport-Security'] = 'max-age=31536000'
        
        # Content Security Policy
        response['Content-Security-Policy'] = "default-src 'self'; ..."
        
        # Referrer Policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        return response
```

---

## Password Security

- **Hashing Algorithm** — bcrypt with automatic salting
- **Minimum Requirements** — Django password validators
  - Minimum length
  - Common password rejection
  - Similarity to user attributes check
  - Numeric-only rejection

---

## Consent Enforcement

AI features require explicit user consent before access.

```python
# ai_assistant/views/chat_views.py
class ConsentRequiredMixin:
    def check_ai_consent(self, request):
        consent = Consent.find_by_user(customer_id, 'customer')
        if not consent or not consent.ai_consent:
            return False, error_response(
                message="AI consent is required",
                errors={'code': 'CONSENT_REQUIRED'},
                status_code=403
            )
        return True, consent
```

---

## Audit Logging

All security-relevant actions are logged to MongoDB.

| Action | Logged |
|--------|--------|
| User login | ✅ |
| Failed login attempts | ✅ |
| Password changes | ✅ |
| 2FA setup/disable | ✅ |
| Loan status changes | ✅ |
| Document uploads | ✅ |
| Admin actions | ✅ |

---

## Production Checklist

| Setting | Development | Production |
|---------|-------------|------------|
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | Test key | Strong random key |
| `ALLOWED_HOSTS` | `localhost` | Your domain |
| `SECURE_SSL_REDIRECT` | `False` | `True` |
| `SESSION_COOKIE_SECURE` | `False` | `True` |
| `CSRF_COOKIE_SECURE` | `False` | `True` |

---

## Related Documentation

- [Authentication](#section-1-authenticationmd) — Full auth flow documentation
- [Consent](#section-4-consentmd) — Consent management
- [Roles](#section-5-rolesmd) — User role permissions

---

## Section 4: CONSENT.md

### Consent Management Documentation

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

- [User Roles](#section-5-rolesmd) — Role-specific consent requirements
- [Authentication](#section-1-authenticationmd) — Auth flow integration

---

## Section 5: ROLES.md

### User Roles Documentation

> Role-based access control for MSME Pathways: Smart Loan Support for the Informal Sector

---

## Overview

The system supports three distinct user roles, each with specific capabilities and access levels:

```
┌─────────────────────────────────────────────────────────────┐
│                    USER ROLES                                │
├─────────────────────────────────────────────────────────────┤
│  MSME Customer   →  Mobile App / Kiosk                      │
│  Loan Officer    →  Web Dashboard                           │
│  System Admin    →  Admin Console                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. MSME Customer

**Target Users:** Sari-sari store owners, market vendors, home-based sellers, informal sector microentrepreneurs

### Capabilities
| Feature | Access |
|---------|--------|
| Register/Login | ✅ Self-registration with email verification |
| AI Financial Assistant | ✅ After consent |
| Loan Education | ✅ After consent |
| Document Upload | ✅ For loan pre-qualification |
| Loan Recommendations | ✅ View AI-generated recommendations |
| 2FA Setup | ✅ Optional |

### Registration Flow
1. Customer signs up via mobile app or kiosk
2. Email OTP verification required
3. Consent collection (data + AI) required before AI features
4. Profile completion for loan pre-qualification

### API Prefix
```
/api/auth/signup/
/api/auth/login/
/api/auth/consent/
```

---

## 2. Loan Officer

**Target Users:** Bank/microfinance institution loan processing staff

### Capabilities
| Feature | Access |
|---------|--------|
| Register | ❌ Admin-created only |
| Login | ✅ Email + password |
| Review Dashboard | ✅ View customer applications |
| Approve/Reject Loans | ✅ Process loan decisions |
| Customer Profiles | ✅ View customer data (with consent) |
| Analytics | ✅ View loan metrics |
| 2FA Setup | ✅ Optional |

### Account Management
- Loan officer accounts are **created by System Admins only**
- Officers receive credentials via secure email
- Password change required on first login

### API Prefix
```
/api/auth/loan-officer/login/
/api/auth/loan-officer/logout/
```

---

## 3. System Admin

**Target Users:** IT administrators, system managers

### Admin Types

| Type | Description | Permissions |
|------|-------------|-------------|
| **Admin** | Regular administrator | Only has specifically assigned permissions |
| **Super Admin** | Full system administrator | Has ALL permissions automatically |

> **When to use which?**
> - Use **Super Admin** for the primary system administrator
> - Use **Admin** with specific permissions for limited access (e.g., an admin who can only view logs)

### Available Permissions

```
create_loan_officer   → Can create new loan officer accounts
manage_loan_officers  → Can edit/deactivate loan officers
manage_users          → Can lock/unlock any user account
view_analytics        → Can access system-wide analytics
view_logs             → Can access audit logs
manage_system         → Can modify system configurations
```

### Capabilities
| Feature | Admin | Super Admin |
|---------|-------|-------------|
| Login | ✅ Username + password | ✅ Username + password |
| Create Loan Officers | ⚠️ Requires permission | ✅ Always |
| View System Logs | ⚠️ Requires permission | ✅ Always |
| Manage Configurations | ⚠️ Requires permission | ✅ Always |
| View Analytics | ⚠️ Requires permission | ✅ Always |
| User Management | ⚠️ Requires permission | ✅ Always |

### API Prefix
```
/api/auth/admin/login/
/api/auth/admin/logout/
/api/auth/admin/loan-officers/
```

---

## How to Create Users

### Customers
Customers **self-register** via the mobile app or kiosk:
```
POST /api/auth/signup/
```

### Loan Officers
Loan officers are **created by admins only**:
```
POST /api/auth/admin/loan-officers/
```
- Requires admin authentication
- Returns a temporary password for the new loan officer
- Loan officer must change password on first login

### Admins
Admins are **created via CLI command only** (no API endpoint):
```bash
# Interactive mode
python manage.py create_admin

# With options
python manage.py create_admin --username admin --email admin@system.com --password YourPass123! --super-admin
```

| Option | Description |
|--------|-------------|
| `--username` | Admin username |
| `--email` | Admin email |
| `--password` | Admin password |
| `--first-name` | First name (optional) |
| `--last-name` | Last name (optional) |
| `--super-admin` | Grant all permissions |
| `--noinput` | Non-interactive mode |

---

## Role Comparison Matrix

| Feature | Customer | Loan Officer | Admin |
|---------|----------|--------------|-------|
| Self-Registration | ✅ | ❌ | ❌ |
| Email Verification | ✅ | ✅ | ❌ |
| 2FA Support | ✅ | ✅ | ✅ |
| Consent Required | ✅ | ✅ | ❌ |
| AI Features | ✅ | ❌ | ❌ |
| Loan Processing | ❌ | ✅ | ❌ |
| User Management | ❌ | ❌ | ✅ |
| System Config | ❌ | ❌ | ✅ |

---

## Authentication Architecture

```
                    ┌─────────────────┐
                    │   API Gateway   │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Customer Auth   │ │ Loan Officer    │ │ Admin Auth      │
│ /api/auth/      │ │ Auth            │ │ /api/auth/admin │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Customer Model  │ │ LoanOfficer     │ │ Admin Model     │
│                 │ │ Model           │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## Security Considerations

1. **Role Isolation**: Each role has separate authentication endpoints
2. **Token Claims**: JWT tokens include `role` claim for authorization
3. **Consent Enforcement**: Customer AI access blocked until consent given
4. **Audit Logging**: All role-based actions are logged for compliance

---

## Related Documentation

- [Authentication System](#section-1-authenticationmd) — Detailed auth flows
- [Consent Management](#section-4-consentmd) — Consent collection and enforcement
