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
