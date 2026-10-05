"""PostgreSQL database models for admissions applications, documents, and audit logs.

Implements explicit, typed relational columns matching the 33-column flat file schema,
with JSONB strictly reserved for variable-length array fields (activities, awards,
ap_test_scores, hooks, documents), status management, and orphan document handling.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from storage.database import Base

# Use JSONB if on PostgreSQL, JSON generic fallback for SQLite testing
JsonType = JSON().with_variant(JSONB, "postgresql")


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Applicant(Base):
    """PostgreSQL relational entity representing an undergraduate applicant record.

    Explicitly models the 33-column flat file schema using typed relational columns,
    limiting JSONB strictly to variable-length array payloads.
    """

    __tablename__ = "applicants"

    # Primary Identifier
    app_id = Column(String(64), primary_key=True, index=True)

    # Core Demographic & Contact Information (relational columns)
    first_name = Column(String(128), nullable=False)
    last_name = Column(String(128), nullable=False)
    date_of_birth = Column(String(32), nullable=True)
    mailing_address = Column(String(256), nullable=True)
    phone_number = Column(String(64), nullable=True)
    email_address = Column(String(128), nullable=True, index=True)
    gender = Column(String(32), nullable=True)
    ethnicity = Column(String(64), nullable=True)

    # School & Geographic Context
    name_of_hs = Column(String(256), nullable=True)
    counselor_name = Column(String(128), nullable=True)
    country = Column(String(64), nullable=True)
    region = Column(String(64), nullable=True)
    intended_major = Column(String(128), nullable=True)

    # Academic & Testing Metrics (typed numeric/string columns)
    admission_year = Column(Integer, nullable=True)
    admission_term = Column(String(32), nullable=True)
    gpa = Column(Float, nullable=True)
    unweighted_gpa = Column(Float, nullable=True)
    weighted_gpa = Column(Float, nullable=True)
    class_rank = Column(String(64), nullable=True)
    rank = Column(String(64), nullable=True)

    superscored_sat_score = Column(Float, nullable=True)
    sat_math = Column(Float, nullable=True)
    sat_ebrw = Column(Float, nullable=True)
    superscored_act_score = Column(Float, nullable=True)
    act_composite = Column(Float, nullable=True)

    total_aps = Column(Float, nullable=True)
    total_ibs = Column(Float, nullable=True)
    ib_courses = Column(Text, nullable=True)

    # Inbound Submission & Review Metadata
    create_date_time = Column(String(64), nullable=True)
    last_updated_csv = Column(String(64), nullable=True)
    review_ctr = Column(Integer, default=0, nullable=True)
    application_status_raw = Column(String(64), nullable=True)
    final_decision = Column(String(64), nullable=True)

    # Variable-Length Array Fields (JSONB ONLY)
    activities = Column(JsonType, default=list, nullable=False)        # List of up to 10 activities
    awards = Column(JsonType, default=list, nullable=False)            # List of up to 5 awards
    ap_test_scores = Column(JsonType, default=list, nullable=False)    # List of up to 12 AP scores/courses
    hooks = Column(JsonType, default=list, nullable=False)             # List of up to 5 hooks
    documents = Column(JsonType, default=list, nullable=False)         # List of attached document metadata

    # Deterministic Gate Workflow Status
    # Statuses: PENDING, READY_FOR_REVIEW, INCOMPLETE, ERROR, HUMAN_REVIEW
    status = Column(String(32), default="PENDING", nullable=False, index=True)
    routing_destination = Column(String(64), default="READY_FOR_REVIEW", nullable=False)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize applicant record to dictionary."""
        return {
            "app_id": self.app_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth,
            "email_address": self.email_address,
            "phone_number": self.phone_number,
            "mailing_address": self.mailing_address,
            "gender": self.gender,
            "ethnicity": self.ethnicity,
            "name_of_hs": self.name_of_hs,
            "counselor_name": self.counselor_name,
            "country": self.country,
            "region": self.region,
            "intended_major": self.intended_major,
            "admission_year": self.admission_year,
            "admission_term": self.admission_term,
            "gpa": self.gpa,
            "unweighted_gpa": self.unweighted_gpa,
            "weighted_gpa": self.weighted_gpa,
            "class_rank": self.class_rank,
            "superscored_sat_score": self.superscored_sat_score,
            "sat_math": self.sat_math,
            "sat_ebrw": self.sat_ebrw,
            "superscored_act_score": self.superscored_act_score,
            "act_composite": self.act_composite,
            "total_aps": self.total_aps,
            "total_ibs": self.total_ibs,
            "activities": self.activities or [],
            "awards": self.awards or [],
            "ap_test_scores": self.ap_test_scores or [],
            "hooks": self.hooks or [],
            "documents": self.documents or [],
            "status": self.status,
            "routing_destination": self.routing_destination,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Backwards compatibility aliases
Application = Applicant
ApplicationRecord = Applicant


class OrphanDocument(Base):
    """Archival record of documents received without an existing CSV applicant row."""

    __tablename__ = "orphan_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    minio_key = Column(String(512), nullable=False)
    detected_app_id = Column(String(64), nullable=True, index=True)
    sha256 = Column(String(64), nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    ingested_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize orphan document record to dictionary."""
        return {
            "id": self.id,
            "filename": self.filename,
            "file_path": self.file_path,
            "minio_key": self.minio_key,
            "detected_app_id": self.detected_app_id,
            "sha256": self.sha256,
            "file_size_bytes": self.file_size_bytes,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
        }


class DocumentRecord(Base):
    """Archival record of inbound documents stored in MinIO."""

    __tablename__ = "document_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    applicant_id = Column(String(64), nullable=False, index=True)
    document_type = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    minio_bucket = Column(String(64), nullable=False, default="admissions-raw-docs")
    minio_object_key = Column(String(512), nullable=False, unique=True)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(64), default="application/pdf", nullable=False)
    sha256_checksum = Column(String(64), nullable=True)
    is_readable = Column(Boolean, default=True, nullable=False)
    parsed_content = Column(JsonType, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AuditLog(Base):
    """Immutable audit trail of pipeline actions protecting student PII (Trust Boundary 2)."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    applicant_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    actor = Column(String(64), nullable=False, default="system_pipeline")
    details = Column(JsonType, default=dict, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
