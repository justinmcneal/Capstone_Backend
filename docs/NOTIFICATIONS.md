# Email Notification Service

## Overview

Email notifications for loan lifecycle events using Gmail SMTP.

---

## Notification Types

| Type | Trigger | Recipient | Template |
|------|---------|-----------|----------|
| `loan_submitted` | Customer submits application | Customer | `loan_submitted.html` |
| `loan_approved` | Officer approves application | Customer | `loan_approved.html` |
| `loan_rejected` | Officer rejects application | Customer | `loan_rejected.html` |
| `loan_disbursed` | Officer disburses funds | Customer | `loan_disbursed.html` |
| `payment_received` | Payment recorded | Customer | `payment_received.html` |
| `document_flagged` | Re-upload requested | Customer | `document_flagged.html` |
| `new_application` | Application assigned | Loan Officer | `new_application.html` |

---

## Configuration

Set these in your `.env` file:

```env
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

> **Security Note:** Never commit real credentials. Use app-specific passwords for Gmail.

---

## Email Templates

Located in `notifications/templates/email/`:

| Template | Description |
|----------|-------------|
| `loan_submitted.html/.txt` | Confirmation of submission |
| `loan_approved.html/.txt` | Approval notification |
| `loan_rejected.html/.txt` | Rejection with reason |
| `loan_disbursed.html/.txt` | Disbursement confirmation |
| `payment_received.html/.txt` | Payment acknowledgment |
| `document_flagged.html/.txt` | Re-upload request |
| `new_application.html/.txt` | Officer assignment alert |

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

Emails are sent automatically at these events:

| Event | Trigger Location | Email Sent To |
|-------|------------------|---------------|
| Loan Application Submitted | `loans/views/customer_views.py` | Customer |
| Loan Approved | `loans/views/officer_views.py` | Customer |
| Loan Rejected | `loans/views/officer_views.py` | Customer |
| Loan Disbursed | `loans/views/officer_views.py` | Customer |
| Payment Recorded | `loans/views/officer_views.py` | Customer |
| Document Re-upload Requested | `documents/views/document_views.py` | Customer |
| Application Assigned (auto) | `loans/services/assignment.py` | Loan Officer |
| Application Assigned (manual) | `loans/services/assignment.py` | Loan Officer |

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
