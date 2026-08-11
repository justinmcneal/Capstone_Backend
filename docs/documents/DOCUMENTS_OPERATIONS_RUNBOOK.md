# Documents Operations Runbook

Last updated: 2026-08-11

This runbook covers private object storage, retention, legal holds, account
deletion cleanup, consistency inventory, monitoring, backup/restore, and the
isolated-environment release gate. Commands that inspect S3 or MongoDB must be
pointed only at the intended environment and are read-only unless an explicit
`--apply` is shown.

## Storage requirements

Production must use `DOCUMENT_STORAGE_BACKEND=s3`. The bucket must have all four
S3 public-access-block controls enabled, `BucketOwnerEnforced` ownership,
default AES-256 or KMS encryption, versioning where supported, and no public or
custom-domain document delivery. Downloads use short-lived SigV4 URLs. CORS must
name exact customer origins and only the headers and POST/PUT methods required
by the presigned workflow; never use `*` origins.

The application identity needs only the configured bucket/prefix operations:
list the document/quarantine prefixes, get/head/put/copy/delete objects, abort
multipart uploads, and use the selected KMS key when applicable. It must not
administer buckets, policies, ACLs, or unrelated prefixes. Prefer workload
identity over long-lived access keys.

Read-only validation:

```bash
python manage.py validate_document_storage
```

This checks public access, encryption, ownership, CORS, and URL expiry. Review
the deployed IAM policy and bucket lifecycle/versioning separately because the
application identity should not require policy-administration permission.

## Retention and legal holds

`DOCUMENT_RETENTION_POLICY_VERSION` identifies the approved policy applied to
new records. `DOCUMENT_RETENTION_DAYS` is the normal deadline; rejected and
superseded records use their shorter settings. The daily retention task only
claims due, non-held records. The storage reconciler then deletes storage and
metadata, retaining retry state if either operation fails.

Legal-hold changes are dry-run by default:

```bash
python manage.py manage_document_legal_hold DOCUMENT_ID --action set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID"
python manage.py manage_document_legal_hold DOCUMENT_ID --action set \
  --reason "CASE_REFERENCE" --operator "ADMIN_ID" --apply
python manage.py manage_document_legal_hold DOCUMENT_ID --action release \
  --operator "ADMIN_ID" --apply
```

Use an approved case reference, record the operator and approval in the change
system, and confirm the object before `--apply`. Held records remain after
account anonymization until release and subsequent cleanup.

## Account deletion and consistency inventory

Account deletion is complete only when both `profile_cleanup_status` and
`document_cleanup_status` are `complete`. Non-held objects enter
`delete_pending`; active upload sessions expire and use their normal cleanup
task. Legal-held records are counted as retained and do not block account
anonymization.

Run the count-only inventory immediately before production index/storage work,
after restore, and during incident investigation:

```bash
python manage.py inventory_document_storage
```

It reports aggregate missing/orphan objects, expired upload sessions, storage and
lifecycle contradictions, missing retention metadata, incomplete legal holds,
deleted-customer records, retention-due records, and legal holds. It never
prints keys, paths, filenames, or customer IDs and performs no correction.
Investigate non-zero findings before an approved corrective action.

## Malware scanner and PDF policy

Production requires `DOCUMENT_MALWARE_SCAN_ENABLED=True` and
`DOCUMENT_MALWARE_SCAN_REQUIRED=True`. Run the configured ClamAV daemon on a
private application network; do not expose TCP 3310 publicly. Restrict network
access to the API workloads, keep signatures updated, and set ClamAV's stream
maximum above the application's 10 MB upload limit. The application timeout and
chunk settings must remain within the startup-validated bounds.

`/api/health/` reports a sanitized `document_malware_scanner` component. Verify
clean, detected, timeout, invalid-response, and unavailable cases in the
isolated deployment environment. Alert when required readiness fails or
`documents_operations_total{operation="malware_scan",outcome="unavailable"}`
increases. Neither metrics nor logs may contain content, filenames, scanner
signatures, hashes, or customer identifiers.

Keep `DOCUMENT_PDF_UPLOAD_POLICY=disabled` unless security owners explicitly
approve scanner-only PDFs or provide a separate approved sandbox/CDR boundary.
ClamAV detects known malware but does not disarm arbitrary active PDF content.

## Monitoring and alerts

Scrape the `documents_*` Prometheus metrics. Alert when:

- upload/finalize or URL-generation error rates rise above baseline;
- storage, notification, AI, or audit failure backlog remains non-zero for two
  collection intervals;
- storage/notification/AI oldest age exceeds its worker retry objective;
- review backlog age exceeds the business review SLA;
- expired upload sessions or retention-due records continue growing;
- inventory reports missing or contradictory state, or a sustained orphan count
  after the upload-session grace period.

Correlate alerts with Celery worker/Beat health and sanitized structured logs.
Logs/metrics must not contain filenames, object paths, content, presigned URLs,
hashes, free-text review reasons, or customer PII.

## Backup and restore

Back up MongoDB metadata and object storage as one documented recovery set with
encryption, access logging, retention, and restore testing. Preserve bucket
versions needed for the recovery window while respecting approved retention and
legal holds. A restore test must confirm:

1. MongoDB indexes and TTL indexes are restored or recreated.
2. Encrypted metadata decrypts with the approved key version.
3. A sampled allowlisted set has matching object/metadata state.
4. Presigned downloads work only for authorized detail requests.
5. Reconciliation resumes without duplicate documents or notifications.
6. Inventory has no unexplained missing, orphan, contradictory, or
   deleted-customer findings.

Never run restore tooling against production as a smoke test. Use an isolated,
access-controlled recovery environment and retain the evidence/change record.

## Final release validation

Before release, use an isolated deployment-like environment to validate real
MongoDB indexes/concurrency, full S3 session/upload/finalize/replay/cleanup,
Redis/Celery leases and retries, ClamAV clean/detected/outage behavior and
signature updates, encryption-key access/rotation, trusted proxies, throttles,
sanitized logging, backup restore, metrics, and alerts. Only then enable
`DOCUMENT_PRESIGNED_UPLOAD_ENABLED=True`. Unit tests do not satisfy this
environmental gate.

Opt-in harnesses exist for the destructive portions and remain skipped unless
their explicit environment gates are present:

```bash
REAL_MONGO_TEST_URI='mongodb://isolated-test-host/' \
pytest -q -m real_mongo tests/test_stage9_real_mongo.py

REAL_S3_TEST_BUCKET='isolated-documents-bucket' \
REAL_S3_TEST_REGION='us-east-1' \
REAL_S3_TEST_ALLOW_MUTATION=yes \
pytest -q -m real_s3 tests/test_documents_real_s3.py

REAL_CLAMAV_TEST_HOST='clamav.internal' \
REAL_CLAMAV_TEST_ALLOW_SCAN=yes \
pytest -q -m real_clamav tests/test_documents_real_clamav.py
```

The ClamAV harness proves readiness and clean/detected verdicts using only
synthetic content. Validate fail-closed outage behavior separately by making the
scanner unavailable in the isolated environment and confirming `/api/health/`
and uploads return `503`; do not stop a shared or production scanner for this
test.

## Development Stage 7 evidence

On 2026-08-11, the Documents real-Mongo pagination/index and concurrent-review
tests passed against randomly named temporary databases. A temporary
loopback-only Redis with persistence disabled and a Celery worker restricted to
a dedicated validation queue returned a successful control ping; both were then
stopped. A process-only production configuration profile passed Django's
deployment check with S3, non-CNN mode, required ClamAV, Redis cache, HTTPS,
HSTS, and secure cookies selected.

The count-only development inventory reported one orphaned local-storage object
and no other consistency, retention, legal-hold, or deleted-customer findings.
Do not delete the orphan without resolving its exact ownership and retention
requirements. This development evidence does not satisfy S3 IAM/bucket,
ClamAV, encryption-key rotation, proxy, restore, logging, metrics, or alert
validation in the eventual deployment environment.
