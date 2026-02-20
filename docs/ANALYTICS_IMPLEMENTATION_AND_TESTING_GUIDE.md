# Analytics Implementation and Testing Guide

Merged documentation for analytics endpoints, audit logs, and role-based testing flow.

## Wave

- Wave: 5
- Status: Done

## Navigation

1. [Analytics & Audit Logs](#section-1-analyticsmd)
2. [Analytics API Testing Guide](#section-2-analytics_testing_guidemd)

## Source Files

1. `ANALYTICS.md`
2. `ANALYTICS_TESTING_GUIDE.md`

---

## Section 1: ANALYTICS.md

# Analytics & Audit Logs

## Overview

Role-specific dashboards and action tracking for all user types.

---

## Endpoints

| Endpoint | Role | Description |
|----------|------|-------------|
| `GET /api/analytics/admin/` | Admin | System-wide stats |
| `GET /api/analytics/officer/` | Loan Officer | Review activity |
| `GET /api/analytics/customer/` | Customer | Personal stats |
| `GET /api/analytics/audit-logs/` | Admin | Action history |

---

## Admin Dashboard Response

```json
{
    "users": {
        "customers": 150,
        "loan_officers": 5,
        "admins": 2,
        "total": 157
    },
    "loans": {
        "total": 45,
        "pending": 12,
        "approved": 28,
        "rejected": 5
    },
    "documents": {
        "total": 200,
        "verified": 150
    },
    "products": [
        {"name": "Micro Loan", "applications": 30, "approved": 25}
    ]
}
```

---

## Loan Officer Dashboard Response

```json
{
    "my_reviews": {
        "total_approved": 28,
        "total_rejected": 5,
        "approved_today": 3
    },
    "queue": {
        "pending_total": 12,
        "assigned_to_me": 4
    },
    "performance": {
        "approval_rate": "84.8%"
    }
}
```

---

## Customer Dashboard Response

```json
{
    "applications": {
        "total": 2,
        "approved": 1,
        "pending": 1
    },
    "documents": {
        "total": 4,
        "verified": 3
    },
    "profile_completion": {
        "percentage": "75%",
        "personal_profile": true,
        "business_profile": true,
        "valid_id_uploaded": true
    }
}
```

---

## Audit Logs

Tracked actions:
- User login
- Loan submitted/approved/rejected
- Document uploaded
- Profile updated

---

## Section 2: ANALYTICS_TESTING_GUIDE.md

# Analytics API Testing Guide

## Base URL
`http://localhost:8000/api/analytics`

---

## Endpoints by Role

### 1. Admin Dashboard
```
GET /api/analytics/admin/
Authorization: Bearer <admin_access_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "users": {
            "customers": 150,
            "loan_officers": 5,
            "admins": 2
        },
        "loans": {
            "total": 45,
            "pending": 12,
            "approved": 28,
            "rejected": 5
        },
        "documents": {
            "total": 200,
            "verified": 150
        }
    }
}
```

---

### 2. Audit Logs (Admin Only)
```
GET /api/analytics/audit-logs/
GET /api/analytics/audit-logs/?limit=100
GET /api/analytics/audit-logs/?action=loan_approved
Authorization: Bearer <admin_access_token>
```

---

### 3. Loan Officer Dashboard
```
GET /api/analytics/officer/
Authorization: Bearer <loan_officer_access_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "my_reviews": {
            "total_approved": 28,
            "approved_today": 3
        },
        "queue": {
            "pending_total": 12,
            "assigned_to_me": 4
        },
        "performance": {
            "approval_rate": "84.8%"
        }
    }
}
```

---

### 4. Customer Dashboard
```
GET /api/analytics/customer/
Authorization: Bearer <customer_access_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "applications": {
            "total": 2,
            "approved": 1
        },
        "documents": {
            "total": 4,
            "verified": 3
        },
        "profile_completion": {
            "percentage": "75%"
        }
    }
}
```

---

## Testing Flow

1. Login as Admin → Call `/api/analytics/admin/`
2. Login as Loan Officer → Call `/api/analytics/officer/`
3. Login as Customer → Call `/api/analytics/customer/`

## cURL Example

```bash
# Admin Dashboard
curl -X GET http://localhost:8000/api/analytics/admin/ \
  -H "Authorization: Bearer <admin_token>"
```
