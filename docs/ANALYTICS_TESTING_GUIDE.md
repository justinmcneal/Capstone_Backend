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
