"""Data models for deterministic manifest validation."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    """Workflow status codes according to institutional policy."""
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    AWAITING_MATERIALS = "AWAITING_MATERIALS"
    INCOMPLETE = "INCOMPLETE"
    COUNSELOR_REVIEW = "COUNSELOR_REVIEW"
    REPLACEMENT_REQUESTED = "REPLACEMENT_REQUESTED"
    STOPPED = "STOPPED"


class DocumentManifestItem(BaseModel):
    """Metadata item representing an individual document within an applicant packet."""
    filename: str
    doc_type: str
    file_size_bytes: int
    mime_type: str = "application/pdf"
    sha256_checksum: Optional[str] = None
    applicant_id: Optional[str] = None
    is_readable: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PacketManifest(BaseModel):
    """Manifest describing an inbound applicant submission packet."""
    applicant_id: str
    application_type: str = "first_year"
    source_feed: str = "CommonApp_SFTP"
    documents: List[DocumentManifestItem] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationFinding(BaseModel):
    """Specific policy or constraint finding generated during validation."""
    policy_id: str
    rule: str
    severity: str  # "ERROR", "WARNING", "INFO"
    status: ValidationStatus
    message: str
    document_type: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Outcome of the deterministic manifest validation gate."""
    applicant_id: str
    is_valid: bool
    status: ValidationStatus
    routing_destination: str
    findings: List[ValidationFinding] = Field(default_factory=list)
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
