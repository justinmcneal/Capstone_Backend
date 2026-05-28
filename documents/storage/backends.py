"""
Storage Backend for Document Upload

Designed for easy migration from local filesystem to cloud storage (S3, GCS).
"""

import os
import uuid
from datetime import datetime
from django.conf import settings
import logging
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from boto3.s3.transfer import TransferConfig, S3Transfer
from botocore.config import Config

logger = logging.getLogger("documents")


class StorageBackend:
    """
    Abstract base for storage backends.
    Implement this interface for different storage providers.
    """

    def save(self, file, customer_id, document_type, original_filename):
        """Save file and return the storage path/URL"""
        raise NotImplementedError

    def delete(self, file_path):
        """Delete file from storage"""
        raise NotImplementedError

    def get_url(self, file_path):
        """Get accessible URL for the file"""
        raise NotImplementedError

    def get_file_bytes(self, file_path):
        """Read file contents as bytes for downstream processing."""
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage for development.

    Files stored in: MEDIA_ROOT/documents/<customer_id>/<document_type>/<filename>
    """

    def __init__(self):
        self.base_path = getattr(settings, "MEDIA_ROOT", "media")
        self.base_url = getattr(settings, "MEDIA_URL", "/media/")

    def _generate_filename(self, original_filename):
        """Generate unique filename while preserving extension"""
        ext = os.path.splitext(original_filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        return f"{timestamp}_{unique_id}{ext}"

    def _ensure_directory(self, path):
        """Create directory if it doesn't exist"""
        os.makedirs(path, exist_ok=True)

    def save(self, file, customer_id, document_type, original_filename):
        """
        Save file to local filesystem.

        Args:
            file: Django UploadedFile object
            customer_id: Customer's ID
            document_type: Type of document
            original_filename: Original filename

        Returns:
            dict with file_path, filename, and size
        """
        # Create directory structure
        relative_dir = os.path.join("documents", str(customer_id), document_type)
        full_dir = os.path.join(self.base_path, relative_dir)
        self._ensure_directory(full_dir)

        # Generate unique filename
        new_filename = self._generate_filename(original_filename)
        relative_path = os.path.join(relative_dir, new_filename)
        full_path = os.path.join(self.base_path, relative_path)

        # Save file
        with open(full_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        file_size = os.path.getsize(full_path)

        logger.info(f"File saved: {relative_path} ({file_size} bytes)")

        return {"file_path": relative_path, "filename": new_filename, "size": file_size}

    def delete(self, file_path):
        """Delete file from local filesystem"""
        full_path = os.path.join(self.base_path, file_path)

        if os.path.exists(full_path):
            os.remove(full_path)
            logger.info(f"File deleted: {file_path}")
            return True

        logger.warning(f"File not found for deletion: {file_path}")
        return False

    def get_url(self, file_path):
        """Get URL for the file"""
        return f"{self.base_url}{file_path}"

    def get_full_path(self, file_path):
        """Get full filesystem path for internal use (e.g., CNN analysis)"""
        return os.path.join(self.base_path, file_path)

    def get_file_bytes(self, file_path):
        """Read file bytes from local filesystem."""
        full_path = self.get_full_path(file_path)
        with open(full_path, "rb") as source:
            return source.read()


class S3StorageBackend(StorageBackend):
    """AWS S3 storage backend."""

    def __init__(self):
        self.bucket_name = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        self.region_name = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
        self.endpoint_url = getattr(settings, "AWS_S3_ENDPOINT_URL", None)
        self.custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", None)
        self.default_acl = getattr(settings, "AWS_DEFAULT_ACL", "private")
        self.file_overwrite = getattr(settings, "AWS_S3_FILE_OVERWRITE", False)
        self.signature_version = getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4")
        self.object_parameters = getattr(settings, "AWS_S3_OBJECT_PARAMETERS", {}) or {}
        self.url_expiry = getattr(settings, "AWS_S3_PRESIGNED_URL_EXPIRY_SECONDS", 3600)
        # Configure client with conservative retry policy
        botocore_config = Config(retries={"max_attempts": 3, "mode": "standard"})
        self.s3 = boto3.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", "") or None,
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", "")
            or None,
            config=botocore_config,
        )
        # Multipart upload settings
        self.multipart_threshold = getattr(
            settings, "AWS_S3_MULTIPART_THRESHOLD_BYTES", 5 * 1024 * 1024
        )
        self.multipart_chunksize = getattr(
            settings, "AWS_S3_MULTIPART_CHUNKSIZE_BYTES", 5 * 1024 * 1024
        )

    def _generate_filename(self, original_filename):
        ext = os.path.splitext(original_filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        return f"{timestamp}_{unique_id}{ext}"

    def _build_object_key(self, customer_id, document_type, original_filename):
        filename = self._generate_filename(original_filename)
        return os.path.join("documents", str(customer_id), document_type, filename)

    def save(self, file, customer_id, document_type, original_filename):
        """Upload file to S3 and return the object key and size."""
        if not self.bucket_name:
            raise ValueError("AWS_STORAGE_BUCKET_NAME is required for S3 storage")

        object_key = self._build_object_key(
            customer_id, document_type, original_filename
        )

        extra_args = dict(self.object_parameters)
        if self.default_acl:
            extra_args["ACL"] = self.default_acl

        try:
            # Choose transfer method with multipart config for large uploads
            transfer_config = TransferConfig(
                multipart_threshold=self.multipart_threshold,
                multipart_chunksize=self.multipart_chunksize,
            )
            transfer = S3Transfer(self.s3, config=transfer_config)

            max_attempts = getattr(settings, "AWS_S3_UPLOAD_MAX_ATTEMPTS", 3)
            base_backoff = getattr(settings, "AWS_S3_UPLOAD_BASE_BACKOFF", 0.5)

            attempt = 0
            while True:
                attempt += 1
                try:
                    # Prefer uploading from a local filename when available (S3Transfer.upload_file)
                    if hasattr(file, "temporary_file_path"):
                        local_path = file.temporary_file_path()
                        if extra_args:
                            transfer.upload_file(
                                local_path,
                                self.bucket_name,
                                object_key,
                                extra_args=extra_args,
                            )
                        else:
                            transfer.upload_file(
                                local_path, self.bucket_name, object_key
                            )
                    else:
                        # Fall back to client.upload_fileobj which is widely available
                        if extra_args:
                            self.s3.upload_fileobj(
                                file, self.bucket_name, object_key, ExtraArgs=extra_args
                            )
                        else:
                            self.s3.upload_fileobj(file, self.bucket_name, object_key)
                    break
                except Exception as exc:
                    if attempt >= max_attempts:
                        raise
                    sleep_time = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Upload attempt %d failed for %s, retrying in %.2fs: %s",
                        attempt,
                        object_key,
                        sleep_time,
                        exc,
                    )
                    time.sleep(sleep_time)
            file_size = getattr(file, "size", None)
            if file_size is None:
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

            logger.info("File saved to S3: %s (%s bytes)", object_key, file_size)
            return {
                "file_path": object_key,
                "filename": os.path.basename(object_key),
                "size": file_size,
            }
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to upload file to S3: %s", exc)
            raise

    def delete(self, file_path):
        """Delete file from S3."""
        if not self.bucket_name:
            raise ValueError("AWS_STORAGE_BUCKET_NAME is required for S3 storage")

        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=file_path)
            logger.info("File deleted from S3: %s", file_path)
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to delete file from S3: %s", exc)
            return False

    def get_url(self, file_path):
        """Get accessible URL for the file stored in S3."""
        if self.custom_domain:
            return f"https://{self.custom_domain}/{file_path}"

        if not self.bucket_name:
            return file_path

        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": file_path},
                ExpiresIn=self.url_expiry,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Failed to generate presigned URL for %s: %s", file_path, exc
            )
            return f"s3://{self.bucket_name}/{file_path}"

    def generate_presigned_get_url(self, file_path, expires_in=None):
        """Generate a presigned GET URL for the given object key."""
        if not expires_in:
            expires_in = self.url_expiry
        try:
            return self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": file_path},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Failed to generate presigned GET URL for %s: %s", file_path, exc
            )
            return None

    def generate_presigned_post(
        self, file_path, expires_in=None, fields=None, conditions=None
    ):
        """Generate a presigned POST for browser direct uploads.

        Returns a dict with `url` and `fields` suitable for form POST uploads.
        """
        if not expires_in:
            expires_in = self.url_expiry
        try:
            post = self.s3.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=file_path,
                Fields=fields or {},
                Conditions=conditions or [],
                ExpiresIn=expires_in,
            )
            return post
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Failed to generate presigned POST for %s: %s", file_path, exc
            )
            return None

    def get_presigned_upload_for_new_object(
        self, customer_id, document_type, original_filename, expires_in=None
    ):
        """Convenience helper to create an object key and return presigned POST data for direct client upload."""
        object_key = self._build_object_key(
            customer_id, document_type, original_filename
        )
        return self.generate_presigned_post(object_key, expires_in=expires_in)

    def get_file_bytes(self, file_path):
        """Read file bytes from S3."""
        if not self.bucket_name:
            raise ValueError("AWS_STORAGE_BUCKET_NAME is required for S3 storage")

        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=file_path)
            body = response.get("Body")
            return body.read() if body else b""
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to read file bytes from S3: %s", exc)
            raise


def get_storage_backend():
    """
    Factory function to get the configured storage backend.

    Configure in settings.py:
        DOCUMENT_STORAGE_BACKEND = 'local'  # or 's3'
    """
    backend_type = getattr(settings, "DOCUMENT_STORAGE_BACKEND", "local")
    if isinstance(backend_type, str):
        backend_type = backend_type.strip().lower()

    if backend_type == "local":
        return LocalStorageBackend()
    if backend_type == "s3":
        return S3StorageBackend()
    else:
        logger.warning(f"Unknown storage backend '{backend_type}', using local")
        return LocalStorageBackend()
