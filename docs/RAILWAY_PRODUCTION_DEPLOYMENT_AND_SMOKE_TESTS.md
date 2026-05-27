# Railway Production Deployment & Smoke Tests

This runbook covers deploying the backend to Railway (production/staging) and a concise smoke‑test sequence to validate core flows after cutover.

Related docs (read first):
- `docs/DEPLOYMENT_AND_OPERATIONS_GUIDE.md` — canonical deployment vars and architecture
- `docs/INFRA_HANDOFF.md` — infra handoff checklist and migration run order
- `docs/MIGRATION_BACKUP_AND_FAQ.md` — DB/media backup commands and migration FAQ
- `docs/PRODUCTION_S3.md` — S3 deployment notes, IAM policy, presigned uploads
- `docs/API_REFERENCE.md` — endpoints used in smoke tests

Preconditions
- Have a staging Railway project and a production Railway project (or equivalent). Do not run production cutover until staging smoke tests pass.
- Ensure GitHub Actions CI passes on the branch to be deployed.
- Obtain or ask infra to provision S3/KMS if `DOCUMENT_STORAGE_BACKEND=s3` will be used.
- Backup MongoDB and snapshot local media (see `docs/MIGRATION_BACKUP_AND_FAQ.md`).

Environment variables (minimum)
- `DEBUG=False`
- `SECRET_KEY`, `SECRET_PEPPER`
- `ALLOWED_HOSTS` (include Railway host)
- `MONGODB_URI`, `MONGODB_NAME`
- `GROQ_API_KEY` (LLM)
- `DOCUMENT_STORAGE_BACKEND` (`local` or `s3`)
- If `s3`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN` (optional)
- `EMAIL_*` settings, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`

Deployment checklist (staging)
1. Confirm CI green and open PR merged to the target branch.
2. Provision staging Railway app and set environment variables from the canonical list.
3. (If using S3) Ensure bucket, policies, and GitHub secrets are configured for staging.
4. Deploy the app on Railway and wait for the service to start.
5. Run database migrations (if any) and ensure Celery/worker processes are running if required.
6. Run quick health check:

```bash
curl -fsS https://<staging-host>/api/health/ | jq
```

Smoke test sequence (staging)
Run these in order and record outputs. Replace `<host>` with staging host.

1) Health
```bash
curl -sS https://<host>/api/health/ | jq
```
Expect: MongoDB + AI status OK

2) Auth (signup -> login)
```bash
curl -sS -X POST https://<host>/api/auth/signup/ -H 'Content-Type: application/json' -d '{"email":"smoke+1@example.com","password":"Test1234"}' | jq
# then login
curl -sS -X POST https://<host>/api/auth/login/ -H 'Content-Type: application/json' -d '{"email":"smoke+1@example.com","password":"Test1234"}' | jq
```
Expect: user created or exists, login returns JWT

3) Document upload (API flow)
- If `DOCUMENT_STORAGE_BACKEND=local`: upload a small PDF image via `/api/documents/upload/` and confirm created document ID and `file_url` resolves.
- If `DOCUMENT_STORAGE_BACKEND=s3`: either use presigned POST from `/api/documents/presigned-upload/` (if implemented) or call `/api/documents/upload/` and ensure S3 object is created.

Example (local):
```bash
curl -sS -H "Authorization: Bearer $TOKEN" -F "file=@./tests/fixtures/minimal.pdf" -F "document_type=valid_id" https://<host>/api/documents/upload/ | jq
```

Expect: 201 Created, `file_url` accessible (or presigned URL returned)

4) Document list / detail / delete
```bash
curl -sS -H "Authorization: Bearer $TOKEN" https://<host>/api/documents/ | jq
curl -sS -H "Authorization: Bearer $TOKEN" https://<host>/api/documents/<document_id>/ | jq
curl -sS -X DELETE -H "Authorization: Bearer $TOKEN" https://<host>/api/documents/<document_id>/ | jq
```
Expect: list returns document, detail returns metadata and file_url, delete returns success

5) Loans flow (basic)
```bash
curl -sS -H "Authorization: Bearer $TOKEN" https://<host>/api/loans/products/ | jq
curl -sS -H "Authorization: Bearer $TOKEN" -X POST https://<host>/api/loans/pre-qualify/ -H 'Content-Type: application/json' -d '{"income":10000}' | jq
```
Expect: products list, pre-qualify returns expected data

6) Analytics & notifications (admin/officer)
- If possible, exercise an admin path to hit `/api/analytics/admin/` and `/api/notifications/` to confirm role-based endpoints.

7) Background jobs
- Verify Celery worker(s) started and scheduled tasks are running (logs), or run a simple task if available.

Smoke test automation (recommended)
- Add a minimal smoke test script (bash or pytest) in `scripts/` or `tests/integration/smoke_tests.py` that runs the above steps using a staging token. Keep tests idempotent.
- Example: `tests/integration/test_smoke_endpoints.py` that uses a staging test account and asserts 200/201 responses for each endpoint.

Post-deploy verification
- Check logs for errors and repeated exceptions during the first 30 minutes.
- Confirm Sentry (or error tracking) has no new critical issues.
- If S3 is used, verify objects exist in the bucket and permissions/presigned URLs function.

Rollback steps
- If failures are critical, revert to the previous release in Railway (use Railway rollback feature) and restore env vars.
- If issue is S3-related, flip `DOCUMENT_STORAGE_BACKEND` back to `local` in staging and production envs and redeploy.
- Restore MongoDB from backup if migration corrupted data (follow `docs/MIGRATION_BACKUP_AND_FAQ.md`).

Troubleshooting hints
- 500 on health endpoints: check MongoDB connection string and Atlas IP whitelist.
- Auth failures: confirm JWT secret and token signing settings.
- File errors: check `MEDIA_ROOT` permissions (when local) or S3 IAM policy (when s3).

Handoff
- Provide infra with `docs/INFRA_HANDOFF.md` and this runbook; run staging smoke tests and sign-off before production cutover.

Notes
- This file centralizes Railway-specific run steps; many modules already include smoke test sequences (search `"Smoke Test"` in `docs/`), adapt them into the scripted smoke tests for automation.
