# Documents Testing Guide

> **Readiness notice (2026-08-10):** This guide documents the current API for
> development and characterization testing. The Documents module is not yet
> production-ready. See `docs/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` for the
> verified gaps and staged remediation plan. A presigned S3 POST remains a
> quarantined object until the separate finalize endpoint validates and creates
> the `Document` record.

## Scope

This guide documents the **Documents service API** under `/api/documents/` for API testing and implementation review. It covers:

- Customer document upload, list, detail, delete, and type endpoints
- Loan officer/admin verification and re-upload request endpoints
- Presigned direct-upload support for S3-like backends
- Upload validation, file scanning, and storage backend abstraction
- AI/CNN document analysis behavior, training, and validation tooling
- Retention, legal holds, account-deletion cleanup, storage inventory, and metrics

Documents are **mutable** — upload, verify, reject, delete, and re-upload all change state and trigger side effects (audit logs, emails, reviewer notifications).

## Base URL and Auth

- **Base URL:** `http://localhost:8000/api/documents`
- **Required headers:**
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- Uploads use `multipart/form-data` with `file` in `request.FILES`.

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/AUTH_ACCESS_SECURITY_GUIDE.md` | Account roles, permissions, and JWT auth |
| `docs/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` | Documents module review, risks, and roadmap |
| `docs/documents/DOCUMENT_AI_GOVERNANCE.md` | AI intended use, consent, approval, rollback, and monitoring gates |
| `docs/documents/DOCUMENTS_OPERATIONS_RUNBOOK.md` | S3, retention, legal hold, inventory, monitoring, and restore operations |
| `docs/ANALYTICS_TESTING_GUIDE.md` | Audit log endpoints that record document actions |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that generate dependent document requirements |

## Role and Permission Matrix

| Endpoint | Allowed Role | Notes |
|----------|--------------|-------|
| `POST /upload/` | Customer | Owner-only upload |
| `POST /presigned-upload/` | Customer | Creates a gated, short-lived quarantine session |
| `POST /presigned-upload/<session_id>/finalize/` | Customer owner | Validates and creates the document once |
| `GET /` | Customer, Loan Officer, Admin, Super Admin | Role-scoped results |
| `GET /<document_id>/` | Customer (owner), scoped Officer, Admin, Super Admin | Concealed from unauthorized users |
| `DELETE /<document_id>/` | Customer | Owner only; cannot delete verified docs |
| `PUT /<document_id>/verify/` | Permitted Loan Officer/Admin | Requires `review_documents` |
| `GET /types/` | Customer, Loan Officer, Admin, Super Admin | Optional `product_id` for product-specific requirements |
| `POST /<document_id>/request-reupload/` | Permitted Loan Officer/Admin | Requires `review_documents` |

---

## Reference Values

### Document Types (`DOCUMENT_TYPES` in code)

`valid_id`, `selfie_with_id`, `proof_of_address`, `business_permit`, `business_photo`, `income_proof`, `other`

### Document Statuses (`DOCUMENT_STATUSES` in code)

`pending`, `needs_review`, `approved`, `rejected`, `expired`

### Allowed MIME Types (`ALLOWED_MIME_TYPES` in code)

`image/jpeg`, `image/jpg`, `image/png`, `application/pdf`

### Max File Size

10 MB (`MAX_FILE_SIZE` in `documents/models/document.py`)

### Verification Status Derived Values

| `verified` | `status` | `verification_status` |
|------------|----------|-----------------------|
| `true` | any | `verified` |
| `false` | `rejected` | `rejected` |
| `false` | otherwise | `unverified` |

---

## Endpoint Reference

### 1. `POST /upload/`

Upload a document for the authenticated customer.

**Auth:** customer only  
**Content-Type:** `multipart/form-data`  
**Request fields (multipart):**
- `file` (required): file upload
- `document_type` (required): one of `DOCUMENT_TYPES`
- `description` (optional): string up to 500 chars

**Validation rules:**
- Allowed MIME types: `image/jpeg`, `image/jpg`, `image/png`, `application/pdf`
- Max file size: 10 MB
- File content is scanned for signature match, executable signatures, image integrity, and dangerous PDF patterns
- Eligible image analysis is persisted and queued after upload; the worker
  re-checks current `ai_consent` before reading bytes

**Response fields (`data`):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Document ID |
| `customer_id` | string | Owner customer ID |
| `customer_name` | string | Resolved display name |
| `document_type` | string | Uploaded document type |
| `filename` | string | Alias for `original_filename` |
| `original_filename` | string | Original upload filename |
| `file_size` | int | Size in bytes |
| `file_size_display` | string | Human-readable size |
| `mime_type` | string | Detected MIME type |
| `status` | string | Initial status, usually `pending` or `needs_review` |
| `verification_status` | string | `verified`, `rejected`, or `unverified` |
| `verified` | bool | Whether an officer has approved it |
| `verified_by` | string or null | Officer ID who verified |
| `verified_at` | ISO datetime or null | Verification timestamp |
| `verification_notes` | string or null | Officer notes alias |
| `rejection_reason` | string or null | Reason if rejected |
| `description` | string or null | Customer-provided description |
| `ai_analysis` | object or null | Quality/CNN results if analysis ran |
| `ai_analysis_status` | string | `not_requested`, `pending`, `processing`, `retry_wait`, `completed`, `failed`, or `skipped_no_consent` |
| `ai_analyzed_at` | ISO datetime or null | Completion time of the latest successful analysis |
| `reupload_requested` | bool | Whether re-upload was requested |
| `reupload_reason` | string or null | Reason for re-upload request |
| `reupload_requested_by` | string or null | Officer who requested re-upload |
| `file_url` | string or null | Accessible URL from storage backend |
| `created_at` | ISO datetime | Alias for `uploaded_at` |
| `uploaded_at` | ISO datetime | When the document was uploaded |
| `revision` | int | Optimistic-concurrency revision for later mutations |
| `replaces_document_id` | string or null | Earlier document replaced by this upload |
| `superseded_by_document_id` | string or null | Replacement document, when present |

**Side effects:**
- Creates a `Document` record in MongoDB
- Writes an audit log entry with `action: document_uploaded`
- Optionally notifies active reviewers asynchronously or synchronously based on settings

---

### 2. `POST /presigned-upload/`

Request presigned POST data for direct browser/client upload to S3.

**Auth:** customer only  
**Request body (JSON):**
```json
{
  "document_type": "valid_id",
  "original_filename": "photo.jpg",
  "description": "Government ID",
  "file_size": 245811,
  "mime_type": "image/jpeg",
  "sha256": "64-lowercase-or-uppercase-hex-characters"
}
```

**Response fields (`data`):**

- `upload_session_id`: owner-bound short-lived session ID
- `finalize_token`: one-time secret; the server stores only its hash
- `expires_at`: upload/finalization deadline
- `post`: S3 form `url` and required `fields`

**Notes:**
- `DOCUMENT_PRESIGNED_UPLOAD_ENABLED` defaults to `False`; the route returns
  `404` without touching storage while disabled.
- Only the S3 backend currently advertises presigned-upload support.
- Local development storage returns 400 for this endpoint
- The request must be made before uploading because the server binds the exact
  size, MIME type, SHA-256, key, session, and expiry into the policy.
- Submit every returned form field unchanged along with the file.
- The object remains in quarantine and is not a document until finalize succeeds.
- Keep the route disabled until the deployment S3 configuration and isolated
  workflow validation in the production-readiness review are complete.

### 3. `POST /presigned-upload/<session_id>/finalize/`

Finalize the quarantined object after the S3 POST succeeds.

**Auth:** owning customer only

```json
{
  "finalize_token": "token returned during session creation"
}
```

The server verifies ownership, token, expiry, object metadata, exact size, MIME
type, computed SHA-256, and normal content-scanning rules. Valid content is moved
to durable document storage and a `Document` record is created.

- First successful finalization returns `201` and `replayed: false`.
- Repeating the same completed finalization returns `200`, the same document,
  and `replayed: true`.
- Wrong owner/token is concealed as `404`; expired sessions return `410`;
  concurrent finalization returns `409`.
- Validation failure removes the quarantine object or leaves it for the scheduled
  cleanup retry when storage deletion fails.

---

### 4. `GET /` (list documents)

List documents scoped to the authenticated user.

**Auth:** customer, loan_officer, admin, super_admin  
**Query params (all optional):**

| Field | Type | Default | Validation |
|-------|------|---------|------------|
| `page` | int | 1 | >= 1 |
| `page_size` | int | 20 | 1–200 |
| `type` | string | | One of `DOCUMENT_TYPES` |
| `status` | string | | One of `DOCUMENT_STATUSES` |
| `customer_id` | string | | For officers/admins; scopes to a specific customer |
| `search` | string | | Exact document type, document ID, or customer ID; max 100 chars |

**Scope rules:**
- Customers: own documents only
- Loan officers: documents belonging to customers they are allowed to handle via application assignment scope
- Admins/super_admins: all documents, optional `customer_id` filter

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `documents` | array |
| `documents[].id` | string |
| `documents[].customer_id` | string |
| `documents[].customer_name` | string |
| `documents[].document_type` | string |
| `documents[].filename` | string |
| `documents[].original_filename` | string |
| `documents[].file_size` | int |
| `documents[].file_size_display` | string |
| `documents[].mime_type` | string |
| `documents[].status` | string |
| `documents[].verification_status` | string |
| `documents[].verified` | bool |
| `documents[].verified_by` | string or null |
| `documents[].verified_at` | ISO datetime or null |
| `documents[].verification_notes` | string or null |
| `documents[].rejection_reason` | string or null |
| `documents[].description` | string or null |
| `documents[].ai_analysis` | object or null |
| `documents[].reupload_requested` | bool |
| `documents[].reupload_reason` | string or null |
| `documents[].reupload_requested_by` | string or null |
| `documents[].file_url` | null (lists are metadata-only) |
| `documents[].revision` | int |
| `documents[].created_at` | ISO datetime |
| `documents[].uploaded_at` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

**Search behavior:**

- Document types accept their exact enum or label form, such as `valid_id` or
  `Valid ID`.
- A valid ObjectId searches both the exact document ID and customer ID.
- Filename and free-text customer-name search return `400`; randomized filename
  encryption cannot support safe indexed substring search.
- Find customers by name through the scoped Profiles directory, then pass the
  returned ID through `customer_id` or exact `search`.

**Pagination behavior:**

- Scope, filters, deletion visibility, count, sorting, skip, and limit run in
  MongoDB before document decryption.
- Ordering is deterministic: `uploaded_at` descending, then `_id` descending.
- `page_size` outside 1–200 returns `400` rather than being silently clamped.
- An empty result has `total_pages: 0`. A page beyond the final page returns an
  empty `documents` array while preserving `total` and `total_pages`.
- Customer names for one page are resolved with one bounded query.

---

### 5. `GET /<document_id>/` (detail)

Get a single document's metadata.

**Auth:** role-scoped  
**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `document_id` | string | yes | Valid MongoDB ObjectId |

**Response fields (`data`):** Same document object shape as list entries, but an
authorized detail response may issue `file_url` on demand.

**Behavior:**
- Customers can only fetch their own documents
- Officers pass through `require_customer_scope_for_officer`
- Admins/super_admins can fetch any document

---

### 6. `DELETE /<document_id>/`

Delete a document record and its stored file.

**Auth:** customer (owner only)  
**Constraints:**
- Only unverified `pending`, `needs_review`, and `rejected` documents can be
  deleted. Approved, verified, and expired documents return 400.
- Optional JSON `revision` must match the current revision when sent.
- The document is atomically claimed before storage deletion, preventing a
  review/delete race.
- A completed deletion returns `200`. If storage or metadata completion fails,
  the endpoint returns `202` and the scheduled reconciler retries idempotently.

**Response fields (`data`):**
- `message`: success message

---

### 7. `PUT /<document_id>/verify/`

Approve or reject a document.

**Auth:** loan_officer or admin with `review_documents`
**Request body (JSON):**
- `action` or `status`: `approve` or `reject` (either accepted)
- `rejection_reason`: required when rejecting; non-empty
- `notes`: optional officer notes
- `revision`: optional non-negative revision; stale values return `409`

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `verified` | bool |
| `revision` | int |

**Side effects:**
- On approve: sets `status=approved`, `verified=true`, `verified_by`, `verified_at`
- On reject: sets `status=rejected`, `rejection_reason`
- Review decisions clear incompatible stale rejection/re-upload/verification
  compatibility fields.
- Sends notification email to customer
- Writes audit log entry with `action: document_verified` or `action: document_rejected`

**State conflicts:**

- `approved` and `expired` are terminal and return `409` for review transitions.
- A rejected document must first receive an explicit re-upload request before it
  can be reviewed again.

---

### 8. `GET /types/`

Get available document types and whether each is required.

**Auth:** customer, loan_officer, admin, super_admin  
**Query params (optional):**

| Field | Type | Description |
|-------|------|-------------|
| `product_id` | string | If provided, returns product-specific required document set |

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `document_types` | array |
| `document_types[].value` | string |
| `document_types[].label` | string |
| `document_types[].required` | bool |
| `requirement_source` | string | `baseline` or `product` |

---

### 9. `POST /<document_id>/request-reupload/`

Request that a customer re-upload a document.

**Auth:** loan_officer or admin with `review_documents`
**Request body (JSON):**
```json
{
  "reason": "Please upload a clearer image",
  "revision": 0
}
```

**Validation:**
- `reason` is required
- `reason` max length is 1000 characters
- Approved and expired documents are terminal and return `409`.

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `document_id` | string |
| `status` | string | Set to `needs_review` |
| `reupload_requested` | bool | `true` |
| `revision` | int | Incremented concurrency revision |

**Side effects:**
- Atomically sets `reupload_requested=true`, `reupload_reason`,
  `reupload_requested_by`, and `reupload_requested_at`.
- Sends email notification to customer
- Writes an allowlisted `document_reupload_requested` audit event without the
  reason text.

---

## Upload Validation & Security

Implemented in `documents/serializers/document_serializers.py`.

- **MIME allowlist:** `image/jpeg`, `image/jpg`, `image/png`, `application/pdf`
- **Max size:** 10 MB
- **File-signature validation:** content bytes must match declared MIME type
- **Executable rejection:** blocks PE, ELF, Mach-O, and Java class signatures
- **Image integrity:** PIL `Image.verify()` for JPEG/PNG
- **Image resource limits:** rejects configured width, height, pixel-count, and
  Pillow decompression-bomb violations before storage
- **PDF active-content scan:** scans the complete bounded upload and rejects
  `/javascript`, `/js`, `/openaction`, `/launch`, `/aa`, `/richmedia`, and
  `/embeddedfile`

These structural checks do not replace an approved malware scanner or PDF
content-disarm policy. That production policy remains a release gate.

**AI analysis gating:**
- Skips analysis when `DOCUMENT_UPLOAD_AI_ANALYSIS` is false
- The worker skips without reading bytes when current `ai_consent` is absent,
  withdrawn, or cannot be confirmed
- Only runs for image uploads (`image/*`); PDFs skip AI image analysis
- Upload/finalize responses do not wait for inference; poll list/detail for the
  operational status and result

---

## Storage Backends

Implemented in `documents/storage/backends.py`.

- **LocalStorageBackend:** stores files under `MEDIA_ROOT/documents/<customer_id>/<document_type>/<filename>`
- **S3-compatible backends:** supports multipart upload and presigned POST generation
- Common interface: `save()`, `delete()`, `get_url()`, `get_file_bytes()`

---

## AI Analysis & CNN Behavior

Implemented in `documents/services/analyzer.py` and `documents/services/cnn_model.py`.

**Current repository state (2026-08-10):**

- `documents/ml/models/document_classifier.pth` is absent, so this checkout uses
  quality-check mode and the CNN evaluation command exits with "No trained CNN
  model found."
- With `DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION=True`, a consented image cannot
  pass type validation while the model is unavailable and is routed to
  `needs_review`.
- The development registry is deliberately `not_approved`; it has no artifact
  or approved dataset-manifest hash. Historical charts/configuration are not
  reproducible production evidence.
- The current dataset is severely imbalanced, contains exact duplicates including
  a train/holdout duplicate group, and gives four classes only one to three
  holdout examples. Do not use the displayed overall accuracy as a production
  acceptance result. See the production-readiness review for the full ML audit.

**Analysis modes:**
- `cnn`: MobileNetV2 model loaded; returns classification and quality results
- `quality_check`: model unavailable; returns quality checks only
- `failed`: safe failure result; no exception string is returned or persisted

Analysis runs in Celery with MongoDB claim leases, bounded exponential backoff,
and a one-minute reconciliation schedule. Duplicate/stale tasks cannot analyze
the same active claim, and an abandoned `processing` lease is reclaimable.

**Quality checks:**
- Minimum dimensions: 200x200
- Blur detection: Laplacian variance threshold
- Aspect ratio warning: >5:1
- Brightness checks: too dark (<40) or overexposed (>240)
- `DOCUMENT_AI_REQUIRE_BLUR_CHECK=True` makes missing OpenCV/NumPy fail analysis
  and degrade `/api/health/` instead of silently skipping blur detection

**CNN classification:**
- Model class: `MobileNetV2` with custom classifier head
- Classes (alphabetical, matching `ImageFolder` ordering):
  - `business_permit`
  - `business_photo`
  - `income_proof`
  - `invalid`
  - `proof_of_address`
  - `selfie_with_id`
  - `valid_id`

The shared `document-photo-letterbox-v2` preprocessing preserves aspect ratio
and pads to a square. Training no longer mirrors documents or stretches them.
A maximum class confidence below the threshold becomes `unknown`; uploads typed
as `other` require human review because `other` is not a classifier class.

**Type validation controls:**
- `DOCUMENT_TYPE_CONFIDENCE_THRESHOLD` (default `0.75`)
- `DOCUMENT_ENFORCE_TYPE_MATCH` (default `True`)
- `DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION` (default `True`)
- `DOCUMENT_AI_REQUIRE_APPROVED_MODEL` (production default `True`)
- `DOCUMENT_AI_REQUIRE_BLUR_CHECK` (production default `True`)
- `DOCUMENT_MAX_IMAGE_PIXELS`, `DOCUMENT_MAX_IMAGE_WIDTH`, and
  `DOCUMENT_MAX_IMAGE_HEIGHT` (startup-validated resource limits)

**Auto-flagging:**
- Upload status becomes `needs_review` when analysis fails validation or quality score is below `0.5`

**Response fields when AI analysis runs:**

| Field | Type |
|-------|------|
| `predicted_type` | string |
| `type_confidence` | float or null |
| `type_matches_expected` | bool or null |
| `type_validation_passed` | bool |
| `analysis_mode` | string | `cnn` or `quality_check` |
| `analysis_status` | string | `completed` or `failed` |
| `model_available` | bool |
| `model_status` | string | Safe artifact readiness/error code |
| `model_version` | string or null |
| `preprocessing_version` | string |
| `threshold_policy_version` | string |
| `manual_review_required` | bool |
| `quality_score` | float 0–1 |
| `quality_issues` | array of strings |

---

## CNN Training & Testing Commands

**Training:**

Training is refused unless `documents/ml/training_data/dataset_manifest.json`
passes the fail-closed validator. Training writes a SHA-bound registry entry as
`not_approved`; independent governance approval is still required.

```bash
python scripts/build_document_dataset_manifest.py \
  --data-root /approved/dataset \
  --provenance /approved/provenance.json
python scripts/check_training_data.py
python scripts/evaluate_document_model.py predictions.json \
  --output evaluation-report.json
python scripts/approve_document_model.py \
  --config documents/ml/models/model_config.json \
  --artifact documents/ml/models/document_classifier.pth \
  --evaluation evaluation-report.json
```

The approval command is dry-run by default. Its explicit `--apply` mode also
requires `--approved-by`; do not run it until the independent report, privacy
review, and rollback target are approved.

```bash
python manage.py train_document_classifier
python manage.py train_document_classifier --epochs 20
python manage.py train_document_classifier --batch-size 16
python manage.py train_document_classifier --learning-rate 0.0005
python manage.py train_document_classifier --fine-tune
```

**Training artifacts:**
- `documents/ml/models/document_classifier.pth`
- `documents/ml/models/model_config.json`
- `documents/ml/reports/*` (if matplotlib installed)

The `.pth` artifact is intentionally ignored by Git and is currently missing.
A production model must be supplied through an approved, integrity-checked model
artifact workflow; generating it locally is not by itself a deployment process.

**Validation:**

```bash
python scripts/test_cnn_model.py /path/to/image.jpg
python scripts/test_cnn_model.py /path/to/folder --batch
python scripts/test_cnn_model.py documents/ml/test_data --confusion
```

---

## Smoke Test Sequence

1. Authenticate as a customer and call `GET /types/`.
2. Upload one image (`valid_id`) and one PDF to confirm both acceptance and AI-skip behavior for PDF.
3. Call `GET /` and verify pagination/filter fields.
4. Call `GET /<document_id>/` for uploaded items.
5. Login as a loan officer with `review_documents` and verify one document via
   `PUT /<document_id>/verify/`, sending the latest `revision`.
6. Request re-upload on another document via `POST /<document_id>/request-reupload/`.
7. Login as customer and confirm verified docs cannot be deleted.
8. Confirm the presigned routes return 404 while disabled. In an isolated S3
   environment, create a session, upload with every returned field, finalize,
   and repeat finalize to confirm the same document is returned.
9. If retraining is needed, run `train_document_classifier` and validate with `scripts/test_cnn_model.py`.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Malformed document ID, missing `file`, invalid `document_type`, invalid filters or non-indexed search, invalid verify payload, missing/blank re-upload reason, oversized/unsafe content, or disallowed deletion |
| `401 Unauthorized` | Missing or invalid JWT |
| `403 Forbidden` | Role mismatch, inactive staff account, or missing `review_documents` permission |
| `404 Not Found` | Document not found in current scope |
| `409 Conflict` | Invalid lifecycle transition or stale mutation `revision` |
| `410 Gone` | A presigned upload session expired before finalization |

Standard error shape:
```json
{
  "status": "error",
  "message": "...",
  "errors": { }
}
```

Standard success shape:
```json
{
  "status": "success",
  "message": "...",
  "data": { }
}
```

---

## Where to Look in Code

| Area | Path |
|------|------|
| URL routing | `documents/urls.py` |
| Views | `documents/views/document_views.py` |
| Serializers/validation | `documents/serializers/document_serializers.py` |
| Model | `documents/models/document.py` |
| Presigned session model | `documents/models/upload_session.py` |
| Storage backends | `documents/storage/backends.py` |
| Presigned finalization | `documents/services/presigned_upload.py` |
| Storage reconciliation | `documents/services/storage_reconciliation.py` |
| Recoverable audit writer | `documents/services/audit.py` |
| Bounded listing helpers | `documents/services/listing.py` |
| AI analysis service | `documents/services/analyzer.py` |
| Background analysis orchestration | `documents/services/analysis.py` |
| Shared preprocessing policy | `documents/services/preprocessing.py` |
| Notification outbox | `documents/models/notification_delivery.py` |
| AI governance | `docs/documents/DOCUMENT_AI_GOVERNANCE.md` |
| CNN model | `documents/services/cnn_model.py` |
| Training command | `documents/management/commands/train_document_classifier.py` |
| Test script | `scripts/test_cnn_model.py` |

---

## Notes for API Test Automation

1. Upload endpoints expect `multipart/form-data`; all others are JSON `GET` or `PUT`/`POST` with JSON bodies.
2. Customer uploads return after durable storage/metadata creation. Eligible AI
   work starts as `pending`; an invalid completed result may later change an
   unreviewed `pending` document to `needs_review`, but never overrides a human
   approval/rejection.
3. Officer verify endpoints accept both `action` and `status` fields; tests should exercise both spellings.
4. Rejection requires `rejection_reason`; blank/whitespace-only values are rejected by the serializer.
5. Document list filtering, count, deterministic sorting, skip, and limit happen
   in MongoDB; only the requested page is decrypted.
6. `customer_name` values for a list page are bulk-resolved with one Customer
   query. Detail responses retain single-resource resolution.
7. List responses deliberately return `file_url: null`; an authorized detail
   request is the on-demand URL boundary.
8. Presigned uploads return 404 while disabled, or 400 when enabled with an unsupported backend. With S3, test the full session → quarantine upload → finalize → idempotent replay flow; the S3 POST alone must not create a document.
9. Reviewer and customer outcome notifications are persisted in the encrypted
   `document_notification_deliveries` outbox before task publication. Unique
   document/type/recipient keys, leases, bounded backoff, and scheduled
   reconciliation make broker and delivery failures recoverable.
10. Document audit events cover upload/finalize, review, re-upload, delete,
    privileged list/detail reads, and denied sensitive reads. Failed writes are
    allowlisted and reconciled from `audit_write_failures`.
11. Invalid ObjectId strings return `400 Invalid document_id format` in detail,
    delete, verify, and request-reupload handlers. Well-formed but missing or
    concealed IDs return `404`.
12. `search` intentionally rejects filename and free-text name queries. Use an
    exact type/ID or the Profiles directory plus `customer_id`.
13. Stage 3/4 tests exercise revision races, partial storage failures, permission
    and real access-helper denials, URL privacy, audit recovery, and recipient
    scope. Repeat concurrency and recovery against isolated real MongoDB/object
    storage during Stage 7 deployment validation.

14. Real-Mongo load/explain, document-index, and concurrent-review tests are
    opt-in through `REAL_MONGO_TEST_URI`; they create and drop a randomly named
    database and must never target a production database account.

15. Stage 7 tests cover versioned deadlines, rejected/superseded retention,
    legal-hold exclusion/release, account cleanup reconciliation, safe customer
    export, count-only inventory, fail-closed storage behavior, and operational
    backlog metrics, image/PDF resource hardening, and legacy lifecycle
    contradictions. They do not inspect the real bucket.

Stage 7 focused command:

```bash
pytest -q tests/test_documents_stage7_retention_operations.py
```

Latest local result: the Documents/S3/analyzer run passed 85 tests and skipped
the explicitly gated real-S3 test. The full suite passed 1,049 tests and skipped
20 opt-in integration tests.

Read-only deployment checks (run only after selecting the intended isolated
Mongo/S3 environment):

```bash
python manage.py validate_document_storage
python manage.py inventory_document_storage
```

Opt-in real-service validation requires explicit mutation permission and an
isolated target. These commands are intentionally not part of the normal suite:

```bash
REAL_MONGO_TEST_URI='mongodb://isolated-test-host/' \
pytest -q -m real_mongo tests/test_stage9_real_mongo.py

REAL_S3_TEST_BUCKET='isolated-documents-bucket' \
REAL_S3_TEST_REGION='us-east-1' \
REAL_S3_TEST_ALLOW_MUTATION=yes \
pytest -q -m real_s3 tests/test_documents_real_s3.py
```

The S3 test creates only UUID-scoped quarantine/final objects, validates replay,
and removes both objects in `finally`. The bucket itself is never created or
deleted by the test.

Focused Stage 3–7 regression command:

```bash
pytest -q tests/test_documents_stage3_consistency.py \
  tests/test_documents_stage4_authorization_audit.py \
  tests/test_documents_stage5_scalable_listing.py \
  tests/test_documents_stage6_background_ai_notifications.py \
  tests/test_documents_stage7_retention_operations.py \
  tests/test_documents_stage1_contract.py \
  tests/test_documents_stage2_presigned_upload.py tests/test_documents_api.py
```
