# Migration Backup & Quick FAQ

Before running any migration, ensure you have a point-in-time backup of MongoDB and a snapshot of local media.

MongoDB (local) quick backup examples:

```
# Dump entire database to folder
mongodump --uri "mongodb://localhost:27017/yourdb" --out ./backups/mongo-$(date +%F)

# Dump single collection
mongodump --uri "mongodb://localhost:27017/yourdb" --collection documents --out ./backups/mongo-$(date +%F)
```

Local media snapshot (POSIX):

```
# Create tarball of media directory
tar -czf media-backup-$(date +%F).tar.gz media/

# Or copy to a backup mount
rsync -av --progress media/ /mnt/backups/media_snapshot/
```

FAQ — common migration issues
- Q: What if a local file is missing during migration?
  - A: The migration script will skip and record the missing file in `migration_status.json`. Inspect the `status_snapshot` in `migration_report.json` after a run.
- Q: How to resume a failed migration?
  - A: Re-run the same command; the script supports resume via `migration_status.json` and will skip already uploaded items.
- Q: How to verify migration correctness?
  - A: Use `scripts/migration_verifier.py` (or inspect `migration_report.json`) to compare local paths to S3 keys and check for failed records.
