# Background Tasks (Celery)

> Automated background jobs using Celery and Redis

---

## Overview

The system uses Celery for asynchronous task execution with Redis as the message broker.

```
┌─────────────────────────────────────────────────────────────┐
│                    CELERY ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────┤
│  Django App  →  Redis Queue  →  Celery Worker  →  Task      │
└─────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Environment Variables

```env
# Redis (Celery broker)
REDIS_URL=redis://localhost:6379/0

# Or use separate settings
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### Celery Config

Located in `config/celery.py`:

```python
from celery import Celery
from celery.schedules import crontab

app = Celery('capstone_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

---

## Scheduled Tasks (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| `cleanup_unverified_accounts_task` | Every 30 minutes | Deletes unverified accounts older than 12 hours |

### Task Definition

```python
# accounts/tasks.py
@shared_task
def cleanup_unverified_accounts_task():
    """
    Deletes customer accounts that haven't been verified within 12 hours.
    This prevents database bloat from abandoned signups.
    """
    hours = 12
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    
    unverified_customers = Customer.find({
        'verified': False,
        'created_at': {'$lte': cutoff_time}
    })
    
    for customer in unverified_customers:
        customer.delete()
```

---

## Running Celery

### Development

```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Celery Worker
celery -A config.celery worker -l info

# Terminal 3: Start Celery Beat (scheduler)
celery -A config.celery beat -l info
```

### Production

Use a process manager like Supervisor or systemd:

```bash
# Worker
celery -A config.celery worker --loglevel=info --concurrency=2

# Beat
celery -A config.celery beat --loglevel=info
```

---

## Planned Tasks (Not Yet Implemented)

| Task | Purpose | Priority |
|------|---------|----------|
| `check_overdue_installments` | Mark installments as overdue | High |
| `send_payment_reminders` | Email upcoming payment reminders | Medium |
| `sync_blockchain_events` | Sync Django with smart contract events | Medium |
| `generate_daily_reports` | Admin analytics reports | Low |

---

## Adding New Tasks

1. Create task in appropriate module:

```python
# loans/tasks.py
from celery import shared_task

@shared_task
def check_overdue_installments_task():
    """Mark overdue installments"""
    # Implementation
```

2. Add to beat schedule in `config/celery.py`:

```python
app.conf.beat_schedule = {
    'check-overdue-daily': {
        'task': 'loans.tasks.check_overdue_installments_task',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight
    },
}
```

---

## Monitoring

### Check Task Status

```python
from celery.result import AsyncResult

result = AsyncResult(task_id)
print(result.status)  # PENDING, STARTED, SUCCESS, FAILURE
print(result.result)  # Task return value
```

### Flower (Optional)

Install Flower for web-based monitoring:

```bash
pip install flower
celery -A config.celery flower --port=5555
```

---

## Related Documentation

- [Django Settings](../config/settings.py) — Celery configuration
- [Accounts Tasks](../accounts/tasks.py) — Cleanup task implementation
