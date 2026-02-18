# MSME Pathways - Backend API

Smart Loan Support System for Filipino Microentrepreneurs

---

## Quick Start (Development)

```bash
# 1. Clone and enter directory
git clone <repo-url>
cd Capstone_Backend

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env
# Edit .env with your values (see Configuration section)

# 5. Initialize database indexes
python init_db.py

# 6. Run server
python manage.py runserver 0.0.0.0:8000
```

API available at: `http://localhost:8000/`

---

## Configuration

### Environment Variables

Copy template first:

```bash
cp .env.example .env
```

Use these minimum values for local development:

```env
# Django
DEBUG=True
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1
SECRET_PEPPER=generate-a-64-char-hex-pepper

# MongoDB Atlas
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/
MONGODB_NAME=capstone_db

# Frontend origins
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173

# Auth/session cookies (dev on HTTP)
AUTH_COOKIE_HTTPONLY=True
AUTH_COOKIE_SECURE=False
AUTH_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False

# Groq LLM (AI Chatbot)
# Get free key at: https://console.groq.com
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.1-8b-instant
GROQ_CHAT_MODEL=llama-3.1-8b-instant
GROQ_QUALIFICATION_MODEL=llama-3.1-8b-instant

# Email (Gmail)
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

```

For full variable reference (dev + production), see `.env.example` and `docs/DEPLOYMENT_GUIDE.md`.

---

## Development vs Production

| Setting | Development | Production |
|---------|-------------|------------|
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | Any value | Strong random key |
| `SECRET_PEPPER` | Set | Set (rotate securely) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | `your-app.railway.app` |
| HTTPS | Off | On (automatic) |
| Secure Cookies | Off | On (automatic) |
| Server | `runserver` | `gunicorn` |
| Static Files | Django | WhiteNoise |

---

## Deploy to Production (Railway)

### 1. Push to GitHub
```bash
git add .
git commit -m "Ready for deployment"
git push origin main
```

### 2. Connect Railway
1. Go to [railway.app](https://railway.app)
2. New Project → Deploy from GitHub
3. Select your repository

### 3. Set Environment Variables

In Railway dashboard, add:

```env
DEBUG=False
SECRET_KEY=<generate-strong-key>
SECRET_PEPPER=<generate-strong-pepper>
ALLOWED_HOSTS=your-app.railway.app
MONGODB_URI=<your-mongodb-atlas-uri>
MONGODB_NAME=capstone_db
GROQ_API_KEY=<your-groq-key>
GROQ_CHAT_MODEL=llama-3.1-8b-instant
GROQ_QUALIFICATION_MODEL=llama-3.1-8b-instant
EMAIL_HOST_USER=<your-email>
EMAIL_HOST_PASSWORD=<your-app-password>
CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app
CSRF_TRUSTED_ORIGINS=https://your-frontend.vercel.app

# Session/cookie security
AUTH_COOKIE_HTTPONLY=True
AUTH_COOKIE_SECURE=True
AUTH_COOKIE_SAMESITE=None
CSRF_COOKIE_SECURE=True
CSRF_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=True
```

If frontend and backend share the same site, you can keep `AUTH_COOKIE_SAMESITE=Lax`.

### 4. Deploy
Railway auto-deploys from `Procfile`:
```
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

---

## API Endpoints

| Module | Base URL | Endpoints |
|--------|----------|-----------|
| Health | `/api/health/` | 1 |
| Auth | `/api/auth/` | 20 |
| Profiles | `/api/profile/` | 5 |
| Documents | `/api/documents/` | 6 |
| Loans | `/api/loans/` | 16 |
| AI Chat | `/api/ai/` | 7 |
| Analytics | `/api/analytics/` | 4 |
| **Total** | | **59** |

See [API_REFERENCE.md](docs/API_REFERENCE.md) for full documentation.

---

## Project Structure

```
Capstone_Backend/
├── accounts/          # Auth, 2FA, user management
├── profiles/          # Customer, business, alternative data
├── documents/         # Document upload, CNN analysis
├── loans/             # Loan products, applications, payments
├── ai_assistant/      # Groq LLM chatbot
├── analytics/         # Dashboards, audit logs
├── notifications/     # Email service
├── config/            # Django settings, URLs
├── docs/              # Documentation
├── Procfile           # Railway deployment
├── runtime.txt        # Python version
└── requirements.txt   # Dependencies
```

---

## Technologies

| Category | Technology |
|----------|------------|
| Framework | Django 4.2 + REST Framework |
| Database | MongoDB Atlas (PyMongo) |
| AI/LLM | Groq (llama-3.1-8b-instant) |
| CNN | PyTorch + MobileNetV2 |
| Auth | JWT + 2FA (TOTP) |
| Email | Gmail SMTP |
| Production | Gunicorn + WhiteNoise |

---

## CNN Training (Optional)

To enable AI document verification:

```bash
# 1. Add training images to documents/ml/training_data/
#    - valid_id/ (50-100 images)
#    - invalid/ (50-100 images)
#    - etc.

# 2. Train the model
python manage.py train_document_classifier --epochs 10

# 3. Model auto-loads on server restart
```

---

## Useful Commands

```bash
# Run development server
python manage.py runserver

# Test with production server locally
gunicorn config.wsgi:application --bind 127.0.0.1:8000

# Collect static files (before deployment)
python manage.py collectstatic

# Check health
curl http://localhost:8000/api/health/
```

---

## Documentation

- [API Reference](docs/API_REFERENCE.md)
- [Gap Analysis](docs/GAP_ANALYSIS.md)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
- [Authentication](docs/AUTHENTICATION.md)
- [CNN Document Analysis](docs/CNN_DOCUMENT_ANALYSIS.md)
