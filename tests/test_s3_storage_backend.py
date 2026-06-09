import io
import boto3
import pytest

try:
    from moto import mock_s3
except Exception:
    # Newer moto variants may expose a compatibility helper
    from moto import mock_aws as mock_s3

from django.conf import settings

from documents.storage.backends import S3StorageBackend


class FakeUploadedFile(io.BytesIO):
    def __init__(self, content: bytes, name: str = 'file.bin'):
        super().__init__(content)
        self.name = name
        self.size = len(content)

    def chunks(self):
        yield self.getvalue()


@mock_s3
def test_s3_storage_save_get_delete_and_presigned_urls(settings):
    # Create mocked S3
    region = 'us-east-1'
    s3 = boto3.client('s3', region_name=region)
    bucket = 'test-bucket'
    s3.create_bucket(Bucket=bucket)

    # Configure django settings for the backend
    settings.AWS_STORAGE_BUCKET_NAME = bucket
    settings.AWS_S3_REGION_NAME = region
    settings.AWS_ACCESS_KEY_ID = 'testing'
    settings.AWS_SECRET_ACCESS_KEY = 'testing'

    backend = S3StorageBackend()

    content = b'hello world'
    fake_file = FakeUploadedFile(content, name='hello.txt')

    # Save
    result = backend.save(fake_file, customer_id='cust123', document_type='id_card', original_filename='hello.txt')
    assert 'file_path' in result
    key = result['file_path']
    assert result['size'] == len(content)

    # Read bytes
    read = backend.get_file_bytes(key)
    assert read == content

    # Presigned GET URL
    url = backend.generate_presigned_get_url(key)
    assert url and isinstance(url, str)

    # Presigned POST
    post = backend.generate_presigned_post(key)
    assert post and 'url' in post and 'fields' in post

    # Delete
    ok = backend.delete(key)
    assert ok
