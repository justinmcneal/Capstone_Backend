import io
import boto3
import pytest

try:
    from moto import mock_s3
except Exception:
    from moto import mock_aws as mock_s3

from documents.storage.backends import S3StorageBackend


class FlakyFile(io.BytesIO):
    def __init__(self, content: bytes, name='flaky.bin'):
        super().__init__(content)
        self.name = name
        self.size = len(content)
    def chunks(self):
        yield self.getvalue()


@mock_s3
def test_multipart_and_retry(monkeypatch, settings):
    region = 'us-east-1'
    s3 = boto3.client('s3', region_name=region)
    bucket = 'test-multipart'
    s3.create_bucket(Bucket=bucket)

    settings.AWS_STORAGE_BUCKET_NAME = bucket
    settings.AWS_S3_REGION_NAME = region

    backend = S3StorageBackend()

    # Create large content slightly bigger than the default multipart threshold
    size = backend.multipart_threshold + 1024
    large_content = b'a' * size
    fake_file = FlakyFile(large_content, name='big.bin')

    # Monkeypatch the s3 client's upload_fileobj to fail once then succeed
    calls = {'count': 0}

    original_upload = backend.s3.upload_fileobj

    def flaky_uploadobj(fp, Bucket, Key, ExtraArgs=None):
        calls['count'] += 1
        if calls['count'] == 1:
            raise Exception('Simulated transient error')
        return original_upload(fp, Bucket, Key, ExtraArgs=ExtraArgs) if hasattr(backend.s3, 'upload_fileobj') else None

    monkeypatch.setattr(backend.s3, 'upload_fileobj', flaky_uploadobj)

    # Should succeed despite transient error due to boto retry config
    result = backend.save(fake_file, customer_id='custX', document_type='other', original_filename='big.bin')
    assert 'file_path' in result
    assert calls['count'] >= 1
