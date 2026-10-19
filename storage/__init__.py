"""Storage layer package providing PostgreSQL ORM models, MinIO client, and StorageManager."""

from storage.database import Base, SessionLocal, engine, get_db
from storage.minio_client import MinIOClient
from storage.models import (
    Applicant,
    Application,
    ApplicationRecord,
    AuditLog,
    DocumentRecord,
    OrphanDocument,
    OrphanTestScore,
)
from storage.storage_manager import StorageManager

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "Applicant",
    "Application",
    "ApplicationRecord",
    "OrphanDocument",
    "OrphanTestScore",
    "DocumentRecord",
    "AuditLog",
    "MinIOClient",
    "StorageManager",
]
