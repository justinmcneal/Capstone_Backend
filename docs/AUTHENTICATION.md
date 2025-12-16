# Customer Authentication System Documentation

> A comprehensive guide to the authentication and security mechanisms implemented in the Capstone Backend.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication Flow](#authentication-flow)
3. [Security Mechanisms](#security-mechanisms)
4. [API Endpoints](#api-endpoints)
5. [Production Best Practices](#production-best-practices)

---

## Overview

This authentication system provides enterprise-grade security for customer accounts, featuring:

- **Email-verified registration** with OTP confirmation
- **Secure login** with rate limiting and account lockout
- **Two-Factor Authentication (2FA)** using TOTP (Time-based One-Time Password)
- **Token-based sessions** with automatic invalidation
- **Production-ready throttling** to prevent abuse

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
