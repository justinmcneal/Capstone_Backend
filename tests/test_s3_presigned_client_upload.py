import io
import requests

import boto3

try:
    from moto import mock_s3
except Exception:
    from moto import mock_aws as mock_s3

from django.conf import settings

from documents.storage.backends import S3StorageBackend


@mock_s3
def test_client_upload_via_presigned_post(settings):
    region = 'us-east-1'
    s3 = boto3.client('s3', region_name=region)
    bucket = 'test-bucket-post-client'
    s3.create_bucket(Bucket=bucket)

    settings.AWS_STORAGE_BUCKET_NAME = bucket
    settings.AWS_S3_REGION_NAME = region

    backend = S3StorageBackend()

    post = backend.generate_presigned_post('documents/cust1/id_card/client.jpg')
    assert post

    # Simulate browser POST using requests (moto intercepts this)
    files = {'file': ('client.jpg', b'clientdata')}
    data = post['fields']
    resp = requests.post(post['url'], data=data, files=files)
    assert resp.status_code in (200, 204)

    # Ensure object exists
    obj = s3.get_object(Bucket=bucket, Key=data.get('key') or 'documents/cust1/id_card/client.jpg')
    body = obj['Body'].read()
    assert body == b'clientdata'
