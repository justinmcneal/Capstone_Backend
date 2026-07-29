**S3 Production Deployment**

- **Purpose**: Document IAM policy, CI steps, migration guidance, and rollout checklist for enabling `DOCUMENT_STORAGE_BACKEND=s3` in production.

IAM Policy (least-privilege example):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name",
        "arn:aws:s3:::your-bucket-name/*"
      ]
    }
  ]
}
```

Deployment/CI notes:

- Add the following environment variables to CI and production secrets (use your secret manager):
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_STORAGE_BUCKET_NAME`
  - `AWS_S3_REGION_NAME` (optional)
  - `AWS_S3_ENDPOINT_URL` (for S3-compatible providers)
  - `DOCUMENT_STORAGE_BACKEND=s3`

- CI should install `boto3` and `moto` only for tests. For production builds, ensure CPU/GPU-heavy ML deps are optional to avoid large images.

Migration checklist (summary):

- Run `python scripts/migrate_media_to_s3.py --dry-run` and review output.
- Run `python scripts/migrate_media_to_s3.py` with `--confirm` on a staging environment.
- Validate objects in S3 and test downloads via the app.
- Flip `DOCUMENT_STORAGE_BACKEND` in staging; run end-to-end tests.
- Plan production cutover window and snapshot local storage before final run.

Staged rollout checklist and example service snippets:

- Staging rollout steps:
  1. Provision S3 bucket and IAM policy as defined above.
  2. Run `python scripts/migrate_media_to_s3.py --dry-run --prefix documents` and inspect mapping.
  3. Run `python scripts/migrate_media_to_s3.py --confirm --prefix documents --apply-db` in staging.
  4. Set `DOCUMENT_STORAGE_BACKEND=s3` in staging and run smoke tests.
  5. Monitor logs for missing files and 403/404s; roll back if critical errors found.

- Example `systemd` unit (migration runner):

```ini
[Unit]
Description=One-time media migration to S3
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/srv/app
User=www-data
Group=www-data
ExecStart=/srv/app/venv/bin/python /srv/app/scripts/migrate_media_to_s3.py --confirm --prefix documents --apply-db

[Install]
WantedBy=multi-user.target
```

- Example `Procfile` entry (Heroku-like):

```
migrate_media: python scripts/migrate_media_to_s3.py --confirm --prefix documents --apply-db
```


Security considerations:

- Use short-lived credentials where possible (STS) or rotate keys regularly.
- Consider enabling server-side encryption (SSE-S3 or SSE-KMS) and document key management.
- Decide on public vs private object policy and CDN distribution for public assets.


SSE / KMS guidance
-------------------

- Recommend enabling server-side encryption with AWS KMS for sensitive documents.
- Example bucket default encryption using KMS (console or CLI):

```
aws s3api put-bucket-encryption --bucket your-bucket-name --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"arn:aws:kms:REGION:ACCOUNT:key/KEY_ID"}}]}'
```

- Use a dedicated KMS key for document storage and restrict key usage via IAM to the service principal only.
- Rotate keys according to your security policy; document the rotation plan and who owns it.


IAM Policy (finalized example)
------------------------------

Use a least-privilege role for backend services. Example policy (attach to role used by app servers):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:HeadObject"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name",
        "arn:aws:s3:::your-bucket-name/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"],
      "Resource": ["arn:aws:kms:REGION:ACCOUNT:key/KEY_ID"]
    }
  ]
}
```


CI / Secrets
------------

- Add the following secrets to GitHub (or your CI secret manager) and reference them in workflows:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_STORAGE_BUCKET_NAME`
  - `AWS_S3_REGION_NAME` (optional)
  - `AWS_S3_ENDPOINT_URL` (if using non-AWS provider)
  - `KMS_KEY_ARN` (if using KMS)

- Example GitHub Actions usage (already in `.github/workflows/ci.yml`):

```yaml
env:
  AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
  AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
  AWS_STORAGE_BUCKET_NAME: ${{ secrets.AWS_STORAGE_BUCKET_NAME }}
```


Monitoring and Alerts
---------------------

- Recommend CloudWatch metrics and alarms to detect upload/download errors, 4xx/5xx spikes, and GetObject error rates.
- Example CloudWatch alarm (JSON) to alert on elevated 4xx errors for GetObject via S3 Data Events or by parsing CloudTrail metrics:

```json
{
  "AlarmName": "S3High4xxErrorRate",
  "AlarmDescription": "Alert when S3 4xx errors spike",
  "ActionsEnabled": true,
  "MetricName": "4xxErrorRate",
  "Namespace": "Custom/S3",
  "Statistic": "Sum",
  "Period": 300,
  "EvaluationPeriods": 1,
  "Threshold": 10,
  "ComparisonOperator": "GreaterThanOrEqualToThreshold"
}
```

- Alternatively use S3 Server access logs or CloudTrail + Athena to build dashboards and alerts for missing-file (GetObject 404) or access-denied (403) trends.


CORS and presigned uploads
--------------------------

- Configure a restrictive CORS policy on the bucket to allow only your frontend origins and required methods for presigned POSTs (POST, GET, HEAD):

```xml
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>https://your-frontend.example.com</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>POST</AllowedMethod>
    <AllowedMethod>HEAD</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <MaxAgeSeconds>3000</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>
```

- Bucket policy example to allow uploads from your app role and prevent public reads:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::your-bucket-name/*",
      "Condition": {
        "Bool": {"aws:SecureTransport": "false"}
      }
    }
  ]
}
```


Frontend presigned POST example
--------------------------------

Save this example as `docs/examples/presigned_upload.html` and adapt your API route to return presigned POST data via `POST /api/documents/presigned-upload/`.

```html
<!doctype html>
<html>
<body>
  <input id="file" type="file" />
  <button id="upload">Upload</button>
  <script>
  async function getPresigned(file) {
    const res = await fetch('/api/documents/presigned-upload/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({document_type: 'other', original_filename: file.name})
    });
    return res.json();
  }

  document.getElementById('upload').onclick = async () => {
    const fileEl = document.getElementById('file');
    if (!fileEl.files.length) return alert('Choose a file');
    const file = fileEl.files[0];
    const presigned = await getPresigned(file);
    const formData = new FormData();
    Object.entries(presigned.data.fields).forEach(([k,v])=>formData.append(k,v));
    formData.append('file', file);
    const upload = await fetch(presigned.data.url, {method: 'POST', body: formData});
    if (upload.ok) alert('Uploaded'); else alert('Upload failed');
  };
  </script>
 </body>
</html>
```


Running the migration in staging
--------------------------------

- Dry-run first to verify mapping:

```bash
python scripts/migrate_media_to_s3.py --dry-run --prefix documents
```

- When verified, run in staging (ensure secrets and `AWS_STORAGE_BUCKET_NAME` are set):

```bash
python scripts/migrate_media_to_s3.py --confirm --prefix documents --apply-db
```

We provided a manual GitHub Actions workflow `run-staging-migration.yml` that can be triggered by a maintainer once secrets are configured. Review and restrict that workflow to protected branches.

