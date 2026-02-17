# API Testing Guide for Insomnia

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
