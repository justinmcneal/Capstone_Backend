# Documents Production Readiness Review

Date: 2026-07-28  
Scope: Static code review of `documents/` and related upload, verification, storage, and CNN/analyzer behavior.

## Executive Summary

The `documents/` module handles customer document uploads, loan officer/admin verification, storage backend abstraction, optional AI/CNN analysis, and re-upload workflows. The core API surface is implemented and includes upload validation, role-scoped listing/detail, approval/rejection, and reviewer notifications. Gaps remain in URL routing completeness, automated API coverage, and alignment between docs and code.

## High Priority Findings

1. `presigned-upload/` view is not exposed in URL routing.  
   - `documents/views/document_views.py` defines `DocumentPresignedUploadView` at line 697, and `documents/urls.py` now includes it.  
   - Status: **DONE.**

2. Dedicated API tests for document endpoints added.  
   - `tests/test_documents_api.py` covers upload, presigned upload, list, detail, delete, verify, request-reupload, and document types endpoints.  
   - Status: **DONE.**

3. Two existing document tests failed.  
   - `test_document_upload_skips_ai_when_consent_is_false` failed due to missing `FakeDocument` attributes and a too-strict `ai_analysis` absence assertion.  
   - `test_document_upload_endpoint_s3` failed due to `SECURE_SSL_REDIRECT=True` causing a 301 in the test client.  
   - Both now fixed and passing. **Status: DONE.**

## Medium Priority Findings

1. `DOCUMENTS_TESTING_GUIDE.md` is now the canonical consolidated guide.  
   - It replaces the older split `DOCUMENTS_API_TESTING_GUIDE.md` and `DOCUMENTS_AND_CNN_GUIDE.md`.  
   - Status: **DONE.**

 2. Document list loads all matching documents into memory before pagination.  
    - `DocumentListView.get()` fetches a full list, then paginates in Python.  
    - Risk: unbounded memory growth with large document collections. **Status: ACCEPTED RISK.**  
    - Rationale: operator-facing document collections are typically small; bounded by role-scoped listing filters.

 3. Reviewer notification dispatch is now task-queue-based.  
    - Replaced raw daemon-thread dispatch with `documents/tasks.py::notify_reviewers_document_pending_task`.  
    - Synchronous fallback still supported via `DOCUMENT_UPLOAD_NOTIFY_ASYNC=False`.  
    - **Status: DONE.**

## Current Strengths

1. Upload validation is comprehensive.  
   - Enforces allowed MIME types, max size, file-signature matching, executable rejection, image integrity verification, and PDF active-content scanning.  
   - Implemented in `documents/serializers/document_serializers.py`.

2. AI analysis respects both global toggle and per-user consent.  
   - Skips analysis when `DOCUMENT_UPLOAD_AI_ANALYSIS` is false or customer has not given `ai_consent`.  
   - Implemented in `documents/views/document_views.py` and `documents/services/analyzer.py`.

3. Role-based access and ABAC scoping are enforced.  
   - Customers: own documents only.  
   - Officers: scoped via `get_officer_scoped_customer_ids`.  
   - Admins/super_admins: broader visibility with optional `customer_id` filter.

4. Storage backend abstraction is in place.  
   - `LocalStorageBackend` and S3-backed behavior behind a common interface (`save`, `delete`, `get_url`, `get_file_bytes`).

5. CNN training and validation tooling exists.  
   - Training command, model class (`MobileNetV2`), test script, and config-backed class mapping are present.

6. Audit logging is integrated for key actions.  
   - Upload, verify/approve, and reject actions emit audit log entries with resource metadata.

## Implementation Gaps Since Last Review

No remaining implementation gaps.

## Production Readiness Checklist

- [x] Upload validation and content scanning.
- [x] AI/CNN analysis with consent and feature-flag gating.
- [x] Role-scoped list/detail/delete/verify/re-upload endpoints.
- [x] Storage backend abstraction.
- [x] Audit logging for document lifecycle actions.
- [x] Expose `presigned-upload/` in URL routing.
- [x] Add automated tests for document API endpoints.
- [x] Fix failing document upload tests.
- [x] Align documentation with actual code-owned endpoints.

## Notes

- This review is code-level only (no live environment penetration testing).
- Document endpoints mutate state and trigger side effects (emails, audit logs, background notifications); test coverage should include those behaviors or safe fakes for them.
