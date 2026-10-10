"""MinIO client configuration and helpers for raw document archival.

Provides S3-compatible object storage operations for immutable document storage,
bucket management, and presigned URL generation.
"""

import logging
import os
from pathlib import Path
from typing import Optional

try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_SDK_AVAILABLE = True
except ImportError:
    MINIO_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)


class MinIOClient:
    """Configures and wraps MinIO object storage interactions."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: Optional[bool] = None,
        default_bucket: Optional[str] = None,
    ):
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self.secure = (
            secure
            if secure is not None
            else os.getenv("MINIO_SECURE", "false").lower() == "true"
        )
        self.default_bucket = default_bucket or os.getenv("MINIO_BUCKET", "applicant-documents")

        if MINIO_SDK_AVAILABLE:
            try:
                self.client = Minio(
                    self.endpoint,
                    access_key=self.access_key,
                    secret_key=self.secret_key,
                    secure=self.secure,
                )
            except Exception as e:
                logger.warning(f"Could not connect to MinIO client: {e}. Running in mock mode.")
                self.client = None
        else:
            logger.info("MinIO Python SDK not installed. Running in mock/development mode.")
            self.client = None

    def ensure_bucket_exists(self, bucket_name: Optional[str] = None) -> bool:
        """Create bucket if it does not already exist."""
        bucket = bucket_name or self.default_bucket
        if not self.client:
            logger.debug(f"[Mock MinIO] Verified bucket exists: '{bucket}'")
            return True

        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: '{bucket}'")
            return True
        except Exception as e:
            logger.error(f"Error ensuring MinIO bucket '{bucket}': {e}")
            return False

    def upload_file(
        self,
        file_path: Path,
        object_key: str,
        bucket_name: Optional[str] = None,
        content_type: str = "application/pdf",
    ) -> str:
        """Upload a local file to MinIO object storage."""
        bucket = bucket_name or self.default_bucket
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Cannot upload non-existent file: {path}")

        if not self.client:
            logger.info(f"[Mock MinIO] Uploaded {path.name} to {bucket}/{object_key}")
            return f"s3://{bucket}/{object_key}"

        try:
            self.ensure_bucket_exists(bucket)
            self.client.fput_object(
                bucket_name=bucket,
                object_name=object_key,
                file_path=str(path),
                content_type=content_type,
            )
            logger.info(f"Successfully uploaded {path.name} to MinIO: {bucket}/{object_key}")
            return f"s3://{bucket}/{object_key}"
        except Exception as e:
            logger.error(f"Failed to upload {path} to MinIO: {e}")
            raise

    def get_presigned_url(
        self,
        object_key: str,
        bucket_name: Optional[str] = None,
        expires_seconds: int = 3600,
    ) -> str:
        """Generate a presigned GET URL for secure document access."""
        bucket = bucket_name or self.default_bucket
        if not self.client:
            return f"http://{self.endpoint}/{bucket}/{object_key}?mock_presigned=true"

        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                bucket,
                object_key,
                expires=timedelta(seconds=expires_seconds),
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {object_key}: {e}")
            return f"http://{self.endpoint}/{bucket}/{object_key}"
