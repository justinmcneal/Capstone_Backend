import boto3

try:
    from moto import mock_s3
except Exception:
    from moto import mock_aws as mock_s3

from django.conf import settings

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
