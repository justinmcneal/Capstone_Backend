# Repayment Schedule Testing Guide

## Overview

View payment schedule for disbursed loans.

---

## How It Works

1. Loan officer disburses loan → Schedule auto-generated
2. Customer views schedule via API

---

## Customer Endpoint

```
GET /api/loans/applications/<id>/schedule/
Authorization: Bearer <customer_token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "loan_id": "abc123",
        "principal": 25000,
        "interest_rate": 0.015,
        "term_months": 12,
        "monthly_payment": 2458.33,
        "total_amount": 29500,
        "total_interest": 4500,
        "paid_count": 0,
        "remaining_balance": 29500,
        "next_payment": {
            "number": 1,
            "due_date": "2026-02-12",
            "total_amount": 2458.33
        },
        "installments": [
            {
                "number": 1,
                "due_date": "2026-02-12",
                "principal": 2083.33,
                "interest": 375.00,
                "total_amount": 2458.33,
                "status": "pending"
            }
        ]
    }
}
```

---

## Calculation

**Simple Interest:**
- Monthly Interest = Principal × Interest Rate
- Monthly Payment = (Principal / Term) + Monthly Interest
- Total = Principal + (Monthly Interest × Term)

**Example (₱25,000 at 1.5%/month for 12 months):**
- Monthly Interest: ₱25,000 × 0.015 = ₱375
- Monthly Principal: ₱25,000 / 12 = ₱2,083.33
- Monthly Payment: ₱2,458.33
- Total Interest: ₱4,500
- Total: ₱29,500

---

## Validation

- Only disbursed loans have schedules
- Customer can only view their own schedules
