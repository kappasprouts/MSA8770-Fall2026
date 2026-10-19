"""Data models for Model Gateway inference and policy-grounded evaluation."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    """Document representation passed to inference context."""
    document_type: str
    content: str
    filename: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InferenceRequest(BaseModel):
    """Request payload for model evaluation."""
    applicant_id: str
    application_type: str = "first_year"
    documents: List[DocumentItem] = Field(default_factory=list)
    high_school_context: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyCitation(BaseModel):
    """Policy citation attached to an evaluation finding."""
    policy_id: str
    title: str
    applied_rule: str
    evidence_found: str


class InferenceResponse(BaseModel):
    """Structured response from the Model Gateway."""
    applicant_id: str
    model_name: str
    evaluation_summary: Dict[str, Any] = Field(default_factory=dict)
    policy_citations: List[PolicyCitation] = Field(default_factory=list)
    essay_bypassed: bool = True
    essay_bypass_reason: str = "POL-ESSAY-01: Personal statements are skipped by model inference to mitigate algorithmic bias and reserved for human review."
    bypassed_documents: List[str] = Field(default_factory=list)
    raw_response: Optional[str] = None
    status: str = "COMPLETED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
