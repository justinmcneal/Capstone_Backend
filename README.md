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
python manage.py runserver 0.0.0.0:8000
```

### WebSocket Configuration

The notification system uses Django Channels with Redis for real-time WebSocket messaging.

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

For the full variable reference, see `.env.example`. For production procedures,
see `docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md`.

```bash
# Dry run (default; no database writes)
python manage.py encrypt_sensitive_fields --rotate

# Apply the reviewed rotation
python manage.py encrypt_sensitive_fields --rotate --apply

# Verify every supported populated field uses the primary key
python manage.py encrypt_sensitive_fields --verify
```

Do not remove a previous key until verification, backups, and the rollback window
are approved. These commands also require the normal management-command
environment, including `SECRET_PEPPER`.

---

### Response Caching (Optional)

The API caches static content (FAQs, education, suggestions, loan products) to improve performance.

**Default: In-memory cache** — works out of the box, no setup required.

**Optional but still do it: Redis cache** — for multi-server deployments:

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

In Railway dashboard, add .env

If frontend and backend share the same site, you can keep `AUTH_COOKIE_SAMESITE=Lax`.

### 4. Deploy
Railway auto-deploys from `Procfile`:

```
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
```

**Note:** Production uses `daphne` (ASGI server) instead of `gunicorn` (WSGI) because the backend supports real-time WebSocket notifications via Django Channels.

# 5. Run with production server (macOS requires OBJC flag)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES gunicorn config.wsgi:application --bind 0.0.0.0:8000 --timeout 120

# Collect static files (before deployment)
python manage.py collectstatic

# Check health
curl http://localhost:8000/api/health/
```

### Encrypted Backup and Restore

```bash
# Create encrypted backup archive (uses MONGODB_URI + BACKUP_ENCRYPTION_PASSPHRASE)
python scripts/create_encrypted_backup.py

# Restore encrypted backup into restore test DB
python scripts/restore_encrypted_backup.py /path/to/backup.archive.gz.enc
```

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
