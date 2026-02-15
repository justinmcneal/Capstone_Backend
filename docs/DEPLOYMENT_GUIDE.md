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

# Document Storage (AWS S3)
DOCUMENT_STORAGE_BACKEND=s3
AWS_REGION=ap-southeast-1
AWS_S3_BUCKET_NAME=your-msme-documents-prod
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_S3_PUBLIC_BASE_URL=https://your-msme-documents-prod.s3.ap-southeast-1.amazonaws.com
```

---

## Production Document Storage (AWS S3)

### Why this is required
- Railway/local container disk is ephemeral; uploaded files can be lost on restart/redeploy.
- Production uploads must be stored in durable object storage (AWS S3).

### Target Architecture
- Backend API runs on Railway.
- Files are uploaded from backend to S3 bucket.
- Database stores S3 object path/key.
- API returns a URL that frontend opens for preview.

### Bucket Setup (AWS Console)
1. Create an S3 bucket:
- Name: `your-msme-documents-prod` (globally unique)
- Region: choose closest to users (example: `ap-southeast-1`)
- Versioning: `Enabled` (recommended)
- Default encryption: `SSE-S3` (minimum) or `SSE-KMS`

2. Add folder/prefix strategy:
- `documents/<customer_id>/<document_type>/<generated_filename>`

3. Configure lifecycle policy:
- Move older objects to cheaper tier (optional)
- Retention/expiration for rejected or replaced docs (if policy allows)

### IAM User / Access Policy
Create a dedicated IAM user for backend (programmatic access only) and attach least-privilege policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucketPrefixOnly",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::your-msme-documents-prod",
      "Condition": {
        "StringLike": {
          "s3:prefix": ["documents/*"]
        }
      }
    },
    {
      "Sid": "ObjectCRUDInDocumentsPrefix",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::your-msme-documents-prod/documents/*"
    }
  ]
}
```

### Bucket CORS (for browser previews/downloads)
Set S3 bucket CORS:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": [
      "https://your-frontend.vercel.app",
      "http://localhost:5173"
    ],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

### Public vs Private Access
- Recommended long-term: private bucket + signed URLs.
- If current app expects direct URL preview, configure accessible object URLs for `documents/*` until signed-URL flow is implemented.
- Do not expose non-document prefixes publicly.

### Railway Environment Variables (S3)
Set these in Railway service settings:
- `DOCUMENT_STORAGE_BACKEND=s3`
- `AWS_REGION=...`
- `AWS_S3_BUCKET_NAME=...`
- `AWS_ACCESS_KEY_ID=...`
- `AWS_SECRET_ACCESS_KEY=...`
- `AWS_S3_PUBLIC_BASE_URL=...`

### Data Migration Plan (Local -> S3)
1. Export current local media files from backend server.
2. Upload to S3 preserving path structure:
- local `media/documents/...` -> S3 `documents/...`
3. Keep DB `file_path` values unchanged if path structure is preserved.
4. Switch env vars to S3 in staging first.
5. Validate previews/downloads from frontend.
6. Roll to production.

### Verification Checklist After S3 Cutover
- Upload new document: appears in S3 under expected prefix.
- View document from Loan Officer page: opens correct S3 URL.
- Delete/reupload flow: old object removed/replaced correctly.
- Existing records from migration open successfully.
- No local disk dependency for production uploads.

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

### Step 3: Configure S3 Storage
```bash
# Create bucket + IAM key
# Add Railway env vars listed above
# Deploy backend with DOCUMENT_STORAGE_BACKEND=s3
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
