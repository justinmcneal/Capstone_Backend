# MSME Pathways Backend API

Smart loan support services for Filipino microentrepreneurs.

The backend is built with Django and Django REST Framework, uses PyMongo with
MongoDB, serves authenticated WebSockets through Django Channels and Daphne, and
uses Redis and Celery for real-time and background work.

## Main Components

- Accounts: JWT authentication, cookies, CSRF, 2FA, recovery, consent, sessions,
  account lifecycle, and administrative account management.
- Profiles: personal/business/alternative data, completion policy, asynchronous
  informational risk scoring, profile export/history, and manual review requests.
- Loans and payments: applications, qualification, schedules, disbursement, and
  repayment workflows.
- Documents: uploads, storage, review, and AI-assisted processing.
- AI assistant, notifications, analytics, Prometheus metrics, and WebSockets.

This project uses PyMongo directly. Django ORM migration commands are not the
database initialization mechanism.

## Module Status

- Accounts: implementation and development validation complete; deployment-
  environment integration checks remain release-time work.
- Profiles: implementation, local tests, real-Mongo concurrency/index tests, and
  development inventories complete. Only deployment-target inventories and
  infrastructure validation remain for release.
- Documents: Stages 1–7 are complete at code and local-test level. Representative
  isolated MongoDB/S3/Redis/Celery/ClamAV/restore/monitoring evidence remains a
  deployment release gate. The production baseline disables document CNN/AI,
  requires human review, and fails closed unless private malware scanning is
  required and enabled.

## Development Quick Start

```bash
# 1. Clone and enter the repository
git clone https://github.com/your-org/Capstone_Backend.git
cd Capstone_Backend

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate             # macOS/Linux
# .venv\Scripts\activate              # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create local configuration
cp .env.example .env
# Review and replace the development values in .env.

# 5. Start Redis for Channels and Celery
redis-server

# 6. For a new/empty development database only, create declared indexes
python init_db.py

# 7. Start the ASGI application
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Django's development server may also be used locally
python manage.py runserver 0.0.0.0:8000
```

`init_db.py` changes MongoDB indexes. Review the configured database and run the
duplicate-profile dry run before using it against an existing database.

## Runtime Services

Run these in separate terminals when testing asynchronous workflows:

```bash
# Celery worker
celery -A config worker --loglevel=info

# Celery Beat scheduler
celery -A config beat --loglevel=info
```

The ASGI server handles both HTTP and WebSocket traffic. Notification clients
connect using the authenticated WebSocket route:

```typescript
const wsUrl = `ws://localhost:8000/ws/notifications/?token=${accessToken}`;
const ws = new WebSocket(wsUrl);
```

Use `wss://` outside local HTTP development. Query-string tokens must not be
logged by clients, proxies, or monitoring systems.

## Configuration

Copy `.env.example` to `.env` and use the template as the variable reference.
Do not commit `.env`, encryption keys, API keys, database credentials, wallet
keys, Firebase credentials, or cloud credentials.

Production configuration and release procedures are documented in
[`docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md`](docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md).

### LLM Provider

The AI assistant supports Groq and Ollama.

```bash
# Groq
LLM_PROVIDER=groq
GROQ_API_KEY='replace-with-development-key'

# Or local Ollama
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

For local Ollama:

```bash
brew install ollama       # macOS example
ollama serve
ollama pull llama3.1
```

Restart the backend and workers after changing provider configuration.

### Redis Cache

In-memory caching is sufficient for single-process development. Configure the
Redis cache for multi-process or multi-instance environments so throttling and
shared cache state are consistent across workers.

## Management and Maintenance Commands

Management commands load the configured environment and may access real data.
Commands described as dry-run are read-only unless `--apply` is explicitly
supplied. Review output, backups, the target database, and a rollback plan before
running state-changing forms.

### Accounts Commands

#### Create an administrator

Interactive mode prompts securely for the password:

```bash
python manage.py create_admin
```

Arguments include `--username`, `--email`, `--first-name`, `--last-name`,
`--super-admin`, `--permissions`, `--all-permissions`, and `--noinput`. Avoid
placing passwords in shell history; prefer the interactive password prompt.

#### Encrypt, rotate, and verify declared sensitive fields

```bash
# Inventory plaintext fields (dry run)
python manage.py encrypt_sensitive_fields

# Inventory fields requiring primary-key rotation (dry run)
python manage.py encrypt_sensitive_fields --rotate

# Apply a reviewed backfill/rotation
python manage.py encrypt_sensitive_fields --rotate --apply

# Verify every populated declared field uses valid primary-key encryption
python manage.py encrypt_sensitive_fields --verify
```

Keep required previous keys in `FIELD_ENCRYPTION_PREVIOUS_KEYS` until rotation,
verification, backups, and the rollback window are complete. The command also
requires the normal management-command environment, including `SECRET_PEPPER`.

#### Scrub legacy plaintext session tokens

```bash
# Inventory legacy active-session records
python manage.py scrub_legacy_sessions

# Invalidate reviewed records and remove plaintext session_token fields
python manage.py scrub_legacy_sessions --apply
```

The applied operation invalidates affected sessions and should run only in an
approved maintenance window.

### Profiles Commands

#### Find profile data retained for already-deleted customers

```bash
# Dry run
python manage.py cleanup_deleted_customer_profiles

# Irreversibly delete the reviewed retained records
python manage.py cleanup_deleted_customer_profiles --apply
```

#### Recalculate stored completion metadata

```bash
# Dry run against the current completion policy
python manage.py recalculate_profile_completion

# Apply revision-guarded metadata updates
python manage.py recalculate_profile_completion --apply
```

#### Recalculate obsolete informational risk scores

```bash
# Dry run: scores missing or obsolete under the current policy
python manage.py recalculate_profile_risk_scores

# Mark reviewed candidates pending and enqueue recalculation
python manage.py recalculate_profile_risk_scores --apply

# Include every alternative-data record (review carefully)
python manage.py recalculate_profile_risk_scores --all
python manage.py recalculate_profile_risk_scores --all --apply
```

Applied risk-score recalculation requires a working Celery broker and workers.

#### Reconcile duplicate profiles

```bash
# Dry run before unique-index creation
python manage.py reconcile_duplicate_profiles

# Retain the newest authoritative document and remove reviewed duplicates
python manage.py reconcile_duplicate_profiles --apply
```

The applied form deletes older duplicate documents. Back up and review the target
database first.

#### Convert legacy business ages to canonical months

```bash
# Dry run
python scripts/backfill_business_age_months.py

# Apply eligible revision-guarded conversions
python scripts/backfill_business_age_months.py --apply
```

Ambiguous legacy values remain unchanged for manual review.

### Documents Commands

#### Inventory storage consistency

This command is read-only and prints aggregate counts, never object keys,
filenames, paths, or customer identifiers:

```bash
python manage.py inventory_document_storage
```

#### Manage a document legal hold

```bash
# Preview only
python manage.py manage_document_legal_hold DOCUMENT_ID --action set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID"

# Apply an approved hold or release
python manage.py manage_document_legal_hold DOCUMENT_ID --action set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID" --apply
python manage.py manage_document_legal_hold DOCUMENT_ID --action release \
  --operator "ADMIN_ID" --apply
```

#### Validate private S3 configuration

Run this read-only check only after selecting the intended isolated/deployment
environment:

```bash
python manage.py validate_document_storage
```

It validates public-access blocking, encryption, object ownership, CORS, URL
expiry, versioning, and quarantine lifecycle. IAM policy and backup/restore
evidence require separate operator review.

## Testing and Static Validation

```bash
# Complete local suite
pytest -q

# Profiles-focused suite
pytest -q tests/test_profiles*.py

# Documents-focused suite
pytest -q tests/test_documents*.py tests/test_s3*.py

# Accounts-focused suites
pytest -q accounts/tests tests/test_accounts*.py

# Static checks
ruff check .

# Django configuration checks
python manage.py check
```

Real-Mongo tests are opt-in and must use an isolated non-production service whose
account can create and remove temporary databases:

```bash
REAL_MONGO_TEST_URI='mongodb://isolated-test-host/' \
pytest -q -m real_mongo tests/test_stage9_real_mongo.py
```

Real-S3 validation is separately opt-in and mutates unique objects in an
explicitly approved isolated bucket:

```bash
REAL_S3_TEST_BUCKET='isolated-documents-bucket' \
REAL_S3_TEST_REGION='us-east-1' \
REAL_S3_TEST_ALLOW_MUTATION=yes \
pytest -q -m real_s3 tests/test_documents_real_s3.py
```

Real-ClamAV validation is opt-in and sends only synthetic clean content and the
harmless standard antivirus test marker to a private scanner:

```bash
REAL_CLAMAV_TEST_HOST='clamav.internal' \
REAL_CLAMAV_TEST_ALLOW_SCAN=yes \
pytest -q -m real_clamav tests/test_documents_real_clamav.py
```

Never point the opt-in database/object-storage tests at production resources.

## Production Deployment

The provided `Procfile` uses separate ASGI, Celery worker, and Celery Beat
processes:

```text
web: daphne -b 0.0.0.0 -p $PORT config.asgi:application
worker: celery -A config worker --loglevel=info
beat: celery -A config beat --loglevel=info
```

Before release:

```bash
# Validate Django configuration with the production environment
python manage.py check --deploy

# Collect static assets
python manage.py collectstatic --noinput

# Check the deployed service
curl https://backend.example.com/api/health/
```

Do not run `init_db.py`, reconciliation commands, storage scripts, or an
encryption `--apply` operation during deployment until their dry runs, backups,
and target environment have been reviewed.

### Encrypted Backup and Restore

These scripts are state-changing operational workflows. Use only with approved
storage, passphrase handling, backup retention, and restore testing.

```bash
# Create an encrypted MongoDB backup archive
python scripts/create_encrypted_backup.py

# Restore into an explicitly selected restore-test database
python scripts/restore_encrypted_backup.py /path/to/backup.archive.gz.enc
```

## Metrics and Observability

The project exposes optional Prometheus metrics when `prometheus-client` is
installed. Notification counters include:

- `notifications_email_send_success_total`
- `notifications_email_send_failure_total`
- `notifications_email_task_success_total`
- `notifications_email_task_failure_total`

Profiles metrics cover scoring outcomes/backlogs, duplicate records, encryption
coverage, audit recovery, review queues, and denied access. See
[`docs/profiles/PROFILES_OPERATIONS.md`](docs/profiles/PROFILES_OPERATIONS.md).

`EMAIL_SENDER_THREADPOOL_MAX_WORKERS` controls the internal notification email
thread pool and defaults to `4`. Tune it only after observing workload and CPU.

## Documentation

- [Accounts production readiness](docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md)
- [Accounts testing guide](docs/accounts/ACCOUNTS_TESTING_GUIDE.md)
- [Profiles production readiness](docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md)
- [Profiles testing guide](docs/profiles/PROFILES_TESTING_GUIDE.md)
- [Profiles client migration](docs/profiles/PROFILES_CLIENT_MIGRATION.md)
- [Profiles completion policy](docs/profiles/PROFILES_COMPLETION_POLICY.md)
- [Profiles risk-scoring policy](docs/profiles/PROFILES_RISK_SCORING_POLICY.md)
- [Profiles operations](docs/profiles/PROFILES_OPERATIONS.md)
- [Documents production readiness](docs/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md)
- [Documents testing guide](docs/DOCUMENTS_TESTING_GUIDE.md)
- [Documents operations](docs/documents/DOCUMENTS_OPERATIONS_RUNBOOK.md)
- [Documents AI governance](docs/documents/DOCUMENT_AI_GOVERNANCE.md)
- [API reference](docs/feats/API_REFERENCE.md)
- [Deployment and operations](docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md)
