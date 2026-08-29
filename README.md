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
- Loans and payments: products, qualification, applications, assignment/review,
  cash/check settlement, centavo-based schedules/payments, payoff, and optional
  feature-gated wallet synchronization.
- Documents: uploads, storage, review, and AI-assisted processing.
- AI Assistant: consent-gated English/Tagalog chat and SSE streaming,
  customer-owned history, read-only customer context tools, controlled guidance,
  and provider safety/quality boundaries.
- Analytics: role-scoped dashboards, protected cross-domain audit events,
  integrity/lifecycle controls, recovery, health, Prometheus metrics, and a
  Grafana operations dashboard.
- Notifications: role-scoped inboxes, authenticated WebSockets, encrypted
  device tokens, durable email/push delivery, preference enforcement, privacy
  lifecycle, and delivery monitoring.

This project uses PyMongo directly. Django ORM migration commands are not the
database initialization mechanism.

## Module Status

- Accounts: implementation and development validation complete; deployment-
  environment integration checks remain release-time work.
- Profiles: implementation, local tests, real-Mongo concurrency/index tests, and
  development inventories complete. Only deployment-target inventories and
  infrastructure validation remain for release.
- Loans: application implementation is complete for the approved cash/check
  baseline. Real-Mongo atomicity/query plans, production Redis/Celery,
  HTTPS/load, monitoring/alerts, recovery, policy approval, and optional
  blockchain evidence remain deployment gates.
- Documents: Stages 1–7 are complete at code and local-test level. Representative
  isolated MongoDB/S3/Redis/Celery/ClamAV/restore/monitoring evidence remains a
  deployment release gate. The production baseline disables document CNN/AI,
  requires human review, and fails closed unless private malware scanning is
  required and enabled.
- Analytics: implementation and isolated development validation are complete,
  including real-Mongo query plans, audit protection, backup/restore, Redis,
  Celery, Prometheus, and a provisioned Grafana dashboard. Restricted production
  database credentials, HTTPS proxy validation, production monitoring/on-call
  delivery, and the final production-mode release check remain deployment gates.
- AI Assistant: implementation and controlled bilingual quality validation are
  complete. Final target-database inventory, deployed multi-worker Redis,
  HTTPS/SSE load, monitoring/alerts, recovery, and release smoke evidence remain
  deployment gates.
- Notifications: REST, WebSocket, durable shared delivery, email preferences,
  FCM token lifecycle, privacy, and monitoring implementation are complete.
  Real MongoDB, Redis/Channels/Celery, SMTP, Firebase, HTTPS/WSS/load,
  monitoring/alerts, policy, and recovery evidence remain deployment gates.

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

### Loans Commands

#### Inventory and backfill loan persistence

```bash
# Read-only count inventory; increase the limit if any collection is truncated
python manage.py loan_data_inventory --limit 10000

# Dry-run encryption, centavo, search, scope, timing, and lifecycle backfill
python manage.py backfill_loan_data --limit 10000

# Apply only after duplicate review, backup/restore, and dry-run approval
python manage.py backfill_loan_data --limit 10000 --apply
```

The applied backfill is compare-and-set protected and refuses invalid,
conflicting, or truncated runs. Repeat the inventory until clean before running
the state-changing database bootstrap against an existing target.

#### Manage a loan legal hold

```bash
# Preview only
python manage.py manage_loan_legal_hold APPLICATION_ID set \
  --reason "CASE_REFERENCE" --actor "ADMIN_ID"

# Apply an approved hold or release
python manage.py manage_loan_legal_hold APPLICATION_ID set \
  --reason "CASE_REFERENCE" --actor "ADMIN_ID" --apply
python manage.py manage_loan_legal_hold APPLICATION_ID release \
  --actor "ADMIN_ID" --apply
```

Do not place customer or financial data in a legal-hold reason.

#### Run the final read-only Loans release gate

```bash
python manage.py loan_release_check
python manage.py loan_release_check --json
```

The release command intentionally fails until the selected baseline and its
MongoDB, workers, HTTPS/load, monitoring, recovery, policy, and smoke evidence
are configured. Blockchain evidence is not required when
`BLOCKCHAIN_ENABLED=False` and clients expose cash/check only.

### Notifications Commands

#### Inventory, backfill, encrypt, and install notification schemas

```bash
# Read-only bounded inventory
python manage.py notification_data_inventory --limit 10000

# Dry-run deterministic legacy-shape backfill
python manage.py backfill_notification_data

# Apply only after reviewing the target, backup, and dry-run counts
python manage.py backfill_notification_data --apply

# Shared sensitive-field inventory and verification
python manage.py encrypt_sensitive_fields
python manage.py encrypt_sensitive_fields --verify

# Preview schema/index installation after the inventory is clean
python manage.py install_notification_schema

# Apply only to the explicitly approved target
python manage.py install_notification_schema --apply
```

The schema installer fails closed when inventory is incomplete or detects
legacy, plaintext, invalid-owner/platform/timestamp, missing lifecycle, or
duplicate-key blockers. Encryption/backfill `--apply` and schema installation
change MongoDB and require reviewed backup and target approval.

#### Run the final read-only Notifications release gate

```bash
python manage.py notifications_release_check
python manage.py notifications_release_check --json
```

The gate intentionally fails until production-safe configuration, clean
MongoDB indexes/validators/inventory, task routing, health, monitoring assets,
and the required deployment evidence are verified.

### Analytics Commands

#### Inventory and backfill protected audit events

```bash
# Read-only integrity, encryption, and retention inventory
python manage.py audit_integrity_inventory --limit 10000

# Dry-run legacy audit protection backfill
python manage.py backfill_audit_events --limit 10000

# Apply only after reviewing the target, backup, and dry-run output
python manage.py backfill_audit_events --limit 10000 --apply
```

The applied backfill encrypts eligible sensitive fields and adds the current
schema, retention, blind-subject, and integrity protection. It refuses invalid
existing signatures, unregistered actions, and update conflicts for operator
review.

#### Manage an audit-event legal hold

```bash
# Preview only
python manage.py manage_audit_legal_hold EVENT_ID --action set \
  --actor "ADMIN_ID" --reason "CASE_REFERENCE"

# Apply an approved hold or release
python manage.py manage_audit_legal_hold EVENT_ID --action set \
  --actor "ADMIN_ID" --reason "CASE_REFERENCE" --apply
python manage.py manage_audit_legal_hold EVENT_ID --action release \
  --actor "ADMIN_ID" --apply
```

#### Run the final read-only Analytics release gate

```bash
python manage.py analytics_release_check
python manage.py analytics_release_check --json
```

The release command intentionally fails until production-mode configuration,
MongoDB bootstrap/integrity, shared cache, proxy, and monitoring evidence are
available. It should not be bypassed merely because the current environment is
development.

### AI Assistant Commands

#### Inventory and backfill protected interaction history

```bash
# Read-only privacy/lifecycle inventory
python manage.py ai_interaction_inventory

# Dry-run encryption and lifecycle backfill
python manage.py backfill_ai_interactions

# Apply only after reviewing the target, backup, and dry-run output
python manage.py backfill_ai_interactions --apply
```

The backfill requires `FIELD_ENCRYPTION_KEY`. Keep previous encryption keys
available until rotation, blind-search rebuilding, verification, and rollback
windows are complete.

#### Reconcile stale chat requests

```bash
# Dry run; never fabricates missing assistant content
python manage.py reconcile_ai_chat_requests

# Apply reviewed lease-state repairs
python manage.py reconcile_ai_chat_requests --apply
```

Partial exchanges remain an operator-review condition.

#### Manage an AI interaction legal hold

```bash
# Preview a hold
python manage.py manage_ai_legal_hold INTERACTION_ID set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID"

# Apply an approved hold or release
python manage.py manage_ai_legal_hold INTERACTION_ID set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID" --apply
python manage.py manage_ai_legal_hold INTERACTION_ID release \
  --operator "ADMIN_ID" --apply
```

#### Run the final read-only AI release gate

```bash
python manage.py ai_release_check
python manage.py ai_release_check --json
```

The release check intentionally fails until the controlled quality artifact and
required deployment-environment evidence flags are configured and verified.
Provider response collection and quality scoring commands are documented in
[`docs/ai_assistant/AI_ASSISTANT_TESTING_GUIDE.md`](docs/ai_assistant/AI_ASSISTANT_TESTING_GUIDE.md).

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

# Loans/blockchain-focused selection (external integrations skip by default)
pytest -q tests \
  -k 'loan or blockchain or qualification or wallet_disbursement or repayment'

# Notifications-focused suite
pytest -q \
  tests/test_notifications_api.py \
  tests/test_notifications_views.py \
  tests/test_notifications_mark_read.py \
  tests/test_notification_isolation.py \
  tests/test_notifications_websocket.py \
  tests/test_websocket_notifications.py \
  tests/test_notifications_email_sender.py \
  tests/test_notifications_stage3_delivery.py \
  tests/test_notifications_stage4_privacy_persistence.py \
  tests/test_notifications_stage5_resilience_observability.py \
  tests/test_assignment_notifications.py \
  tests/test_notification_timestamps.py

# Analytics-focused suite (real-environment probes skip without opt-in flags)
pytest -q \
  tests/test_analytics_api.py \
  tests/test_analytics_stage3_integrity_lifecycle.py \
  tests/test_analytics_stage4_scope_metrics.py \
  tests/test_analytics_stage5_scalability_operations.py \
  tests/test_analytics_stage6_request_auth.py \
  tests/test_analytics_monitoring_assets.py \
  tests/test_analytics_real_mongo.py \
  tests/test_analytics_deployment_integrations.py

# AI Assistant-focused suite
pytest -q \
  tests/test_ai_stage*.py \
  tests/test_ai_model_methods.py \
  tests/test_ai_streaming.py \
  tests/test_chatbot_api.py \
  tests/test_ai_context_builder.py \
  tests/test_ai_knowledge.py \
  tests/test_ai_tool_safety_integration.py \
  tests/test_tool_safety.py \
  tests/test_context_builder.py \
  tests/test_documents_ai_consent.py \
  accounts/tests/test_field_encryption_lifecycle.py

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
installed. For local ASGI monitoring, configure `.env` and restart Daphne:

```dotenv
PROMETHEUS_METRICS_ENABLED=True
PROMETHEUS_METRICS_HTTP_SERVER_ENABLED=True
PROMETHEUS_METRICS_HTTP_SERVER_PORT=8001
PROMETHEUS_METRICS_URL=http://127.0.0.1:8001/metrics
```

Keep the exporter private. Ports `8001`, `9090`, and `3000` are local monitoring
ports and must not be exposed publicly.

### Local Analytics Monitoring with Prometheus and Grafana

Install the local monitoring tools on macOS:

```bash
brew install prometheus grafana
```

Run the following in separate terminals from the repository root. If Daphne is
already running, stop it and restart it with the first command so the metrics
settings are loaded.

```bash
# Terminal 1: backend plus private metrics sidecar on port 8001
.venv/bin/dotenv -f .env run -- \
  .venv/bin/daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Terminal 2: Prometheus
mkdir -p /tmp/capstone-analytics-prometheus-live
prometheus \
  --config.file="$PWD/monitoring/analytics/prometheus-smoke.yml" \
  --storage.tsdb.path=/tmp/capstone-analytics-prometheus-live \
  --web.listen-address=127.0.0.1:9090

# Terminal 3: Grafana with the repository-provisioned datasource/dashboard
mkdir -p /tmp/capstone-grafana-data /tmp/capstone-grafana-logs
ANALYTICS_DASHBOARD_PATH="$PWD/monitoring/analytics" \
GF_SECURITY_ADMIN_USER=admin \
GF_SECURITY_ADMIN_PASSWORD=admin \
/opt/homebrew/opt/grafana/bin/grafana server \
  --homepath /opt/homebrew/opt/grafana/share/grafana \
  --config /opt/homebrew/etc/grafana/grafana.ini \
  --packaging=brew \
  cfg:default.paths.provisioning="$PWD/monitoring/grafana/provisioning" \
  cfg:default.paths.data=/tmp/capstone-grafana-data \
  cfg:default.paths.logs=/tmp/capstone-grafana-logs \
  cfg:server.http_addr=127.0.0.1 \
  cfg:server.http_port=3000
```

Open these pages:

| Page | URL | Purpose |
| --- | --- | --- |
| Raw application metrics | `http://127.0.0.1:8001/metrics` | Inspect exported Prometheus metric families. |
| Prometheus targets | `http://127.0.0.1:9090/targets` | Confirm `capstone-analytics-smoke` is `UP`. |
| Prometheus rules | `http://127.0.0.1:9090/rules` | Inspect loaded Analytics recording and alert rules. |
| Analytics Grafana dashboard | `http://127.0.0.1:3000/d/capstone-analytics/capstone-analytics-operations` | View request, latency, size, recovery, replay, and integrity panels. |

The local Grafana bootstrap login is `admin` / `admin`. Replace it if Grafana
prompts. These credentials are for this localhost-only development instance and
must never be used in production.

To generate visible customer traffic with Insomnia:

1. Log in through the customer authentication endpoint.
2. Copy the returned access token.
3. Send an authenticated request:

```http
GET http://127.0.0.1:8000/api/analytics/customer/
Authorization: Bearer <customer-access-token>
```

4. In Grafana, select **Last 5 minutes** and refresh. The request-rate, latency,
   and response-size panels should populate within a few seconds.

A login creates an audit event, but the login endpoint itself does not increment
`analytics_requests_total`; the authenticated Analytics request above does.
Metrics intentionally omit email addresses, tokens, customer IDs, IP addresses,
request bodies, and stored event details.

Verify configuration and alert behavior from the command line:

```bash
promtool check config monitoring/analytics/prometheus-smoke.yml
promtool check rules monitoring/analytics/prometheus-rules.yml

cd monitoring/analytics
promtool test rules prometheus-rules.test.yml
cd ../..

pytest -q tests/test_analytics_monitoring_assets.py
```

Stop each foreground service with `Ctrl+C`. Local Prometheus and Grafana data
are stored under `/tmp`; remove those directories after stopping the services
when the history is no longer needed:

```bash
rm -rf /tmp/capstone-analytics-prometheus-live
rm -rf /tmp/capstone-grafana-data /tmp/capstone-grafana-logs
```

Analytics metrics include request outcomes, duration, response size, audit-write
failures, replay outcomes, recovery backlog/age, and integrity findings.
Notifications metrics cover REST outcomes/latency, durable and per-channel
delivery outcomes, retry/terminal backlog and oldest age, token invalidation,
WebSocket connections/actions/broadcasts, and metrics-collector freshness. Use
the assets under `monitoring/notifications/` and the operator commands in
[`docs/NOTIFICATIONS_TESTING_GUIDE.md`](docs/NOTIFICATIONS_TESTING_GUIDE.md).
The final read-only Notifications gate is intentionally fail-closed:

```bash
.venv/bin/python manage.py notifications_release_check
.venv/bin/python manage.py notifications_release_check --json
```

Prometheus rules, rule tests, a smoke configuration, and the Notifications
Grafana dashboard are under `monitoring/notifications/`. Generate authenticated
REST/WebSocket traffic and synthetic delivery outcomes before concluding that
an empty panel is a monitoring failure.

AI Assistant metrics cover API/provider/tool outcomes and latency, token usage,
active streams, budget rejection, and audit/persistence failures. Prometheus
rules, a smoke configuration, and an importable Grafana dashboard are under
`monitoring/ai_assistant/`. Generate authenticated chat or streaming traffic to
populate the AI series, and use the testing guide for the deployment validation
sequence.

Loans metrics cover API/lifecycle/settlement outcomes and latency, delivery
outcomes, worker/job freshness, integrity findings, and critical backlog counts
and age. Prometheus rules, rule tests, a smoke configuration, and the Grafana
dashboard are under `monitoring/loans/`. If blockchain is disabled, wallet/chain
panels are expected to remain inactive while cash/check monitoring remains
required.

Profiles metrics cover scoring outcomes/backlogs, duplicate records, encryption
coverage, audit recovery, review queues, and denied access. See
[`docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md`](docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md).

For production monitoring, use private service discovery, persistent protected
storage, a non-default Grafana administrator credential, authentication/TLS,
and a tested Alertmanager or Grafana contact point. See
[`docs/analytics/ANALYTICS_TESTING_GUIDE.md`](docs/analytics/ANALYTICS_TESTING_GUIDE.md) for release
checks and production-topology boundaries.

Notification email and push work runs through the dedicated Celery queue; there
is no in-process notification email thread pool.

## Documentation

- [Accounts production readiness](docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md)
- [Accounts testing guide](docs/accounts/ACCOUNTS_TESTING_GUIDE.md)
- [Profiles production readiness](docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md)
- [Profiles testing guide](docs/profiles/PROFILES_TESTING_GUIDE.md)
- [Documents production readiness](docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md)
- [Documents testing guide](docs/documents/DOCUMENTS_TESTING_GUIDE.md)
- [Loans module status](docs/LOANS_PRODUCTION_READINESS_REVIEW.md)
- [Loans testing guide](docs/LOANS_TESTING_GUIDE.md)
- [Notifications module status](docs/NOTIFICATIONS_PRODUCTION_READINESS_REVIEW.md)
- [Notifications testing guide](docs/NOTIFICATIONS_TESTING_GUIDE.md)
- [Analytics module status](docs/analytics/ANALYTICS_PRODUCTION_READINESS_REVIEW.md)
- [Analytics testing guide](docs/analytics/ANALYTICS_TESTING_GUIDE.md)
- [AI Assistant module status](docs/ai_assistant/AI_ASSISTANT_PRODUCTION_READINESS_REVIEW.md)
- [AI Assistant testing guide](docs/ai_assistant/AI_ASSISTANT_TESTING_GUIDE.md)
- [API reference](docs/feats/API_REFERENCE.md)
- [Deployment and operations](docs/feats/DEPLOYMENT_AND_OPERATIONS_GUIDE.md)
