**S3 Migration Rollback Runbook**

Purpose: provide quick rollback steps if migration causes critical issues (missing files, broken URLs, incorrect DB updates).

Immediate actions
- Pause incoming writes to affected areas (e.g., put the service into maintenance mode).
- Do not delete any local files during rollback — migration is designed to be non-destructive.

Rollback steps
1. If DB updates were applied (`--apply-db`), restore from DB backup taken before migration. If you do not have a backup, revert the `file_path` field using the migration log (we record original local paths in logs when running with `--apply-db` enabled).
2. Set `DOCUMENT_STORAGE_BACKEND=local` in staging or production to restore local serving while you recover.
3. Validate document retrieval in the app for a sample of customer records.
4. Re-run `migration_verifier.py` to ensure S3 missing reports are unchanged or to confirm that the rollback restored accessibility.

Notes
- Always take a DB snapshot (Mongo dump) before running `--apply-db`.
- Test the rollback procedure once in staging to ensure it performs as expected.
