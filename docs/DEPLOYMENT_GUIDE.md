# MSME Pathways - Deployment Guide

> **Last Updated:** January 16, 2026

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

```env
# Django
DEBUG=False
SECRET_KEY=your-production-secret-key
ALLOWED_HOSTS=your-app.railway.app

# MongoDB (already set)
MONGODB_URI=mongodb+srv://...

# LLM (Groq Cloud - already configured)
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=llama-3.1-8b-instant

# Email
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=app-specific-password

# CORS (for frontend)
CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app
```

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

### Step 3: Deploy to Railway
```bash
# Push to GitHub, connect Railway
# Set environment variables
# Done!
```

### Step 4: Deploy Frontend
```bash
# Web: Connect Vercel to GitHub
# Mobile: expo build:android / expo build:ios
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
