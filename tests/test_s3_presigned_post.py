import base64
import json

import boto3

try:
    from moto import mock_s3
except Exception:
    from moto import mock_aws as mock_s3


from documents.storage.backends import S3StorageBackend


@mock_s3
def test_presigned_post_fields(settings):
    region = 'us-east-1'
    s3 = boto3.client('s3', region_name=region)
    bucket = 'test-bucket-post'
    s3.create_bucket(Bucket=bucket)

    settings.AWS_STORAGE_BUCKET_NAME = bucket
    settings.AWS_S3_REGION_NAME = region

    backend = S3StorageBackend()
    post = backend.generate_presigned_post('documents/cust1/id_card/test.jpg')
    assert post
    assert 'url' in post and 'fields' in post
    fields = post['fields']
    # Presigned POST fields should include at least key or policy
    assert ('key' in fields) or ('policy' in fields)


@mock_s3
def test_quarantine_presign_binds_session_type_hash_and_exact_size(settings):
    region = "us-east-1"
    s3 = boto3.client("s3", region_name=region)
    bucket = "test-bucket-quarantine"
    s3.create_bucket(Bucket=bucket)
    settings.AWS_STORAGE_BUCKET_NAME = bucket
    settings.AWS_S3_REGION_NAME = region

    backend = S3StorageBackend()
    upload = backend.create_quarantined_presigned_upload(
        session_id="session-123",
        original_filename="identity.jpg",
        expected_size=1234,
        expected_mime_type="image/jpeg",
        expected_sha256="a" * 64,
        expires_in=900,
    )

    assert upload["object_key"].startswith("document-uploads/quarantine/")
    fields = upload["post"]["fields"]
    assert fields["Content-Type"] == "image/jpeg"
    assert fields["x-amz-meta-upload-session"] == "session-123"
    assert fields["x-amz-meta-sha256"] == "a" * 64
    policy = json.loads(base64.b64decode(fields["policy"]))
    assert ["content-length-range", 1234, 1234] in policy["conditions"]
