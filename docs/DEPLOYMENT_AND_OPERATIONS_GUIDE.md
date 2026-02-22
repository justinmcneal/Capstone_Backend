# Deployment and Operations Guide

Merged documentation for deployment, MongoDB Atlas setup, and background task operations.

## Wave

- Wave: 7
- Status: Done

## Navigation

1. [MSME Pathways - Deployment Guide](#section-1-deployment_guidemd)
2. [MongoDB Atlas Setup Guide](#section-2-mongodb_atlas_setupmd)
3. [Background Tasks (Celery)](#section-3-background_tasksmd)

## Source Files

1. `DEPLOYMENT_GUIDE.md`
2. `MONGODB_ATLAS_SETUP.md`
3. `BACKGROUND_TASKS.md`

---

## Section 1: DEPLOYMENT_GUIDE.md

# MSME Pathways - Deployment Guide

> **Last Updated:** February 18, 2026

---

## Current State

| Component | Location | Status |
|-----------|----------|--------|
| MongoDB | Atlas Cloud | ✅ Deployed |
| Django Backend | localhost:8000 | ❌ Not deployed |
| LLM (Groq) | Cloud API | ✅ Available |
| CNN Model | Inside Django | ⚠️ Needs training data |

---

## Deployment Architecture

```
┌────────────────────────────────────────────────┐
│              Railway (Free Tier)               │
│  ┌──────────────────────────────────────────┐  │
│  │              Django Backend              │  │
│  │  ┌─────────────┐    ┌─────────────────┐  │  │
│  │  │  REST API   │    │  CNN (14MB)     │  │  │
│  │  │  59 endpoints│    │  Runs on CPU    │  │  │
│  │  └─────────────┘    └─────────────────┘  │  │
│  └──────────────────────────────────────────┘  │
│                      ↓                         │
│              Groq API (LLM)                    │
│              MongoDB Atlas                     │
└────────────────────────────────────────────────┘

Frontend: Vercel (Web) + Expo (Mobile)
```

**Key Point:** CNN runs INSIDE Django, not separately!

---

## What You Need to Deploy

### 1. Backend (Railway - Free)
- Django REST API
- CNN model (included, 14MB)
- $0/month (500 hrs free)

### 2. LLM (Groq - Free)
- Uses Groq Cloud API (already integrated)
- 14,400 requests/day free
- $0/month

### 3. Database (Already Done)
- MongoDB Atlas M0
- $0/month

### 4. Frontend (Vercel + Expo - Free)
- Web: Vercel
- Mobile: Expo EAS
- $0/month

**Total: $0/month**

---

## Environment Variables for Production

This is the canonical backend deployment set for Railway.

```env
# Core Django
DEBUG=False
SECRET_KEY=<generate-strong-random-key>
SECRET_PEPPER=<generate-64-char-hex-pepper>
ALLOWED_HOSTS=your-app.railway.app

# Database
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
MONGODB_NAME=capstone_db

# Frontend origin + CSRF trust
CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app
CSRF_TRUSTED_ORIGINS=https://your-frontend.vercel.app

# Cookie/session security
# Use SameSite=None when frontend/backend are on different top-level domains
AUTH_COOKIE_HTTPONLY=True
AUTH_COOKIE_SECURE=True
AUTH_COOKIE_SAMESITE=None
AUTH_COOKIE_PATH=/
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_HTTPONLY=False
CSRF_COOKIE_SECURE=True
CSRF_COOKIE_SAMESITE=None

# HTTPS hardening
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# AI (Groq)
GROQ_API_KEY=<your-groq-api-key>
GROQ_MODEL=llama-3.1-8b-instant
GROQ_CHAT_MODEL=llama-3.1-8b-instant
GROQ_QUALIFICATION_MODEL=llama-3.1-8b-instant

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<your-email@gmail.com>
EMAIL_HOST_PASSWORD=<your-app-password>
DEFAULT_FROM_EMAIL=<your-email@gmail.com>
EMAIL_TIMEOUT=10

# Document processing behavior
DOCUMENT_UPLOAD_AI_ANALYSIS=True
DOCUMENT_UPLOAD_NOTIFY_REVIEWERS=True
DOCUMENT_UPLOAD_NOTIFY_ASYNC=True
DOCUMENT_TYPE_CONFIDENCE_THRESHOLD=0.75
DOCUMENT_ENFORCE_TYPE_MATCH=True
DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION=True

# Celery (optional)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### Frontend Environment Variable (Web)

Set in frontend deployment (Vercel):

```env
VITE_API_URL=https://your-app.railway.app
```

---

## Document Storage Status (Important)

Current backend implementation supports `local` storage only.

- `DOCUMENT_STORAGE_BACKEND` is currently hardcoded to `local` in settings.
- `S3StorageBackend` and `GCSStorageBackend` are scaffolded but not implemented.
- `DOCUMENT_STORAGE_BACKEND=s3` is not active yet in runtime code.

Practical production note:
- Railway filesystem is ephemeral; uploaded files may not persist across redeploys/restarts.
- If you need durable storage in production, implement and test S3 backend first, then switch.

### Planned S3 Migration (Future Work)

1. Implement `S3StorageBackend` in `documents/storage/backends.py`.
2. Add S3 env vars and IAM policy.
3. Validate upload/read/delete end-to-end in staging.
4. Migrate existing local files to S3.
5. Roll out to production.

---

## Step-by-Step Deployment

### Step 1: Switch LLM to Groq
```python
# Get free API key at: https://console.groq.com
# Set GROQ_API_KEY in .env
```

### Step 2: Train CNN (Optional)
```bash
# Add training images to documents/ml/training_data/
python manage.py train_document_classifier
```

### Step 3: Prepare Production Environment Variables
```bash
# Use the canonical env block above
# Confirm CORS_ALLOWED_ORIGINS and CSRF_TRUSTED_ORIGINS
# Confirm cookie security values for cross-site deployment
```

### Step 4: Deploy to Railway
```bash
# Push to GitHub, connect Railway
# Set environment variables
# Done!
```

### Step 5: Deploy Frontend
```bash
# Web: Connect Vercel to GitHub
# Mobile: expo build:android / expo build:ios
```

### Step 6: (Optional) Implement S3 Before Durable File Rollout
```bash
# Implement S3 backend in documents/storage/backends.py
# Test in staging
# Migrate existing files
```

---

## CNN Clarification

| Myth | Reality |
|------|---------|
| CNN needs separate server | ❌ Runs inside Django |
| CNN needs GPU | ❌ CPU works fine (14MB model) |
| CNN is expensive | ❌ $0 - included in backend |
| CNN needs training from scratch | ❌ Uses pre-trained MobileNetV2 |

The CNN only needs:
1. Training data (images)
2. Run `python manage.py train_document_classifier`
3. Auto-loads when Django starts

---

## Cost Summary

| Service | Free Tier | You Pay |
|---------|-----------|---------|
| Railway | 500 hrs/mo | $0 |
| Groq | 14K req/day | $0 |
| MongoDB Atlas | M0 tier | $0 |
| Vercel | Unlimited | $0 |
| Expo | Free builds | $0 |
| **Total** | | **$0/month** |

---

## Section 2: MONGODB_ATLAS_SETUP.md

# MongoDB Atlas Setup Guide

Complete beginner guide to set up MongoDB Atlas for the Capstone Backend.

---

## Step 1: Create MongoDB Atlas Account

1. Go to [https://www.mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas)
2. Click **"Try Free"** or **"Start Free"**
3. Sign up with email or Google account
4. Verify your email if required

---

## Step 2: Create a New Cluster (Free Tier)

1. After login, click **"Build a Database"**
2. Choose **"M0 FREE"** (Shared, Free Forever)
3. Select your preferred cloud provider:
   - **AWS** (recommended)
   - Google Cloud
   - Azure
4. Choose a region closest to you (e.g., `Singapore` for Philippines)
5. Name your cluster (e.g., `CapstoneCluster`)
6. Click **"Create"**

> ⏳ Wait 1-3 minutes for cluster to be created

---

## Step 3: Create Database User

1. In the left sidebar, click **"Database Access"**
2. Click **"Add New Database User"**
3. Choose **"Password"** authentication
4. Enter credentials:
   - **Username:** `capstone_admin` (or your choice)
   - **Password:** Click **"Autogenerate Secure Password"** and **COPY IT**
5. Under **"Database User Privileges"**, select:
   - **"Read and write to any database"**
6. Click **"Add User"**

> ⚠️ **IMPORTANT:** Save your password! You won't see it again.

---

## Step 4: Whitelist Your IP Address

1. In the left sidebar, click **"Network Access"**
2. Click **"Add IP Address"**
3. Choose one of these options:

   **Option A - For Development (Recommended):**
   - Click **"Allow Access from Anywhere"**
   - This adds `0.0.0.0/0` (allows all IPs)
   
   **Option B - For Production:**
   - Click **"Add Current IP Address"**
   - Your current IP will be added

4. Click **"Confirm"**

> ⏳ Wait 1-2 minutes for changes to take effect

---

## Step 5: Get Your Connection String

1. In the left sidebar, click **"Database"**
2. Find your cluster and click **"Connect"**
3. Choose **"Connect your application"**
4. Select:
   - **Driver:** Python
   - **Version:** 3.12 or later
5. Copy the connection string. It looks like:

```
mongodb+srv://<username>:<password>@capstonecluster.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

---

## Step 6: Update Your .env File

Open your `.env` file and update the MongoDB settings:

```env
# MongoDB Atlas Configuration
MONGODB_URI=mongodb+srv://capstone_admin:YOUR_PASSWORD_HERE@capstonecluster.xxxxx.mongodb.net/?retryWrites=true&w=majority&appName=CapstoneCluster
MONGODB_NAME=capstone_db
```

**Replace:**
- `capstone_admin` → Your database username
- `YOUR_PASSWORD_HERE` → Your database password (URL-encoded if special chars)
- `capstonecluster.xxxxx.mongodb.net` → Your actual cluster hostname

---

## Step 7: URL Encode Special Characters

If your password has special characters, encode them:

| Character | Encoded |
|-----------|---------|
| `@` | `%40` |
| `:` | `%3A` |
| `/` | `%2F` |
| `#` | `%23` |
| `?` | `%3F` |
| `&` | `%26` |
| `=` | `%3D` |
| `+` | `%2B` |
| `%` | `%25` |

**Example:**
- Password: `MyP@ss#123`
- Encoded: `MyP%40ss%23123`

---

## Step 8: Test the Connection

Run the Django server:

```bash
python manage.py runserver
```

If successful, you should see:
```
Starting development server at http://127.0.0.1:8000/
```

---

## Troubleshooting

### Error: SSL Handshake Failed
**Cause:** IP not whitelisted or network issues

**Fix:**
1. Go to **Network Access** in Atlas
2. Ensure your IP is whitelisted or add `0.0.0.0/0`
3. Wait 1-2 minutes for changes to propagate
4. Try connecting again

### Error: Authentication Failed
**Cause:** Wrong username/password

**Fix:**
1. Double-check your username and password
2. Make sure special characters are URL-encoded
3. Create a new database user if unsure

### Error: Connection Timeout
**Cause:** Firewall blocking connection

**Fix:**
1. Try a different network (e.g., mobile hotspot)
2. Check if your firewall allows outbound connections on port 27017
3. Try adding `&ssl=true&tlsAllowInvalidCertificates=true` to connection string (dev only)

---

## Sample .env Configuration

```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# MongoDB Atlas
MONGODB_URI=mongodb+srv://capstone_admin:MySecurePassword123@capstonecluster.abc123.mongodb.net/?retryWrites=true&w=majority&appName=CapstoneCluster
MONGODB_NAME=capstone_db

# Email (Gmail example)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0
```

---

## Verify MongoDB Connection in Python

You can test your connection directly:

```python
from pymongo import MongoClient

uri = "mongodb+srv://capstone_admin:password@capstonecluster.abc123.mongodb.net/?retryWrites=true&w=majority"

try:
    client = MongoClient(uri)
    client.admin.command('ping')
    print("✅ Connected successfully to MongoDB Atlas!")
except Exception as e:
    print(f"❌ Connection failed: {e}")
```

Run with: `python -c "..."`

---

## Next Steps

Once connected:
1. Test the signup endpoint: `POST /api/auth/signup/`
2. Check MongoDB Atlas → **Browse Collections** to see your data
3. Continue with API testing using the [API Reference](./API_REFERENCE.md)

---

## Section 3: BACKGROUND_TASKS.md

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
