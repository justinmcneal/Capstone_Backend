# Loan Disbursement Testing Guide

## Overview

Mark approved loans as disbursed and notify customers.

---

## Endpoint

```
POST /api/loans/officer/applications/<id>/disburse/
Authorization: Bearer <officer_token>
Content-Type: application/json

{
    "amount": 25000,
    "method": "bank_transfer",
    "reference": "TXN-2026-001234"
}
```

---

## Request Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `amount` | No | approved_amount | Disbursed amount |
| `method` | No | bank_transfer | Method: bank_transfer, cash, etc. |
| `reference` | **Yes** | - | Transaction reference number |

---

## Response

```json
{
    "status": "success",
    "data": {
        "id": "abc123",
        "status": "disbursed",
        "disbursed_amount": 25000,
        "disbursement_method": "bank_transfer",
        "disbursement_reference": "TXN-2026-001234",
        "disbursed_at": "2026-01-07T11:18:00Z"
    },
    "message": "Loan disbursed successfully"
}
```

---

## Validation

- Only **approved** loans can be disbursed
- `reference` is required
- Officer/Admin authentication required

---

## Email Notification

Customer receives email with:
- Disbursed amount
- Disbursement method
- Reference number
