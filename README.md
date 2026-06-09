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

# 5. Start Redis (required for WebSocket channel layers)
redis-server

# 6. Initialize database indexes
python init_db.py

# 7. Run ASGI server with Daphne (supports WebSockets)
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Or use Django's development ASGI server:
# python manage.py runserver 0.0.0.0:8000
```

API available at: `http://localhost:8000/`

WebSocket available at: `ws://localhost:8000/ws/notifications/`

### WebSocket Configuration

The notification system uses Django Channels with Redis for real-time WebSocket messaging.

**Required environment variables:**

```env
# Redis connection for Channel Layers
REDIS_HOST=localhost
REDIS_PORT=6379

# WebSocket toggle (can disable if needed)
WEBSOCKET_ENABLED=True
```

**Frontend WebSocket connection:**

```typescript
const wsUrl = `ws://localhost:8000/ws/notifications/?token=${accessToken}`;
const ws = new WebSocket(wsUrl);
```

**Note:** The backend uses JWT authentication via query parameter (`?token=...`) for WebSocket connections. The frontend automatically attaches the access token from localStorage.

---

## AI Chatbot — LLM Provider Setup

The AI assistant supports two LLM providers. Switch between them via a single `.env` variable:

**Option A: Groq (Cloud — default)**
```bash
# In .env
LLM_PROVIDER=groq
# Free tier: 14,400 requests/day
# Get API key at: https://console.groq.com
```

**Option B: Ollama (Local — no rate limits)**
```bash
# 1. Install Ollama
brew install ollama  # macOS

# 2. Start Ollama server
ollama serve

# 3. Pull a model
ollama pull llama3.1

# 4. Switch provider in .env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

Restart the backend after switching providers.

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
FIELD_ENCRYPTION_KEY=generate-a-fernet-key

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

### Response Caching (Optional)

The API caches static content (FAQs, education, suggestions, loan products) to improve performance.

**Default: In-memory cache** — works out of the box, no setup required.

**Optional but still do it: Redis cache** — for multi-server deployments:
```bash
# In .env
USE_REDIS_CACHE=true
REDIS_URL=redis://localhost:6379/0
```

**Verify caching is working:**
```bash
# Call an endpoint twice - second call should have "cached": true
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/ai/faqs/

# Response will include:
# { "data": { "faqs": [...], "cached": true }, ... }
```

**Cache TTLs:**
| Content | TTL | Invalidation |
|---------|-----|--------------|
| FAQs | 24 hours | Restart server |
| Education | 24 hours | Restart server |
| Suggestions | 12 hours | Restart server |
| Loan Products | 30 mins | Auto (on admin CRUD) |

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
FIELD_ENCRYPTION_KEY=<generate-fernet-key>
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
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
```

**Note:** Production uses `daphne` (ASGI server) instead of `gunicorn` (WSGI) because the backend supports real-time WebSocket notifications via Django Channels.

### Production WebSocket Requirements

1. **Redis** must be available for the Channels layer backend
2. Set `WEBSOCKET_ENABLED=True` in production environment variables
3. Configure `REDIS_HOST` and `REDIS_PORT` to point to your Redis instance
4. The frontend must connect via `wss://` (secure WebSocket) in production
5. Ensure CORS/CSRF origins allow your production frontend domain

### Local Development with WebSockets

```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Django ASGI server (supports HTTP + WebSocket)
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# OR use Daphne with hot reload for development:
# daphne --reload -b 0.0.0.0 -p 8000 config.asgi:application
```

```bash
## Useful Commands (Production)

```bash
# 6. Run with production server (macOS requires OBJC flag)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES gunicorn config.wsgi:application --bind 0.0.0.0:8000 --timeout 120

# Collect static files (before deployment)
python manage.py collectstatic

# Check health
curl http://localhost:8000/api/health/
```

### Switch AI Provider

```bash
# Use Groq (cloud, free tier)
# In .env: LLM_PROVIDER=groq

# Use Ollama (local, no limits)
# In .env: LLM_PROVIDER=ollama
# Make sure Ollama is running: ollama serve
```

### Encrypted Backup and Restore

```bash
# Create encrypted backup archive (uses MONGODB_URI + BACKUP_ENCRYPTION_PASSPHRASE)
python scripts/create_encrypted_backup.py

# Restore encrypted backup into restore test DB
python scripts/restore_encrypted_backup.py /path/to/backup.archive.gz.enc
```

---

## Documentation

- [API Reference](docs/API_REFERENCE.md)
- [Gap Analysis](docs/GAP_ANALYSIS.md)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
- [Authentication](docs/AUTHENTICATION.md)
- [CNN Document Analysis](docs/CNN_DOCUMENT_ANALYSIS.md)

---

## Notifications: Email Sender & Metrics

Configuration options added to improve email throughput and observability:

- `EMAIL_SENDER_THREADPOOL_MAX_WORKERS` (Django `settings`): integer (default 4)
	- Controls the size of the internal `ThreadPoolExecutor` used when `EmailSender(send_async=True)`.
	- Example (in `settings.py` or via environment-backed settings):

```python
# config/settings.py
EMAIL_SENDER_THREADPOOL_MAX_WORKERS = 8
```

- Prometheus metrics (optional): the email sender and Celery task expose simple counters
	when `prometheus-client` is installed:

	- `notifications_email_send_success_total`
	- `notifications_email_send_failure_total`
	- `notifications_email_task_success_total`
	- `notifications_email_task_failure_total`

	To enable scraping, run a Prometheus metrics HTTP server on startup (or integrate with
	your existing metrics endpoint). Example (quick, development-friendly):

```python
# in config/wsgi.py or a startup module
from prometheus_client import start_http_server

# start metrics server on port 8001 (choose an appropriate port for your infra)
start_http_server(8001)
```

	For production deployments, integrate with your existing metrics stack (e.g. expose
	metrics via your application's central metrics endpoint or use a pushgateway).

Notes:
- The Prometheus counters are optional and guarded; the code falls back gracefully if
	`prometheus-client` is not installed.
- Adjust `EMAIL_SENDER_THREADPOOL_MAX_WORKERS` based on workload and available CPU.

