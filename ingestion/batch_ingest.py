"""Pure Batch Ingestion & Linking Module for Admissions Data (Component 2).

Implements Two-Pass Ingestion:
- Pass 1: Parse the application flat file (CSV), extract standard scalar columns
  and structured lists (activities, awards, APs, hooks), and stage/upsert application
  records in PostgreSQL (or dry-run store).
- Pass 2: Traverse all documents across the batch directory.
  * If document maps to a known app_id: check format/magic bytes (%PDF-),
    compute SHA-256, upload to MinIO bucket ('admissions-raw-docs'), and attach
    document metadata to the applicant's documents JSONB array.
  * If document has no matching application record (orphan / late-coming LOR):
    save to the OrphanDocument table and upload to MinIO under 'orphans/'.
- Enforces lightweight Trust Boundary 1 perimeter hygiene: check file existence,
  file size (1 KB to 15 MB), and read the first 5 bytes for standard PDF magic
  numbers (b"%PDF-") without opening or scanning document text/pages.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import logging
import mimetypes
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
import csv
from uuid import uuid4

from config import derive_routing_destination, get_file_constraints, load_policies
from storage.date_utils import parse_date_of_birth
from storage.storage_manager import StorageManager

logger = logging.getLogger(__name__)

# Standard PDF Magic Bytes Header (First 5 bytes)
PDF_MAGIC_BYTES = b"%PDF-"
MIN_FILE_SIZE_BYTES = 1024  # 1 KB
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB

# A repeated CSV row may update only the columns actually supplied by that feed.
# Documents, workflow status, and test-feed-only fields have separate owners.
CSV_UPDATE_FIELDS = {
    "First_Name": ("first_name",),
    "Last_Name": ("last_name",),
    "Date_Of_Birth": ("date_of_birth",),
    "Mailing_Address": ("mailing_address",),
    "Primary_Phone_Number": ("phone_number",),
    "Email_Address": ("email_address",),
    "Gender": ("gender",),
    "Ethnicity": ("ethnicity",),
    "Name_of_HS": ("name_of_hs",),
    "Counselor_Name": ("counselor_name",),
    "Country": ("country",),
    "Region": ("region",),
    "Intended_Major": ("intended_major",),
    "Admission_Year": ("admission_year",),
    "Admission_Term": ("admission_term",),
    "Unweighted_GPA": ("unweighted_gpa",),
    "Weighted_GPA": ("weighted_gpa",),
    "Rank": ("rank",),
    "Superscored_SAT_Score": ("superscored_sat_score",),
    "Superscored_ACT_Score": ("superscored_act_score", "act_composite"),
    "Total_APs": ("total_aps",),
    "Total_IBs": ("total_ibs",),
    "IB_Courses": ("ib_test_scores",),
    "Create_Date_Time": ("create_date_time",),
    "Last_Updated": ("last_updated_csv",),
    "Review_Ctr": ("review_ctr",),
    "Application_status": ("application_status_raw",),
    "Final_Decision": ("final_decision",),
    "Activities": ("activities",),
    "Awards": ("awards",),
    "AP_Courses": ("ap_test_scores",),
    "Hooks": ("hooks",),
}


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file in streaming chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_and_normalize_app_id(text: Optional[str]) -> Optional[str]:
    """Extract and normalize applicant ID from filename, path, or directory name.

    Supports formats like APP_001, APP001, app_001, APP-001, app10, etc.,
    normalizing to standard canonical format: APP_XXX (e.g. APP_001).
    """
    if not text:
        return None
    match = re.search(r"APP[_\-\s]?(\d+)", str(text), re.IGNORECASE)
    if match:
        digits = match.group(1)
        if len(digits) >= 3:
            return f"APP_{digits}"
        else:
            num = int(digits)
            return f"APP_{num:03d}"
    return None


def _parse_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_gpa(val: Any) -> Optional[Decimal]:
    """Parse CSV GPA without binary float rounding before NUMERIC(5,3) storage."""
    if val is None or str(val).strip().lower() in {"", "nan"}:
        return None
    try:
        value = Decimal(str(val).strip())
        if not value.is_finite():
            return None
        return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _parse_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _has_csv_value(value: Any) -> bool:
    """Treat blank cells in a repeated feed as absent updates."""
    return value is not None and str(value).strip().lower() not in ("", "nan")


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
    minio_key: str = field(default="")
    minio_bucket: str = "admissions-raw-docs"
    exists: bool = True
    is_readable: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.minio_key and self.applicant_id and self.filename:
            self.minio_key = f"{self.applicant_id}/{self.filename}"

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Produce a document record without dropping metadata from an earlier batch."""
        record = dict(self.metadata)
        record.update({
            "doc_type": self.doc_type,
            "minio_key": self.minio_key,
            "minio_bucket": self.minio_bucket,
            "filename": self.filename,
            "sha256": self.sha256_checksum,
            "file_size": self.file_size_bytes,
            "mime_type": self.mime_type,
            "exists": self.exists,
            "is_readable": self.is_readable,
            "error_message": self.error_message,
        })
        return record

    def to_storage_record_dict(self, bucket: Optional[str] = None) -> Dict[str, Any]:
        """Produce dictionary formatted for PostgreSQL document_records and MinIO object storage."""
        return {
            "applicant_id": self.applicant_id,
            "document_type": self.doc_type,
            "filename": self.filename,
            "minio_bucket": bucket or self.minio_bucket,
            "minio_object_key": self.minio_key,
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
    activities: List[str] = field(default_factory=list)
    awards: List[str] = field(default_factory=list)
    ap_test_scores: List[Any] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    subfolder_path: Optional[Path] = None
    documents: List[IngestedDocument] = field(default_factory=list)
    trust_boundary_errors: List[str] = field(default_factory=list)
    status: str = "PENDING"
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def routing_destination(self) -> str:
        return derive_routing_destination(self.status)

    def to_applicant_dict(self) -> Dict[str, Any]:
        """Produce dictionary with explicit typed relational columns and JSONB arrays."""
        m = self.metadata
        unweighted = _parse_gpa(m.get("Unweighted_GPA"))
        weighted = _parse_gpa(m.get("Weighted_GPA"))
        sat = _parse_float(m.get("Superscored_SAT_Score"))
        act = _parse_float(m.get("Superscored_ACT_Score"))
        adm_yr = _parse_int(m.get("Admission_Year"))
        tot_aps = _parse_float(m.get("Total_APs"))
        tot_ibs = _parse_float(m.get("Total_IBs"))
        rev_ctr = _parse_int(m.get("Review_Ctr")) or 0

        doc_dicts = [d.to_metadata_dict() for d in self.documents]

        return {
            "app_id": self.applicant_id,
            "first_name": str(m.get("First_Name") or "").strip(),
            "last_name": str(m.get("Last_Name") or "").strip(),
            "date_of_birth": parse_date_of_birth(m.get("Date_Of_Birth")),
            "mailing_address": str(m.get("Mailing_Address") or "").strip() or None,
            "phone_number": str(m.get("Primary_Phone_Number") or "").strip() or None,
            "email_address": str(m.get("Email_Address") or "").strip() or None,
            "gender": str(m.get("Gender") or "").strip() or None,
            "ethnicity": str(m.get("Ethnicity") or "").strip() or None,
            "name_of_hs": str(m.get("Name_of_HS") or "").strip() or None,
            "counselor_name": str(m.get("Counselor_Name") or "").strip() or None,
            "country": str(m.get("Country") or "").strip() or None,
            "region": str(m.get("Region") or "").strip() or None,
            "intended_major": str(m.get("Intended_Major") or "").strip() or None,
            "admission_year": adm_yr,
            "admission_term": str(m.get("Admission_Term") or "").strip() or None,
            "unweighted_gpa": unweighted,
            "weighted_gpa": weighted,
            "rank": str(m.get("Rank") or "").strip() or None,
            "superscored_sat_score": sat,
            "sat_math": None,
            "sat_ebrw": None,
            "superscored_act_score": act,
            "act_composite": act,
            "total_aps": tot_aps,
            "total_ibs": tot_ibs,
            "ib_test_scores": [
                item.strip() for item in str(m.get("IB_Courses") or "").split(",")
                if item.strip()
            ][:12],
            "create_date_time": str(m.get("Create_Date_Time") or "").strip() or None,
            "last_updated_csv": str(m.get("Last_Updated") or "").strip() or None,
            "review_ctr": rev_ctr,
            "application_status_raw": str(m.get("Application_status") or "").strip() or None,
            "final_decision": str(m.get("Final_Decision") or "").strip() or None,
            "activities": self.activities,
            "awards": self.awards,
            "ap_test_scores": self.ap_test_scores,
            "hooks": self.hooks,
            "documents": doc_dicts,
            "status": self.status,
        }


@dataclass
class BatchIngestionResult:
    """Outcome of full two-pass batch ingestion."""
    applications: List[IngestedApplication] = field(default_factory=list)
    orphans: List[Dict[str, Any]] = field(default_factory=list)
    total_processed: int = 0
    csv_path: Optional[Path] = None
    affected_ids: List[str] = field(default_factory=list)

    def __iter__(self) -> Iterator[IngestedApplication]:
        return iter(self.applications)

    def __len__(self) -> int:
        return len(self.applications)

    def __getitem__(self, idx: int) -> IngestedApplication:
        return self.applications[idx]


class BatchIngestor:
    """Ingests application batches using two-pass ingestion, linking CSV records to documents
    and persisting into PostgreSQL relational columns and MinIO raw object storage.
    """

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
        "recommendation_letter_1": "recommendation_letter_1",
        "recommendation_letter_2": "recommendation_letter_2",
        "recommendation_letter": "recommendation_letter_1",
        "lor_1": "recommendation_letter_1",
        "lor_2": "recommendation_letter_2",
        "lor": "recommendation_letter_1",
        "counselor_recommendation": "recommendation_letter_1",
        "teacher_recommendation": "recommendation_letter_2",
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

    def __init__(
        self,
        config_path: Optional[Path] = None,
        storage_manager: Optional[StorageManager] = None,
    ):
        self.config_path = config_path
        self.policies = load_policies(config_path)
        self.file_constraints = self.policies.get("file_constraints", {})
        self.allowed_mimes = set(self.file_constraints.get("allowed_mime_types", ["application/pdf"]))
        self.allowed_exts = set(self.file_constraints.get("allowed_extensions", [".pdf"]))
        self.min_size = self.file_constraints.get("min_file_size_bytes", MIN_FILE_SIZE_BYTES)
        self.max_size = self.file_constraints.get("max_file_size_bytes", MAX_FILE_SIZE_BYTES)
        self.storage = storage_manager or StorageManager()
        self.affected_ids: List[str] = []
        self._gate = None

    @property
    def gate(self):
        """Lazily load ManifestValidationGate to avoid circular import."""
        if self._gate is None:
            from validation.manifest_gate import ManifestValidationGate
            self._gate = ManifestValidationGate(config_path=self.config_path)
        return self._gate

    def _db_applicant_to_ingested(self, db_app: Any) -> IngestedApplication:
        """Convert a database Applicant record to an IngestedApplication instance."""
        existing_docs: List[IngestedDocument] = []
        raw_docs = getattr(db_app, "documents", []) or []
        for d in raw_docs:
            if isinstance(d, dict):
                existing_docs.append(
                    IngestedDocument(
                        filename=d.get("filename", "document.pdf"),
                        file_path=Path(d.get("storage_path") or d.get("filename") or "document.pdf"),
                        doc_type=d.get("doc_type", "other"),
                        file_size_bytes=d.get("file_size", d.get("file_size_bytes", 1024)),
                        mime_type=d.get("mime_type", "application/pdf"),
                        sha256_checksum=d.get("sha256", d.get("sha256_checksum", "0" * 64)),
                        applicant_id=db_app.app_id,
                        minio_key=d.get("minio_key", ""),
                        minio_bucket=d.get("minio_bucket", self.storage.minio_bucket),
                        exists=d.get("exists", True),
                        is_readable=d.get("is_readable", True),
                        error_message=d.get("error_message"),
                        metadata=dict(d),
                    )
                )
            elif isinstance(d, IngestedDocument):
                existing_docs.append(d)

        # Earlier runs may already have appended the same object more than once.
        # Keep its latest metadata and count it once during manifest validation.
        unique_docs = {doc.minio_key: doc for doc in existing_docs}
        existing_docs = list(unique_docs.values())

        metadata = {
            "App_ID": db_app.app_id,
            "First_Name": db_app.first_name,
            "Last_Name": db_app.last_name,
            "Date_Of_Birth": db_app.date_of_birth,
            "Email_Address": db_app.email_address,
            "Name_of_HS": db_app.name_of_hs,
            "Intended_Major": db_app.intended_major,
            "Admission_Year": db_app.admission_year,
            "Admission_Term": db_app.admission_term,
            "Superscored_SAT_Score": db_app.superscored_sat_score,
            "Superscored_ACT_Score": db_app.superscored_act_score,
            "sat_math": db_app.sat_math,
            "sat_ebrw": db_app.sat_ebrw,
            "act_composite": db_app.act_composite,
        }

        return IngestedApplication(
            applicant_id=db_app.app_id,
            metadata=metadata,
            activities=list(db_app.activities or []),
            awards=list(db_app.awards or []),
            ap_test_scores=list(db_app.ap_test_scores or []),
            hooks=list(db_app.hooks or []),
            subfolder_path=None,
            documents=existing_docs,
            trust_boundary_errors=[],
            status=db_app.status,
        )

    @staticmethod
    def _attach_document(app: IngestedApplication, document: IngestedDocument) -> None:
        """Replace a previously ingested object at the same storage key."""
        for index, existing in enumerate(app.documents):
            if existing.minio_key == document.minio_key:
                app.documents[index] = document
                return
        app.documents.append(document)

    @staticmethod
    def _orphan_minio_key(input_dir: Path, doc_path: Path, checksum: str) -> str:
        """Give distinct orphan files stable object keys across batch replays."""
        relative_path = doc_path.relative_to(input_dir).as_posix()
        digest = checksum or hashlib.sha256(str(doc_path.resolve()).encode()).hexdigest()
        return f"orphans/{digest}/{relative_path}"

    def classify_document(self, filename: str) -> str:
        """Deterministically classify document into its canonical policy type."""
        stem = Path(filename).stem.lower().replace("-", "_")
        if stem in self.CANONICAL_TYPE_MAP:
            return self.CANONICAL_TYPE_MAP[stem]

        # Prioritize exact sub-pattern matches
        for pattern, canonical in self.CANONICAL_TYPE_MAP.items():
            if pattern in stem:
                return canonical

        return stem

    def find_csv_file(self, input_dir: Path) -> Path:
        """Locate the batch applicant CSV file."""
        csv_files = list(input_dir.glob("*.csv"))
        if csv_files:
            for c in csv_files:
                if "applicant" in c.name.lower():
                    return c
            return csv_files[0]

        # Document-only batches must not replay an unrelated CSV from the workspace.
        raise FileNotFoundError(f"No CSV file found in {input_dir}")

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

    def pass_1_parse_and_stage_csv(
        self, input_dir: Path, applicant_ids: Optional[Set[str]] = None
    ) -> Tuple[Path, Dict[str, IngestedApplication]]:
        """Pass 1: Parse application flat file (CSV), extract standard scalar columns
        and structured lists (activities, awards, APs, hooks), and stage/upsert application
        records into PostgreSQL (or dry-run store).
        """
        csv_path = self.find_csv_file(input_dir)
        csv_records = self.parse_csv(csv_path)

        # Detect subfolders in input_dir to scope batch if needed
        subfolders = {d.name for d in input_dir.iterdir() if d.is_dir()}
        scoped_ids = {extract_and_normalize_app_id(name) or name for name in subfolders}

        staged_applicants: Dict[str, IngestedApplication] = {}

        for csv_record in csv_records:
            raw_app_id = csv_record.get("App_ID") or csv_record.get("applicant_id") or csv_record.get("Applicant_ID", "")
            if not raw_app_id:
                continue
            if re.fullmatch(r"APP[_\-\s]?\d+", raw_app_id, re.IGNORECASE) is None:
                raise ValueError(f"Invalid applicant ID in CSV: {raw_app_id!r}")

            existing = self.storage.get_applicant(raw_app_id)
            app_id = existing.app_id if existing else (extract_and_normalize_app_id(raw_app_id) or raw_app_id)
            canonical_id = extract_and_normalize_app_id(app_id) or app_id
            if applicant_ids is not None and canonical_id not in applicant_ids:
                continue
            if subfolders and canonical_id not in scoped_ids:
                # Skip records not in this batch if batch directory is scoped by subfolders
                continue

            record = dict(csv_record)
            record["App_ID"] = app_id

            # Extract variable-length array fields
            activities_str = record.get("Activities") or ""
            activities = [s.strip() for s in activities_str.split(",") if s.strip()][:10]

            awards_str = record.get("Awards") or ""
            awards = [s.strip() for s in awards_str.split(",") if s.strip()][:5]

            ap_str = record.get("AP_Courses") or ""
            ap_scores = [s.strip() for s in ap_str.split(",") if s.strip()][:12]

            hooks_str = record.get("Hooks") or ""
            hooks = [s.strip() for s in hooks_str.split(",") if s.strip()][:5]

            # Find matching subfolder if present
            subfolder_path = None
            for cand in [input_dir / raw_app_id, input_dir / app_id, input_dir / canonical_id]:
                if cand.exists() and cand.is_dir():
                    subfolder_path = cand
                    break

            ingested_app = IngestedApplication(
                applicant_id=app_id,
                metadata=record,
                activities=activities,
                awards=awards,
                ap_test_scores=ap_scores,
                hooks=hooks,
                subfolder_path=subfolder_path,
                documents=[],
                trust_boundary_errors=[],
                status="PENDING",
            )

            applicant_data = ingested_app.to_applicant_dict()
            update_fields = None
            if existing:
                update_fields = {
                    field_name
                    for csv_name, field_names in CSV_UPDATE_FIELDS.items()
                    if csv_name in csv_record and _has_csv_value(csv_record[csv_name])
                    for field_name in field_names
                }

                # The flat file lists AP courses; scored AP results belong to the
                # independent test-score feed and must survive a CSV repeat.
                if "ap_test_scores" in update_fields:
                    scored_aps = [item for item in (existing.ap_test_scores or []) if isinstance(item, dict)]
                    applicant_data["ap_test_scores"] = ap_scores + scored_aps

                # A blank or older CSV superscore cannot erase a later score feed.
                for field_name in ("superscored_sat_score", "superscored_act_score", "act_composite"):
                    if field_name in update_fields:
                        incoming = applicant_data[field_name]
                        prior = getattr(existing, field_name)
                        if incoming is None or (prior is not None and incoming < prior):
                            update_fields.remove(field_name)

            # Stage CSV-owned fields, then hydrate the packet from the persisted row
            # so pass 2 sees earlier documents and score-feed updates.
            staged_db = self.storage.stage_applicant(applicant_data, update_fields=update_fields)
            stored_packet = self._db_applicant_to_ingested(staged_db)
            ingested_app.applicant_id = staged_db.app_id
            ingested_app.documents = stored_packet.documents
            ingested_app.ap_test_scores = stored_packet.ap_test_scores
            ingested_app.status = staged_db.status
            ingested_app.metadata = dict(stored_packet.metadata)
            ingested_app.metadata.update({
                key: value for key, value in record.items()
                if not existing or _has_csv_value(value)
            })
            ingested_app.metadata.update({
                "App_ID": staged_db.app_id,
                "Superscored_SAT_Score": staged_db.superscored_sat_score,
                "Superscored_ACT_Score": staged_db.superscored_act_score,
                "sat_math": staged_db.sat_math,
                "sat_ebrw": staged_db.sat_ebrw,
                "act_composite": staged_db.act_composite,
                "ap_test_scores": staged_db.ap_test_scores,
            })
            staged_applicants[staged_db.app_id] = ingested_app

        logger.info("Pass 1 Complete: Staged %d applicants from %s", len(staged_applicants), csv_path.name)
        return csv_path, staged_applicants

    def pass_2_traverse_and_link_documents(
        self,
        input_dir: Path,
        staged_applicants: Dict[str, IngestedApplication],
        applicant_ids: Optional[Set[str]] = None,
        audit_run_id: Optional[str] = None,
    ) -> Tuple[List[IngestedApplication], List[Dict[str, Any]]]:
        """Pass 2: Traverse all documents across the batch directory.
        - Case 1: If document maps to an in-memory staged applicant from Pass 1,
          upload to MinIO ('admissions-raw-docs') and attach metadata to documents JSONB array.
        - Case 2: If document's extracted app_id is NOT in staged_applicants, perform a
          quick database lookup against PostgreSQL (Applicant table).
          If record exists in DB (from a prior night's batch):
            1. Add app_id to staged_applicants.
            2. Attach document metadata to the applicant's documents JSONB array (and upload to MinIO).
            3. Re-evaluate the complete packet after document traversal.
        - Case 3: If not found in DB either, route to the OrphanDocument table and upload to MinIO under 'orphans/'.
        """
        orphans_list: List[Dict[str, Any]] = []
        affected_ids: List[str] = []
        if audit_run_id is None:
            audit_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]

        # Find all documents: in applicant subfolders and at root of input_dir
        candidate_files: List[Tuple[Optional[str], Path, Optional[str]]] = []

        for item in sorted(input_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                # Subdirectory
                folder_id = extract_and_normalize_app_id(item.name)
                subfolder_id = folder_id or item.name.replace("-", "_")
                for doc_file in sorted(item.iterdir()):
                    if doc_file.is_file() and not doc_file.name.startswith(".") and not doc_file.name.endswith(".csv"):
                        filename_id = extract_and_normalize_app_id(doc_file.name)
                        doc_id = filename_id or subfolder_id
                        scope_id = folder_id or filename_id or subfolder_id
                        if applicant_ids is not None and scope_id not in applicant_ids:
                            continue
                        conflict_id = folder_id if filename_id and folder_id and filename_id != folder_id else None
                        candidate_files.append((doc_id, doc_file, conflict_id))
            elif item.is_file() and not item.name.startswith(".") and not item.name.endswith(".csv"):
                # Loose file at root level
                detected_id = extract_and_normalize_app_id(item.name)
                if applicant_ids is not None and detected_id not in applicant_ids:
                    continue
                candidate_files.append((detected_id, item, None))

        # Build alias map for staged applicants
        applicant_alias_map: Dict[str, str] = {}
        for app_id in staged_applicants.keys():
            norm_id = extract_and_normalize_app_id(app_id) or app_id
            applicant_alias_map[app_id] = app_id
            applicant_alias_map[norm_id] = app_id
            applicant_alias_map[app_id.replace("-", "_")] = app_id
            applicant_alias_map[app_id.replace("_", "-")] = app_id

        for detected_id, doc_path, conflicting_folder_id in candidate_files:
            matched_app_id = applicant_alias_map.get(detected_id) if detected_id else None
            if not matched_app_id and detected_id:
                matched_app_id = detected_id

            try:
                size = doc_path.stat().st_size
            except OSError:
                # The trust-boundary check records the specific read/stat error
                # and routes the packet to human review below.
                size = 0
            exists, readable, mime, err = self.verify_file_trust_boundary(doc_path, matched_app_id or "ORPHAN")
            checksum = ""
            if exists:
                try:
                    checksum = compute_sha256(doc_path)
                except OSError as exc:
                    readable = False
                    err = f"Cannot hash '{doc_path.name}': {exc}"
            doc_type = self.classify_document(doc_path.name)

            if conflicting_folder_id:
                # A filename must not move a document into another applicant's
                # packet when its enclosing folder identifies someone else.
                folder_app_id = applicant_alias_map.get(conflicting_folder_id, conflicting_folder_id)
                target_app = staged_applicants.get(folder_app_id)
                if target_app is None:
                    db_app = self.storage.get_applicant(folder_app_id)
                    if db_app:
                        target_app = self._db_applicant_to_ingested(db_app)
                        staged_applicants[db_app.app_id] = target_app
                conflict_error = (
                    f"Applicant ID mismatch for '{doc_path.name}': "
                    f"folder {conflicting_folder_id}, filename {detected_id}"
                )
                logger.warning(conflict_error)
                if target_app is not None:
                    target_app.trust_boundary_errors.append(conflict_error)

                minio_key = self._orphan_minio_key(input_dir, doc_path, checksum)
                self.storage.upload_file(
                    file_path=doc_path,
                    minio_key=minio_key,
                    bucket_name=self.storage.minio_bucket,
                )
                orphan_dict = {
                    "filename": doc_path.name,
                    "file_path": str(doc_path),
                    "minio_key": minio_key,
                    "detected_app_id": None,
                    "sha256": checksum,
                    "file_size_bytes": size,
                }
                self.storage.save_orphan(orphan_dict)
                orphans_list.append(orphan_dict)
                continue

            if matched_app_id and matched_app_id in staged_applicants:
                # CASE 1: MATCHED with staged applicant from Pass 1
                target_app = staged_applicants[matched_app_id]
                minio_key = f"{matched_app_id}/{doc_path.name}"

                self.storage.upload_file(
                    file_path=doc_path,
                    minio_key=minio_key,
                    bucket_name=self.storage.minio_bucket,
                )

                doc_item = IngestedDocument(
                    filename=doc_path.name,
                    file_path=doc_path,
                    doc_type=doc_type,
                    file_size_bytes=size,
                    mime_type=mime,
                    sha256_checksum=checksum,
                    applicant_id=matched_app_id,
                    minio_key=minio_key,
                    minio_bucket=self.storage.minio_bucket,
                    exists=exists,
                    is_readable=readable,
                    error_message=err,
                )
                self._attach_document(target_app, doc_item)
                if err:
                    target_app.trust_boundary_errors.append(err)

            elif (matched_app_id or detected_id) and (
                (matched_app_id and self.storage.get_applicant(matched_app_id))
                or (detected_id and self.storage.get_applicant(detected_id))
            ):
                # CASE 2: NOT in staged_applicants from Pass 1, but exists in DB from prior night's batch
                lookup_id = matched_app_id or detected_id
                db_app = self.storage.get_applicant(lookup_id) or (self.storage.get_applicant(detected_id) if detected_id else None)
                canonical_id = db_app.app_id
                logger.info("Case 2: Found applicant %s in database from prior batch", canonical_id)

                # 1. Add the prior applicant to this batch's evaluation set.
                if canonical_id in staged_applicants:
                    target_app = staged_applicants[canonical_id]
                else:
                    target_app = self._db_applicant_to_ingested(db_app)
                    staged_applicants[canonical_id] = target_app
                    norm_id = extract_and_normalize_app_id(canonical_id) or canonical_id
                    applicant_alias_map[canonical_id] = canonical_id
                    applicant_alias_map[norm_id] = canonical_id
                    applicant_alias_map[canonical_id.replace("-", "_")] = canonical_id
                    applicant_alias_map[canonical_id.replace("_", "-")] = canonical_id

                # 2. Attach document metadata to the applicant's documents JSONB array & upload to MinIO
                minio_key = f"{canonical_id}/{doc_path.name}"
                self.storage.upload_file(
                    file_path=doc_path,
                    minio_key=minio_key,
                    bucket_name=self.storage.minio_bucket,
                )

                doc_item = IngestedDocument(
                    filename=doc_path.name,
                    file_path=doc_path,
                    doc_type=doc_type,
                    file_size_bytes=size,
                    mime_type=mime,
                    sha256_checksum=checksum,
                    applicant_id=canonical_id,
                    minio_key=minio_key,
                    minio_bucket=self.storage.minio_bucket,
                    exists=exists,
                    is_readable=readable,
                    error_message=err,
                )
                self._attach_document(target_app, doc_item)
                if err:
                    target_app.trust_boundary_errors.append(err)

            else:
                # CASE 3: UNMATCHED in CSV and DB -> Orphan Document
                minio_key = self._orphan_minio_key(input_dir, doc_path, checksum)
                logger.warning("Case 3: Orphan document detected: %s (detected_id: %s)", doc_path.name, detected_id)

                self.storage.upload_file(
                    file_path=doc_path,
                    minio_key=minio_key,
                    bucket_name=self.storage.minio_bucket,
                )

                orphan_dict = {
                    "filename": doc_path.name,
                    "file_path": str(doc_path),
                    "minio_key": minio_key,
                    "detected_app_id": detected_id,
                    "sha256": checksum,
                    "file_size_bytes": size,
                }
                self.storage.save_orphan(orphan_dict)
                orphans_list.append(orphan_dict)

        # Evaluate the complete merged packet once, after every late document is
        # attached. This also updates repeated CSV applicants without new PDFs.
        for app in staged_applicants.values():
            routed = self.gate.evaluate_applicant(app)
            app.status = routed.status.value
            if not self.storage.update_applicant_status(
                app_id=app.applicant_id,
                status=routed.status.value,
                documents=[d.to_metadata_dict() for d in app.documents],
                audit_action="MANIFEST_EVALUATED",
                audit_details={
                    "run_id": audit_run_id,
                    "missing_fields": list(routed.missing_fields),
                    "missing_documents": list(routed.missing_documents),
                    "error_count": len(routed.errors),
                    "total_documents": routed.total_documents,
                    "ready_for_review": routed.is_valid,
                },
            ):
                raise RuntimeError(f"Could not persist ingestion outcome for {app.applicant_id}")
            if routed.is_valid:
                affected_ids.append(app.applicant_id)

        self.affected_ids = affected_ids
        logger.info(
            "Pass 2 Complete: Processed %d documents across %d applicants (%d orphans, %d ready)",
            len(candidate_files),
            len(staged_applicants),
            len(orphans_list),
            len(affected_ids),
        )
        return list(staged_applicants.values()), orphans_list

    def ingest_batch(
        self,
        input_dir: Path,
        applicant_ids: Optional[Set[str]] = None,
        audit_run_id: Optional[str] = None,
    ) -> BatchIngestionResult:
        """Execute full two-pass batch ingestion on input_dir."""
        input_path = Path(input_dir)
        scoped_ids = (
            {extract_and_normalize_app_id(app_id) or app_id for app_id in applicant_ids}
            if applicant_ids is not None else None
        )
        try:
            csv_path, staged_applicants = self.pass_1_parse_and_stage_csv(input_path, scoped_ids)
        except FileNotFoundError:
            csv_path = None
            staged_applicants = {}

        apps, orphans = self.pass_2_traverse_and_link_documents(
            input_path, staged_applicants, scoped_ids, audit_run_id=audit_run_id
        )

        return BatchIngestionResult(
            applications=apps,
            orphans=orphans,
            total_processed=len(apps),
            csv_path=csv_path,
            affected_ids=list(self.affected_ids),
        )
