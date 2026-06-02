# Documents API Testing Guide

## Scope
Documents handles customer file uploads, verification by loan officers, and storage management. This guide lists the endpoints, request/response shapes, validation rules, and a smoke-test sequence.

## Base URL and Auth
- Base URL: `http://localhost:8000/api/documents`
- Required headers (where applicable):
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```
- Uploads use `multipart/form-data` with `file` in `request.FILES`.

## Endpoints

1. `POST /upload/`
- Auth: authenticated customer only
- Content-Type: `multipart/form-data`
- Request fields (multipart):
  - `file` (required): file upload (JPEG, PNG, PDF)
  - `document_type` (required): one of available `DOCUMENT_TYPES` (e.g. `valid_id`, `selfie_with_id`, `proof_of_address`, `business_permit`, `business_photo`, `income_proof`, `other`)
  - `description` (optional): string up to 500 chars
- Validation rules:
  - Allowed MIME types: `image/jpeg`, `image/png`, `application/pdf`
  - Max file size: 10 MB
  - File content is scanned for signature match, executable signatures, image integrity, and dangerous PDF patterns
- Key response fields (201):
  - `id`, `document_type`, `original_filename`, `file_size`, `file_size_display`, `status`, `uploaded_at`
  - Optional: `ai_analysis` object if image analysis ran (quality_score, is_valid, predicted_type, etc.)


2. `POST /presigned-upload/`
- Auth: authenticated customer only
- Request body (JSON):
```json
{
  "document_type": "valid_id",
  "original_filename": "photo.jpg"
}
```
- Response (if storage backend supports presigned POST): presigned `post` data (fields and URL) for direct client upload.
- Instead of sending your file to your backend server first, your backend gives you a temporary permission slip that lets you upload the file directly to cloud storage (like AWS S3).

3. `GET /` (list documents)
- Auth: customer (their own), loan_officer, admin, super_admin (role-dependent scope)
- Query params:
  - `page` (int), `page_size` (int, max 200)
  - `type` (document_type filter)
  - `status` (one of DOCUMENT_STATUSES: `pending`, `needs_review`, `approved`, `rejected`, `expired`)
  - `customer_id` (for officers/admins)
  - `search` (search filename or document_type)
- Key response fields:
  - `documents`: list of documents with fields: `id`, `customer_id`, `document_type`, `filename`, `file_size`, `file_size_display`, `mime_type`, `status`, `verified`, `verified_by`, `verified_at`, `verification_notes`, `ai_analysis`, `reupload_requested`, `reupload_reason`, `file_url`, `uploaded_at`
  - Pagination metadata: `total`, `page`, `page_size`, `total_pages`

4. `GET /<document_id>/` (detail)
- Auth: role-scoped (customers only their own; officers/admins per scope)
- Response fields: `id`, `customer_id`, `document_type`, `original_filename`, `file_size`, `file_size_display`, `mime_type`, `status`, `verified`, `verified_by`, `verified_at`, `rejection_reason`, `description`, `ai_analysis`, `file_url`, `uploaded_at`

5. `DELETE /<document_id>/`
- Auth: authenticated customer (owner only)
- Constraints:
  - Cannot delete verified documents (400)
  - Deletes file from storage and removes DB record
- Response: success message

6. `PUT /<document_id>/verify/` (loan officer/admin)
- Auth: loan_officer or admin
- Request body (JSON):
  - `action` or `status`: `approve` or `reject` (either field accepted)
  - `rejection_reason`: required when rejecting (non-empty)
  - `notes`: optional
- Response fields: `id`, `status`, `verified`
- Side effects: sets `verified`, `verified_by`, `verified_at`, sends notification email to customer, writes audit log

7. `GET /types/`
- Auth: customer/loan_officer/admin
- Query params: `product_id` optional to get product-specific required document set
- Response: `document_types` array with `{value, label, required}`, and `requirement_source` (`baseline` or `product`)

8. `POST /<document_id>/request-reupload/` (loan officer/admin)
- Auth: loan_officer or admin
- Request body (JSON):
  - `reason` (required string, max 1000 chars)
- Response: `document_id`, `status`, `reupload_requested`
- Side effects: marks document `needs_review`, records `reupload_reason`, notifies customer by email

9. `GET /api/accounts/consent/audit/`
- Auth: admin only
- Response:
  - `summary`: totals for customers, `ai_consent_true`, `ai_consent_false`, and `missing_consent_records`
  - `customers`: list of customers with `customer_id`, `full_name`, `email`, `verified`, `has_consent_record`, `data_consent`, `ai_consent`, `consent_date`, and `updated_at`

## Validation & Security Notes
- Upload scanner checks file signatures and rejects executable or mismatched content.
- PDF uploads are scanned for active content patterns (javascript/openaction/launch, etc.).
- Image uploads are verified with PIL for corruption.
- Storage backends may differ: presigned uploads are only available for S3-like backends.
- AI analysis runs only when BOTH:
  - the global setting `DOCUMENT_UPLOAD_AI_ANALYSIS` is enabled (config), and
  - the uploading customer has explicitly given `ai_consent` (see `/api/accounts/consent/`).
  If either is false, AI analysis is skipped and no `ai_analysis` will be stored on the document.

## Smoke Test Sequence
1. Authenticate as a customer and set `Authorization` header.
2. `POST /presigned-upload/` to get upload data (if using direct browser upload) or `POST /upload/` with `multipart/form-data` to upload a small valid ID image.
3. `GET /` and verify the uploaded document appears with `status: pending`.
4. As a loan officer, call `GET /` (with officer scope) and `PUT /<id>/verify/` to approve the document.
5. As the customer, `GET /<id>/` and confirm `verified: true` and `verified_at` set.
6. Test rejection flow: loan officer `PUT /<id>/verify/` with `action: reject` and `rejection_reason` and ensure customer receives notification and `status: rejected`.
7. Test `POST /<id>/request-reupload/` with a reason — confirm `reupload_requested: true` and email sent.

## Common Errors
- `400 Bad Request`: missing file, invalid `document_type`, invalid `rejection_reason`, invalid query params
- `401 Unauthorized`: missing/invalid token
- `403 Forbidden`: role not permitted for the action
- `404 Not Found`: document not found (or concealed by owner checks)

## Where to look in code
- Views: `documents/views/document_views.py`
- Serializers/validation: `documents/serializers/document_serializers.py`
- Model/storage: `documents/models/document.py`, `documents/storage/backends.py`
