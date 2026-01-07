# Officer Assignment Testing Guide

## Overview

Assign loan applications to officers for review.

---

## Endpoints

### 1. Manual Assignment (Admin)
```
POST /api/loans/admin/applications/<id>/assign/
Authorization: Bearer <admin_token>
Content-Type: application/json

{
    "officer_id": "<officer_id>"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "application_id": "abc123",
        "assigned_officer": "def456",
        "officer_name": "John Doe",
        "status": "under_review"
    },
    "message": "Application assigned successfully"
}
```

---

### 2. View Officer Workloads (Admin)
```
GET /api/loans/admin/officers/workload/
Authorization: Bearer <admin_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "officers": [
            {
                "id": "def456",
                "employee_id": "EMP001",
                "name": "John Doe",
                "pending_count": 5,
                "active": true
            }
        ],
        "total": 1
    }
}
```

---

## Auto-Assignment

On loan submission, applications are automatically assigned to the officer with fewest pending applications. Officer receives email notification.
