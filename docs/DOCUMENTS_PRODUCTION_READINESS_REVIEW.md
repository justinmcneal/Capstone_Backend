# Documents Production Readiness Review

Last updated: 2026-08-09

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
allowlisted audit queue. Remaining blockers are concentrated in scalable query
delivery, notification/AI operations, retention/account-deletion integration,
and deployment-target configuration and validation.

Current remediation status:

- [x] Stage 1 — Contract, state machine, and regression baseline
- [x] Stage 2 — Safe upload finalization and content security
- [x] Stage 3 — Atomic lifecycle transitions and storage consistency
- [x] Stage 4 — Authorization, privacy, and audit completeness
- [ ] Stage 5 — Query scalability and response delivery
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
| `GET /` | Customer/officer/admin/super admin | Partial; authorized/audited but query remains unbounded |
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
- AI runs only under the existing global/consent/image gates. Analyzer failure
  is stored as a safe failed/manual-review result without an internal exception
  string.
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
- Quality checks cover minimum dimensions, aspect ratio, brightness, and blur
  when optional image dependencies are available.
- A MobileNetV2 classifier and training command exist for seven image classes.
- Confidence, expected/predicted type, quality score, analysis mode, and issues
  can be persisted with the document.
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
- `scripts/check_training_data.py` reports below-minimum classes as warnings but
  still prints `MINIMUM REQUIREMENTS MET` and exits successfully unless a class
  is empty or missing. It does not detect duplicates, train/test leakage,
  provenance, subject/source grouping, or class-balance release gates.

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

### 4. Reviewer lookup and recipient scope are fixed; delivery durability remains

`Document.find_by_id` now satisfies the Celery task contract. Reviewers must be
active and have `review_documents`; when a customer has an assigned officer,
only that officer is selected, while permitted admins retain oversight access.
Bounded retry/backoff, idempotency, a durable delivery outbox, and notification
reconciliation remain Stage 6 work.

### 5. Listing does not scale and performs excessive sensitive work

The list endpoint loads every matching document, constructs/decrypts every
model, applies search in Python, and only then paginates. Admin listings can be
unbounded. Filename search cannot use a normal index because filename encryption
is randomized. Customer-name resolution still causes per-row database work.
Stage 4 stopped list serialization from minting storage URLs; document detail is
now the on-demand URL boundary.

This is not an acceptable production risk merely because today's development
collection is small. Server-side bounded pagination, an approved search design,
bulk customer lookup, and bounded database work are required.

### 6. Audit coverage and recovery are remediated

Upload/finalize, review, re-upload, delete, staff list/detail reads, and denied
sensitive reads use one allowlisted document audit writer and the shared trusted-
proxy client-IP helper. Filenames, review notes, rejection reasons, and re-upload
reasons are excluded from audit payloads. Failed writes are queued under the
`documents` domain and replayed every minute. Required staff-read audits fail
closed with `503`; post-commit mutation audit failures do not misreport the
mutation as failed.

### 7. Error handling can expose internals

- Stage 1 now returns `400 Invalid document_id format` for malformed IDs in
  detail, delete, verify, and request-reupload handlers.
- Upload stores `str(exception)` in `ai_analysis` and treats an analyzer exception
  as valid; that internal message can later be returned through the API.
- Verification no longer logs the authenticated email or request payload.
- S3 URL generation can fall back to returning an internal `s3://` URI.
- Unknown storage backend names silently fall back to local storage.

### 8. Production storage configuration is not wired

`config/settings.py` hard-codes `DOCUMENT_STORAGE_BACKEND = 'local'` and does not
load the AWS settings consumed by `S3StorageBackend`. `.env.example` lists those
variables, but setting them does not configure this Django settings module.
Local media serving is only wired through Django in debug mode, so this is a
deployment blocker rather than a harmless default.

Production must fail closed on an unknown/missing backend, validate bucket and
region configuration at startup, require private objects and encryption at
rest, and define presigned URL expiry/CORS/lifecycle behavior.

### 9. Document retention and customer lifecycle are missing

The Profiles lifecycle cleanup removes profile-domain records but does not
remove document metadata or stored document objects. No document retention,
legal-hold, expiry, account-deletion, orphan inventory, or cleanup command was
found. Document data is also absent from the profile-only customer export, with
no separate Documents export policy documented.

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
  side effect failed; persist audit failures and leave notification delivery
  durability to Stage 6.~~
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

**Status: Blocked for production**

- [ ] Replace `Document.find()` list materialization with database-side sort,
  bounded pagination, and count or cursor pagination.
- [ ] Decide an approved searchable-metadata design compatible with encryption;
  do not add plaintext filename search accidentally.
- [ ] Bulk-resolve customer display names and eliminate per-row lookups.
- [x] ~~Separate metadata listing from short-lived URL issuance by returning no
  URL from list calls and issuing it only from authorized detail calls.~~
- [ ] Add deterministic ordering, stable empty-page semantics, and pagination
  boundary tests.
- [ ] Load/performance-test customer, officer, and admin scopes at expected and
  worst-case collection sizes.

### Stage 6 — Background work, notifications, and AI governance

**Status: Blocked for production**

- [x] ~~Fix the missing `Document.find_by_id` lookup used by the Celery task.~~
- [ ] Add a Celery task test that exercises the actual model contract plus
  delivery failure/retry behavior.
- [ ] Add bounded retries/backoff, idempotency/delivery state, and reconciliation
  for reviewer/customer notifications.
- [ ] Move expensive analysis out of the request path or explicitly budget and
  monitor synchronous latency/memory.
- [ ] Fail safely on analysis errors without exposing exception strings or
  marking the result valid.
- [ ] Load inference architecture without downloading pretrained weights and add
  startup/health checks for the required artifact.
- [ ] Create a versioned model registry entry containing artifact hash, code and
  preprocessing versions, dataset-manifest hash, approval status, metrics,
  threshold policy, deployment date, and rollback target.
- [ ] Remove exact duplicates and create immutable grouped/stratified
  train/validation/holdout manifests by source/document/subject. Never tune on
  the final holdout set.
- [ ] Collect materially more licensed, consented, anonymized, representative
  samples for every underrepresented class and a broader out-of-distribution
  set. Establish minimum independent sample counts before evaluating a class.
- [ ] Replace generic augmentation/aspect distortion with a validated
  document-photo preprocessing and augmentation policy.
- [ ] Evaluate macro and per-class precision/recall/F1, confusion matrix,
  calibration, confidence intervals, subgroup/device robustness, false-accept
  and false-reject costs, and open-set rejection. Set calibrated per-class or
  risk-based thresholds rather than relying on headline accuracy.
- [ ] Decide how `other` is represented and add an explicit unknown/OOD outcome
  instead of forcing every image into a known class.
- [ ] Persist model/policy/preprocessing versions and operational analysis
  status with each inference.
- [ ] Make the dataset checker fail on below-minimum classes, corrupt/undersized
  files, exact/cross-split duplicates, missing provenance, and split-manifest
  violations; emit a machine-readable report.
- [ ] Complete privacy/license/consent/anonymization review for every dataset
  item. Keep approved datasets in access-controlled versioned storage rather
  than ordinary Git, and address existing Git history under an approved data-
  governance procedure.
- [ ] Document AI intended use, human-review requirement, consent withdrawal,
  appeal/correction, acceptance metrics, deployment, rollback, and drift policy.
- [ ] Add model-available/unavailable/error/stale-task and consent-transition
  tests.

### Stage 7 — Retention, deployment configuration, and operations

**Status: Blocked for production**

- [ ] Load `DOCUMENT_STORAGE_BACKEND` and all required S3 options from validated
  settings; fail closed outside development.
- [ ] Define and test private bucket, server-side encryption, CORS, URL expiry,
  object ownership, and least-privilege IAM requirements.
- [ ] Integrate document metadata and objects with customer account deletion,
  including retryable partial-cleanup state.
- [ ] Define retention periods, legal hold, expiry, superseded-document cleanup,
  customer export, and backup/restore behavior.
- [ ] Add dry-run-by-default orphan, missing-object, expired-upload-session,
  contradictory-state, and deleted-customer retention inventories.
- [ ] Add metrics/alerts for upload/finalize failures, orphan counts, storage
  reconciliation, review backlog/age, notification failures, AI failures, audit
  backlog, and URL-generation errors.
- [ ] Validate real MongoDB indexes/concurrency, object storage, Redis/Celery,
  encryption keys, proxies, throttles, logging, restore, and monitoring in an
  isolated deployment-like environment before production release.

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
