# Email Notification Service

## Overview

Email notifications for loan lifecycle events using Gmail SMTP.

---

## Notification Types

| Type | Trigger | Recipient |
|------|---------|-----------|
| `loan_submitted` | Application created | Customer |
| `loan_approved` | Officer approves | Customer |
| `loan_rejected` | Officer rejects | Customer |
| `document_flagged` | AI detects issues | Customer |
| `new_application` | Application created | Loan Officer |

---

## Configuration

Already in your `.env`:

```
EMAIL_HOST_USER=sorianoeligabriel@gmail.com
EMAIL_HOST_PASSWORD=exsl ffan ntwx aprv
DEFAULT_FROM_EMAIL=sorianoeligabriel@gmail.com
```

---

## Email Templates

Located in `notifications/templates/email/`:

| Template | Description |
|----------|-------------|
| `loan_submitted.html/.txt` | Confirmation |
| `loan_approved.html/.txt` | Approval celebration |
| `loan_rejected.html/.txt` | Rejection with reason |
| `document_flagged.html/.txt` | Quality issues |
| `new_application.html/.txt` | Officer alert |

---

## Usage

```python
from notifications.services import get_email_sender

sender = get_email_sender()

# Send approval email
sender.send_loan_approved(
    customer_email="customer@example.com",
    customer_name="Juan Dela Cruz",
    loan_id="abc123",
    approved_amount=25000
)
```

---

## Automatic Triggers

Emails are sent automatically when:
1. **Loan Approved** → Customer gets approval email
2. **Loan Rejected** → Customer gets rejection email

---

## Testing

```bash
# Start Django server
python manage.py runserver

# Approve a loan via API (email will be sent)
PUT /api/loans/officer/applications/<id>/review/
{
    "action": "approve",
    "approved_amount": 20000
}
```
