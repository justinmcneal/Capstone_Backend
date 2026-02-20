# Notifications Implementation and Testing Guide

Merged documentation for notification service behavior and API testing flow.

## Wave

- Wave: 4
- Status: Done

## Navigation

1. [Email Notification Service](#section-1-notificationsmd)
2. [Notifications API Testing Guide](#section-2-notifications_testing_guidemd)

## Source Files

1. `NOTIFICATIONS.md`
2. `NOTIFICATIONS_TESTING_GUIDE.md`

---

## Section 1: NOTIFICATIONS.md

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

---

## Section 2: NOTIFICATIONS_TESTING_GUIDE.md

# Notifications API Testing Guide

## Overview

Email notifications are sent automatically on loan events. No manual API calls needed.

---

## Automatic Email Triggers

| Event | When | Email Sent To |
|-------|------|---------------|
| Loan Submitted | Customer submits application | Customer |
| Loan Approved | Officer approves loan | Customer |
| Loan Rejected | Officer rejects loan | Customer |
| Loan Disbursed | Officer disburses funds | Customer |
| Payment Received | Payment recorded | Customer |
| Document Flagged | Re-upload requested | Customer |
| New Application | Application assigned | Loan Officer |

---

## Testing

### 1. Configure Email in `.env`

```env
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

> **Security Note:** Use app-specific passwords for Gmail. Never commit real credentials.

### 2. Start Server
```bash
python manage.py runserver
```

### 3. Approve a Loan
```bash
# Login as loan officer, then:
curl -X PUT http://localhost:8000/api/loans/officer/applications/<app_id>/review/ \
  -H "Authorization: Bearer <officer_token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve", "approved_amount": 20000}'
```

### 4. Check Customer Email
The customer should receive an approval email.

---

## Manual Email Test (Optional)

```python
# Django shell
python manage.py shell

from notifications.services import get_email_sender
sender = get_email_sender()
sender.send_loan_approved(
    customer_email="test@example.com",
    customer_name="Test User",
    loan_id="test123",
    approved_amount=25000
)
```

---

## Notification Log

Sent notifications are stored in MongoDB `notifications` collection:
```json
{
    "recipient_email": "customer@example.com",
    "notification_type": "loan_approved",
    "status": "sent",
    "sent_at": "2026-01-07T10:00:00Z"
}
```
