"""Read-only validation for the configured private S3 document bucket."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from documents.storage import get_storage_backend


class Command(BaseCommand):
    help = "Validate production S3 security controls without changing the bucket"

    def handle(self, *args, **options):
        if settings.DOCUMENT_STORAGE_BACKEND != "s3":
            raise CommandError("DOCUMENT_STORAGE_BACKEND must be s3")
        backend = get_storage_backend()
        bucket = backend.bucket_name
        checks = {}

        public = backend.s3.get_public_access_block(Bucket=bucket)[
            "PublicAccessBlockConfiguration"
        ]
        checks["public_access_block"] = all(
            public.get(name) is True
            for name in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        )
        rules = backend.s3.get_bucket_encryption(Bucket=bucket)[
            "ServerSideEncryptionConfiguration"
        ]["Rules"]
        algorithms = {
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for rule in rules
        }
        checks["default_encryption"] = bool(algorithms & {"AES256", "aws:kms"})
        ownership = backend.s3.get_bucket_ownership_controls(Bucket=bucket)[
            "OwnershipControls"
        ]["Rules"]
        checks["bucket_owner_enforced"] = any(
            rule.get("ObjectOwnership") == "BucketOwnerEnforced" for rule in ownership
        )
        try:
            cors_rules = backend.s3.get_bucket_cors(Bucket=bucket).get("CORSRules", [])
        except backend.s3.exceptions.NoSuchCORSConfiguration:
            cors_rules = []
        checks["cors_no_wildcard_origins"] = bool(cors_rules) and all(
            all("*" not in origin for origin in rule.get("AllowedOrigins", []))
            for rule in cors_rules
        )
        checks["cors_upload_methods"] = any(
            {"POST", "PUT"} & set(rule.get("AllowedMethods", [])) for rule in cors_rules
        )
        checks["short_url_expiry"] = 60 <= backend.url_expiry <= 900
        checks["versioning_enabled"] = (
            backend.s3.get_bucket_versioning(Bucket=bucket).get("Status") == "Enabled"
        )
        try:
            lifecycle_rules = backend.s3.get_bucket_lifecycle_configuration(
                Bucket=bucket
            ).get("Rules", [])
        except backend.s3.exceptions.NoSuchLifecycleConfiguration:
            lifecycle_rules = []
        quarantine_prefix = "document-uploads/quarantine/"
        checks["quarantine_lifecycle"] = any(
            rule.get("Status") == "Enabled"
            and (
                rule.get("Prefix") == quarantine_prefix
                or rule.get("Filter", {}).get("Prefix") == quarantine_prefix
            )
            and 1
            <= int(rule.get("Expiration", {}).get("Days", 0) or 0)
            <= settings.DOCUMENT_QUARANTINE_RETENTION_DAYS
            for rule in lifecycle_rules
        )
        self.stdout.write(json.dumps(checks, sort_keys=True))
        if not all(checks.values()):
            raise CommandError("One or more document storage checks failed")
