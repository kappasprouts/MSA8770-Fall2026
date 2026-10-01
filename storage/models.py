"""PostgreSQL database models for applications, document archival records, and audit logs.

Implements JSONB fields for application payloads and AI reviews, default status='READY_FOR_REVIEW',
and immutable audit logging for Trust Boundary 2.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from storage.database import Base

# Use JSONB if on PostgreSQL, JSON generic fallback for SQLite testing
JsonType = JSON().with_variant(JSONB, "postgresql")


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Application(Base):
    """Application record stored in PostgreSQL with status defaulted to READY_FOR_REVIEW."""

    __tablename__ = "applications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    applicant_id = Column(String(64), unique=True, nullable=False, index=True)
    application_type = Column(String(32), default="first_year", nullable=False)
    status = Column(String(32), default="READY_FOR_REVIEW", nullable=False, index=True)
    routing_destination = Column(String(64), default="READY_FOR_REVIEW", nullable=False)

    # Core structured JSON payloads (Architecture Section 4 component 6)
    application_data = Column(JsonType, default=dict, nullable=False)
    ai_review = Column(JsonType, default=dict, nullable=False)
    validation_findings = Column(JsonType, default=list, nullable=False)

    is_complete = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "READY_FOR_REVIEW")
        kwargs.setdefault("routing_destination", "READY_FOR_REVIEW")
        kwargs.setdefault("is_complete", True)
        kwargs.setdefault("application_data", {})
        kwargs.setdefault("ai_review", {})
        kwargs.setdefault("validation_findings", [])
        super().__init__(**kwargs)

    def to_dict(self):
        return {
            "id": self.id,
            "applicant_id": self.applicant_id,
            "application_type": self.application_type,
            "status": self.status,
            "routing_destination": self.routing_destination,
            "application_data": self.application_data,
            "ai_review": self.ai_review,
            "validation_findings": self.validation_findings,
            "is_complete": self.is_complete,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentRecord(Base):
    """Archival record of inbound documents stored in MinIO."""

    __tablename__ = "document_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    applicant_id = Column(String(64), nullable=False, index=True)
    document_type = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    minio_bucket = Column(String(64), nullable=False, default="applicant-documents")
    minio_object_key = Column(String(512), nullable=False, unique=True)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(64), default="application/pdf", nullable=False)
    sha256_checksum = Column(String(64), nullable=True)
    is_readable = Column(Boolean, default=True, nullable=False)
    parsed_content = Column(JsonType, default=dict, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class AuditLog(Base):
    """Immutable audit trail of pipeline actions protecting student PII (Trust Boundary 2)."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    applicant_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    actor = Column(String(64), nullable=False, default="system_pipeline")
    details = Column(JsonType, default=dict, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
