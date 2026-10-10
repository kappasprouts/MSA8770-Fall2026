"""Data models for document parsing and OCR payloads."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ParsedPage(BaseModel):
    """Extracted text and metadata for an individual page."""
    page_number: int
    text: str = ""
    char_count: int = 0
    confidence: float = 1.0  # 0.0 to 1.0
    ocr_applied: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """Structured JSON representation of a parsed document."""
    applicant_id: Optional[str] = None
    document_type: str
    source_file: str
    total_pages: int = 0
    full_text: str = ""
    pages: List[ParsedPage] = Field(default_factory=list)
    extraction_method: str = "PyMuPDF"  # PyMuPDF, Tesseract_OCR, or Hybrid
    is_readable: bool = True
    classification_confidence: float = 1.0
    extracted_entities: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json_dict(self) -> Dict[str, Any]:
        """Return clean dictionary representation suitable for JSON persistence or APIs."""
        return self.model_dump()
