# Documents and CNN Implementation and Testing Guide

## Scope
This guide covers:
- Document upload and verification APIs under `/api/documents/`
- Role-based access for customer, loan officer, admin, and super admin
- Document AI analysis behavior (quality checks and CNN classification)
- CNN training and validation workflow used by the backend

## Base URL and Auth
- Base URL: `http://localhost:8000/api/documents`
- Required headers:
```http
Authorization: Bearer <access_token>
```
- Upload endpoint uses `multipart/form-data`.
- All document endpoints require authenticated JWT.

## Canonical Document Types and Statuses
Document types (`documents/models/document.py`):
- `valid_id`
- `selfie_with_id`
- `proof_of_address`
- `business_permit`
- `business_photo`
- `income_proof`
- `other`

Document statuses:
- `pending`
- `needs_review`
- `approved`
- `rejected`
- `expired`

## Endpoint Access Matrix
| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/types/` | Customer, Loan Officer, Admin, Super Admin |
| `POST` | `/upload/` | Customer |
| `GET` | `/` | Customer, Loan Officer, Admin, Super Admin |
| `GET` | `/<document_id>/` | Customer (owner), scoped Loan Officer, Admin, Super Admin |
| `DELETE` | `/<document_id>/` | Customer (owner only) |
| `PUT` | `/<document_id>/verify/` | Loan Officer, Admin, Super Admin |
| `POST` | `/<document_id>/request-reupload/` | Loan Officer, Admin, Super Admin |

## Endpoint Contract
1. `GET /types/`
- Optional query param: `product_id`
- Returns `document_types` with `required` flags and `requirement_source`.
- Without `product_id`, baseline required docs are used.

2. `POST /upload/`
- Form fields:
  - `file` (required)
  - `document_type` (required)
  - `description` (optional)
- Accepted MIME types: `image/jpeg`, `image/jpg`, `image/png`, `application/pdf`
- Max file size: 10 MB
- Upload validation includes:
  - MIME allowlist
  - file signature check
  - executable signature rejection
  - image integrity verification
  - PDF active-content pattern scan
- Response includes uploaded metadata and optional `ai_analysis` payload.

3. `GET /`
- Query params:
  - `page` (default `1`, min `1`)
  - `page_size` (default `20`, clamped `1..200`)
  - `type` (document type filter)
  - `status` (document status filter)
  - `customer_id` (officer/admin scope filter)
  - `search` (filename/type search)
- Customers only see own documents.
- Loan officers are scoped to assigned/allowed customers.

4. `GET /<document_id>/`
- Returns document metadata, verification fields, `ai_analysis`, and `file_url`.
- Ownership and scope checks are enforced.

5. `DELETE /<document_id>/`
- Customer owner only.
- Verified documents cannot be deleted.

6. `PUT /<document_id>/verify/`
- Body accepts either `action` or `status` with values:
  - `approve` or `approved`
  - `reject` or `rejected`
- `rejection_reason` is required when rejecting.
- `notes` optional.

7. `POST /<document_id>/request-reupload/`
- Body:
```json
{
  "reason": "Please upload a clearer image"
}
```
- `reason` required, max 1000 chars.
- Marks document for re-upload workflow.

## AI Analysis and CNN Runtime Behavior
Document analysis is triggered on upload when enabled.

Feature flags:
- `DOCUMENT_UPLOAD_AI_ANALYSIS` (default `True`)
- `DOCUMENT_UPLOAD_NOTIFY_REVIEWERS` (default `True`)
- `DOCUMENT_UPLOAD_NOTIFY_ASYNC` (default `True`)

Analyzer behavior (`documents/services/analyzer.py`):
- Runs only for image uploads (`image/*`).
- PDFs are accepted but skip AI image analysis.
- Quality checks include size, blur, aspect ratio, brightness.
- If model is available, returns CNN classification fields:
  - `predicted_type`
  - `type_confidence`
  - `type_matches_expected`
  - `type_validation_passed`
  - `analysis_mode: "cnn"`
- If model is unavailable, falls back to `analysis_mode: "quality_check"`.

Type-validation environment controls:
- `DOCUMENT_TYPE_CONFIDENCE_THRESHOLD` (default `0.75`)
- `DOCUMENT_ENFORCE_TYPE_MATCH` (default `True`)
- `DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION` (default `True`)

Auto-flagging rule:
- Upload status becomes `needs_review` when analysis fails validation or quality score is below `0.5`.

## CNN Classes, Data, and Training
Model class order (`documents/services/cnn_model.py`):
- `business_permit`
- `business_photo`
- `income_proof`
- `invalid`
- `proof_of_address`
- `selfie_with_id`
- `valid_id`

Training data location:
- `documents/ml/training_data/<class_name>/`

Train command:
```bash
python manage.py train_document_classifier
```

Common options:
```bash
python manage.py train_document_classifier --epochs 20
python manage.py train_document_classifier --batch-size 16
python manage.py train_document_classifier --learning-rate 0.0005
python manage.py train_document_classifier --fine-tune
```

Training artifacts:
- `documents/ml/models/document_classifier.pth`
- `documents/ml/models/model_config.json`
- `documents/ml/reports/*` (if matplotlib installed)

## CNN Validation Commands
Single image:
```bash
python scripts/test_cnn_model.py /path/to/image.jpg
```

Batch folder:
```bash
python scripts/test_cnn_model.py /path/to/folder --batch
```

Confusion matrix (labeled test data in `documents/ml/test_data/`):
```bash
python scripts/test_cnn_model.py documents/ml/test_data --confusion
```

## Smoke Test Sequence
1. Login as customer and call `GET /types/`.
2. Upload one image (`valid_id`) and one PDF to confirm both acceptance and AI-skip behavior for PDF.
3. Call `GET /` and verify pagination/filter fields.
4. Call `GET /<document_id>/` for uploaded items.
5. Login as loan officer and verify one document via `PUT /<document_id>/verify/`.
6. Request re-upload on another document via `POST /<document_id>/request-reupload/`.
7. Login as customer and confirm verified docs cannot be deleted.
8. If retraining is needed, run `train_document_classifier` and validate with `scripts/test_cnn_model.py`.

## Common Error Cases
1. `400 Bad Request`
- Missing `file`, invalid `document_type`, invalid filters, invalid verify payload, missing/blank re-upload reason, oversized file, invalid/unsafe file content.

2. `401 Unauthorized`
- Missing or invalid JWT.

3. `403 Forbidden`
- Role mismatch, ownership/scope violation.

4. `404 Not Found`
- Document not found in current scope.

## References
- `documents/urls.py`
- `documents/views/document_views.py`
- `documents/serializers/document_serializers.py`
- `documents/services/analyzer.py`
- `documents/services/cnn_model.py`
- `documents/management/commands/train_document_classifier.py`
