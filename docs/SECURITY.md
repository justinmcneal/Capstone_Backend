# Security Features

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

- [Authentication](./AUTHENTICATION.md) — Full auth flow documentation
- [Consent](./CONSENT.md) — Consent management
- [Roles](./ROLES.md) — User role permissions
