# Production S3 Document Storage Phase Implementation Plan

**Project:** MSME Loan Platform Backend  
**Scope:** Backend and document storage only  
**Date:** 2026-05-27  
**Status:** Draft for Implementation

---

## Objective

Replace local filesystem document storage with a production-ready S3-backed storage layer, while preserving the existing document upload, download URL generation, delete, and AI analysis flows.

This plan intentionally excludes web and mobile client work.

---

## Current State

The repo currently supports:

- Local filesystem storage via `LocalStorageBackend`
- Storage backend selection hardcoded to `local`
- Document upload, list, detail, and delete flows calling the storage factory
- AI document analysis that currently depends on a local full file path

The repo does not yet support:

- A real `S3StorageBackend` implementation
- Environment-driven backend selection
- S3 credentials and bucket configuration in `.env.example`
- Migration of existing local media files to S3
- Test coverage for S3 storage behavior

---

## Phase 1 — Backend Design and Configuration

### Goal

Make storage backend selection configurable and prepare the application for S3 credentials and runtime selection.

### Tasks

1. Add a real backend selector in `documents/storage/backends.py`.
2. Implement env-driven selection for `local`, `s3`, and future cloud backends.
3. Add S3 configuration variables to `.env.example`.
4. Add storage-related settings in `config/settings.py`.
5. Add the required AWS SDK dependency in `requirements.txt`.

### Deliverables

- `S3StorageBackend` class stub or implementation
- Backend factory that returns S3 when configured
- Production env variables for bucket, region, and credentials
- Dependency list updated for S3 support

### Acceptance Criteria

- `DOCUMENT_STORAGE_BACKEND=s3` selects the S3 backend
- Local storage remains the default for development
- Missing or invalid backend names safely fall back to local or fail clearly
- Environment values are documented and load correctly

### Status

- Completed on 2026-05-27: environment-driven backend selection implemented, `S3StorageBackend` implemented and selectable via `DOCUMENT_STORAGE_BACKEND`, `.env.example` and `requirements.txt` updated.

---

## Phase 2 — S3 Backend Implementation

### Goal

Implement upload, delete, and URL generation behavior for S3 without breaking existing document views.

### Tasks

1. Implement `save(file, customer_id, document_type, original_filename)` using S3 object upload.
2. Implement `delete(file_path)` using S3 object deletion.
3. Implement `get_url(file_path)` using either signed URLs or a public/CDN URL pattern.
4. Preserve the current document path structure so records remain stable.
5. Decide whether stored file keys are private and access controlled or public.

### Recommended S3 Key Structure

`documents/<customer_id>/<document_type>/<generated_filename>`

### Deliverables

- Working `S3StorageBackend`
- Stable object key format
- URL generation strategy documented
- Delete behavior aligned with stored object keys

### Acceptance Criteria

- Upload stores the file in S3 and returns a usable file path/key
- Delete removes the remote object
- List/detail views return valid URLs for stored files
- Local storage behavior remains unchanged when backend is set to `local`

### Status

- Completed on 2026-05-27: `S3StorageBackend` upload/delete/get_url implemented with presigned URL helpers, multipart and retry support added, presigned POST support added, and unit tests added and passing.

---

## Phase 3 — AI Analysis Compatibility

### Goal

Ensure the document AI analysis flow still works after moving file storage to S3.

### Problem

`document_views.py` currently passes a local filesystem path into the analyzer. That works only when the uploaded file exists on disk.

### Tasks

1. Add a storage-agnostic way to obtain file bytes for analysis.
2. Update the upload flow so AI analysis can read from S3 without requiring a local path.
3. Keep local-path support for development and backward compatibility if useful.
4. Prefer a bytes-based analyzer input or a temporary download path for S3 objects.

### Recommended Approach

Use a storage-layer helper such as `get_file_bytes(file_path)` or a temporary download method, then pass bytes into the analyzer.

### Deliverables

- S3-compatible AI analysis path
- No local-filesystem dependency in production uploads
- Clear fallback behavior for analysis failures
 
### Status

- Completed on 2026-05-27: implemented storage-agnostic `get_file_bytes` in `documents/storage/backends.py`, updated `DocumentUploadView` to call `storage.get_file_bytes(...)`, and modified the analyzer to accept both bytes and filesystem paths. Unit tests validating analyzer bytes input and S3 storage tests pass.

### Acceptance Criteria Validation

- Image uploads support AI quality/type analysis using bytes input: Verified by `tests/test_analyzer_bytes.py`.
- S3 uploads do not fail due to missing local path: Verified by S3-backed tests.
- Upload requests remain resilient when AI analysis fails: Analyzer failures are caught and upload continues; behavior exercised in tests.

### Acceptance Criteria

- Image uploads still support AI quality/type analysis
- S3 uploads do not fail because no local file path exists
- Upload request remains resilient even if AI analysis fails

---

## Phase 4 — Migration From Local Media

### Goal

Move existing uploaded documents from local `media/` storage to S3 safely.

### Tasks

1. Create a migration script or management command.
2. Read existing `Document.file_path` values from MongoDB.
3. Upload each file to S3 using the same key structure.
4. Update records only after successful upload confirmation.
5. Support resumable migration and idempotency.
6. Preserve rollback options until verification is complete.

### Migration Rules

- Do not delete local files until remote copies are confirmed
- Skip records whose local file is missing and report them separately
- Track migration status in logs or a dedicated collection

### Deliverables

- Migration command/script
- Dry-run mode
- Resume-safe migration behavior
- Post-migration verification report

### Acceptance Criteria

- Existing documents are copied to S3
- Document records still resolve to valid URLs after migration
- Failed records are reported clearly and can be retried

### Status

- Not started in AWS: migration tooling exists (`scripts/migrate_media_to_s3.py`, `scripts/migration_verifier.py`, rollback runbook, and manual GitHub Actions workflow), but no real S3 migration has been executed because AWS credentials/bucket provisioning are not available yet.

### What remains

- Back up MongoDB and local media before any migration.
- Provision AWS S3/KMS resources (or have infra do it).
- Add GitHub secrets or provide staging AWS credentials.
- Run a staging dry-run, inspect the verifier report, then apply.

---

## Phase 5 — Testing and Validation

### Goal

Verify that S3 storage works across upload, retrieval, deletion, and AI analysis.

### Tasks

1. Add unit tests for `S3StorageBackend`.
2. Add storage factory tests for backend selection.
3. Add document view tests for upload/list/detail/delete against S3.
4. Add tests for AI analysis compatibility with S3-backed files.
5. Add migration tests or command-level validation tests.

### Test Matrix

- Local backend upload/delete/get_url
- S3 backend upload/delete/get_url
- Invalid backend fallback
- Upload with AI analysis enabled
- Document URL rendering in list/detail endpoints
- Migration dry-run and success path

### Deliverables

- Backend test coverage for S3
- Document endpoint regression tests
- Migration validation tests

### Acceptance Criteria

- Tests pass for both local and S3 modes
- No regression in current document upload behavior
- No regression in AI analysis behavior

### Status

- Functionally complete for the S3 backend and analyzer path: unit tests for S3 storage, presigned uploads, multipart/retry behavior, and analyzer-bytes compatibility are passing locally. Remaining work is staging/production validation against a real AWS environment.

### What remains

- Run the migration-related tests and smoke tests in staging once AWS is available.
- Add/confirm any document endpoint integration tests in the full deployment environment if needed.

---

## Phase 6 — Production Rollout

### Goal

Enable S3 in production with minimal downtime and clear rollback.

### Tasks

1. Configure production env vars.
2. Run migration in staging first.
3. Validate uploads, downloads, deletes, and AI analysis.
4. Switch production backend to `s3`.
5. Monitor for missing objects, broken URLs, or permission issues.

### Rollout Checklist

- Bucket exists and IAM policy is correct
- Credentials are injected securely
- Backend selection is set to `s3`
- Existing documents are migrated
- Smoke tests pass after cutover
- Rollback path to local storage is documented

### Acceptance Criteria

- S3 is the active production document store
- New uploads persist across restarts and redeploys
- Document retrieval and deletion work as expected
- The migration is complete and verified

### Status

- Not started in production: rollout documentation and code paths are ready, but final production cutover depends on AWS account/bucket/credentials and a successful staging migration.

### What remains

- Confirm bucket, IAM policy, KMS settings, and CI secrets.
- Complete staging migration and verification.
- Flip staging to `DOCUMENT_STORAGE_BACKEND=s3` and smoke test.
- Schedule production cutover only after staging proves stable.

---

## Suggested Implementation Order

1. Add settings and dependency wiring.
2. Implement `S3StorageBackend`.
3. Update the AI analysis upload path.
4. Add tests for storage and document views.
5. Write the migration command.
6. Run staging validation.
7. Switch production to S3.

---

## Risks and Notes

- The current upload AI flow assumes local file paths, so this must be addressed before production S3 cutover.
- URL strategy matters: private buckets require signed URLs, while public buckets or CDN-backed access require different handling.
- Migration should be idempotent because document uploads may already exist in production data.
- Local storage should remain available as a dev/test fallback.

---

## Final Success Definition

This work is complete when:

- `DOCUMENT_STORAGE_BACKEND=s3` is supported in runtime code
- Document uploads, deletes, and URLs work with S3
- AI document analysis works without local filesystem dependency
- Existing local files are migrated safely
- Tests cover both local and S3 storage paths

## Current Handoff Summary

- Implemented locally in the repo: Phases 1, 2, and 3; S3 backend, AI analysis compatibility, migration scripts, verifier, rollback docs, tests, Terraform templates, and frontend example.
- Not yet executed in AWS: Phase 4 migration, staging flip, and production rollout.
- Blocker: no AWS admin privileges or access keys available for the `zuittbootcamper67` IAM user, so live AWS steps are intentionally paused until an admin or AWS owner enables them.
