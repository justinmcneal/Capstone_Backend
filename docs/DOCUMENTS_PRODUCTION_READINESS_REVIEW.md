# Documents Production Readiness Review

Last updated: 2026-08-10

Scope: `documents/` plus document routes, serializers, PyMongo persistence,
local/S3 storage, presigned uploads, AI/CNN analysis, reviewer notifications,
loan/profile consumers, account lifecycle integration, audit logging,
configuration, and document-related automated tests.

## Purpose and Status Definitions

This document is the source-of-truth implementation and remediation checklist
for customer document upload, storage, review, re-upload, retrieval, deletion,
AI-assisted quality checks, and operational controls. It records behavior found
in the code; it does not treat a route, test, or configuration example as proof
that the complete production workflow is safe.

- **Complete**: implemented and covered by relevant automated tests.
- **Partial**: useful implementation exists, but important behavior is missing,
  inconsistent, or unsafe.
- **Not implemented**: no production implementation was found.
- **Blocked for production**: a security, privacy, correctness, concurrency,
  retention, durability, or deployment issue must be fixed before release.

Checklist convention:

- `[x]` with ~~strikethrough~~ means implemented and statically verified.
- `[ ]` means not implemented or still requiring validation.
- A **PARTIAL** stage contains both completed and unchecked work.

The project uses PyMongo directly. Unit tests that replace the model, storage,
audit logger, email sender, or authorization checks do not prove real MongoDB,
object-storage, broker, or failure-recovery behavior.

## Executive Summary

The Documents module has a useful core but is **not production-ready yet**.
Authenticated direct uploads, file validation, encrypted metadata, role-scoped
reads, officer approval/rejection, re-upload requests, local and S3 storage
adapters, consent-gated image analysis, reviewer/customer email hooks, and loan
qualification consumers are implemented.

Stage 2 replaces the original incomplete presigned object grant with a
short-lived owner-bound upload session, exact size/type/hash policy, quarantine
key, one-time idempotent finalize endpoint, server-side object/content
validation, normal `Document` creation, AI/audit/notification integration, and
scheduled abandoned-object cleanup. The feature remains disabled by default
until S3 deployment configuration and isolated environment validation are
complete.

Stages 3 and 4 add revision-guarded lifecycle writes, replacement lineage,
durable storage cleanup, retryable deletion, explicit reviewer permissions,
assignment-scoped reviewer recipients, metadata-only list responses, trusted
client-IP handling, complete document audit coverage, and a recoverable
allowlisted audit queue. Stage 5 moves listing filters, counts, deterministic
sorting, and bounded pagination into MongoDB, replaces unsafe substring search
with indexed exact search, and bulk-resolves page customer names. Stage 6 moves
image analysis out of upload requests, adds consent-aware leased retries,
durable reviewer/customer notification delivery, artifact integrity gates, and
fail-closed dataset validation. Remaining blockers are concentrated in approval
of representative AI data/artifacts and Stage 7 retention/deployment operations.

Current remediation status:

- [x] Stage 1 — Contract, state machine, and regression baseline
- [x] Stage 2 — Safe upload finalization and content security
- [x] Stage 3 — Atomic lifecycle transitions and storage consistency
- [x] Stage 4 — Authorization, privacy, and audit completeness
- [x] Stage 5 — Query scalability and response delivery
- [ ] Stage 6 — Background work, notifications, and AI governance
- [ ] Stage 7 — Retention, deployment configuration, and operations

## Verified Implemented Foundations

### Models and persistence

- A PyMongo-backed `Document` model stores records in `documents`.
- The model supports insert/update, lookup, customer lookup, delete, approval,
  rejection, re-upload state, serialization, and index creation.
- Document mutations carry a `revision`; review, re-upload, supersession, and
  delete claims use narrow MongoDB compare-and-set writes and stale requests
  receive `409`.
- Replacement uploads retain forward/backward document lineage rather than
  reopening or rewriting the earlier document's review history.
- Deletion uses `delete_pending`/`delete_failed` storage states. A scheduled
  reconciler retries object deletion and removes metadata only after the object
  deletion is satisfied.
- Failed direct/finalize rollback deletes are persisted in the encrypted
  `document_storage_cleanup` queue and retried idempotently.
- Index declarations cover customer ID, type, status, upload time, and common
  customer/type/status combinations; creation is wired into `init_db.py`.
- Listing indexes cover global, customer, customer/type/status, and
  type/status access paths with `uploaded_at`/`_id` ordering.
- Customer lookups tolerate legacy customer IDs stored as strings or
  `ObjectId` values.
- Original filename, storage path, description, notes, rejection reason, and
  re-upload reason are declared for field-level encryption and included in the
  shared encryption backfill tooling.
- Downstream loan qualification reads the customer's documents and can require
  the latest document of each required type to be approved.

### API surface

The following routes are registered under `/api/documents/`:

| Route | Current role boundary | Implementation status |
|---|---|---|
| `POST upload/` | Customer | Implemented; rollback/replacement recovery included |
| `POST presigned-upload/` | Customer | Stage 2 session issuance; disabled by default |
| `POST presigned-upload/<session_id>/finalize/` | Customer owner | Stage 2 one-time validation/finalization |
| `GET /` | Customer/officer/admin/super admin | Implemented; scoped, audited, bounded, and metadata-only |
| `GET <document_id>/` | Role/resource scoped | Implemented; staff read is audit-gated |
| `DELETE <document_id>/` | Owning customer | Implemented; revision-guarded and retryable |
| `PUT <document_id>/verify/` | Permitted officer/admin | Implemented; atomic and audited |
| `GET types/` | Authenticated supported roles | Implemented |
| `POST <document_id>/request-reupload/` | Permitted officer/admin | Implemented; atomic and audited |

### Upload validation

- Upload serializer enforces a 10 MB application limit and permits JPEG, PNG,
  and PDF MIME types.
- File signatures are compared with the declared MIME type.
- Common executable signatures are rejected.
- JPEG/PNG data is opened and verified by Pillow.
- PDFs receive a heuristic scan for selected active-content markers.
- Document type and description are validated and text fields are sanitized.
- Upload endpoints use `DocumentUploadRateThrottle`, currently configured at
  100 requests per hour per authenticated user.

These are useful defenses, not a malware-scanning boundary. PDF scanning reads
only the first portion of the file and uses substring matching; there is no AV,
sandbox, quarantine, or content-disarm process.

### Authorization foundations

- Customer upload and delete operations require the customer role.
- Customers list and read only their own documents.
- Loan officers use the shared customer-resource scope derived from assigned
  applications, eligible unassigned work, and their earlier approvals.
- Admin and super-admin reads are broader by design.
- Officers cannot review customers outside their calculated scope.
- Verified documents cannot be deleted through the customer endpoint.

### Storage foundations

- `LocalStorageBackend` stores generated filenames under a customer/type
  hierarchy and implements save, delete, URL, and byte retrieval.
- `S3StorageBackend` implements ordinary and multipart upload, retries, delete,
  presigned GET URLs, presigned POST generation, and byte retrieval.
- Stored object names are server-generated rather than directly trusting the
  uploaded filename.
- Upload responses can provide a local URL, custom-domain URL, or presigned S3
  URL through the backend abstraction.

### Safe presigned upload workflow

- `DocumentUploadSession` persists owner, document type, sanitized filename,
  description, expected size/MIME/SHA-256, hashed finalize token, quarantine
  object key, state, expiry, and resulting document ID.
- The raw finalize token is returned once; only its SHA-256 digest is stored.
- S3 presigned conditions bind the exact quarantine key, MIME type, expected
  byte length, session metadata, and expected SHA-256 metadata.
- Finalization is customer-owned, token-bound, expiry-checked, and atomically
  claims an `issued` session before doing work.
- The server heads and downloads the object, verifies metadata, exact length,
  computed SHA-256, executable signature, MIME signature, image integrity, and
  PDF active-content rules before promotion.
- Valid content is copied from the quarantine prefix to a server-generated
  durable document key; the quarantine object is removed.
- `upload_session_id` has a sparse unique document index. Repeating finalize
  returns the already-created document instead of creating a duplicate.
- Image analysis is scheduled after durable creation and runs through the same
  leased/retryable worker path as direct uploads. Consent is re-checked before
  the worker reads bytes; failure is recorded with a non-sensitive code.
- Finalization attempts the normal upload audit and reviewer notification after
  durable creation without returning a misleading mutation failure for an audit
  failure.
- A ten-minute Celery Beat task deletes expired/failed quarantine objects and
  marks sessions expired. Completed/cleaned sessions receive a one-day TTL.
- The workflow is feature-gated by
  `DOCUMENT_PRESIGNED_UPLOAD_ENABLED=False`; local storage remains unsupported.

### Review and downstream behavior

- Officers/admins can approve or reject a document and customers can receive an
  email about the result.
- Officers/admins can request a clearer/replacement upload with a reason.
- `/types/` supports baseline required types and product-specific requirements.
- Profile summaries report document totals/statuses.
- Loan application views expose customer document status to authorized officers.
- Loan qualification can gate applications on approved required documents.

### AI/CNN foundations

- Image analysis is gated by a global feature flag and the customer's recorded
  AI consent. PDFs skip image analysis.
- Upload requests no longer read document bytes for inference. MongoDB records
  `pending`, `processing`, `retry_wait`, `completed`, `failed`, or
  `skipped_no_consent`; Celery Beat republishes due work and stale processing
  leases can be reclaimed.
- Quality checks cover minimum dimensions, aspect ratio, brightness, and blur
  when optional image dependencies are available.
- A MobileNetV2 classifier and training command exist for seven image classes.
- Confidence, expected/predicted type, quality score, operational state, model
  version, preprocessing version, threshold policy, and manual-review flag can
  be persisted with the document.
- A failed quality/type result changes the initial status to `needs_review`.

### ML artifact and dataset inventory

The following inventory was recorded on 2026-08-09 without reproducing document
image contents:

- The classifier is a seven-class MobileNetV2. The API also accepts an `other`
  document type, but the classifier has no corresponding class.
- `document_classifier.pth` is absent. The runtime therefore cannot load the CNN
  from this checkout and operates in quality-check mode.
- `model_config.json` records 90.12% best internal validation accuracy over six
  epochs, while the saved holdout charts show 77 correct predictions out of 83
  (92.77%). Neither result is tied to a retained model hash, code revision,
  dataset manifest, or reproducible evaluation run.
- The training set contains 403 images: `business_permit` 2,
  `business_photo` 54, `income_proof` 4, `invalid` 170,
  `proof_of_address` 6, `selfie_with_id` 14, and `valid_id` 153. The largest
  class is 85 times the smallest.
- The holdout set contains 83 images: 1, 16, 1, 40, 2, 3, and 20 respectively
  in the same class order. Four classes therefore have only one to three test
  examples.
- The saved holdout charts report 50% recall and 40% F1 for
  `proof_of_address`. Apparent 100% accuracy for several classes is based on only
  one or three examples and is not statistically meaningful.
- Exact-hash inventory found 15 duplicate groups covering 35 files. One group,
  covering three files, crosses the training/holdout boundary and invalidates
  strict holdout independence for those samples.
- Two training images are below the documented 224-by-224 minimum.
- The repository currently tracks 401 training/test images even though its own
  ML documentation says real personal documents must not be committed. The
  related `.gitignore` dataset/report rules are commented out. Image provenance,
  licenses, consent, anonymization, retention, and Git-history disposition have
  not been proven by repository metadata.
- Stage 6 replaces `scripts/check_training_data.py` with a fail-closed validator
  for class minimums, corrupt/undersized images, exact duplicates, manifest
  hashes, provenance/license-or-consent/anonymization metadata, subject-level
  split leakage, and missing manifest files. It emits a JSON report. The current
  repository dataset has not been altered or re-certified by that tooling.

### Automated test baseline

- Dedicated tests cover representative upload, consent, list/scope, type,
  detail, verified-delete, approve/reject, re-upload, S3 upload, multipart retry,
  presigned POST, URL, and delete behavior.
- Before Stage 1, the focused suite collected and passed 21 tests. After Stage 1,
  it passed 31. After Stage 2, the expanded focused suite passed 39 tests:

  ```text
  pytest -q tests/test_documents_stage1_contract.py \
    tests/test_documents_stage2_presigned_upload.py \
    tests/test_documents_ai_consent.py tests/test_documents_api.py \
    tests/test_documents_integration_s3.py \
    tests/test_s3_multipart_and_retry.py \
    tests/test_s3_presigned_client_upload.py \
    tests/test_s3_presigned_post.py tests/test_s3_storage_backend.py
  ```

- Most endpoint tests are unit-style and replace authorization, persistence,
  storage, audit, or notification dependencies. There is no real-Mongo document
  concurrency/index suite and no deployment-target S3 finalization run yet.
- The post-Stage 2 full suite collected 1,021 tests: 1,004 passed and 17 opt-in
  integration tests were skipped.
- After Stages 3 and 4, the focused suite covers 50 tests, including stale
  review, review/delete race, replacement lineage, rollback/deletion recovery,
  explicit permission denial, real access-helper scope denial, metadata-only
  lists, recoverable audit failure, and notification recipient scope.
- The post-Stage 4 full suite collected 1,032 tests: 1,015 passed and 17 opt-in
  integration tests were skipped.
- Stage 5 adds six focused tests for database pagination, stable tie-breaking,
  empty/beyond-page behavior, deletion-state exclusion, indexed exact search,
  one-query customer-name resolution, and listing index declarations. An opt-in
  real-Mongo test loads 5,000 records across customer/officer/admin query shapes
  and inspects execution statistics.
- The post-Stage 5 full suite collected 1,039 tests: 1,021 passed and 18 opt-in
  integration tests were skipped. The additional skip is the isolated
  real-Mongo Stage 5 load/explain test.
- Stage 6 adds 15 focused tests for durable enqueue failure, consent re-check,
  safe/traceable completion, bounded terminal failure, due-work reconciliation,
  stale-lease recovery, encrypted notification outbox retry/idempotency,
  fail-closed analyzer output, offline approved-artifact loading, dataset
  manifest governance, explicit unknown/OOD rejection, aspect-preserving
  preprocessing, evaluation/approval binding, idempotent in-app broadcast, and
  analysis indexes.
- The expanded focused Documents suite passed 71 tests. The post-Stage 6 full
  suite collected 1,054 tests: 1,036 passed and 18 opt-in integration tests were
  skipped.

## Confirmed Production Blockers and Gaps

### 1. Presigned upload code is remediated; deployment validation remains

Stage 2 implements the tracked quarantine/finalize workflow described above and
keeps it disabled by default. Remaining work belongs to the deployment gate:
wire and validate S3 settings, private bucket encryption/IAM/CORS/lifecycle,
exercise a real isolated S3-compatible target, and confirm Celery cleanup. Do
not enable the feature merely because unit/moto tests pass.

### 2. Storage/database consistency is remediated at code level

Direct-upload database failures now attempt an immediate object rollback and
durably queue the path if rollback fails. Presigned finalization does not remove
a committed object merely because its session completion marker failed; replay
repairs that marker. Customer delete first atomically claims the document, then
removes metadata only after idempotent storage deletion. Failed operations are
retained for the five-minute storage reconciler.

### 3. Review/re-upload/delete races are remediated at code level

All three mutation paths now compare the caller's optional `revision` with the
stored revision while also checking the allowed current status and storage
state. Only one concurrent transition wins; stale requests receive `409`.
Compatibility fields are normalized in the same atomic update. Replacement
uploads create a new record with lineage instead of reopening the old record.

### 4. Notification scope and delivery durability are remediated

`Document.find_by_id` now satisfies the Celery task contract. Reviewers must be
active and have `review_documents`; when a customer has an assigned officer,
only that officer is selected, while permitted admins retain oversight access.
Stage 6 writes encrypted, idempotent reviewer/customer delivery records before
Celery publication. Claim leases, bounded backoff, terminal state, unique
document/type/recipient keys, and a one-minute reconciler cover broker and
delivery failures without failing the completed domain mutation. The delivery
ID also deduplicates the in-app/push record across email retries.

### 5. Listing scalability and sensitive response work are remediated

The list endpoint now applies role scope, customer/type/status filters, storage
visibility, count, deterministic `uploaded_at`/`_id` ordering, `skip`, and
`limit` in MongoDB. Only one page is decrypted. Page size is explicitly bounded
to 200, empty results report zero pages, and pages beyond the end are stable
empty arrays with the same total.

Randomized encrypted filenames are not searched and no plaintext shadow field
was added. `search` accepts only an exact document type, document ID, or customer
ID; name discovery belongs to the scoped Profiles directory and then uses the
indexed `customer_id` filter. Customer display names for one result page are
resolved with one bounded query, and list calls never mint storage URLs.

### 6. Audit coverage and recovery are remediated

Upload/finalize, review, re-upload, delete, staff list/detail reads, and denied
sensitive reads use one allowlisted document audit writer and the shared trusted-
proxy client-IP helper. Filenames, review notes, rejection reasons, and re-upload
reasons are excluded from audit payloads. Failed writes are queued under the
`documents` domain and replayed every minute. Required staff-read audits fail
closed with `503`; post-commit mutation audit failures do not misreport the
mutation as failed.

### 7. Error handling and storage fallback are remediated

- Stage 1 now returns `400 Invalid document_id format` for malformed IDs in
  detail, delete, verify, and request-reupload handlers.
- Background analysis stores allowlisted error codes and does not expose raw
  exception messages through document responses.
- Verification no longer logs the authenticated email or request payload.
- S3 URL failures return no URL and increment an operational counter; internal
  `s3://` identifiers are never returned to clients.
- Unknown storage backend names fail closed, and local paths are constrained to
  the configured media root.

### 8. Production storage configuration is implemented at code level

Settings now load and validate the selected backend, S3 bucket/region,
credentials or workload identity inputs, endpoint, ACL, signature version,
encryption parameters, URL expiry, multipart sizing, and retry controls. Local
storage is rejected when `DEBUG=False`; S3 overwrite, public ACLs/custom-domain
downloads, unsupported signatures, missing bucket configuration, and absent
server-side encryption fail startup validation.

The read-only `validate_document_storage` command checks the deployment bucket's
public-access block, default encryption, object ownership, CORS origins/methods,
and URL expiry. IAM policy and bucket lifecycle evidence still require review in
the isolated deployment target.

### 9. Document retention and customer lifecycle are implemented

New records receive a versioned retention deadline. Rejected and superseded
records receive configured shorter deadlines, while legal holds prevent
retention deletion until explicit release. A daily bounded task claims due
records into the retryable storage deletion workflow. Account deletion has a
separate durable document-cleanup marker, expires active upload sessions, claims
non-held objects, and remains pending until reconciliation removes object and
metadata. Customer exports contain allowlisted metadata but exclude filenames,
paths, hashes, URLs, review notes, and AI output. Count-only inventory and a
dry-run legal-hold command support operations without printing storage IDs.

### 10. AI operational governance is incomplete

- The trained weight artifact is missing, so CNN inference is not available in
  this checkout despite retained configuration and evaluation charts. With the
  default `DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION=True`, a consented image
  analyzed without the model fails type validation and is sent to
  `needs_review`; this fail-safe behavior needs explicit product/operations
  handling and monitoring.
- Analysis runs inline during upload and reads the uploaded object back into
  memory, increasing latency and memory use.
- Analyzer errors are swallowed into a nominally valid result.
- Optional dependency absence silently removes blur checks.
- Model loading constructs MobileNetV2 with pretrained weights before loading the
  saved state, which can attempt an unnecessary network download and cause an
  otherwise valid local model to be treated as unavailable. Inference should
  construct the exact architecture without downloading base weights.
- Model load/health/version, artifact hash, preprocessing version, and dataset
  version are not exposed operationally in stored results.
- Training uses a single random, non-stratified image-level 80/20 split. Closely
  related images and exact duplicates can enter different splits, and very small
  classes may be nearly absent from validation. A grouped, stratified split by
  source/document/subject is required before reporting accuracy.
- The holdout evaluator prints `Production-ready` from overall accuracy alone.
  It has no minimum per-class sample size, macro-F1/recall gate, confidence
  interval, calibration/error-cost gate, leakage check, or machine-readable
  signed evaluation report.
- The training augmentation includes horizontal flips, which create mirrored
  text/documents that are generally unlike valid uploads. Forced 224-by-224
  resizing also distorts aspect ratio. Domain-appropriate rotation, perspective,
  exposure, compression, blur, occlusion, and aspect-preserving padding should
  be validated instead of assuming generic image augmentation improves accuracy.
- Softmax always chooses one known class. A single broad `invalid` class is not
  sufficient open-set/out-of-distribution detection, and the global 0.75
  threshold has not been calibrated per class. The evaluation chart also marks
  0.80, so documented and evaluated thresholds disagree.
- `other` uploads have no CNN class and will normally conflict with a forced
  known-class prediction when matching is enforced.
- The dataset is severely imbalanced and several classes have too few independent
  training/holdout examples to establish reliable recall. Class-weighted loss
  does not replace collecting representative independent data.
- Hundreds of dataset images are tracked in Git while provenance, licenses,
  consent, anonymization, and retention are unverified. This requires a privacy
  and data-governance review before any retraining or distribution.
- The CNN only predicts a visual category. It does not prove authenticity,
  ownership, document expiry, readable fields, tampering, selfie/ID face match,
  or malware safety and must never be described as document verification.
- Fairness and robustness across camera devices, compression, lighting,
  geography, document templates, age/skin-tone groups for selfies, and adversarial
  or out-of-distribution inputs have not been evaluated.
- AI output is advisory but the exact manual-review and appeal policy is not
  documented in this module.

## Staged Remediation Plan

### Stage 1 — Contract, state machine, and regression baseline

**Status: Complete**

- [x] ~~Inventory routes, roles, persistence, storage, AI, downstream consumers,
  configuration, and existing tests.~~
- [x] ~~Record the original 21-test baseline and expanded 31-test Stage 1
  baseline.~~
- [x] ~~Define the canonical state machine and allowed transitions for `pending`,
  `needs_review`, `approved`, `rejected`, and `expired`.~~
- [x] ~~Treat approved and expired documents as terminal. A replacement will be
  represented as a new document in Stage 3 rather than mutating the approved
  record.~~
- [x] ~~Define malformed document IDs as `400`, missing/inaccessible resources as
  `404`, invalid lifecycle transitions as `409`, and serializer errors as
  `400`.~~
- [x] ~~Keep presigned upload registered for future compatibility but disabled by
  default until the Stage 2 session/finalization workflow exists.~~
- [x] ~~Add lifecycle normalization, terminal-state, invalid-ID, and disabled-
  presigned-route regression tests.~~

Stage 1 contract decisions:

- `status` is canonical. The legacy `verified` fields remain in responses and
  storage for compatibility but are normalized whenever a review/re-upload
  transition occurs.
- `pending` may move to `needs_review`, `approved`, or `rejected`.
  `needs_review` may remain `needs_review` for a refreshed request or move to
  `approved`/`rejected`. `rejected` may return to `needs_review` only through an
  explicit re-upload request. `approved` and `expired` are terminal.
- Customer deletion is permitted only for unverified `pending`, `needs_review`,
  or `rejected` documents and is enforced atomically.
- Approved-document replacement creates a new record linked through a Stage 3
  supersession design; the approved record is not reopened.
- The original incomplete presigned object grant was feature-gated off by
  default. Stage 2 replaced it with a tracked, owner-bound, single-use session
  and finalize protocol; the gate remains off pending deployment validation.

### Stage 2 — Safe upload finalization and content security

**Status: Complete at code and automated-test level; feature remains deployment-gated**

- [x] ~~Introduce a short-lived, owner-bound, single-use upload-session record
  with a hashed finalize secret.~~
- [x] ~~Generate restrictive presigned conditions for quarantine key, MIME type,
  exact content length, session metadata, and expected SHA-256.~~
- [x] ~~Add a finalize endpoint that validates session ownership/token/expiry,
  heads and downloads the object, verifies exact size/type/hash/session binding,
  performs normal content scans, creates the document once, audits it, and
  enqueues existing post-processing.~~
- [x] ~~Make finalization atomically claimable and idempotent; conceal wrong-owner
  and wrong-token sessions and reject concurrent claims.~~
- [x] ~~Quarantine uploads until validation succeeds, promote valid content, and
  delete failed/abandoned objects with a scheduled ten-minute cleanup task.~~
- [x] ~~Add sparse unique `upload_session_id` indexing and session expiry/TTL
  indexes to `init_db.py`.~~
- [x] ~~Add automated tests for success, replay, owner/token isolation, mismatch
  cleanup, expiry cleanup, endpoint issuance, and restrictive S3 policy.~~

Full antivirus/sandbox/content-disarm policy and decompression-bomb hardening
remain part of the broader content-security/operations release gate; the Stage 2
workflow ensures unvalidated content is never promoted into document storage.

### Stage 3 — Atomic lifecycle transitions and storage consistency

**Status: Complete at code and automated-test level; real-service validation is a Stage 7 gate**

- [x] ~~Add a `revision` and narrow compare-and-set updates for review,
  re-upload, and delete transitions; return `409` on stale writes.~~
- [x] ~~Enforce allowed transitions and clear incompatible verification/
  rejection/re-upload fields atomically.~~
- [x] ~~Model replacement/supersession rather than mutating contradictory
  flags.~~
- [x] ~~Add durable storage-operation state and idempotent reconciliation for
  failed upload, finalize, and delete steps.~~
- [x] ~~Do not return mutation failure merely because a post-commit audit/email
  side effect failed; persist audit and notification failures for scheduled
  reconciliation.~~
- [x] ~~Add automated concurrent-review, review/delete-race, duplicate-finalize,
  partial-failure, and retry tests using the isolated test database/storage.~~

The same concurrency and retry cases must still be repeated against isolated
real MongoDB and object storage during Stage 7 deployment validation. That
environmental proof is not represented as incomplete Stage 3 application code.

### Stage 4 — Authorization, privacy, and audit completeness

**Status: Complete at code and automated-test level**

- [x] ~~Enforce customer ownership and loan-officer resource scope on current
  API reads and mutations.~~
- [x] ~~Require explicit `review_documents` permission for admin/officer
  mutations.~~
- [x] ~~Scope reviewer notifications to active, permitted recipients authorized
  for that customer's assignment.~~
- [x] ~~Audit delete, re-upload, staff list/detail reads, denied sensitive reads,
  and presigned-session/finalization events with allowlisted metadata.~~
- [x] ~~Use the trusted-proxy IP helper and remove sensitive request-payload
  logs.~~
- [x] ~~Add recoverable, allowlisted failed-audit persistence and one-minute
  reconciliation.~~
- [x] ~~Make list responses metadata-only (`file_url: null`); issue a short-lived
  URL only through the authorized detail response.~~
- [x] ~~Add negative cross-customer, cross-officer, inactive-account, and
  permission matrix tests without bypassing the real access helpers.~~

### Stage 5 — Query scalability and response delivery

**Status: Complete at code and automated-test level; real-service load validation is a Stage 7 gate**

- [x] ~~Replace `Document.find()` list materialization with database-side count,
  deterministic sort, skip, and bounded page pagination.~~
- [x] ~~Restrict search to indexed exact document type/document/customer IDs;
  do not add plaintext or in-memory filename search.~~
- [x] ~~Bulk-resolve one page of customer display names with one query and
  eliminate serializer-level per-row lookups.~~
- [x] ~~Separate metadata listing from short-lived URL issuance by returning no
  URL from list calls and issuing it only from authorized detail calls.~~
- [x] ~~Add deterministic `uploaded_at`/`_id` ordering, stable empty/beyond-page
  semantics, page-size validation, and pagination boundary tests.~~
- [x] ~~Add an opt-in real-Mongo test covering 5,000 records across customer,
  officer, and admin query shapes plus execution statistics.~~

The opt-in load test must still be executed against an approved isolated real
MongoDB target during Stage 7 validation. The normal test suite never reads
deployment credentials or mutates an external database.

### Stage 6 — Background work, notifications, and AI governance

**Status: Partial — runtime controls complete; dataset/model approval remains blocked**

- [x] ~~Fix the missing `Document.find_by_id` lookup used by the Celery task.~~
- [x] ~~Add Celery/service tests that exercise the real `Document` contract,
  consent transitions, stale leases, broker failure, and delivery retry.~~
- [x] ~~Add bounded retries/backoff, encrypted idempotent delivery state, and
  scheduled reconciliation for reviewer and customer notifications.~~
- [x] ~~Move image analysis out of direct and presigned request paths into
  bounded, leased, idempotent background work.~~
- [x] ~~Fail safely on analysis errors without persisting/returning exception
  strings or marking failed results valid.~~
- [x] ~~Load inference architecture with `pretrained=False`, verify approved
  artifact hashes, and expose document-model readiness through `/api/health/`.~~
- [x] ~~Define a versioned registry schema and make training emit artifact hash,
  code/preprocessing/dataset/threshold versions, approval state, metrics,
  deployment date, and rollback fields without self-approval.~~
- [ ] Approve a real registry entry only after an independently reproduced
  evaluation; the current artifact is absent and the development registry is
  deliberately `not_approved` with no artifact/dataset hash.
- [x] ~~Add a dry-run-first deterministic manifest builder that requires source,
  license/consent, anonymization, and subject metadata and keeps each subject in
  one train/validation/holdout split.~~
- [ ] Remove the inventoried exact duplicates and create an approved immutable
  grouped/stratified
  train/validation/holdout manifest by source/document/subject. Never tune on
  the final holdout set.
- [ ] Collect materially more licensed, consented, anonymized, representative
  samples for every underrepresented class and a broader out-of-distribution
  set. Establish minimum independent sample counts before evaluating a class.
- [x] ~~Replace mirroring/aspect distortion with shared versioned
  aspect-preserving letterbox preprocessing and conservative document-photo
  augmentation.~~ Independent robustness evidence for this policy remains part
  of the evaluation gate below.
- [x] ~~Add reproducible evaluation tooling for macro and per-class
  precision/recall/F1, confusion matrix,
  calibration, confidence intervals, subgroup/device robustness, false-accept
  and false-reject rates, latency, and open-set rejection, plus a dry-run-first
  approval gate bound to artifact/dataset/policy hashes.~~
- [ ] Run that evaluation on an approved independent holdout/OOD set, select and
  document calibrated per-class or risk-based thresholds, and obtain human
  approval rather than relying on headline accuracy.
- [x] ~~Map below-threshold classifier results to explicit `unknown` and route
  `other` uploads to manual review instead of forcing either into a known
  class.~~
- [x] ~~Persist model/policy/preprocessing versions, manual-review requirement,
  and operational analysis status with each inference.~~
- [x] ~~Make the dataset checker fail on below-minimum classes, corrupt/undersized
  files, exact/cross-split duplicates, missing provenance, and split-manifest
  violations; emit a machine-readable report.~~
- [ ] Complete privacy/license/consent/anonymization review for every dataset
  item. Keep approved datasets in access-controlled versioned storage rather
  than ordinary Git, and address existing Git history under an approved data-
  governance procedure.
- [x] ~~Document AI intended use, human-review requirement, consent withdrawal,
  appeal/correction, acceptance metrics, deployment, rollback, and drift policy.
  See `docs/documents/DOCUMENT_AI_GOVERNANCE.md`.~~
- [x] ~~Add model-available/unavailable/error/stale-task and consent-transition
  tests.~~

Runtime Stage 6 is complete, but the unchecked data collection, independent
holdout/OOD evaluation, privacy review, dataset reconciliation, and artifact
approval items are evidence-producing governance work rather than code-only
tasks. They remain a production blocker and must not be checked merely because
enforcement tooling now exists.

### Stage 7 — Retention, deployment configuration, and operations

**Status: Complete at code and automated-test level; deployment validation pending**

- [x] ~~Load `DOCUMENT_STORAGE_BACKEND` and all required S3 options from validated
  settings; fail closed outside development.~~
- [x] ~~Define private bucket, server-side encryption, CORS, URL expiry, object
  ownership, and least-privilege IAM requirements; add a read-only validator for
  bucket controls. Deployed IAM proof remains in the environmental gate.~~
- [x] ~~Integrate document metadata and objects with customer account deletion,
  including retryable partial-cleanup state.~~
- [x] ~~Define retention periods, legal hold, expiry, superseded-document cleanup,
  customer export, and backup/restore behavior in the operations runbook.~~
- [x] ~~Add read-only orphan, missing-object, expired-upload-session,
  contradictory-state, and deleted-customer retention inventories.~~
- [x] ~~Add metrics for upload/finalize failures, storage reconciliation,
  review backlog/age, notification failures, AI failures, audit backlog,
  retention/legal holds, and URL-generation errors, with alert guidance in the
  runbook. Orphan/missing counts come from the deliberate inventory command.~~
- [ ] Validate real MongoDB indexes/concurrency, object storage, Redis/Celery,
  encryption keys, proxies, throttles, logging, restore, and monitoring in an
  isolated deployment-like environment before production release.

Stage 7's implementation is complete. The final unchecked item is intentionally
environmental: it must produce evidence from the actual deployment topology and
cannot be satisfied by mocked tests or development configuration.

## API and Client Impact Notes

- Customer mobile may continue using `POST upload/`. It must not use presigned
  upload until the server feature is enabled after deployment validation.
- The Stage 2 client protocol is: calculate file size/MIME/SHA-256, create an
  upload session, submit the returned S3 fields and file, then finalize with the
  session ID and one-time token. The S3 POST alone never creates a visible
  document.
- Loan-officer/admin clients should be prepared for `409` stale-transition
  responses once optimistic concurrency is added and should refresh the record.
- Clients should use `status` as the future canonical state only after the state
  model is normalized; current `verified` and re-upload flags can conflict.
- Separating download URL issuance from list responses will require clients to
  request a URL when the user opens/downloads a document.
- Upload/finalize clients must treat `ai_analysis_status` as asynchronous. They
  should not expect a quality score or `needs_review` decision in the initial
  upload response and may refresh list/detail to observe completion.

## Documentation and Test Alignment

`docs/DOCUMENTS_TESTING_GUIDE.md` describes the current endpoint shapes,
documents the Stage 2 session/upload/finalize protocol, corrects the re-upload
audit claim, and records known current defects. It is a current-behavior testing
guide, not evidence of production readiness.

The previous review's statements that no implementation gaps remained, in-memory
pagination was an accepted risk, reviewer dispatch was complete, and all audit
lifecycle actions were covered are superseded by this evidence-based review.

## Release Gate

Do not classify the Documents module as production-ready until all seven stages
are complete, focused and full suites pass, real MongoDB concurrency/index tests
pass, an isolated object-storage workflow proves upload/finalize/cleanup, and the
deployment configuration plus retention/audit/monitoring runbooks are validated.
