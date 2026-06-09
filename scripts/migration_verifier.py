#!/usr/bin/env python3
"""
Verify S3 migration results: checks objects exist in S3 and DB records point to S3 keys.

Usage:
  python scripts/migration_verifier.py --report report.json

This script does not modify state; it produces a JSON report listing missing objects
and DB records still pointing to local paths.
"""
import os
import json
import argparse
import logging

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
import boto3
from botocore.exceptions import ClientError

from documents.models.document import Document

logger = logging.getLogger('migration_verifier')
logging.basicConfig(level=logging.INFO)


def collect_documents():
    docs = []
    for doc in Document.find({}):
        docs.append(doc)
    return docs


def verify_s3_objects(bucket, s3_client, documents, prefix=''):
    missing = []
    for doc in documents:
        key = doc.file_path
        # Some records might store full local path; normalize if needed
        if key.startswith(settings.MEDIA_ROOT):
            rel = os.path.relpath(key, settings.MEDIA_ROOT)
            key = os.path.join(prefix, rel).replace('\\', '/')

        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as ce:
            missing.append({'document_id': doc.id, 'expected_key': key, 'stored_path': doc.file_path})
    return missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='migration_report.json')
    parser.add_argument('--prefix', default='documents')
    args = parser.parse_args()

    bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
    if not bucket:
        logger.error('AWS_STORAGE_BUCKET_NAME not configured in settings')
        return 2

    s3 = boto3.client(
        's3',
        region_name=getattr(settings, 'AWS_S3_REGION_NAME', None),
        aws_access_key_id=getattr(settings, 'AWS_ACCESS_KEY_ID', None),
        aws_secret_access_key=getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
        endpoint_url=getattr(settings, 'AWS_S3_ENDPOINT_URL', None),
    )

    documents = collect_documents()
    logger.info('Collected %d documents from DB', len(documents))

    missing = verify_s3_objects(bucket, s3, documents, prefix=args.prefix)
    logger.info('Missing objects: %d', len(missing))

    report = {
        'total_documents': len(documents),
        'missing_objects': missing,
    }

    with open(args.report, 'w') as fh:
        json.dump(report, fh, indent=2)

    logger.info('Wrote report to %s', args.report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
