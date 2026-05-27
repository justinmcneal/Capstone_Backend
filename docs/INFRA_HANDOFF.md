# Infra Handoff Checklist

Provide the following to your infra/admin person to perform staging migration and cutover.

Required resources/secrets:
- S3 bucket name (example: `msme-documents-prod`)
- KMS key ARN for SSE (optional)
- IAM credentials with `s3:PutObject`, `s3:HeadObject`, `s3:DeleteObject`, `kms:Encrypt` (if using KMS)
- GitHub secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (if needed)

Suggested run order (staging):

1. Provision S3 bucket & KMS (or reuse existing infra templates under `infra/terraform/s3/`).
2. Ensure CI has GitHub secrets set and run the moto-based tests (no creds required) for sanity.
3. Backup MongoDB and local media (see `docs/MIGRATION_BACKUP_AND_FAQ.md`).
4. Create staging S3 bucket and configure CORS/policy.
5. Run dry-run migration:

```
python scripts/migrate_media_to_s3.py --dry-run --prefix documents
```

6. Inspect `migration_status.json` and `migration_report.json`.
7. Run actual migration with DB update (staging):

```
python scripts/migrate_media_to_s3.py --apply-db --confirm --prefix documents
```

8. Run `scripts/migration_verifier.py` and review outputs.
9. Flip staging env `DOCUMENT_STORAGE_BACKEND=s3` and run smoke tests.

If you want, provide these instructions as a PR description for infra to follow.
