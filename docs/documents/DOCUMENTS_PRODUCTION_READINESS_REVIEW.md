# Documents Module Documentation and Status

Last updated: 2026-08-12

## Overview

The `documents` module manages customer document upload, validation, private
storage, retrieval, review, replacement, deletion, retention, and integration
with loan qualification. It uses Django REST Framework for the API, PyMongo for
metadata and workflow state, local or S3-compatible object storage for file
content, Celery for recoverable background work, and Redis for Celery and
optional shared caching.

The module supports two upload paths:

- a server-mediated multipart upload available to customer clients; and
- an optional S3 presigned workflow that uploads into quarantine and creates a
  document only after an owner-bound finalization request validates the object.

The approved production baseline does not use CNN or image-quality inference.
Documents pass structural checks, resource limits, the configured PDF policy,
and fail-closed malware scanning before an authorized person reviews them.

Detailed endpoint examples and validation procedures are maintained in
`docs/documents/DOCUMENTS_TESTING_GUIDE.md`. This document describes the
implemented module, its current API and security posture, operational contract,
and the evidence still required from the eventual deployment environment.

## Current Status

**Module implementation status: Complete for the approved non-CNN baseline**

**Production deployment status: Ready for production-environment validation**

All application-code gaps identified during the Documents review have been
addressed and the local automated suites are clean. Production approval still
depends on proving the configured S3/IAM, private ClamAV, Redis/Celery,
encryption-key, proxy, backup/restore, logging, metrics, and alerting behavior in
the selected deployment topology.

| Area | Status | Summary |
| --- | --- | --- |
| Direct upload | Implemented | Customer multipart upload includes structural validation, malware enforcement, durable storage, metadata creation, audit, and follow-up work. |
| Presigned upload | Implemented; deployment-gated | Owner-bound, single-use quarantine sessions and idempotent finalization are available but disabled by default. |
| Document review | Implemented | Scoped officers/admins can approve, reject, or request re-upload with atomic lifecycle transitions. |
| Retrieval and listing | Implemented | Role-scoped, indexed, bounded metadata listing and authorized on-demand URL issuance are available. |
| Storage consistency | Implemented | Failed object operations enter retryable cleanup or deletion workflows. |
| Privacy and authorization | Implemented | Ownership, officer assignment scope, reviewer permissions, encrypted metadata, and audit controls are enforced. |
| Notifications | Implemented | Reviewer and customer deliveries use an encrypted, leased, retryable outbox. |
| Retention and account lifecycle | Implemented | Versioned retention, legal holds, expiry, export, and account-deletion cleanup are available. |
| Malware scanning | Implemented; deployment proof pending | Required production scans fail closed; private ClamAV behavior must be proven in the target environment. |
| AI/CNN | Deliberately disabled | The production baseline sets `DOCUMENT_UPLOAD_AI_ANALYSIS=False` and requires human review. |
| Local automated validation | Passing | Latest full run: 1,058 passed and 21 opt-in integration tests skipped. |
| Deployment validation | Pending | Real S3/IAM, ClamAV, key rotation, proxies, restore, monitoring, and alert evidence remain. |

## Module Responsibilities

### Document lifecycle and persistence

Documents are stored in the MongoDB `documents` collection through PyMongo.
The canonical lifecycle states are `pending`, `needs_review`, `approved`,
`rejected`, and `expired`.

- `pending` may move to `needs_review`, `approved`, or `rejected`.
- `needs_review` may be refreshed or move to `approved` or `rejected`.
- `rejected` may return to `needs_review` through an explicit re-upload request.
- `approved` and `expired` are terminal.
- Replacing an approved document creates a new linked record instead of
  rewriting the earlier review history.

Mutations carry a `revision`. Review, re-upload, supersession, and delete claims
use narrow compare-and-set writes, and stale requests return HTTP 409. Legacy
`verified` fields remain for client compatibility, but `status` is canonical
and current writes normalize the compatibility fields.

Indexes cover owner, document type, status, upload time, upload session, common
role/listing query shapes, deterministic `uploaded_at`/`_id` ordering, session
expiry, and background-work reconciliation. Index creation is wired through the
project's PyMongo initialization path rather than Django ORM migrations.

### Direct upload

`POST /api/documents/upload/` accepts a customer-owned multipart upload of at
most 10 MB. JPEG, PNG, and policy-permitted PDF files are supported. The API:

1. validates type, description, size, signature, executable markers, and
   image/PDF structural rules;
2. streams the bounded file to ClamAV when scanning is enabled;
3. stores the object under a server-generated path;
4. creates the MongoDB record and replacement lineage;
5. records the audit event and schedules reviewer notification; and
6. schedules optional analysis only when that development feature is enabled.

If metadata creation fails after object storage, the service tries an immediate
rollback and persists an encrypted cleanup item if deletion also fails.

### Presigned quarantine and finalization

The optional S3 flow is controlled by
`DOCUMENT_PRESIGNED_UPLOAD_ENABLED=False`. Session issuance binds the owning
customer, type, sanitized filename, exact byte length, MIME type, SHA-256,
expiry, quarantine key, and a one-time finalize secret. Only the secret's hash
is stored.

The client submits every returned S3 form field and then calls the finalize
endpoint. Finalization atomically claims the session, confirms ownership and
secret, heads and downloads the object, verifies its metadata and computed
content properties, scans it, promotes it to a server-generated durable key,
and creates one `Document` record. `upload_session_id` is uniquely indexed, so a
successful replay returns the existing document rather than creating another.

A scanner outage restores the session to a retryable state, leaves the object
quarantined, and returns HTTP 503. Permanent validation failures invalidate the
session and clean the object. Celery Beat removes expired and abandoned
quarantine objects. This flow must remain disabled until the target bucket,
IAM, CORS, scanner, and cleanup behavior pass deployment validation.

### Validation and malware boundary

The upload boundary enforces:

- a MIME allowlist and 10 MB application limit;
- declared MIME and file-signature agreement;
- rejection of common PE, ELF, Mach-O, and Java executable signatures;
- Pillow decoding, dimensions, pixel-count, and decompression-bomb limits for
  JPEG and PNG;
- a bounded full-file scan for selected active PDF markers; and
- fail-closed ClamAV streaming for direct and presigned content.

Production requires `DOCUMENT_MALWARE_SCAN_ENABLED=True` and
`DOCUMENT_MALWARE_SCAN_REQUIRED=True`. A detection receives a generic rejection,
while a missing, timed-out, or invalid scanner verdict returns HTTP 503. ClamAV
is not a sandbox or content-disarm-and-reconstruction service. The production
default therefore uses `DOCUMENT_PDF_UPLOAD_POLICY=disabled`; changing it to
`scan` requires explicit acceptance of scanner-only PDF risk or a separately
approved sandbox/CDR boundary.

### Storage and delivery

`LocalStorageBackend` is intended for development. It stores generated names
under a customer/type hierarchy and supports save, delete, URL generation, and
byte retrieval.

`S3StorageBackend` is required for production. It supports ordinary and
multipart upload, retry, deletion, object copy/promotion, presigned POST,
short-lived presigned GET, and byte retrieval. Production objects must remain
private; clients receive no public or stable object URL.

List responses are metadata-only and deliberately return `file_url: null`. A
short-lived file URL is minted only after an authorized detail request. Stored
paths and original filenames are encrypted fields and must not be logged,
placed in metrics, or exposed in inventory output.

### Listing and search

List scope, filter, count, deterministic sort, skip, and bounded limit execute
in MongoDB before decryption. Page size is limited to 1–200 and ordering is
`uploaded_at` descending followed by `_id` descending. Customer display names
for one page are bulk-resolved with one bounded query.

Search is intentionally limited to indexed exact document type, document ID,
or customer ID. Filename and free-text customer-name searches are rejected.
Clients should use the scoped Profiles directory to resolve a customer and then
filter Documents by the returned ID.

### Human review and replacement

Loan officers and administrators with `review_documents` may approve, reject,
or request re-upload. Officers are further limited by shared customer-resource
scope derived from application assignment, eligible unassigned work, or earlier
approval. Administrators and super administrators have broader document access
by design.

Review and re-upload writes validate the current state and optional revision.
Approved and expired records cannot be reopened. Replacement uploads retain
forward and backward lineage using `replaces_document_id` and
`superseded_by_document_id`.

### Deletion and storage reconciliation

An owning customer may delete only an unverified `pending`, `needs_review`, or
`rejected` document. The record is atomically claimed before object deletion,
which prevents review/delete races. Approved, verified, and expired documents
cannot be deleted through the customer endpoint.

Deletion uses `delete_pending` and `delete_failed` storage states. The scheduled
reconciler retries object deletion and removes metadata only after deletion is
satisfied. Failed direct-upload and finalization rollback operations use the
encrypted `document_storage_cleanup` queue and idempotent retry processing.

### Audit and notification delivery

Audit events cover upload/finalize, review, re-upload, delete, privileged list
and detail reads, and denied sensitive reads. Staff-sensitive reads fail closed
if their required audit record cannot be confirmed. Post-commit mutation audit
failures use an allowlisted recovery queue so a committed document mutation is
not falsely reported as failed.

Reviewer and customer outcome notifications are stored in the encrypted
`document_notification_deliveries` outbox before publication. Unique delivery
keys, leases, bounded backoff, idempotent in-app delivery, and scheduled
reconciliation make broker and provider failures recoverable. Reviewer
recipients must be active, permitted, and within the customer's assignment
scope.

### Retention, legal holds, and account lifecycle

New records receive a versioned retention deadline. Rejected and superseded
records may use shorter configured periods. The daily task claims due records
only when no active legal hold applies, after which normal storage
reconciliation removes content and metadata.

Legal-hold operations are dry-run by default and record the case reference,
operator, and timestamps. Held document records and objects survive customer
anonymization until the hold is released and normal retention cleanup becomes
eligible.

Customer deletion expires active upload sessions and moves non-held documents
through retryable deletion. Account cleanup is complete only when both profile
and document cleanup statuses are complete. Customer export returns safe
account-owned document metadata and never embeds private object content or
long-lived URLs.

### Loan and profile integration

The document-type endpoint can return baseline or product-specific required
types. Profile summaries expose document counts and status summaries. Authorized
loan views can expose customer document status, and loan qualification may
require the latest document of every required type to be approved.

### Non-CNN production baseline

Production must set `DOCUMENT_UPLOAD_AI_ANALYSIS=False`. No CNN or quality-only
inference runs, model readiness does not determine Documents health, and every
approval remains a human decision. Signature validation, resource controls,
PDF policy, ClamAV, and normal review remain active.

The optional analysis implementation remains available for development and a
future separately approved feature. It is asynchronous, consent-aware,
leased/retryable, versioned, integrity-gated, and unable to override a human
decision. It may only advise review priority or set an unreviewed upload to
`needs_review`; it must never approve/reject a document, determine eligibility,
infer identity, or establish authenticity, ownership, expiry, tampering, or
face match.

The current repository does not contain an approved model artifact or adequate
dataset evidence. The inventoried data is imbalanced, contains duplicate and
cross-split samples, has underpowered class holdouts, and lacks complete
provenance/privacy approval. This does not block the non-CNN release, but it
prohibits optional CNN enablement and does not authorize data reuse or
distribution.

## API Status

All routes are under `/api/documents/`.

| Method and route | Role/scope | Status | Purpose |
| --- | --- | --- | --- |
| `POST upload/` | Customer | Implemented | Validate and durably upload a document. |
| `POST presigned-upload/` | Customer | Implemented; disabled by default | Create an owner-bound quarantine session and presigned POST. |
| `POST presigned-upload/<session_id>/finalize/` | Owning customer | Implemented; disabled with issuance | Validate/promote the object and create the document once. |
| `GET /` | Customer, scoped officer, admin, super admin | Implemented | Return a bounded metadata-only document page. |
| `GET <document_id>/` | Owner/resource scoped | Implemented | Return document detail and an on-demand short-lived URL. |
| `DELETE <document_id>/` | Owning customer | Implemented | Claim and delete an eligible unverified document. |
| `PUT <document_id>/verify/` | Permitted scoped officer/admin | Implemented | Approve or reject through an atomic transition. |
| `GET types/` | Authenticated supported roles | Implemented | Return baseline or product-specific document requirements. |
| `POST <document_id>/request-reupload/` | Permitted scoped officer/admin | Implemented | Request a replacement with a reason. |

Malformed document IDs return HTTP 400. Missing or deliberately concealed
resources return 404. Invalid lifecycle/stale revision transitions return 409.
Expired upload sessions return 410, and unavailable fail-closed scanning returns
503.

## Security and Privacy Features

- Role, ownership, officer assignment, and explicit reviewer-permission checks
- Private object storage and short-lived authorized download URLs
- Server-generated object names and quarantine prefixes
- Exact upload size, MIME, hash, owner, token, and session binding
- One-time hashed finalize secrets and idempotent session completion
- Structural image/PDF controls and fail-closed malware scanning
- Optimistic concurrency for lifecycle mutations
- Versioned field encryption for filename, path, description, review notes,
  rejection reason, and re-upload reason
- Trusted-proxy-aware client IP handling
- Allowlists for recoverable audit metadata
- Encrypted notification and storage-cleanup queues
- No private URLs in list responses and no sensitive values in metrics/inventory
- Retention deadlines, legal holds, retryable deletion, and safe export
- Consent re-check before optional analysis reads document bytes

The shared field-encryption key lifecycle, JWT/authentication boundary, account
roles, and customer-resource authorization helpers are owned by Accounts. The
Documents module consumes those controls and must be validated with the same
deployment keys and proxy topology.

## Background Work and Scheduled Operations

Celery workers and Beat provide:

- expired/abandoned presigned-session cleanup;
- failed object rollback and document deletion reconciliation;
- notification outbox publication and delivery retry;
- failed audit-write reconciliation;
- retention expiry and legal-hold-aware deletion;
- customer account document cleanup; and
- optional analysis leasing/retry when the feature is enabled in development.

Workers use leases, bounded retry/backoff, and idempotent state transitions.
Deployment health must include both worker and scheduler liveness because a
healthy HTTP process alone does not prove cleanup or delivery progress.

## Operational Requirements

### Private S3 configuration

Production must use `DOCUMENT_STORAGE_BACKEND=s3`. The configured bucket must
have all public-access-block controls enabled, `BucketOwnerEnforced` ownership,
default AES-256 or KMS encryption, versioning where supported, and no public or
custom-domain document delivery. Presigned URLs use SigV4 and short expiry.
CORS must list exact client origins and only required methods/headers.

The workload identity should access only the configured document/quarantine
prefixes and selected KMS key. It needs the object, multipart, copy, delete, and
prefix-list operations used by the application, but no bucket-policy, ACL, or
unrelated-prefix administration. Prefer workload identity over long-lived keys.

### Local-to-S3 migration and rollback

The repository includes `scripts/migrate_media_to_s3.py`,
`scripts/migration_verifier.py`, a manual staging workflow, and Terraform
templates under `infra/terraform/s3/`. These are operational tools, not evidence
that a real migration has passed. No production or staging AWS migration is
recorded as complete.

If an environment has existing local document media, migration requires an
approved MongoDB backup and immutable media snapshot, a staging dry run,
restricted review of the status/report artifacts, an approved apply window, and
post-copy verification before cutover. Status and verifier reports can contain
document identifiers and storage paths; treat them as sensitive operational
artifacts, keep them out of Git and ordinary logs, restrict access, and remove
them under the approved retention policy.

Do not delete or overwrite local source files until S3 validation, restore, and
rollback evidence is approved. During cutover, quiesce document writes or use a
formally tested dual-write/reconciliation design. Changing the backend to
`local` is not a complete rollback after S3-only uploads have occurred: the
operator must preserve new objects, restore or reconcile metadata from the
approved migration record, verify accessibility, and run consistency inventory.

### Monitoring and alerting

Scrape `documents_*` Prometheus metrics and alert on:

- abnormal upload/finalize or URL-generation errors;
- persistent storage, notification, AI, or audit retry backlog;
- oldest retry age above its worker objective;
- review backlog age beyond the business SLA;
- growing expired sessions or retention-due counts;
- required scanner readiness failure or unavailable scan outcomes; and
- unexplained missing, orphan, contradictory, or deleted-customer inventory.

Correlate alerts with Redis, Celery worker/Beat, MongoDB, S3, and ClamAV health.
Logs and metrics must exclude filenames, paths, file content, presigned URLs,
hashes, review reason text, scanner signatures, and customer identifiers.

### Backup and restore

MongoDB metadata and object storage form one recovery set. Backups require
encryption, access logging, approved retention, compatible object versioning,
and periodic restore testing in an isolated environment. A restore test must
confirm:

1. indexes and TTL indexes are restored or recreated;
2. encrypted metadata decrypts with the approved key version;
3. sampled allowlisted metadata has matching private objects;
4. presigned downloads require authorized detail access;
5. reconciliation resumes without duplicate documents or notifications; and
6. inventory reports no unexplained missing, orphan, contradictory, or
   deleted-customer state.

Restore tooling must never be smoke-tested against production.

## Maintenance and Validation Commands

These commands are documented here for operators. Commands touching configured
MongoDB or object storage must be pointed at the intended environment and run
under the project's approval procedures.

| Command | Mutation behavior | Purpose |
| --- | --- | --- |
| `python manage.py validate_document_storage` | Read-only | Check bucket public access, encryption, ownership, CORS, and URL-expiry controls. |
| `python manage.py inventory_document_storage` | Read-only/count-only | Report missing/orphan objects, expired sessions, contradictions, retention gaps, legal holds, and deleted-customer records without identifiers. |
| `python manage.py manage_document_legal_hold DOCUMENT_ID --action set --reason CASE --operator ADMIN_ID` | Dry-run by default | Preview a legal hold. |
| Same legal-hold command with `--apply` | State-changing | Set or release a hold after approved case/change review. |
| `python scripts/migrate_media_to_s3.py --dry-run --prefix documents` | Reads configured MongoDB/local media/S3 and writes sensitive local reports | Preview an approved isolated local-to-S3 migration. |
| `python scripts/migration_verifier.py --report migration_report.json --prefix documents` | Reads MongoDB/S3 and writes a sensitive local report | Verify copied objects and stored keys in an approved isolated target. |
| Migration command with `--confirm --apply-db` | State-changing | Copy objects and update document metadata only after backup, dry-run review, and explicit change approval. |

Run inventory immediately before production index/storage work, after restore,
and during relevant incidents. Investigate every unexplained non-zero finding
before an approved corrective action; the command intentionally performs no
repair.

## Automated Validation Status

The focused tests cover API contracts, upload validation, consent, role/scope,
atomic review/delete races, replacement lineage, rollback/deletion recovery,
audit recovery, reviewer recipient scope, database-side pagination and search,
background analysis, durable notification delivery, retention, legal holds,
account cleanup, safe export, storage inventory, S3 adapters/policies,
presigned finalization, and ClamAV fail-closed behavior.

Latest recorded evidence:

- Documents/S3/ClamAV suite: 93 passed and 2 opt-in real-service tests skipped.
- Full project suite: 1,058 passed and 21 opt-in integration tests skipped.
- Stage 7 retention/operations and malware subset: 22 passed.
- Both real-Mongo Documents harnesses passed against randomly named temporary
  databases, including 5,000-record query/index behavior and concurrent review.
- A temporary loopback-only Redis and isolated Celery queue returned a worker
  control response and were shut down afterward.
- A process-only production-safe settings profile passed
  `manage.py check --deploy` with no findings.
- The development count-only inventory found one local-storage orphan and zero
  other consistency, retention, hold, or deleted-customer findings. The orphan
  was not deleted and must be reconciled before that storage is reused/migrated.

Real S3 and real ClamAV harnesses remain intentionally gated and skipped until
approved isolated endpoints are supplied. Mock/unit tests do not satisfy the
deployment release conditions below.

## Client Notes

- Customer mobile clients may continue using `POST upload/`.
- Do not implement or expose the presigned flow until its feature flag is
  enabled after deployment validation.
- A presigned S3 POST never creates a visible document by itself. The client
  calculates size/MIME/SHA-256, requests a session, submits all returned form
  fields, and finalizes with the session ID and one-time token.
- Treat `status` as canonical and `revision` as the concurrency version.
- On HTTP 409, refresh the resource before deciding whether to retry.
- Lists intentionally contain no usable `file_url`; request detail when a user
  opens or downloads a document.
- HTTP 503 from upload/finalize represents a temporary fail-closed scanner
  outage. Direct upload resends the file; presigned upload retries finalization
  with the same valid session and token rather than uploading another object.
- With the approved production baseline, clients should not wait for or display
  AI scores. Human review determines approval.
- Officer/admin clients must support approve, reject, re-upload request, stale
  conflict refresh, and scoped 404 behavior.

No new route is required solely by this documentation consolidation.

## Remaining Gaps and Release Conditions

There are no known remaining application-code blockers for the approved
non-CNN Documents baseline. The module must not be called production-deployed
until the selected deployment environment provides evidence for all of the
following:

- private S3 bucket controls, least-privilege IAM/KMS, exact CORS, short URL
  expiry, multipart behavior, and full quarantine/finalize/replay/cleanup;
- when existing local media must be retained, approved staging migration,
  sensitive-report handling, cutover, verification, and rollback rehearsal;
- private ClamAV readiness, current signatures, stream-size policy, clean,
  detected, invalid-response, timeout, and outage behavior;
- deployed encryption-key access, previous-key reads, rotation, and restore;
- real Redis/Celery delivery, lease, retry, Beat, and backlog behavior;
- trusted-proxy depth, HTTPS, secure cookies, CORS/CSRF, and production throttle
  configuration;
- sanitized structured logging and the defined metrics/alerts;
- MongoDB/object-storage backup and isolated restore as one recovery set;
- retention, legal-hold, account-deletion, and post-restore inventory evidence;
  and
- reconciliation of the one known development local-storage orphan before that
  storage is reused or migrated.

Only after this evidence is approved may operators enable presigned uploads.
PDFs remain disabled unless their separate residual risk is approved.

## Optional Future CNN Release Conditions

CNN/image-quality analysis is a separate optional feature, not a release gap
for the current module. Enabling it in any environment serving real customer
documents requires all of the following:

- an immutable, approved, subject-grouped dataset manifest with item-level
  source, license/consent, anonymization, hashes, and split assignments;
- removal of duplicate/cross-split samples and materially representative class,
  device, capture-quality, subgroup, and out-of-distribution coverage;
- independent holdout results with sample counts and confidence intervals,
  macro/per-class precision, recall and F1, confusion matrix, calibration,
  false-accept/false-reject rates, robustness, OOD rejection, latency, and
  memory evidence;
- risk-based per-class thresholds and an explicit `unknown`/`other` policy;
- an approved registry entry bound to model, code, preprocessing, dataset,
  threshold policy, artifact SHA-256, deployment date, and rollback target;
- current consent re-check, human-review/appeal behavior, drift and disagreement
  monitoring, alert thresholds, change control, and rollback rehearsal; and
- a separate privacy and repository-history disposition for existing training
  material, with approved data kept outside normal Git and production builds.

Training must create `not_approved` artifacts and may never self-approve. Any
model, preprocessing, class mapping, threshold, or dataset change creates a new
registry version and repeats the approval gates. The independent final holdout
must not be used for tuning.

## Review Boundaries

This documentation covers `documents/`, document routes and serializers,
PyMongo records and indexes, storage adapters, presigned uploads, scanning,
optional analysis code, background work, account lifecycle hooks, audit and
notification integration, loan/profile consumers, configuration, management
commands, and document-related tests.

It does not by itself certify:

- the eventual cloud account, bucket, IAM/KMS policy, network, or ClamAV host;
- live customer data quality, historical metadata, or orphan resolution;
- the legal adequacy of retention, consent, privacy, or AI policies;
- the safety of enabling PDFs without an approved sandbox/CDR decision;
- production traffic capacity or business review SLA staffing; or
- optional CNN accuracy, fairness, provenance, privacy, or approval.

Accounts owns authentication, roles, encryption-key infrastructure, consent,
and customer lifecycle orchestration. Profiles owns customer/officer profile
data and directory behavior. Loans owns product requirements, applications,
assignment scope, and qualification policy. Documents consumes those contracts
without redefining them.

## Related Documentation

- `docs/documents/DOCUMENTS_TESTING_GUIDE.md` — endpoint examples, focused
  suites, real-service harnesses, and operational verification procedures
- `docs/accounts/ACCOUNTS_PRODUCTION_READINESS_REVIEW.md` — authentication,
  authorization, consent, field encryption, and account lifecycle contracts
- `docs/profiles/PROFILES_PRODUCTION_READINESS_REVIEW.md` — profile ownership,
  scoped customer directory, and cleanup integration
- `docs/LOANS_TESTING_GUIDE.md` — loan requirements, assignment scope, and
  document-dependent qualification behavior
