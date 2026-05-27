AWS Resource & Migration Setup
=============================

This document describes the steps to provision AWS resources and run the migration.

1) Create AWS account and configure CLI with an admin user.

2) Use Terraform under `infra/terraform/s3` to create S3 + KMS (example):

```bash
cd infra/terraform/s3
terraform init
terraform apply -var='bucket_name=your-bucket-name' -auto-approve
```

3) Note outputs: bucket name and KMS key ARN.

4) Create an IAM role or user for your backend and attach the policy from `docs/PRODUCTION_S3.md`.

5) Add GitHub secrets (Settings → Secrets):
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_STORAGE_BUCKET_NAME`
   - `AWS_S3_REGION_NAME`
   - `KMS_KEY_ARN` (optional)

6) Run migration dry-run locally or via GitHub Actions:

```bash
# dry-run
make migrate-dry

# verify
make verify

# apply
make migrate-apply
```

7) After apply, run verifier and inspect `migration_report.json`.

8) Flip `DOCUMENT_STORAGE_BACKEND=s3` in staging and run smoke tests.
