## Release PR: Railway staging → production

Summary
- Deploy backend to Railway (staging) and run smoke tests before production cutover.

What this PR contains
- Infra changes (if any): Terraform templates, bucket names, IAM policy references.
- Application changes: branch to deploy (commit range listed in the PR).
- New or updated runbooks: `docs/RAILWAY_PRODUCTION_DEPLOYMENT_AND_SMOKE_TESTS.md` and `docs/INFRA_HANDOFF.md`.

Action for infra (reviewers)
1. Provision S3 bucket and KMS per `docs/PRODUCTION_S3.md` (if `DOCUMENT_STORAGE_BACKEND=s3`).
2. Add Railway variables exactly as named in `docs/RAILWAY_PRODUCTION_DEPLOYMENT_AND_SMOKE_TESTS.md`.
3. Deploy to Railway staging and confirm web + worker services start.
4. Run staging smoke tests (see commands below) and paste the run output into the PR thread.
5. After sign-off, replicate env vars in Railway production and deploy during the approved maintenance window.

Smoke-test commands (run from repository root)

```bash
# export staging target
export SMOKE_BASE_URL=https://<staging-host>

# Option A: run with email/password (runner will create the user if missing)
export SMOKE_EMAIL=smoke+runner@example.com
export SMOKE_PASSWORD=Test1234
python scripts/smoke_test_railway.py --base-url "$SMOKE_BASE_URL" --email "$SMOKE_EMAIL" --password "$SMOKE_PASSWORD"

# Option B: run with pre-generated token
export SMOKE_ACCESS_TOKEN=<jwt>
python scripts/smoke_test_railway.py --base-url "$SMOKE_BASE_URL" --access-token "$SMOKE_ACCESS_TOKEN"
```

What to paste into the PR after running smoke tests
- `health` output JSON
- `auth` signup/login responses (redact tokens if needed)
- `document upload` response JSON and confirmation that S3 object exists (if s3)
- Any failures, stack traces or logs from web/worker during test run

Acceptance criteria
- All smoke-test steps pass without 5xx errors.
- No fatal exceptions in web or worker logs during the test window.
- Infra confirms S3/KMS policies are correct and objects accessible with presigned URLs.

Rollback plan
- Railway rollback to previous release (UI) and/or set `DOCUMENT_STORAGE_BACKEND=local` and redeploy.

Notes
- This PR template is intentionally short — use the runbook for full steps and commands.
