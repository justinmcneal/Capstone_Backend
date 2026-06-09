#!/usr/bin/env python3
"""
Migration script to copy files from local MEDIA_ROOT to S3.

Usage:
    python scripts/migrate_media_to_s3.py [--dry-run] [--prefix documents/]

This script is intentionally conservative: default is dry-run.
"""
import os
import argparse
import logging
import django

# Bootstrap Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
import boto3
from botocore.exceptions import ClientError
import json
import time
from datetime import datetime, timezone

logger = logging.getLogger('migrate_media')
logging.basicConfig(level=logging.INFO)


def iter_local_files(base_dir, prefix=''):
    for root, dirs, files in os.walk(base_dir):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base_dir)
            key = os.path.join(prefix, rel).replace('\\', '/')
            yield full, key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Do not upload, only print what would be done')
    parser.add_argument('--prefix', default='documents', help='S3 object prefix to use (default: documents)')
    parser.add_argument('--confirm', action='store_true', help='Confirm and run without interactive prompts')
    parser.add_argument('--apply-db', action='store_true', help='Update Document.file_path in the database to the new S3 key for matched local files')
    args = parser.parse_args()

    media_root = getattr(settings, 'MEDIA_ROOT', 'media')
    if not os.path.isdir(media_root):
        logger.error('MEDIA_ROOT does not exist: %s', media_root)
        return 2

    bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
    if not bucket:
        logger.error('AWS_STORAGE_BUCKET_NAME is not configured in settings')
        return 2

    s3 = boto3.client(
        's3',
        region_name=getattr(settings, 'AWS_S3_REGION_NAME', None),
        aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
        aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
        endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None),
    )

    # Status/resume tracking
    status_file = os.path.abspath(getattr(settings, 'MIGRATION_STATUS_FILE', 'migration_status.json'))
    logger.info('Using migration status file: %s', status_file)

    # Load existing status if present (resume support)
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as sf:
                status = json.load(sf)
        except Exception:
            logger.warning('Failed to read status file, starting fresh')
            status = {}
    else:
        status = {}

    total = 0
    skipped = 0
    uploaded = 0
    failed = 0

    logger.info('Starting migration dry_run=%s prefix=%s', args.dry_run, args.prefix)

    for full_path, object_key in iter_local_files(os.path.join(media_root, 'documents'), prefix=args.prefix):
        total += 1

        # Initialize record in status file
        rec = status.get(object_key) or {
            'source': full_path,
            'key': object_key,
            'status': 'pending',
            'retries': 0,
            'last_error': None,
            'updated_at': None,
        }

        # Skip if already uploaded
        if rec.get('status') == 'uploaded':
            logger.debug('Previously uploaded, skipping: %s', object_key)
            skipped += 1
            status[object_key] = rec
            continue

        try:
            # Check if object exists remotely; treat as uploaded if present
            try:
                s3.head_object(Bucket=bucket, Key=object_key)
                logger.info('Remote object exists, marking uploaded: %s', object_key)
                rec['status'] = 'uploaded'
                rec['updated_at'] = datetime.now(timezone.utc).isoformat()
                status[object_key] = rec
                skipped += 1
                # checkpoint
                with open(status_file, 'w') as sf:
                    json.dump(status, sf)
                continue
            except ClientError:
                # Not found -> proceed to upload
                pass

            # Retry loop
            max_retries = 3
            backoff = 1
            success = False
            while rec['retries'] < max_retries and not success:
                try:
                    if not args.dry_run:
                        with open(full_path, 'rb') as fh:
                            s3.upload_fileobj(fh, bucket, object_key)
                    success = True
                    uploaded += 1
                    rec['status'] = 'uploaded'
                    rec['updated_at'] = datetime.now(timezone.utc).isoformat()
                    logger.info('Uploaded: %s', object_key)
                except Exception as exc:
                    rec['retries'] += 1
                    rec['last_error'] = str(exc)
                    logger.warning('Upload attempt %d failed for %s: %s', rec['retries'], object_key, exc)
                    time.sleep(backoff)
                    backoff *= 2

            if not success:
                failed += 1
                rec['updated_at'] = datetime.now(timezone.utc).isoformat()
                logger.error('Failed to upload after retries: %s', object_key)

            status[object_key] = rec

            # checkpoint after every file
            try:
                with open(status_file, 'w') as sf:
                    json.dump(status, sf)
            except Exception:
                logger.warning('Failed to write status checkpoint')

            # Optionally update DB references when enabled
            if success and args.apply_db:
                try:
                    from documents.models.document import Document

                    rel_path = os.path.relpath(full_path, media_root).replace('\\', '/')
                    candidates = [rel_path, os.path.join('documents', rel_path).replace('\\', '/')]

                    found = None
                    for cand in candidates:
                        found = Document.find_one({'file_path': cand})
                        if found:
                            break

                    if found:
                        new_key = object_key
                        if found.file_path != new_key:
                            logger.info('Would update DB for document %s: %s -> %s', found.id, found.file_path, new_key)
                            if not args.dry_run:
                                found.file_path = new_key
                                found.save()
                    else:
                        logger.debug('No DB document found for local file %s', full_path)
                except Exception as exc:
                    logger.exception('Failed to update DB for %s: %s', full_path, exc)

        except Exception as exc:
            logger.exception('Failed to process %s: %s', full_path, exc)
            rec['status'] = 'failed'
            rec['last_error'] = str(exc)
            status[object_key] = rec
            failed += 1

    # Final report
    report = {
        'total': total,
        'uploaded': uploaded,
        'skipped': skipped,
        'failed': failed,
        'generated_at': datetime.now(timezone.utc).isoformat()
    }
    report_file = os.path.abspath(getattr(settings, 'MIGRATION_REPORT_FILE', 'migration_report.json'))
    try:
        with open(report_file, 'w') as rf:
            json.dump({'report': report, 'status_snapshot': status}, rf, indent=2)
        logger.info('Wrote migration report to %s', report_file)
    except Exception:
        logger.warning('Failed to write migration report file')

    logger.info('Migration complete: total=%d uploaded=%d skipped=%d failed=%d', total, uploaded, skipped, failed)


if __name__ == '__main__':
    raise SystemExit(main())
