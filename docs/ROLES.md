# User Roles Documentation

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

- [Authentication System](./AUTHENTICATION.md) — Detailed auth flows
- [Consent Management](./CONSENT.md) — Consent collection and enforcement
