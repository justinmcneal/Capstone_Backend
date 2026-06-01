# Backfill `business_age_months` from `years_in_operation`

Purpose
-------
Some older records use the legacy `years_in_operation` field (years). The canonical field is `business_age_months` (months). This document describes the safe migration and backfill process.

Dry run
-------
Preview what would be changed without modifying the DB:

```bash
./venv/bin/python scripts/backfill_business_age_months.py --dry
```

This prints each document `_id` and the months value that would be written.

Full run
--------
After verifying the dry run and taking backups, run the real backfill:

```bash
# Ensure your environment is set (DJANGO_SETTINGS_MODULE, virtualenv activated)
./venv/bin/python scripts/backfill_business_age_months.py
```

Precautions
-----------
- Always take a database backup before running the full backfill.
- Run the script during a low-traffic maintenance window.
- Test the script in a staging environment first.
- Consider putting the code change behind a feature flag if your deployment supports it.

Rollback
--------
This backfill is additive (writes `business_age_months`). To roll back, restore from backup. If you only want to remove the written field for a small set of documents, use a manual `update_many` or targeted `update_one` undo.

Next steps
----------
- After backfill, monitor logs and alerts for anomalies.
- Deprecate `years_in_operation` in the API clients over a scheduled window (e.g., 2-4 weeks) and then remove alias support in a follow-up release.
