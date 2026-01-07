# Notifications API Testing Guide

## Overview

Email notifications are sent automatically on loan events. No manual API calls needed.

---

## Automatic Email Triggers

| Event | When | Email Sent To |
|-------|------|---------------|
| Loan Approved | Officer approves loan | Customer |
| Loan Rejected | Officer rejects loan | Customer |

---

## Testing

### 1. Configure Email (Already in `.env`)
```
EMAIL_HOST_USER=sorianoeligabriel@gmail.com
EMAIL_HOST_PASSWORD=exsl ffan ntwx aprv
```

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
