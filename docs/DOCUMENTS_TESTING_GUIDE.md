# Documents Testing Guide

## Scope

This guide documents the **Documents service API** under `/api/documents/` for API testing and implementation review. It covers:

- Customer document upload, list, detail, delete, and type endpoints
- Loan officer/admin verification and re-upload request endpoints
- Presigned direct-upload support for S3-like backends
- Upload validation, file scanning, and storage backend abstraction
- AI/CNN document analysis behavior, training, and validation tooling

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
| `docs/ANALYTICS_TESTING_GUIDE.md` | Audit log endpoints that record document actions |
| `docs/LOANS_TESTING_GUIDE.md` | Loan APIs that generate dependent document requirements |

## Role and Permission Matrix

| Endpoint | Allowed Role | Notes |
|----------|--------------|-------|
| `POST /upload/` | Customer | Owner-only upload |
| `POST /presigned-upload/` | Customer | Returns S3 presigned POST data when backend supports it |
| `GET /` | Customer, Loan Officer, Admin, Super Admin | Role-scoped results |
| `GET /<document_id>/` | Customer (owner), scoped Officer, Admin, Super Admin | Concealed from unauthorized users |
| `DELETE /<document_id>/` | Customer | Owner only; cannot delete verified docs |
| `PUT /<document_id>/verify/` | Loan Officer, Admin | Approve/reject with `action` or `status` |
| `GET /types/` | Customer, Loan Officer, Admin, Super Admin | Optional `product_id` for product-specific requirements |
| `POST /<document_id>/request-reupload/` | Loan Officer, Admin | Flags document for another upload |

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
- If `DOCUMENT_UPLOAD_AI_ANALYSIS` is enabled and the customer has `ai_consent`, image uploads receive AI analysis

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
| `reupload_requested` | bool | Whether re-upload was requested |
| `reupload_reason` | string or null | Reason for re-upload request |
| `reupload_requested_by` | string or null | Officer who requested re-upload |
| `file_url` | string or null | Accessible URL from storage backend |
| `created_at` | ISO datetime | Alias for `uploaded_at` |
| `uploaded_at` | ISO datetime | When the document was uploaded |

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
  "original_filename": "photo.jpg"
}
```

**Response fields (`data`):**
- Presigned `post` data including `url` and form `fields` when the active storage backend supports it
- Error when the backend does not support presigned uploads

**Notes:**
- Only S3-like backends currently implement `get_presigned_upload_for_new_object()`
- Local development storage returns 400 for this endpoint

---

### 3. `GET /` (list documents)

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
| `search` | string | | Case-insensitive match on filename or document type, plus customer name |

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
| `documents[].file_url` | string or null |
| `documents[].created_at` | ISO datetime |
| `documents[].uploaded_at` | ISO datetime |
| `total` | int |
| `page` | int |
| `page_size` | int |
| `total_pages` | int |

**Search behavior:**
- Matches `original_filename` and `document_type` case-insensitively
- Also matches customer first/last names by querying `Customer` records

---

### 4. `GET /<document_id>/` (detail)

Get a single document's metadata.

**Auth:** role-scoped  
**Path params:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `document_id` | string | yes | Valid MongoDB ObjectId |

**Response fields (`data`):** Same document object shape as list detail entries.

**Behavior:**
- Customers can only fetch their own documents
- Officers pass through `require_customer_scope_for_officer`
- Admins/super_admins can fetch any document

---

### 5. `DELETE /<document_id>/`

Delete a document record and its stored file.

**Auth:** customer (owner only)  
**Constraints:**
- Verified documents cannot be deleted; returns 400
- File is removed from the storage backend
- Document record is removed from MongoDB

**Response fields (`data`):**
- `message`: success message

---

### 6. `PUT /<document_id>/verify/`

Approve or reject a document.

**Auth:** loan_officer or admin  
**Request body (JSON):**
- `action` or `status`: `approve` or `reject` (either accepted)
- `rejection_reason`: required when rejecting; non-empty
- `notes`: optional officer notes

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `id` | string |
| `status` | string |
| `verified` | bool |

**Side effects:**
- On approve: sets `status=approved`, `verified=true`, `verified_by`, `verified_at`
- On reject: sets `status=rejected`, `rejection_reason`
- Sends notification email to customer
- Writes audit log entry with `action: document_verified` or `action: document_rejected`

---

### 7. `GET /types/`

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

### 8. `POST /<document_id>/request-reupload/`

Request that a customer re-upload a document.

**Auth:** loan_officer or admin  
**Request body (JSON):**
```json
{
  "reason": "Please upload a clearer image"
}
```

**Validation:**
- `reason` is required
- `reason` max length is 1000 characters

**Response fields (`data`):**

| Field | Type |
|-------|------|
| `document_id` | string |
| `status` | string | Set to `needs_review` |
| `reupload_requested` | bool | `true` |

**Side effects:**
- Sets `reupload_requested=true`, `reupload_reason`, `reupload_requested_by`, `reupload_requested_at`
- Sends email notification to customer
- Writes audit log entry

---

## Upload Validation & Security

Implemented in `documents/serializers/document_serializers.py`.

- **MIME allowlist:** `image/jpeg`, `image/jpg`, `image/png`, `application/pdf`
- **Max size:** 10 MB
- **File-signature validation:** content bytes must match declared MIME type
- **Executable rejection:** blocks PE, ELF, Mach-O, and Java class signatures
- **Image integrity:** PIL `Image.verify()` for JPEG/PNG
- **PDF active-content scan:** rejects PDFs containing `/javascript`, `/js`, `/openaction`, `/launch`, `/aa`, `/richmedia`, `/embeddedfile`

**AI analysis gating:**
- Skips analysis when `DOCUMENT_UPLOAD_AI_ANALYSIS` is false
- Skips analysis when the customer has not given `ai_consent`
- Only runs for image uploads (`image/*`); PDFs skip AI image analysis

---

## Storage Backends

Implemented in `documents/storage/backends.py`.

- **LocalStorageBackend:** stores files under `MEDIA_ROOT/documents/<customer_id>/<document_type>/<filename>`
- **S3-compatible backends:** supports multipart upload and presigned POST generation
- Common interface: `save()`, `delete()`, `get_url()`, `get_file_bytes()`

---

## AI Analysis & CNN Behavior

Implemented in `documents/services/analyzer.py` and `documents/services/cnn_model.py`.

**Analysis modes:**
- `cnn`: MobileNetV2 model loaded; returns classification and quality results
- `quality_check`: model unavailable; returns quality checks only

**Quality checks:**
- Minimum dimensions: 200x200
- Blur detection: Laplacian variance threshold
- Aspect ratio warning: >5:1
- Brightness checks: too dark (<40) or overexposed (>240)

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

**Type validation controls:**
- `DOCUMENT_TYPE_CONFIDENCE_THRESHOLD` (default `0.75`)
- `DOCUMENT_ENFORCE_TYPE_MATCH` (default `True`)
- `DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION` (default `True`)

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
| `model_available` | bool |
| `quality_score` | float 0–1 |
| `quality_issues` | array of strings |

---

## CNN Training & Testing Commands

**Training:**

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
5. Login as loan officer and verify one document via `PUT /<document_id>/verify/`.
6. Request re-upload on another document via `POST /<document_id>/request-reupload/`.
7. Login as customer and confirm verified docs cannot be deleted.
8. Test `POST /presigned-upload/` to confirm 400 when local storage is active.
9. If retraining is needed, run `train_document_classifier` and validate with `scripts/test_cnn_model.py`.

---

## Common Error Cases

| Code | When |
|------|------|
| `400 Bad Request` | Missing `file`, invalid `document_type`, invalid filters, invalid verify payload, missing/blank re-upload reason, oversized file, invalid/unsafe file content, attempt to delete verified document |
| `401 Unauthorized` | Missing or invalid JWT |
| `403 Forbidden` | Role mismatch, ownership/scope violation, missing AI consent where required |
| `404 Not Found` | Document not found in current scope |

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
| Storage backends | `documents/storage/backends.py` |
| AI analysis service | `documents/services/analyzer.py` |
| CNN model | `documents/services/cnn_model.py` |
| Training command | `documents/management/commands/train_document_classifier.py` |
| Test script | `scripts/test_cnn_model.py` |

---

## Notes for API Test Automation

1. Upload endpoints expect `multipart/form-data`; all others are JSON `GET` or `PUT`/`POST` with JSON bodies.
2. Customer-uploaded documents start as `pending` unless AI quality/type validation fails, which sets `needs_review`.
3. Officer verify endpoints accept both `action` and `status` fields; tests should exercise both spellings.
4. Rejection requires `rejection_reason`; blank/whitespace-only values are rejected by the serializer.
5. Document list pagination happens in Python after loading matching documents; expect `total` to reflect full matched set, not DB count.
6. `customer_name` in list/response is resolved dynamically by querying the `Customer` collection.
7. `file_url` depends on the active storage backend; in tests, ensure the storage backend is patched or mocked.
8. Presigned uploads return 400 when the storage backend does not implement `get_presigned_upload_for_new_object()`.
9. Reviewer notifications are triggered on upload for `pending` and `needs_review` documents; in tests, mock the email sender to avoid side effects.
10. Audit logs for documents use actions `document_uploaded`, `document_verified`, and `document_rejected`.
