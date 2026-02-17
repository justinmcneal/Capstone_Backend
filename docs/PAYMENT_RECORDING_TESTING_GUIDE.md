# Loan Payment Recording Testing Guide

## Overview

Record customer payments against repayment schedules.

---

## Endpoints

### 1. Record Payment (Officer)
```
POST /api/loans/officer/payments/
Authorization: Bearer <officer_token>
Content-Type: application/json

{
    "loan_id": "abc123",
    "installment_number": 1,
    "amount": 2500,
    "payment_method": "cash",
    "reference": "REC-2026-001"
}
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "payment_id": "xyz789",
        "loan_id": "abc123",
        "installment_number": 1,
        "amount": 2500,
        "installment_status": "paid",
        "remaining_balance": 27000
    },
    "message": "Payment recorded successfully"
}
```

---

### 2. View Payment History (Customer)
```
GET /api/loans/applications/<id>/payments/
Authorization: Bearer <customer_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "payments": [
            {
                "id": "xyz789",
                "amount": 2500,
                "installment_number": 1,
                "payment_method": "cash",
                "reference": "REC-2026-001",
                "recorded_at": "2026-01-12T08:50:00Z"
            }
        ],
        "total_paid": 2500,
        "count": 1
    }
}
```

---

## Payment Methods

- `cash`
- `bank_transfer`
- `gcash`
- `maya`
- `other`

---

## Auto-Update Schedule

When payment recorded:
- Full payment → installment status = `paid`
- Partial payment → installment status = `partial`
