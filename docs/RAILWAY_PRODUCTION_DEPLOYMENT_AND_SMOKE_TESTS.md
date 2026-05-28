## Railway Production Deployment & Smoke Tests (Checklist)

Purpose
This file is the exact rollout checklist and environment-variable reference to deploy the backend to Railway (staging → production) and run a repeatable smoke-test sequence. Use this as the single source of truth for infra handoff.

Read first
- [docs/INFRA_HANDOFF.md](docs/INFRA_HANDOFF.md)
- [docs/MIGRATION_BACKUP_AND_FAQ.md](docs/MIGRATION_BACKUP_AND_FAQ.md)
- [docs/PRODUCTION_S3.md](docs/PRODUCTION_S3.md)

Preconditions
- CI for the target branch is green and the branch has been merged.
- Staging Railway project is provisioned and reachable.
- Infra has provisioned S3/KMS and provided credentials if `DOCUMENT_STORAGE_BACKEND=s3`.
- MongoDB backups and media snapshots taken (see MIGRATION_BACKUP_AND_FAQ).

Railway secrets / env var canonical list (exact names to set in Railway)
Set these as Railway project variables/secrets. For Railway UI use the same names below. Sample placeholders show expected format.

- `DEBUG` = "False"
- `SECRET_KEY` = "<Django secret, 50+ chars>"
- `SECRET_PEPPER` = "<random pepper used for hashing>"
- `ALLOWED_HOSTS` = "<staging.example.com,production.example.com>"
- `MONGODB_URI` = "mongodb+srv://<user>:<password>@cluster0.mongodb.net/?retryWrites=true&w=majority"
- `MONGODB_NAME` = "capstone_db"
- `DOCUMENT_STORAGE_BACKEND` = "s3"  # or "local"

If using S3 (exact Railway secrets)
- `AWS_ACCESS_KEY_ID` = "<AKIA...>"
- `AWS_SECRET_ACCESS_KEY` = "<secret>"
- `AWS_STORAGE_BUCKET_NAME` = "capstone-media-production"
- `AWS_S3_REGION_NAME` = "us-east-1"
- `AWS_S3_CUSTOM_DOMAIN` = "<optional custom domain>"

Other optional/operational vars
- `GROQ_API_KEY` = "<llm or search api key>"
- `SENTRY_DSN` = "<sentry dsn>"
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `CORS_ALLOWED_ORIGINS` = "https://my-frontend.example.com"
- `CSRF_TRUSTED_ORIGINS` = "https://my-frontend.example.com"

How to set Railway secrets (quick)
1. Railway UI: Project → Variables → Add the exact name/value pairs from this list.
2. Railway CLI (example):

```bash
railway variables set SECRET_KEY="$(openssl rand -hex 32)" --project <project_id>
railway variables set MONGODB_URI="${MONGODB_URI}" --project <project_id>
```

Staging deployment checklist (exact steps)
1. Merge PR and confirm GitHub Actions CI passed for the target branch.
2. In Railway staging project: set the env vars from the canonical list above.
3. Deploy from the target branch (Railway auto-deploy or manual deploy).
4. Run DB migrations (if your deploy process does not run them automatically):

```bash
railway run --command "python manage.py migrate" --project <project_id>
```

5. Ensure background workers (Celery) are configured as a separate service in Railway and that their env vars match the web service.
6. Wait until web service health endpoint is responding (below).

Health check (quick)

```bash
curl -fsS https://<staging-host>/api/health/ | jq
```

Expect JSON with service and DB status fields and any AI/LLM checks.

Repeatable smoke test (automated)
Use `scripts/smoke_test_railway.py` — it supports `--base-url`, `--email/--password` or `--access-token`, and flags to skip optional checks.

Examples

Run the full smoke test with credentials provided as Railway variables:

```bash
export SMOKE_BASE_URL=https://<staging-host>
export SMOKE_EMAIL=smoke+runner@example.com
export SMOKE_PASSWORD=Test1234
python scripts/smoke_test_railway.py --base-url "$SMOKE_BASE_URL" --email "$SMOKE_EMAIL" --password "$SMOKE_PASSWORD"
```

Run using a pre-generated token:

```bash
export SMOKE_BASE_URL=https://<staging-host>
export SMOKE_ACCESS_TOKEN=<jwt>
python scripts/smoke_test_railway.py --base-url "$SMOKE_BASE_URL" --access-token "$SMOKE_ACCESS_TOKEN"
```

GitHub Actions (manual workflow)
- The repository includes `.github/workflows/railway-smoke-tests.yml`. It is manually triggered and expects repository secrets named `SMOKE_ACCESS_TOKEN` or `SMOKE_EMAIL`/`SMOKE_PASSWORD` and `SMOKE_BASE_URL`.

Exact smoke test validation steps (what must pass)
1. `health` returns HTTP 200 and all subcomponents OK.
2. `auth` signup/login returns 200/201 and a usable token.
3. `document upload` returns 201 and the `file_url` (and if S3, the object exists in the bucket).
4. `document list/detail/delete` perform as expected (list contains created doc, detail returns metadata, delete removes it).
5. `loans` base endpoints return 200 and expected payload shapes.
6. Background worker jobs start and do not throw fatal exceptions in logs during basic tasks.

Production cutover (after staging sign-off)
1. Ensure staging smoke tests passed and infra approved the S3/bucket/kms configuration.
2. In Railway production project: set env vars (same canonical names) — ensure `DOCUMENT_STORAGE_BACKEND` is set to `s3` only after S3 and IAM are provisioned and tested.
3. Deploy production release (manual or CI-driven). Run DB migrations as needed.
4. Run smoke tests against production (ideally in maintenance window) and monitor logs/errors.

Rollback actions (exact)
- Use Railway UI to roll back to the previous successful deployment.
- If the failure is S3-specific, set `DOCUMENT_STORAGE_BACKEND=local` in production env vars and redeploy to restore prior file handling.
- If DB corruption detected, follow `docs/MIGRATION_BACKUP_AND_FAQ.md` to restore MongoDB from backup and redeploy.

Troubleshooting quick tips
- Health 500: verify `MONGODB_URI`, network access, and Atlas IP allowlists.
- Auth 401/403: verify `SECRET_KEY` and `SECRET_PEPPER` match across services and token signing settings.
- Presigned upload failures: validate `AWS_*` credentials, bucket policy, and `AWS_S3_REGION_NAME`.

Contacts & sign-off
- Provide infra with a link to this file and request: "Please provision S3, add the Railway variables above, then run staging smoke tests and report results." Leave a timestamped approval comment when staging passes.

This file is intentionally prescriptive: set the exact variable names shown in Railway, run the automated smoke test, and only cut over production after a successful staging run and infra sign-off.
