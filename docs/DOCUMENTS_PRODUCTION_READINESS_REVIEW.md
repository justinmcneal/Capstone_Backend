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

The highest-risk gap is the presigned upload route. It returns permission to
write an object directly to S3 but has no upload-session record, restrictive
size/type conditions, completion endpoint, server-side validation, `Document`
creation, audit event, AI analysis, or abandoned-object cleanup. A successful
presigned POST therefore creates an untrusted, untracked storage object rather
than a usable document.

Other production blockers include non-atomic storage/database workflows, a
broken asynchronous reviewer task (`Document.find_by_id` does not exist),
unscoped reviewer broadcasts, contradictory review states, unbounded in-memory
listing, incomplete audit coverage, missing document retention/account-deletion
integration, and production storage settings that are advertised in
`.env.example` but are not loaded by `config/settings.py`.

Current remediation status:

- [ ] Stage 1 — Contract, state machine, and regression baseline
- [ ] Stage 2 — Safe upload finalization and content security
- [ ] Stage 3 — Atomic lifecycle transitions and storage consistency
- [ ] Stage 4 — Authorization, privacy, and audit completeness
- [ ] Stage 5 — Query scalability and response delivery
- [ ] Stage 6 — Background work, notifications, and AI governance
- [ ] Stage 7 — Retention, deployment configuration, and operations

## Verified Implemented Foundations

### Models and persistence

- A PyMongo-backed `Document` model stores records in `documents`.
- The model supports insert/update, lookup, customer lookup, delete, approval,
  rejection, re-upload state, serialization, and index creation.
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
| `POST upload/` | Customer | Partial; core upload works, consistency gaps remain |
| `POST presigned-upload/` | Customer | Blocked; object grant only, not a completed upload |
| `GET /` | Customer/officer/admin/super admin | Partial; scoped but unbounded |
| `GET <document_id>/` | Role/resource scoped | Partial; invalid IDs return `500` |
| `DELETE <document_id>/` | Owning customer | Partial; storage/DB deletion is non-atomic |
| `PUT <document_id>/verify/` | Officer/admin | Partial; state/concurrency/audit gaps remain |
| `GET types/` | Authenticated supported roles | Implemented |
| `POST <document_id>/request-reupload/` | Officer/admin | Partial; state/audit gaps remain |

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
- On 2026-08-09, the focused suite collected and passed 21 tests:

  ```text
  pytest -q tests/test_documents_ai_consent.py tests/test_documents_api.py \
    tests/test_documents_integration_s3.py \
    tests/test_s3_multipart_and_retry.py \
    tests/test_s3_presigned_client_upload.py \
    tests/test_s3_presigned_post.py tests/test_s3_storage_backend.py
  ```

- Most endpoint tests are unit-style and replace authorization, persistence,
  storage, audit, or notification dependencies. There is no real-Mongo document
  concurrency/index suite and no end-to-end presigned-finalization workflow.

## Confirmed Production Blockers and Gaps

### 1. Presigned upload is incomplete and unsafe as a document workflow

`POST presigned-upload/` creates a key and returns a generic presigned POST. It
does not impose a maximum content length or required MIME type, issue a tracked
single-use upload session, bind an expected hash, or create a pending document
record. After the client uploads, no endpoint verifies object existence, size,
signature, image/PDF safety, or ownership and no endpoint finalizes the
`Document` record. The normal AI, audit, and reviewer-notification paths never
run. Abandoned and malicious objects have no cleanup path.

Until Stage 2 is complete, disable or do not expose this endpoint outside an
isolated development environment.

### 2. Upload and deletion can leave storage and MongoDB inconsistent

Direct upload writes storage before MongoDB. A database failure leaves an
orphaned object. An audit failure after both writes returns `500` even though the
upload already succeeded, inviting a retry and duplicate document.

Delete removes storage first and ignores a false return from the S3 backend,
then deletes MongoDB metadata. Storage failure can therefore report success and
retain the object; database failure after storage removal can retain a broken
record. No durable cleanup/reconciliation queue exists.

### 3. Review and re-upload transitions are not atomic

Approval, rejection, and re-upload load a document and save the full snapshot.
There is no revision or compare-and-set condition, so concurrent reviewers can
overwrite one another. Terminal transitions are not constrained.

State fields are not normalized during transitions. For example, requesting a
re-upload on an approved document sets `status=needs_review` without clearing
`verified`; approval can retain an old rejection or re-upload reason. These
combinations can make the `verified`, `status`, and re-upload fields disagree.
Customer delete also races with verification between its read and delete.

### 4. Asynchronous reviewer notification is broken and over-broad

`notify_reviewers_document_pending_task` calls `Document.find_by_id`, but the
model does not define that method. With asynchronous notification enabled by
default, queued work fails when executed.

The notification service sends customer name, document type, and document ID to
every active officer and admin, rather than only reviewers with resource scope
and the required permission. The task has no retry/backoff, idempotency key,
durable outbox, delivery state, or reconciliation process.

### 5. Listing does not scale and performs excessive sensitive work

The list endpoint loads every matching document, constructs/decrypts every
model, applies search in Python, and only then paginates. Admin listings can be
unbounded. Filename search cannot use a normal index because filename encryption
is randomized. Customer-name resolution and file-URL generation can also cause
per-row database and S3 calls.

This is not an acceptable production risk merely because today's development
collection is small. Server-side bounded pagination, an approved search design,
bulk customer lookup, and controlled URL generation are required.

### 6. Audit coverage and failure semantics are incomplete

- Upload and approve/reject attempt audit writes, but audit happens after the
  durable mutation and a failure is returned as `500`.
- Delete and request-reupload do not create audit events.
- Sensitive officer/admin list and detail reads are not audited.
- Upload audit metadata includes the original filename, which may contain
  personal information.
- Document actions read raw `REMOTE_ADDR` rather than the shared trusted-proxy IP
  policy.
- There is no document-domain failed-audit queue/reconciler like the Profiles
  module uses.

The testing guide previously claimed re-upload was audited; the code does not do
that today.

### 7. Error handling exposes internals or returns incorrect statuses

- Malformed `document_id` values reach `ObjectId(...)` inside broad exception
  handlers and produce generic `500` responses in detail, delete, and verify.
- Upload stores `str(exception)` in `ai_analysis` and treats an analyzer exception
  as valid; that internal message can later be returned through the API.
- Verification logs the authenticated email and full request payload, including
  notes and rejection reason.
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

**Status: PARTIAL**

- [x] ~~Inventory routes, roles, persistence, storage, AI, downstream consumers,
  configuration, and existing tests.~~
- [x] ~~Record the 21-test focused baseline.~~
- [ ] Define the canonical state machine and allowed transitions for `pending`,
  `needs_review`, `approved`, `rejected`, `expired`, and re-upload replacement.
- [ ] Decide whether an approved document is immutable, superseded, or versioned
  when a replacement is uploaded.
- [ ] Define the canonical response/error contract and invalid-ID behavior.
- [ ] Decide whether presigned upload is supported or temporarily removed.
- [ ] Add characterization tests for every blocker above before implementation.

### Stage 2 — Safe upload finalization and content security

**Status: Blocked for production**

- [ ] Introduce a short-lived, owner-bound, single-use upload-session record.
- [ ] Generate restrictive presigned conditions for key, MIME type, and maximum
  content length; require private ACL/encryption settings.
- [ ] Add a finalize endpoint that validates session ownership and expiry, heads
  the object, verifies exact key/size/type/hash, performs normal content scans,
  creates the document once, audits it, and enqueues post-processing.
- [ ] Make finalize idempotent and reject key substitution or replay.
- [ ] Quarantine uploads until validation succeeds and delete failed/abandoned
  objects with a scheduled reconciler.
- [ ] Strengthen PDF/image defenses with decompression-bomb handling and a
  reviewed malware/quarantine policy.
- [ ] Add end-to-end mocked-S3 and deployment-target tests for success, replay,
  expiry, oversize, wrong type/key, failed scan, and cleanup.

### Stage 3 — Atomic lifecycle transitions and storage consistency

**Status: Blocked for production**

- [ ] Add a `revision` and narrow compare-and-set updates for review, re-upload,
  and delete transitions; return `409` on stale writes.
- [ ] Enforce allowed transitions and clear incompatible verification/rejection/
  re-upload fields atomically.
- [ ] Model replacement/supersession rather than mutating contradictory flags.
- [ ] Add durable storage-operation state and idempotent reconciliation for
  failed upload, finalize, and delete steps.
- [ ] Do not return mutation failure merely because a post-commit audit/email
  side effect failed; record and reconcile the failed side effect.
- [ ] Add concurrent-review, review/delete-race, duplicate-finalize, partial-
  failure, and retry tests against an isolated real MongoDB instance.

### Stage 4 — Authorization, privacy, and audit completeness

**Status: PARTIAL**

- [x] ~~Enforce customer ownership and loan-officer resource scope on current
  API reads and mutations.~~
- [ ] Require explicit document-review permissions for admin/officer mutations.
- [ ] Scope reviewer notifications to recipients authorized for that customer.
- [ ] Audit delete, re-upload, staff list/detail reads, denied sensitive reads,
  and presigned-session/finalization events with allowlisted metadata.
- [ ] Use the trusted-proxy IP helper and remove sensitive request-payload logs.
- [ ] Add recoverable, allowlisted failed-audit persistence and reconciliation.
- [ ] Define whether document URLs are issued separately/on demand so list calls
  do not mint access URLs for every row.
- [ ] Add negative cross-customer, cross-officer, inactive-account, and permission
  matrix tests without bypassing the real access helpers.

### Stage 5 — Query scalability and response delivery

**Status: Blocked for production**

- [ ] Replace `Document.find()` list materialization with database-side sort,
  bounded pagination, and count or cursor pagination.
- [ ] Decide an approved searchable-metadata design compatible with encryption;
  do not add plaintext filename search accidentally.
- [ ] Bulk-resolve customer display names and eliminate per-row lookups.
- [ ] Separate metadata listing from short-lived download URL issuance.
- [ ] Add deterministic ordering, stable empty-page semantics, and pagination
  boundary tests.
- [ ] Load/performance-test customer, officer, and admin scopes at expected and
  worst-case collection sizes.

### Stage 6 — Background work, notifications, and AI governance

**Status: Blocked for production**

- [ ] Fix the missing document lookup used by the Celery task and add a task test
  that exercises the actual model contract.
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

- Customer mobile must continue using `POST upload/` for complete uploads until
  the finalized presigned protocol exists. Receiving a presigned POST does not
  currently create a document visible to the customer or staff.
- A safe presigned workflow will require customer-client changes: create upload
  session, upload to S3, then finalize with the session token and integrity
  metadata.
- Loan-officer/admin clients should be prepared for `409` stale-transition
  responses once optimistic concurrency is added and should refresh the record.
- Clients should use `status` as the future canonical state only after the state
  model is normalized; current `verified` and re-upload flags can conflict.
- Separating download URL issuance from list responses will require clients to
  request a URL when the user opens/downloads a document.

## Documentation and Test Alignment

`docs/DOCUMENTS_TESTING_GUIDE.md` describes the current endpoint shapes and now
explicitly marks the presigned route as incomplete, corrects the re-upload audit
claim, and records known current defects. It is a current-behavior testing guide,
not evidence of production readiness.

The previous review's statements that no implementation gaps remained, in-memory
pagination was an accepted risk, reviewer dispatch was complete, and all audit
lifecycle actions were covered are superseded by this evidence-based review.

## Release Gate

Do not classify the Documents module as production-ready until all seven stages
are complete, focused and full suites pass, real MongoDB concurrency/index tests
pass, an isolated object-storage workflow proves upload/finalize/cleanup, and the
deployment configuration plus retention/audit/monitoring runbooks are validated.
