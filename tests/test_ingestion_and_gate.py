"""Unit and integration tests for Component 2 (Ingestion) & Component 3 (Validation Gate).

Verifies:
1. Pure ingestion & linking without OCR, DocumentParser, or PyMuPDF page-to-image/PNG rendering.
2. No image files (.png) generated or stored.
3. Lightweight Trust Boundary 1 perimeter hygiene: existence, 1KB-15MB size, b"%PDF-" magic bytes
   without opening or scanning document text/pages.
4. Deterministic 3-way routing:
   - VALID -> status: "READY_FOR_REVIEW" (application packet complete, ready for handoff)
   - AWAITING_MATERIALS -> missing required files -> Applicant Packet Update
   - INCOMPLETE -> missing required metadata fields -> Applicant Packet Update
   - ERROR -> status: "ERROR" (corrupted/missing magic bytes/size violation -> Human Review)
5. Hard stop enforcement: CLI runner halts before downstream summarizers/agents with exit code 0.
6. Schema mappings: explicit typed relational columns + JSONB variable-length arrays.
7. Two-Pass orphan document handling: saving to OrphanDocument and MinIO 'orphans/'.
8. affected_ids.json generation and export for downstream Summarizing Agent.
9. Two letters of recommendation (LOR) requirement enforcement.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from ingestion.batch_ingest import (
    BatchIngestor,
    IngestedApplication,
    IngestedDocument,
    PDF_MAGIC_BYTES,
    compute_sha256,
    extract_and_normalize_app_id,
)
from storage.models import Applicant, OrphanDocument
from storage.storage_manager import StorageManager, normalize_applicant_id
from validation.manifest_gate import (
    GateRoutingDestination,
    GateStatus,
    ManifestValidationGate,
)
from run_ingestion_check import run_pipeline


@pytest.fixture
def batch_dir():
    return Path("batch_01")


@pytest.fixture
def config_file():
    return Path("config/policies.yaml")


def _write_regression_batch(batch_path, app_id, first_name, document_names=()):
    """Create a small first-year batch with only perimeter-valid PDFs."""
    batch_path.mkdir()
    (batch_path / "applicant_data.csv").write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,"
        "Intended_Major,Admission_Year,Admission_Term,AP_Courses\n"
        f"{app_id},{first_name},Rostova,2008-03-15,elena.r@example.com,"
        "Northwest Academy,Physics,2026,Fall,AP Biology\n",
        encoding="utf-8",
    )
    if document_names:
        app_dir = batch_path / app_id
        app_dir.mkdir()
        for index, filename in enumerate(document_names):
            (app_dir / filename).write_bytes(
                PDF_MAGIC_BYTES + b"1.4\n" + bytes([65 + index]) * 2048
            )


def _run_regression_pipeline(tmp_path, batch_path, config_file, storage, run_name):
    return run_pipeline(
        input_dir=batch_path,
        config_file=config_file,
        report_file=tmp_path / f"{run_name}_report.txt",
        affected_ids_file=tmp_path / f"{run_name}_affected.json",
        storage_manager=storage,
    )


def test_malformed_csv_id_cannot_update_an_existing_applicant(tmp_path, config_file):
    """A substring resembling an ID must not be treated as a canonical CSV ID."""
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'applicants.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    storage.stage_applicant({"app_id": "APP_001", "first_name": "Original", "last_name": "Student"})
    batch = tmp_path / "invalid_id"
    batch.mkdir()
    (batch / "applicant_data.csv").write_text(
        "App_ID,First_Name\nXAPP001Z,Incorrect\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Invalid applicant ID in CSV"):
        _run_regression_pipeline(tmp_path, batch, config_file, storage, "invalid_id")

    assert storage.get_applicant("APP_001").first_name == "Original"


def test_batch_ingest_finds_all_applicants(batch_dir, config_file):
    """Verify batch ingestor correctly indexes all applicants in batch_01."""
    ingestor = BatchIngestor(config_path=config_file)
    apps = ingestor.ingest_batch(batch_dir)
    assert len(apps) == 10
    app_ids = [a.applicant_id for a in apps]
    assert "APP_001" in app_ids
    assert "APP_008" in app_ids
    assert "APP_010" in app_ids


def test_pure_ingestion_no_image_rendering_or_storage(batch_dir, config_file):
    """Verify no image files (.png/.jpg) are generated, and PyMuPDF/OCR are not imported."""
    # Ensure batch_ingest does not import fitz or OCR
    import ingestion.batch_ingest as bi_module
    assert not hasattr(bi_module, "fitz"), "PyMuPDF (fitz) must not be imported in pure batch ingestion"
    assert not hasattr(bi_module, "DocumentParser"), "DocumentParser must not be imported in pure batch ingestion"
    assert not hasattr(bi_module, "pytesseract"), "Tesseract must not be imported in pure batch ingestion"

    # Run ingestion
    ingestor = BatchIngestor(config_path=config_file)
    apps = ingestor.ingest_batch(batch_dir)

    # Verify no .png or image files exist or were created
    png_files = list(batch_dir.glob("**/*.png"))
    jpg_files = list(batch_dir.glob("**/*.jpg"))
    assert len(png_files) == 0, f"Found unexpected PNG files: {png_files}"
    assert len(jpg_files) == 0, f"Found unexpected JPG files: {jpg_files}"

    # Verify SHA-256 checksums and MinIO storage keys are populated
    for app in apps:
        for doc in app.documents:
            assert len(doc.sha256_checksum) == 64, f"Invalid SHA-256 checksum for {doc.filename}"
            assert doc.minio_key == f"{app.applicant_id}/{doc.filename}"
            meta_dict = doc.to_metadata_dict()
            assert meta_dict["minio_key"] == f"{app.applicant_id}/{doc.filename}"
            assert meta_dict["sha256"] == doc.sha256_checksum


def test_schema_mapping_scalar_and_jsonb_arrays(batch_dir, config_file):
    """Verify Pass 1 extracts 33-column flat file schema into typed relational fields
    and stores variable-length arrays (activities, awards, ap_test_scores, hooks) in JSONB.
    """
    storage = StorageManager()
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)
    _, staged = ingestor.pass_1_parse_and_stage_csv(batch_dir)

    app_001 = staged["APP_001"]
    data = app_001.to_applicant_dict()

    # Typed relational columns
    assert data["app_id"] == "APP_001"
    assert data["first_name"] == "Alex"
    assert data["last_name"] == "Bennett"
    assert data["date_of_birth"] == date(2008, 11, 21)
    assert data["unweighted_gpa"] == Decimal("3.860")
    assert data["weighted_gpa"] == Decimal("4.680")
    assert data["superscored_sat_score"] == 1500.0
    assert data["total_aps"] == 7.0
    assert data["admission_year"] == 2026
    assert data["admission_term"] in ("F", "Fall")

    # JSONB array fields
    assert isinstance(data["activities"], list)
    assert len(data["activities"]) <= 10
    assert "Varsity soccer player" in data["activities"]

    assert isinstance(data["awards"], list)
    assert len(data["awards"]) <= 5
    assert "School academic honor roll" in data["awards"]

    assert isinstance(data["ap_test_scores"], list)
    assert len(data["ap_test_scores"]) <= 12
    assert "AP World History" in data["ap_test_scores"]

    assert isinstance(data["hooks"], list)
    assert len(data["hooks"]) <= 5

    # Check APP_002 hooks
    app_002 = staged["APP_002"]
    data_002 = app_002.to_applicant_dict()
    assert "First-Gen" in data_002["hooks"]


def test_trust_boundary_1_perimeter_hygiene(tmp_path, config_file):
    """Verify lightweight Trust Boundary 1 perimeter hygiene:
    - file existence
    - file size (1 KB to 15 MB)
    - first 5 bytes check (b"%PDF-") without opening/scanning document text/pages.
    """
    ingestor = BatchIngestor(config_path=config_file)

    # 1. Non-existent file
    missing_file = tmp_path / "missing.pdf"
    exists, readable, mime, err = ingestor.verify_file_trust_boundary(missing_file, "APP_TEST")
    assert exists is False
    assert readable is False
    assert "does not exist" in err

    # 2. File below 1 KB
    small_file = tmp_path / "small.pdf"
    small_file.write_bytes(b"%PDF-short")
    exists, readable, mime, err = ingestor.verify_file_trust_boundary(small_file, "APP_TEST")
    assert exists is True
    assert readable is False
    assert "below minimum" in err

    # 3. File missing PDF magic bytes
    bad_magic = tmp_path / "bad_magic.pdf"
    bad_magic.write_bytes(b"NOTPD" + b"A" * 2000)
    exists, readable, mime, err = ingestor.verify_file_trust_boundary(bad_magic, "APP_TEST")
    assert exists is True
    assert readable is False
    assert "Invalid PDF magic bytes" in err

    # 4. Disallowed extension
    wrong_ext = tmp_path / "document.txt"
    wrong_ext.write_bytes(b"%PDF-" + b"B" * 2000)
    exists, readable, mime, err = ingestor.verify_file_trust_boundary(wrong_ext, "APP_TEST")
    assert exists is True
    assert readable is False
    assert "Disallowed extension" in err

    # 5. Valid PDF file (passes perimeter hygiene)
    valid_file = tmp_path / "valid.pdf"
    valid_file.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"X" * 2048)
    exists, readable, mime, err = ingestor.verify_file_trust_boundary(valid_file, "APP_TEST")
    assert exists is True
    assert readable is True
    assert mime == "application/pdf"
    assert err is None


def test_trust_boundary_1_does_not_scan_pages_app_008(batch_dir, config_file):
    """Verify that pure ingestion does NOT open or scan document text/pages.
    APP_008's transcript has valid header and size, so it must pass pure TB1 perimeter check.
    """
    ingestor = BatchIngestor(config_path=config_file)
    apps = ingestor.ingest_batch(batch_dir)
    app_008 = next(a for a in apps if a.applicant_id == "APP_008")

    assert len(app_008.trust_boundary_errors) == 0
    transcript_doc = next(d for d in app_008.documents if d.doc_type == "transcript")
    assert transcript_doc.exists is True
    assert transcript_doc.is_readable is True
    assert transcript_doc.error_message is None


def test_two_pass_orphan_document_handling(tmp_path, config_file):
    """Verify Pass 2 records unmatched files into the OrphanDocument table and MinIO 'orphans/'."""
    batch_dir = tmp_path / "orphan_test_batch"
    batch_dir.mkdir()

    # 1. Create a minimal CSV with only APP_001
    csv_file = batch_dir / "applicant_data.csv"
    csv_file.write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,Intended_Major,Admission_Year,Admission_Term\n"
        "APP_001,John,Doe,2007-01-01,john@example.com,City High,CS,2026,Fall\n",
        encoding="utf-8",
    )

    # 2. Valid matched document for APP_001
    app_001_dir = batch_dir / "APP_001"
    app_001_dir.mkdir()
    (app_001_dir / "transcript.pdf").write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"X" * 2000)

    # 3. Unmatched orphan document at root level (e.g. late LOR for non-existent APP_999)
    orphan_file = batch_dir / "APP_999_recommendation_letter.pdf"
    orphan_file.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"Y" * 2000)

    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'orphan_test_store.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)
    result = ingestor.ingest_batch(batch_dir)

    # Verify APP_001 is staged and has its document
    assert len(result.applications) == 1
    assert result.applications[0].applicant_id == "APP_001"
    assert len(result.applications[0].documents) == 1

    # Verify orphan document was recorded
    assert len(result.orphans) == 1
    orphan = result.orphans[0]
    assert orphan["filename"] == "APP_999_recommendation_letter.pdf"
    assert orphan["minio_key"].startswith("orphans/")
    assert orphan["minio_key"].endswith("/APP_999_recommendation_letter.pdf")
    assert orphan["detected_app_id"] == "APP_999"

    ingestor.ingest_batch(batch_dir)
    assert len(storage.get_all_orphans()) == 1


def test_manifest_validation_gate_routing(batch_dir, config_file):
    """Verify deterministic routing across batch_01:
    - VALID -> status: 'READY_FOR_REVIEW' (9 applicants)
    - AWAITING_MATERIALS -> status: 'AWAITING_MATERIALS' (APP_010 missing transcript)
    - ERROR -> status: 'ERROR' (0 in clean batch_01)
    """
    ingestor = BatchIngestor(config_path=config_file)
    result_ingest = ingestor.ingest_batch(batch_dir)

    gate = ManifestValidationGate(config_path=config_file)
    result = gate.evaluate_batch(result_ingest.applications)

    assert result.total_processed == 10
    assert result.total_valid == 9
    assert result.total_awaiting_materials == 1
    assert result.total_incomplete == 0
    assert result.total_error == 0

    # Verify affected_ids contains the 9 ready applicants
    assert len(result.affected_ids) == 9
    assert "APP_001" in result.affected_ids
    assert "APP_008" in result.affected_ids
    assert "APP_010" not in result.affected_ids

    # Verify APP_001 is VALID -> READY_FOR_REVIEW
    app_001 = next(a for a in result.routed_applicants if a.applicant_id == "APP_001")
    assert app_001.status == GateStatus.READY_FOR_REVIEW
    assert app_001.status == GateStatus.VALID
    assert app_001.status.value == "READY_FOR_REVIEW"
    assert app_001.routing_destination == GateRoutingDestination.READY_FOR_REVIEW.value
    assert app_001.is_valid is True

    # Verify APP_008 is VALID -> READY_FOR_REVIEW
    app_008 = next(a for a in result.routed_applicants if a.applicant_id == "APP_008")
    assert app_008.status == GateStatus.READY_FOR_REVIEW
    assert app_008.routing_destination == GateRoutingDestination.READY_FOR_REVIEW.value
    assert app_008.is_valid is True

    # Verify APP_010 is AWAITING_MATERIALS -> Applicant Packet Update
    app_010 = next(a for a in result.routed_applicants if a.applicant_id == "APP_010")
    assert app_010.status == GateStatus.AWAITING_MATERIALS
    assert app_010.status.value == "AWAITING_MATERIALS"
    assert app_010.routing_destination == GateRoutingDestination.APPLICANT_PACKET_UPDATE.value
    assert app_010.is_valid is False
    assert "transcript" in app_010.missing_documents


def test_manifest_gate_enforces_two_lors_requirement(config_file):
    """Verify that the manifest gate strictly requires 2 letters of recommendation."""
    gate = ManifestValidationGate(config_path=config_file)

    base_metadata = {
        "App_ID": "APP_LOR_TEST",
        "First_Name": "Sam",
        "Last_Name": "Taylor",
        "Date_Of_Birth": "2007-02-15",
        "Email_Address": "sam@example.com",
        "Name_of_HS": "West High",
        "Intended_Major": "Biology",
        "Admission_Year": "2026",
        "Admission_Term": "Fall",
    }

    doc_app_form = IngestedDocument(
        filename="application_form.pdf",
        file_path=Path("/tmp/app.pdf"),
        doc_type="application_form",
        file_size_bytes=5000,
        mime_type="application/pdf",
        sha256_checksum="a" * 64,
        applicant_id="APP_LOR_TEST",
    )
    doc_transcript = IngestedDocument(
        filename="transcript.pdf",
        file_path=Path("/tmp/trans.pdf"),
        doc_type="transcript",
        file_size_bytes=5000,
        mime_type="application/pdf",
        sha256_checksum="b" * 64,
        applicant_id="APP_LOR_TEST",
    )
    doc_essay = IngestedDocument(
        filename="personal_statement.pdf",
        file_path=Path("/tmp/essay.pdf"),
        doc_type="personal_statement",
        file_size_bytes=5000,
        mime_type="application/pdf",
        sha256_checksum="c" * 64,
        applicant_id="APP_LOR_TEST",
    )
    doc_lor_1 = IngestedDocument(
        filename="recommendation_letter_1.pdf",
        file_path=Path("/tmp/lor1.pdf"),
        doc_type="recommendation_letter_1",
        file_size_bytes=5000,
        mime_type="application/pdf",
        sha256_checksum="d" * 64,
        applicant_id="APP_LOR_TEST",
    )
    doc_lor_2 = IngestedDocument(
        filename="recommendation_letter_2.pdf",
        file_path=Path("/tmp/lor2.pdf"),
        doc_type="recommendation_letter_2",
        file_size_bytes=5000,
        mime_type="application/pdf",
        sha256_checksum="e" * 64,
        applicant_id="APP_LOR_TEST",
    )

    # 1. Packet with only 1 LOR -> Must await materials
    app_with_1_lor = IngestedApplication(
        applicant_id="APP_LOR_TEST",
        metadata=base_metadata,
        documents=[doc_app_form, doc_transcript, doc_essay, doc_lor_1],
    )
    routed_1 = gate.evaluate_applicant(app_with_1_lor)
    assert routed_1.status == GateStatus.AWAITING_MATERIALS
    assert "recommendation_letter_2" in routed_1.missing_documents

    # 2. Packet with 2 LORs -> Must be VALID / READY_FOR_REVIEW
    app_with_2_lors = IngestedApplication(
        applicant_id="APP_LOR_TEST",
        metadata=base_metadata,
        documents=[doc_app_form, doc_transcript, doc_essay, doc_lor_1, doc_lor_2],
    )
    routed_2 = gate.evaluate_applicant(app_with_2_lors)
    assert routed_2.status == GateStatus.READY_FOR_REVIEW
    assert routed_2.is_valid is True
    assert len(routed_2.missing_documents) == 0

    # Missing metadata alone remains INCOMPLETE.
    no_email = IngestedApplication(
        applicant_id="APP_LOR_TEST",
        metadata={**base_metadata, "Email_Address": ""},
        documents=[doc_app_form, doc_transcript, doc_essay, doc_lor_1, doc_lor_2],
    )
    routed_fields = gate.evaluate_applicant(no_email)
    assert routed_fields.status == GateStatus.INCOMPLETE
    assert routed_fields.missing_documents == []
    assert routed_fields.missing_fields == ["Email_Address"]
    assert routed_fields.routing_destination == "Applicant Packet Update"

    # When both are missing, required metadata takes priority while both
    # findings remain visible in the report/API result.
    no_email_or_second_letter = IngestedApplication(
        applicant_id="APP_LOR_TEST",
        metadata={**base_metadata, "Email_Address": ""},
        documents=[doc_app_form, doc_transcript, doc_essay, doc_lor_1],
    )
    routed_both = gate.evaluate_applicant(no_email_or_second_letter)
    assert routed_both.status == GateStatus.INCOMPLETE
    assert routed_both.missing_fields == ["Email_Address"]
    assert routed_both.missing_documents == ["recommendation_letter_2"]


def test_manifest_validation_gate_routes_error_queue(config_file):
    """Verify corrupted/magic-bytes/size violations route to ERROR -> Human Review."""
    gate = ManifestValidationGate(config_path=config_file)

    corrupted_doc = IngestedDocument(
        filename="corrupted_transcript.pdf",
        file_path=Path("/tmp/corrupted.pdf"),
        doc_type="transcript",
        file_size_bytes=500,  # Below 1 KB
        mime_type="application/octet-stream",
        sha256_checksum="abc",
        applicant_id="APP_ERR",
        exists=True,
        is_readable=False,
        error_message="Invalid PDF magic bytes b'NOTPD' in 'corrupted_transcript.pdf'",
    )
    bad_app = IngestedApplication(
        applicant_id="APP_ERR",
        metadata={
            "App_ID": "APP_ERR",
            "First_Name": "Jane",
            "Last_Name": "Doe",
            "Date_Of_Birth": "2005-01-01",
            "Email_Address": "jane@example.com",
            "Name_of_HS": "Test High",
            "Intended_Major": "CS",
            "Admission_Year": "2026",
            "Admission_Term": "Fall",
        },
        documents=[corrupted_doc],
        trust_boundary_errors=["Invalid PDF magic bytes b'NOTPD' in 'corrupted_transcript.pdf'"],
    )

    routed = gate.evaluate_applicant(bad_app)
    assert routed.status == GateStatus.ERROR
    assert routed.status.value == "ERROR"
    assert routed.routing_destination == GateRoutingDestination.HUMAN_REVIEW.value
    assert routed.is_valid is False
    assert any("Invalid PDF magic bytes" in err for err in routed.errors)


def test_hard_stop_enforcement_and_affected_ids_export(tmp_path):
    """Verify CLI runner halts execution with exit code 0, prints hard stop, and exports affected_ids.json."""
    report_file = tmp_path / "test_report.txt"
    affected_ids_file = tmp_path / "affected_ids.json"
    cmd = [
        sys.executable,
        "run_ingestion_check.py",
        "--input-dir",
        "batch_01",
        "--output",
        str(report_file),
        "--affected-ids",
        str(affected_ids_file),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    assert proc.returncode == 0, f"CLI runner failed with return code {proc.returncode}:\n{proc.stderr}"
    stdout = proc.stdout
    assert "[HARD STOP] Ingestion and completeness check is complete." in stdout
    assert "[HARD STOP] Pipeline execution halted prior to the summarizing agent." in stdout
    assert "Affected IDs (READY_FOR_REVIEW):" in stdout
    assert report_file.exists()
    assert affected_ids_file.exists()

    # Verify affected_ids.json content
    affected_data = json.loads(affected_ids_file.read_text(encoding="utf-8"))
    assert len(affected_data) == 9
    assert "APP_001" in affected_data
    assert "APP_009" in affected_data
    assert "APP_010" not in affected_data

    # Verify report content
    report_content = report_file.read_text(encoding="utf-8")
    assert "Total Applications Processed : 10" in report_content
    assert "Valid Applications (Ready)   : 9" in report_content
    assert "Awaiting Materials           : 1" in report_content
    assert "Incomplete Applications      : 0" in report_content
    assert "Error / Corrupted Packets    : 0" in report_content
    assert "PIPELINE HALT ENFORCEMENT & HANDOFF" in report_content


def test_no_downstream_agents_or_ocr_triggered(tmp_path):
    """Verify that neither ModelGateway, summarizers, nor DocumentParser are invoked during pipeline run."""
    report_file = tmp_path / "test_report.txt"
    affected_file = tmp_path / "test_affected.json"

    with patch("gateway.client.ModelGateway", side_effect=RuntimeError("Downstream ModelGateway must NOT be called")), \
         patch("parsing.parser.DocumentParser", side_effect=RuntimeError("Downstream DocumentParser must NOT be called")):
        result = run_pipeline(
            input_dir="batch_01",
            config_file="config/policies.yaml",
            report_file=str(report_file),
            affected_ids_file=str(affected_file),
        )

    assert result.total_processed == 10
    assert result.total_valid == 9
    assert result.total_awaiting_materials == 1
    assert result.total_incomplete == 0
    assert result.total_error == 0
    assert len(result.affected_ids) == 9


def test_case_2_db_lookup_late_arriving_document(tmp_path, config_file):
    """Verify Case 2: When a document's extracted app_id is NOT in staged_applicants from Pass 1,
    the ingestor performs a database lookup against PostgreSQL (Applicant table).
    If the applicant exists in the DB (from a prior night's batch):
    1. app_id is added to staged_applicants and affected_ids.
    2. Document metadata is attached to the applicant's documents JSONB array.
    3. Manifest gate re-evaluation is triggered for that applicant.
    If not in DB either, document is routed to orphans (Case 3).
    """
    storage = StorageManager()
    storage.db_available = False
    storage.dry_run_applicants = {}
    storage.dry_run_orphans = []

    # 1. Seed an applicant existing ONLY in the database from a prior night's batch (missing transcript)
    prior_docs = [
        {"doc_type": "application_form", "filename": "application_form.pdf", "exists": True, "is_readable": True},
        {"doc_type": "personal_statement", "filename": "personal_statement.pdf", "exists": True, "is_readable": True},
        {"doc_type": "recommendation_letter_1", "filename": "recommendation_letter_1.pdf", "exists": True, "is_readable": True},
        {"doc_type": "recommendation_letter_2", "filename": "recommendation_letter_2.pdf", "exists": True, "is_readable": True},
    ]
    prior_app = Applicant(
        app_id="APP_042",
        first_name="Elena",
        last_name="Rostova",
        date_of_birth="2008-03-15",
        email_address="elena.r@example.com",
        name_of_hs="Northwest Academy",
        intended_major="Physics",
        admission_year=2026,
        admission_term="Fall",
        status="AWAITING_MATERIALS",
        documents=prior_docs,
    )
    storage.stage_applicant(prior_app.to_dict())

    # 2. Create tonight's batch directory
    # CSV has ONLY APP_001 (APP_042 is NOT in the CSV)
    batch_dir = tmp_path / "delta_batch"
    batch_dir.mkdir()
    csv_file = batch_dir / "applicant_data.csv"
    csv_file.write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,Intended_Major,Admission_Year,Admission_Term\n"
        "APP_001,John,Doe,2007-01-01,john@example.com,City High,CS,2026,Fall\n",
        encoding="utf-8",
    )
    # APP_001 docs
    app_001_dir = batch_dir / "APP_001"
    app_001_dir.mkdir()
    (app_001_dir / "transcript.pdf").write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"A" * 2000)

    # Late-arriving transcript for APP_042 (existing in DB only)
    late_doc = batch_dir / "APP_042_transcript.pdf"
    late_doc.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"T" * 2000)

    # Truly unmapped document for APP_999 (not in CSV, not in DB -> Case 3)
    orphan_doc = batch_dir / "APP_999_portfolio.pdf"
    orphan_doc.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"O" * 2000)

    # 3. Run two-pass batch ingestion
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)
    result = ingestor.ingest_batch(batch_dir)

    # Verify APP_042 was added to staged_applicants / result.applications
    app_ids = [a.applicant_id for a in result.applications]
    assert "APP_042" in app_ids
    assert "APP_001" in app_ids

    # Verify APP_042 was added to affected_ids
    assert "APP_042" in result.affected_ids
    assert "APP_042" in ingestor.affected_ids

    # Verify late-arriving document was attached to APP_042's documents JSONB array
    db_updated = storage.get_applicant("APP_042")
    doc_filenames = [d["filename"] for d in db_updated.documents]
    assert "APP_042_transcript.pdf" in doc_filenames
    assert len(db_updated.documents) == 5  # 4 prior + 1 new

    # Verify manifest gate was re-evaluated and promoted APP_042 to READY_FOR_REVIEW
    assert db_updated.status == "READY_FOR_REVIEW"
    assert db_updated.routing_destination == "READY_FOR_REVIEW"

    # Verify APP_999 was routed to orphans (Case 3) and APP_042 was NOT
    orphan_app_ids = [o.get("detected_app_id") for o in result.orphans]
    assert "APP_999" in orphan_app_ids
    assert "APP_042" not in orphan_app_ids


def test_persistent_dry_run_multi_batch_late_arrival(tmp_path, config_file, batch_dir):
    """Verify persistent local dry-run state across multi-batch CLI runs:
    1. Run Batch 1 on batch_01 (ingesting APP_001..APP_010) using persistent SQLite store.
       APP_010 is missing its transcript and ends with status AWAITING_MATERIALS.
    2. In a separate CLI execution with a fresh StorageManager instance connected to the same store,
       run Pass 2 / late-arrival check on a delta batch containing APP010_transcript.pdf.
    3. Verify APP_010 is retrieved from the persistent store, promoted to READY_FOR_REVIEW,
       added to affected_ids.json, and NOT marked as an orphan.
    4. Verify an unmatched document (APP_999) is correctly routed to orphans.
    """
    store_file = tmp_path / ".test_persistent_store.db"
    report1 = tmp_path / "batch1_report.txt"
    affected1 = tmp_path / "batch1_affected.json"

    # Separate Run 1: Batch 1
    storage_run1 = StorageManager(sqlite_store_path=str(store_file))
    assert storage_run1.is_sqlite_fallback is True
    assert storage_run1.db_available is True

    result_1 = run_pipeline(
        input_dir=batch_dir,
        config_file=config_file,
        report_file=report1,
        affected_ids_file=affected1,
        storage_manager=storage_run1,
    )

    # In Batch 1, APP_010 is AWAITING_MATERIALS (missing transcript)
    assert result_1.total_processed == 10
    assert result_1.total_awaiting_materials == 1
    assert result_1.total_incomplete == 0
    assert "APP_010" not in result_1.affected_ids
    app_010_stored = storage_run1.get_applicant("APP_010")
    assert app_010_stored is not None
    assert app_010_stored.status == "AWAITING_MATERIALS"

    # Create delta batch directory with late-arriving transcript for APP_010 (testing flexible regex: APP010)
    delta_dir = tmp_path / "delta_batch_late"
    delta_dir.mkdir()
    late_transcript = delta_dir / "APP010_transcript.pdf"
    late_transcript.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"LATE_TRANSCRIPT" * 100)

    unmatched_doc = delta_dir / "APP_999_unmatched.pdf"
    unmatched_doc.write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"ORPHAN_CONTENT" * 100)

    # Separate Run 2: Completely fresh StorageManager instance simulating subsequent CLI run
    report2 = tmp_path / "batch2_report.txt"
    affected2 = tmp_path / "batch2_affected.json"
    storage_run2 = StorageManager(sqlite_store_path=str(store_file))
    assert storage_run2.is_sqlite_fallback is True

    result_2 = run_pipeline(
        input_dir=delta_dir,
        config_file=config_file,
        report_file=report2,
        affected_ids_file=affected2,
        storage_manager=storage_run2,
    )

    # Verify APP_010 was found from persistent SQLite store and promoted to READY_FOR_REVIEW
    assert "APP_010" in result_2.affected_ids
    with open(affected2, "r", encoding="utf-8") as f:
        affected_ids_disk = json.load(f)
    assert "APP_010" in affected_ids_disk

    # Verify APP_010 in storage has all 5 documents and is READY_FOR_REVIEW
    app_010_final = storage_run2.get_applicant("APP_010")
    assert app_010_final is not None
    assert app_010_final.status == "READY_FOR_REVIEW"
    assert app_010_final.routing_destination == "READY_FOR_REVIEW"
    doc_names = [d["filename"] for d in app_010_final.documents]
    assert "APP010_transcript.pdf" in doc_names
    assert len(app_010_final.documents) == 10  # 9 batch_01 docs + 1 late-arriving transcript

    # Verify APP_010 was NOT marked as an orphan, and APP_999 was
    orphan_ids = [o.detected_app_id for o in storage_run2.get_all_orphans()]
    assert "APP_010" not in orphan_ids
    assert "APP_999" in orphan_ids

    # Replaying the same document-only delta must not append a second transcript.
    storage_run3 = StorageManager(sqlite_store_path=str(store_file))
    replay_result = run_pipeline(
        input_dir=delta_dir,
        config_file=config_file,
        report_file=tmp_path / "batch3_report.txt",
        affected_ids_file=tmp_path / "batch3_affected.json",
        storage_manager=storage_run3,
    )
    replayed = storage_run3.get_applicant("APP_010")
    assert replayed.status == "READY_FOR_REVIEW"
    assert len(replayed.documents) == 10
    assert [d["filename"] for d in replayed.documents].count("APP010_transcript.pdf") == 1
    assert "APP_010" in replay_result.affected_ids


def test_repeated_csv_upserts_without_erasing_documents_or_score_feed(tmp_path, config_file):
    """A later CSV correction must retain earlier documents and feed-owned scores."""
    store_file = tmp_path / "repeat_store.db"
    original_batch = tmp_path / "original_batch"
    required_docs = (
        "application_form.pdf",
        "transcript.pdf",
        "personal_statement.pdf",
        "recommendation_letter_1.pdf",
        "recommendation_letter_2.pdf",
    )
    _write_regression_batch(original_batch, "APP_042", "Elena", required_docs)

    original_storage = StorageManager(
        database_url=f"sqlite:///{store_file}", minio_endpoint="127.0.0.1:1"
    )
    first_result = _run_regression_pipeline(
        tmp_path, original_batch, config_file, original_storage, "original"
    )
    assert first_result.affected_ids == ["APP_042"]
    assert len(original_storage.get_applicant("APP_042").documents) == 5

    scored_ap = {"subject": "AP Biology", "score": 5}
    original_storage.update_applicant_scores(
        "APP_042", sat_math=750, sat_ebrw=720, ap_test_scores=[scored_ap]
    )

    corrected_batch = tmp_path / "corrected_csv_only"
    _write_regression_batch(corrected_batch, "APP_042", "Ellie")
    later_storage = StorageManager(
        database_url=f"sqlite:///{store_file}", minio_endpoint="127.0.0.1:1"
    )
    repeat_result = _run_regression_pipeline(
        tmp_path, corrected_batch, config_file, later_storage, "corrected"
    )

    updated = later_storage.get_applicant("APP_042")
    assert updated.first_name == "Ellie"
    assert {doc["filename"] for doc in updated.documents} == set(required_docs)
    assert len(updated.documents) == 5
    assert updated.sat_math == 750
    assert updated.sat_ebrw == 720
    assert updated.superscored_sat_score == 1470
    assert scored_ap in updated.ap_test_scores
    assert updated.status == "READY_FOR_REVIEW"
    assert updated.routing_destination == "READY_FOR_REVIEW"
    assert repeat_result.affected_ids == ["APP_042"]

    # A sparse correction should update its supplied field without blanking the
    # required metadata that came from the original CSV.
    sparse_batch = tmp_path / "sparse_csv_only"
    sparse_batch.mkdir()
    (sparse_batch / "applicant_data.csv").write_text(
        "App_ID,First_Name\nAPP_042,Elle\n", encoding="utf-8"
    )
    sparse_result = _run_regression_pipeline(
        tmp_path, sparse_batch, config_file, later_storage, "sparse"
    )
    sparse_app = later_storage.get_applicant("APP_042")
    assert sparse_app.first_name == "Elle"
    assert sparse_app.last_name == "Rostova"
    assert len(sparse_app.documents) == 5
    assert sparse_app.sat_math == 750
    assert sparse_app.status == "READY_FOR_REVIEW"
    assert sparse_result.affected_ids == ["APP_042"]


def test_repeated_csv_id_and_late_document_promote_without_duplicates(tmp_path, config_file):
    """A late transcript joins the canonical prior row, even with a new CSV ID spelling."""
    store_file = tmp_path / "late_repeat_store.db"
    initial_batch = tmp_path / "initial_incomplete"
    _write_regression_batch(
        initial_batch,
        "APP_042",
        "Elena",
        (
            "application_form.pdf",
            "personal_statement.pdf",
            "recommendation_letter_1.pdf",
            "recommendation_letter_2.pdf",
        ),
    )
    initial_storage = StorageManager(
        database_url=f"sqlite:///{store_file}", minio_endpoint="127.0.0.1:1"
    )
    first_result = _run_regression_pipeline(
        tmp_path, initial_batch, config_file, initial_storage, "incomplete"
    )
    assert first_result.affected_ids == []
    assert initial_storage.get_applicant("APP_042").status == "AWAITING_MATERIALS"

    late_batch = tmp_path / "late_with_repeated_csv"
    _write_regression_batch(late_batch, "app42", "Ellie")
    (late_batch / "APP042_transcript.pdf").write_bytes(
        PDF_MAGIC_BYTES + b"1.4\n" + b"LATE" * 512
    )

    for run_name in ("late_first", "late_repeat"):
        later_storage = StorageManager(
            database_url=f"sqlite:///{store_file}", minio_endpoint="127.0.0.1:1"
        )
        result = _run_regression_pipeline(
            tmp_path, late_batch, config_file, later_storage, run_name
        )

        assert [app.app_id for app in later_storage.get_all_applicants()] == ["APP_042"]
        updated = later_storage.get_applicant("APP_042")
        assert updated.first_name == "Ellie"
        assert updated.status == "READY_FOR_REVIEW"
        assert updated.routing_destination == "READY_FOR_REVIEW"
        assert len(updated.documents) == 5
        assert len({doc["filename"] for doc in updated.documents}) == 5
        assert "APP042_transcript.pdf" in {doc["filename"] for doc in updated.documents}
        assert result.affected_ids == ["APP_042"]
        assert result.total_valid == 1
        assert later_storage.get_all_orphans() == []


def test_filename_id_conflict_does_not_link_to_another_applicant(tmp_path, config_file):
    """A file inside one applicant's folder cannot complete a different packet."""
    batch = tmp_path / "mismatched_document_batch"
    batch.mkdir()
    (batch / "applicant_data.csv").write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,"
        "Intended_Major,Admission_Year,Admission_Term\n"
        "APP_042,Elena,Rostova,2008-03-15,elena@example.com,Northwest Academy,Physics,2026,Fall\n"
        "APP_043,Jordan,Lee,2008-03-16,jordan@example.com,Northwest Academy,Physics,2026,Fall\n",
        encoding="utf-8",
    )
    for app_id in ("APP_042", "APP_043"):
        folder = batch / app_id
        folder.mkdir()
        for filename in (
            "application_form.pdf",
            "personal_statement.pdf",
            "recommendation_letter_1.pdf",
            "recommendation_letter_2.pdf",
        ):
            (folder / filename).write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"X" * 2048)

    # The folder and explicit filename IDs conflict. Neither applicant supplied
    # an ordinary transcript in this batch.
    (batch / "APP_042" / "APP_043_transcript.pdf").write_bytes(
        PDF_MAGIC_BYTES + b"1.4\n" + b"T" * 2048
    )
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'mismatch.db'}", minio_endpoint="127.0.0.1:1"
    )
    result = BatchIngestor(config_path=config_file, storage_manager=storage).ingest_batch(batch)

    folder_app = storage.get_applicant("APP_042")
    filename_app = storage.get_applicant("APP_043")
    assert folder_app.status == "ERROR"
    assert filename_app.status == "AWAITING_MATERIALS"
    assert "APP_043_transcript.pdf" not in {d["filename"] for d in filename_app.documents}
    assert result.affected_ids == []


def test_duplicate_recommendation_content_cannot_satisfy_two_letter_rule(tmp_path, config_file):
    """Two filenames with the same recommendation bytes count as one letter."""
    batch = tmp_path / "duplicate_letters_batch"
    _write_regression_batch(batch, "APP_042", "Elena")
    folder = batch / "APP_042"
    folder.mkdir()
    for filename, marker in (
        ("application_form.pdf", b"A"),
        ("transcript.pdf", b"T"),
        ("personal_statement.pdf", b"P"),
    ):
        (folder / filename).write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + marker * 2048)
    repeated_letter = PDF_MAGIC_BYTES + b"1.4\n" + b"L" * 2048
    (folder / "recommendation_letter_1.pdf").write_bytes(repeated_letter)
    (folder / "recommendation_letter_2.pdf").write_bytes(repeated_letter)

    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'duplicate_letters.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    result = BatchIngestor(config_path=config_file, storage_manager=storage).ingest_batch(batch)

    assert storage.get_applicant("APP_042").status == "AWAITING_MATERIALS"
    assert result.affected_ids == []


def test_document_only_subfolder_batch_never_uses_workspace_csv(tmp_path, config_file):
    """A delta subfolder carries only its documents, with no CSV from another path."""
    initial = tmp_path / "initial_document_batch"
    _write_regression_batch(
        initial,
        "APP_042",
        "Elena",
        (
            "application_form.pdf",
            "personal_statement.pdf",
            "recommendation_letter_1.pdf",
            "recommendation_letter_2.pdf",
        ),
    )
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'document_only.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)
    ingestor.ingest_batch(initial)
    assert storage.get_applicant("APP_042").status == "AWAITING_MATERIALS"

    delta = tmp_path / "document_only_delta"
    delta.mkdir()
    folder = delta / "APP_042"
    folder.mkdir()
    (folder / "transcript.pdf").write_bytes(PDF_MAGIC_BYTES + b"1.4\n" + b"T" * 2048)
    result = ingestor.ingest_batch(delta)

    assert result.csv_path is None
    assert result.affected_ids == ["APP_042"]
    updated = storage.get_applicant("APP_042")
    assert updated.first_name == "Elena"
    assert updated.status == "READY_FOR_REVIEW"
    assert len(updated.documents) == 5


def test_blank_cells_in_repeated_csv_preserve_existing_metadata(tmp_path, config_file):
    """Blank cells in a repeated row are omissions, not requests to clear fields."""
    initial = tmp_path / "initial_full_metadata"
    _write_regression_batch(
        initial,
        "APP_042",
        "Elena",
        (
            "application_form.pdf",
            "transcript.pdf",
            "personal_statement.pdf",
            "recommendation_letter_1.pdf",
            "recommendation_letter_2.pdf",
        ),
    )
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'blank_repeat.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)
    ingestor.ingest_batch(initial)
    assert storage.get_applicant("APP_042").status == "READY_FOR_REVIEW"

    correction = tmp_path / "correction_with_empty_cells"
    correction.mkdir()
    (correction / "applicant_data.csv").write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,"
        "Intended_Major,Admission_Year,Admission_Term,AP_Courses\n"
        "APP_042,Ellie,,,,,,,,\n",
        encoding="utf-8",
    )
    result = ingestor.ingest_batch(correction)

    updated = storage.get_applicant("APP_042")
    assert updated.first_name == "Ellie"
    assert updated.last_name == "Rostova"
    assert updated.email_address == "elena.r@example.com"
    assert updated.name_of_hs == "Northwest Academy"
    assert updated.admission_year == 2026
    assert updated.admission_term == "Fall"
    assert updated.ap_test_scores == ["AP Biology"]
    assert len(updated.documents) == 5
    assert updated.status == "READY_FOR_REVIEW"
    assert result.affected_ids == ["APP_042"]


def test_orphan_database_write_failure_is_not_silently_cached(tmp_path, monkeypatch):
    """A failed durable orphan insert must surface instead of reporting a dry-run success."""
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'orphan_failure.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    original_add = storage.SessionLocal.class_.add

    def fail_orphan_add(session, instance, *args, **kwargs):
        if isinstance(instance, OrphanDocument):
            raise RuntimeError("simulated orphan insert failure")
        return original_add(session, instance, *args, **kwargs)

    monkeypatch.setattr(storage.SessionLocal.class_, "add", fail_orphan_add)
    with pytest.raises(RuntimeError, match="simulated orphan insert failure"):
        storage.save_orphan({
            "filename": "APP_999_transcript.pdf",
            "file_path": str(tmp_path / "APP_999_transcript.pdf"),
            "minio_key": "orphans/APP_999_transcript.pdf",
            "detected_app_id": "APP_999",
            "sha256": "a" * 64,
            "file_size_bytes": 2048,
        })

    assert storage.get_all_orphans() == []
    assert storage.dry_run_orphans == []


def test_document_stat_failure_routes_to_error(tmp_path, config_file, monkeypatch):
    """An unreadable file stat is a gate error, not an unhandled Pass 2 exception."""
    batch_path = tmp_path / "stat_failure_batch"
    _write_regression_batch(batch_path, "APP_042", "Elena", ("application_form.pdf",))
    affected_file = tmp_path / "stat_failure_affected.json"
    target_doc = batch_path / "APP_042" / "application_form.pdf"
    original_stat = Path.stat
    original_exists = Path.exists
    original_is_file = Path.is_file

    def failing_stat(path, *args, **kwargs):
        if path == target_doc:
            raise OSError("simulated stat failure")
        return original_stat(path, *args, **kwargs)

    def existing_file(path):
        return True if path == target_doc else original_exists(path)

    def candidate_file(path):
        return True if path == target_doc else original_is_file(path)

    monkeypatch.setattr(Path, "stat", failing_stat)
    monkeypatch.setattr(Path, "exists", existing_file)
    monkeypatch.setattr(Path, "is_file", candidate_file)
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'stat_failure.db'}",
        minio_endpoint="127.0.0.1:1",
    )

    result = run_pipeline(
        input_dir=batch_path,
        config_file=config_file,
        report_file=tmp_path / "stat_failure_report.txt",
        affected_ids_file=affected_file,
        storage_manager=storage,
    )

    assert result.total_error == 1
    assert result.routed_applicants[0].status == GateStatus.ERROR
    assert result.routed_applicants[0].routing_destination == "Human Review"
    assert result.affected_ids == []
    assert json.loads(affected_file.read_text(encoding="utf-8")) == []
    stored = storage.get_applicant("APP_042")
    assert stored.status == "ERROR"
    assert stored.routing_destination == "Human Review"
    assert stored.documents[0]["is_readable"] is False
    assert "simulated stat failure" in stored.documents[0]["error_message"]


def test_csv_replay_requires_historical_minio_objects_for_handoff(tmp_path, config_file):
    """A packet cannot be exported when its stored documents have no MinIO objects."""
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'missing_objects.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    required_docs = (
        "application_form.pdf",
        "transcript.pdf",
        "personal_statement.pdf",
        "recommendation_letter_1.pdf",
        "recommendation_letter_2.pdf",
    )
    storage.stage_applicant({
        "app_id": "APP_042",
        "first_name": "Elena",
        "last_name": "Rostova",
        "date_of_birth": "2008-03-15",
        "email_address": "elena.r@example.com",
        "name_of_hs": "Northwest Academy",
        "intended_major": "Physics",
        "admission_year": 2026,
        "admission_term": "Fall",
        "status": "READY_FOR_REVIEW",
        "documents": [
            {
                "filename": filename,
                "doc_type": filename.removesuffix(".pdf"),
                "minio_key": f"APP_042/{filename}",
                "minio_bucket": "admissions-raw-docs",
                "sha256": f"{index:064x}",
                "file_size": 2048,
                "is_readable": True,
            }
            for index, filename in enumerate(required_docs, start=1)
        ],
    })

    class MissingObjectClient:
        def __init__(self):
            self.lookups = []

        def stat_object(self, bucket, key):
            self.lookups.append((bucket, key))
            raise FileNotFoundError(f"missing MinIO object: {key}")

    fake_minio = MissingObjectClient()
    storage.minio_available = True
    storage.minio_client = fake_minio
    replay_batch = tmp_path / "csv_only_replay"
    _write_regression_batch(replay_batch, "APP_042", "Ellie")
    affected_file = tmp_path / "should_not_export.json"

    with pytest.raises(RuntimeError):
        run_pipeline(
            input_dir=replay_batch,
            config_file=config_file,
            report_file=tmp_path / "missing_objects_report.txt",
            affected_ids_file=affected_file,
            storage_manager=storage,
            require_object_storage=True,
        )

    assert fake_minio.lookups
    assert not affected_file.exists()
    updated = storage.get_applicant("APP_042")
    assert updated.status == "ERROR"
    assert updated.routing_destination == "Human Review"


def test_extract_and_normalize_app_id_robustness():
    """Verify that extract_and_normalize_app_id flexibly handles various applicant ID formats."""
    assert extract_and_normalize_app_id("APP_001") == "APP_001"
    assert extract_and_normalize_app_id("APP001") == "APP_001"
    assert extract_and_normalize_app_id("app_001") == "APP_001"
    assert extract_and_normalize_app_id("APP-001") == "APP_001"
    assert extract_and_normalize_app_id("app-001") == "APP_001"
    assert extract_and_normalize_app_id("APP 001") == "APP_001"
    assert extract_and_normalize_app_id("app10") == "APP_010"
    assert extract_and_normalize_app_id("APP010_transcript.pdf") == "APP_010"
    assert extract_and_normalize_app_id("APP-042-essay.pdf") == "APP_042"
    assert extract_and_normalize_app_id("app_010_transcript.pdf") == "APP_010"
    assert extract_and_normalize_app_id("transcript_APP010.pdf") == "APP_010"
    assert extract_and_normalize_app_id("transcript.pdf") is None
    assert extract_and_normalize_app_id("") is None
    assert extract_and_normalize_app_id(None) is None


def test_storage_manager_format_tolerance_and_clear(tmp_path):
    """Verify StorageManager get_applicant format tolerance and clear_local_store."""
    db_file = tmp_path / "format_test.db"
    storage = StorageManager(sqlite_store_path=str(db_file))
    storage.stage_applicant({
        "app_id": "APP_005",
        "first_name": "Taylor",
        "last_name": "Swift",
    })

    # Test flexible lookup
    assert storage.get_applicant("APP_005") is not None
    assert storage.get_applicant("APP005") is not None
    assert storage.get_applicant("app_005") is not None
    assert storage.get_applicant("APP-005") is not None
    assert storage.get_applicant("app-005") is not None
    assert storage.get_applicant("app5") is not None

    # Test clear_local_store
    storage.clear_local_store()
    assert storage.get_applicant("APP_005") is None


def test_failed_object_upload_stops_batch_before_handoff(tmp_path, batch_dir, config_file):
    """A live MinIO failure must not be reported as a successful upload."""
    class FailingMinio:
        def fput_object(self, **kwargs):
            raise OSError("simulated storage outage")

    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'upload_failure.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    storage.minio_available = True
    storage.minio_client = FailingMinio()
    ingestor = BatchIngestor(config_path=config_file, storage_manager=storage)

    with pytest.raises(RuntimeError, match="MinIO upload failed"):
        ingestor.ingest_batch(batch_dir)


def test_strict_handoff_rejects_minio_dry_run(tmp_path, batch_dir, config_file):
    """The summary-agent handoff requires actual object storage when requested."""
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'strict_store.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    affected_file = tmp_path / "affected_ids.json"
    with pytest.raises(RuntimeError, match="MinIO is unavailable"):
        run_pipeline(
            input_dir=batch_dir,
            config_file=config_file,
            report_file=tmp_path / "report.txt",
            affected_ids_file=affected_file,
            storage_manager=storage,
            require_object_storage=True,
        )
    assert not affected_file.exists()
