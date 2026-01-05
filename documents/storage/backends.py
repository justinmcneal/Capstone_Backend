"""
Storage Backend for Document Upload

Designed for easy migration from local filesystem to cloud storage (S3, GCS).
"""
import os
import uuid
from datetime import datetime
from django.conf import settings
import logging

logger = logging.getLogger('documents')


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


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage for development.
    
    Files stored in: MEDIA_ROOT/documents/<customer_id>/<document_type>/<filename>
    """
    
    def __init__(self):
        self.base_path = getattr(settings, 'MEDIA_ROOT', 'media')
        self.base_url = getattr(settings, 'MEDIA_URL', '/media/')
    
    def _generate_filename(self, original_filename):
        """Generate unique filename while preserving extension"""
        ext = os.path.splitext(original_filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().strftime('%Y%m%d')
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
        relative_dir = os.path.join('documents', str(customer_id), document_type)
        full_dir = os.path.join(self.base_path, relative_dir)
        self._ensure_directory(full_dir)
        
        # Generate unique filename
        new_filename = self._generate_filename(original_filename)
        relative_path = os.path.join(relative_dir, new_filename)
        full_path = os.path.join(self.base_path, relative_path)
        
        # Save file
        with open(full_path, 'wb+') as destination:
            for chunk in file.chunks():
                destination.write(chunk)
        
        file_size = os.path.getsize(full_path)
        
        logger.info(f"File saved: {relative_path} ({file_size} bytes)")
        
        return {
            'file_path': relative_path,
            'filename': new_filename,
            'size': file_size
        }
    
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


# Future cloud storage backends can be added here:
# class S3StorageBackend(StorageBackend):
#     """AWS S3 storage backend"""
#     pass
# 
# class GCSStorageBackend(StorageBackend):
#     """Google Cloud Storage backend"""
#     pass


def get_storage_backend():
    """
    Factory function to get the configured storage backend.
    
    Configure in settings.py:
        DOCUMENT_STORAGE_BACKEND = 'local'  # or 's3', 'gcs'
    """
    backend_type = getattr(settings, 'DOCUMENT_STORAGE_BACKEND', 'local')
    
    if backend_type == 'local':
        return LocalStorageBackend()
    # elif backend_type == 's3':
    #     return S3StorageBackend()
    # elif backend_type == 'gcs':
    #     return GCSStorageBackend()
    else:
        logger.warning(f"Unknown storage backend '{backend_type}', using local")
        return LocalStorageBackend()
