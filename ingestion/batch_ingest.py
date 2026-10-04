"""Pure Batch Ingestion & Linking Module for Admissions Data (Component 2).

Enforces Lightweight Trust Boundary 1 Perimeter Hygiene:
- Ingests and parses applicant CSV data.
- Deterministically links each applicant record to documents via applicant ID subfolders or prefixed filenames.
- Lightweight perimeter hygiene: checks file existence, size constraints (1 KB to 15 MB),
  and standard PDF magic numbers (b"%PDF-") without opening or scanning document text/pages.
- Strictly pure ingestion: no OCR, no DocumentParser, and no PyMuPDF page-to-image/PNG rendering.
- Maintains SHA-256 checksums, clean metadata, and file paths ready for PostgreSQL and MinIO.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import csv

from config import get_file_constraints, load_policies

logger = logging.getLogger(__name__)

# Standard PDF Magic Bytes Header (First 5 bytes)
PDF_MAGIC_BYTES = b"%PDF-"
MIN_FILE_SIZE_BYTES = 1024  # 1 KB
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file in streaming chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass
class IngestedDocument:
    """Document linked to an applicant record with Trust Boundary 1 verification metadata."""
    filename: str
    file_path: Path
    doc_type: str
    file_size_bytes: int
    mime_type: str
    sha256_checksum: str
    applicant_id: str
    exists: bool = True
    is_readable: bool = True
    error_message: Optional[str] = None
    minio_object_key: str = field(default="")
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.minio_object_key and self.applicant_id and self.filename:
            self.minio_object_key = f"{self.applicant_id}/{self.filename}"

    def to_storage_record_dict(self, bucket: str = "applicant-documents") -> Dict[str, Any]:
        """Produce dictionary formatted for PostgreSQL document_records and MinIO object storage."""
        return {
            "applicant_id": self.applicant_id,
            "document_type": self.doc_type,
            "filename": self.filename,
            "minio_bucket": bucket,
            "minio_object_key": self.minio_object_key,
            "file_size_bytes": self.file_size_bytes,
            "mime_type": self.mime_type,
            "sha256_checksum": self.sha256_checksum,
            "is_readable": self.is_readable,
            "error_message": self.error_message,
            "storage_path": str(self.file_path),
        }


@dataclass
class IngestedApplication:
    """Ingested applicant packet linking CSV metadata to physical documents."""
    applicant_id: str
    metadata: Dict[str, Any]
    subfolder_path: Optional[Path] = None
    documents: List[IngestedDocument] = field(default_factory=list)
    trust_boundary_errors: List[str] = field(default_factory=list)
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_postgres_application_data(self) -> Dict[str, Any]:
        """Format clean metadata ready for PostgreSQL applications table JSONB payload."""
        return {
            "applicant_id": self.applicant_id,
            "csv_metadata": self.metadata,
            "documents_count": len(self.documents),
            "documents": [d.to_storage_record_dict() for d in self.documents],
            "subfolder": str(self.subfolder_path) if self.subfolder_path else None,
            "trust_boundary_errors": self.trust_boundary_errors,
            "ingested_at": self.ingested_at.isoformat(),
        }


class BatchIngestor:
    """Ingests application batches, maps CSV records to documents, and enforces Trust Boundary 1 perimeter hygiene."""

    CANONICAL_TYPE_MAP = {
        "transcript": "transcript",
        "official_transcript": "transcript",
        "academic_transcript": "transcript",
        "application_form": "application_form",
        "common_app_application": "application_form",
        "commonapp": "application_form",
        "applicant_profile": "application_form",
        "personal_statement": "personal_statement",
        "essay": "personal_statement",
        "personal_essay": "personal_statement",
        "statement_of_purpose": "personal_statement",
        "recommendation_letter": "recommendation_letter",
        "recommendation_letter_1": "recommendation_letter",
        "recommendation_letter_2": "recommendation_letter",
        "lor": "recommendation_letter",
        "standardized_test_score": "standardized_test_score",
        "sat_score": "standardized_test_score",
        "act_score": "standardized_test_score",
        "test_score": "standardized_test_score",
        "activities_and_awards": "activities_and_awards",
        "activities": "activities_and_awards",
        "awards": "activities_and_awards",
        "advanced_coursework_and_ap_scores": "advanced_coursework_and_ap_scores",
        "ap_scores": "advanced_coursework_and_ap_scores",
        "university_supplement": "university_supplement",
        "supplement": "university_supplement",
        "exception_supporting_document": "exception_supporting_document",
        "special_circumstance": "exception_supporting_document",
    }

    def __init__(self, config_path: Optional[Path] = None):
        self.policies = load_policies(config_path)
        self.file_constraints = self.policies.get("file_constraints", {})
        self.allowed_mimes = set(self.file_constraints.get("allowed_mime_types", ["application/pdf"]))
        self.allowed_exts = set(self.file_constraints.get("allowed_extensions", [".pdf"]))
        self.min_size = self.file_constraints.get("min_file_size_bytes", MIN_FILE_SIZE_BYTES)
        self.max_size = self.file_constraints.get("max_file_size_bytes", MAX_FILE_SIZE_BYTES)

    def classify_document(self, filename: str) -> str:
        """Deterministically classify document into its canonical policy type."""
        stem = Path(filename).stem.lower().replace("-", "_")
        if stem in self.CANONICAL_TYPE_MAP:
            return self.CANONICAL_TYPE_MAP[stem]

        # Prefix / partial matching
        for pattern, canonical in self.CANONICAL_TYPE_MAP.items():
            if pattern in stem:
                return canonical

        return stem

    def find_csv_file(self, input_dir: Path) -> Path:
        """Locate the batch applicant CSV file."""
        csv_files = list(input_dir.glob("*.csv"))
        if csv_files:
            # Prioritize file with applicant in name if multiple
            for c in csv_files:
                if "applicant" in c.name.lower():
                    return c
            return csv_files[0]

        # Fallback to applicant_data in workspace
        root = input_dir.resolve().parent
        for candidate_dir in [root / "applicant_data", Path("applicant_data")]:
            if candidate_dir.exists():
                candidates = list(candidate_dir.glob("*V3.csv")) or list(candidate_dir.glob("*.csv"))
                if candidates:
                    return candidates[0]

        raise FileNotFoundError(f"No CSV file found in {input_dir} or applicant_data/")

    def parse_csv(self, csv_path: Path) -> List[Dict[str, Any]]:
        """Parse applicant CSV records with clean stripped metadata."""
        records: List[Dict[str, Any]] = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
                records.append(cleaned)
        return records

    def verify_file_trust_boundary(self, file_path: Path, applicant_id: str) -> Tuple[bool, bool, str, Optional[str]]:
        """Enforce lightweight Trust Boundary 1 perimeter hygiene:
        1. Check file existence.
        2. Check extension (.pdf).
        3. Check file size (1 KB to 15 MB).
        4. Read the first 5 bytes for standard PDF magic numbers (b"%PDF-")
           without opening or scanning the document text/pages.

        Returns:
            (exists, is_readable, mime_type, error_message)
        """
        if not file_path.exists() or not file_path.is_file():
            return False, False, "unknown", f"File does not exist: {file_path.name}"

        # 1. Extension check
        ext = file_path.suffix.lower()
        if ext not in self.allowed_exts:
            return True, False, "unknown", f"Disallowed extension '{ext}' in '{file_path.name}' (expected {self.allowed_exts})"

        # 2. File size constraints check (1 KB to 15 MB)
        try:
            size = file_path.stat().st_size
        except OSError as e:
            return True, False, "unknown", f"Cannot access file stat for '{file_path.name}': {e}"

        if size < self.min_size:
            return True, False, "application/pdf", f"File size {size} bytes is below minimum {self.min_size} bytes (1 KB) for '{file_path.name}'"
        if size > self.max_size:
            return True, False, "application/pdf", f"File size {size} bytes exceeds maximum {self.max_size} bytes (15 MB) for '{file_path.name}'"

        # 3. Read first 5 bytes for standard PDF magic numbers (b"%PDF-") without opening/scanning pages
        try:
            with open(file_path, "rb") as f:
                magic_bytes = f.read(5)
        except OSError as e:
            return True, False, "unknown", f"Cannot read file header for '{file_path.name}': {e}"

        if magic_bytes != PDF_MAGIC_BYTES:
            return True, False, "application/octet-stream", f"Invalid PDF magic bytes {magic_bytes!r} in '{file_path.name}' (expected b'%PDF-')"

        return True, True, "application/pdf", None

    def link_applicant_documents(
        self,
        applicant_id: str,
        input_dir: Path,
    ) -> Tuple[Optional[Path], List[IngestedDocument], List[str]]:
        """Link applicant record to files in input_dir using subfolder or prefix mapping."""
        documents: List[IngestedDocument] = []
        errors: List[str] = []

        # Find subfolder: check APP_001, APP-001, etc.
        candidates = [
            input_dir / applicant_id,
            input_dir / applicant_id.replace("-", "_"),
            input_dir / applicant_id.replace("_", "-"),
        ]

        target_dir = None
        for cand in candidates:
            if cand.exists() and cand.is_dir():
                target_dir = cand
                break

        if target_dir is None:
            # Check for direct files prefixed with applicant_id
            prefixed_files = sorted([p for p in input_dir.glob(f"{applicant_id}*") if p.is_file() and not p.name.startswith(".")])
            if not prefixed_files:
                errors.append(f"No document directory or files found for applicant '{applicant_id}'")
                return None, documents, errors
            files_to_process = prefixed_files
        else:
            files_to_process = sorted([p for p in target_dir.glob("*") if p.is_file() and not p.name.startswith(".")])

        for fp in files_to_process:
            size = fp.stat().st_size if fp.exists() else 0
            exists, readable, mime, err = self.verify_file_trust_boundary(fp, applicant_id)
            checksum = compute_sha256(fp) if exists else ""
            doc_type = self.classify_document(fp.name)

            if err:
                errors.append(err)

            doc_item = IngestedDocument(
                filename=fp.name,
                file_path=fp,
                doc_type=doc_type,
                file_size_bytes=size,
                mime_type=mime,
                sha256_checksum=checksum,
                applicant_id=applicant_id,
                exists=exists,
                is_readable=readable,
                error_message=err,
                minio_object_key=f"{applicant_id}/{fp.name}",
            )
            documents.append(doc_item)

        return target_dir, documents, errors

    def ingest_batch(self, input_dir: Path) -> List[IngestedApplication]:
        """Execute full pure batch ingestion and document linking on input_dir."""
        input_path = Path(input_dir)
        csv_path = self.find_csv_file(input_path)
        csv_records = self.parse_csv(csv_path)

        # Check if subfolders exist in input_path
        subfolders = {d.name for d in input_path.iterdir() if d.is_dir()}

        ingested_apps: List[IngestedApplication] = []

        for record in csv_records:
            app_id = record.get("App_ID") or record.get("applicant_id") or record.get("Applicant_ID", "")
            if not app_id:
                continue

            # If the CSV has records not in this batch and subfolders exist, only process matching records
            app_variants = {app_id, app_id.replace("-", "_"), app_id.replace("_", "-")}
            if subfolders and not (app_variants & subfolders):
                continue

            subfolder, docs, errs = self.link_applicant_documents(app_id, input_path)

            app = IngestedApplication(
                applicant_id=app_id,
                metadata=record,
                subfolder_path=subfolder,
                documents=docs,
                trust_boundary_errors=errs,
            )
            ingested_apps.append(app)

        return ingested_apps
