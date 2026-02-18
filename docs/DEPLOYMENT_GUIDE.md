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
