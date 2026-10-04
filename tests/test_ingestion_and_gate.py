"""Unit and integration tests for Component 2 (Ingestion) & Component 3 (Validation Gate).

Verifies:
1. Pure ingestion & linking without OCR, DocumentParser, or PyMuPDF page-to-image/PNG rendering.
2. No image files (.png) generated or stored.
3. Lightweight Trust Boundary 1 perimeter hygiene: existence, 1KB-15MB size, b"%PDF-" magic bytes
   without opening or scanning document text/pages.
4. Deterministic 3-way routing:
   - VALID -> status: "READY_FOR_REVIEW" (application packet complete, ready for handoff)
   - INCOMPLETE -> status: "INCOMPLETE" (missing required files -> Applicant Packet Update)
   - ERROR -> status: "ERROR" (corrupted/missing magic bytes/size violation -> Human Review)
5. Hard stop enforcement: CLI runner halts before downstream summarizers/agents with exit code 0.
"""

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
)
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
            assert doc.minio_object_key == f"{app.applicant_id}/{doc.filename}"
            storage_dict = doc.to_storage_record_dict()
            assert storage_dict["minio_bucket"] == "applicant-documents"
            assert storage_dict["minio_object_key"] == f"{app.applicant_id}/{doc.filename}"


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

    # In pure ingestion, APP_008 has 0 perimeter hygiene errors
    assert len(app_008.trust_boundary_errors) == 0
    transcript_doc = next(d for d in app_008.documents if d.doc_type == "transcript")
    assert transcript_doc.exists is True
    assert transcript_doc.is_readable is True
    assert transcript_doc.error_message is None


def test_manifest_validation_gate_3_way_routing(batch_dir, config_file):
    """Verify deterministic 3-way routing across batch_01:
    - VALID -> status: 'READY_FOR_REVIEW' (9 applicants)
    - INCOMPLETE -> status: 'INCOMPLETE' (APP_010 missing transcript)
    - ERROR -> status: 'ERROR' (0 in clean batch_01)
    """
    ingestor = BatchIngestor(config_path=config_file)
    apps = ingestor.ingest_batch(batch_dir)

    gate = ManifestValidationGate(config_path=config_file)
    result = gate.evaluate_batch(apps)

    assert result.total_processed == 10
    assert result.total_valid == 9
    assert result.total_incomplete == 1
    assert result.total_error == 0

    # Verify APP_001 is VALID -> READY_FOR_REVIEW
    app_001 = next(a for a in result.routed_applicants if a.applicant_id == "APP_001")
    assert app_001.status == GateStatus.READY_FOR_REVIEW
    assert app_001.status == GateStatus.VALID
    assert app_001.status.value == "READY_FOR_REVIEW"
    assert app_001.routing_destination == GateRoutingDestination.READY_FOR_REVIEW.value
    assert app_001.is_valid is True

    # Verify APP_008 is VALID -> READY_FOR_REVIEW (no text scan false positive)
    app_008 = next(a for a in result.routed_applicants if a.applicant_id == "APP_008")
    assert app_008.status == GateStatus.READY_FOR_REVIEW
    assert app_008.routing_destination == GateRoutingDestination.READY_FOR_REVIEW.value
    assert app_008.is_valid is True

    # Verify APP_010 is INCOMPLETE -> Applicant Packet Update
    app_010 = next(a for a in result.routed_applicants if a.applicant_id == "APP_010")
    assert app_010.status == GateStatus.INCOMPLETE
    assert app_010.status.value == "INCOMPLETE"
    assert app_010.routing_destination == GateRoutingDestination.APPLICANT_PACKET_UPDATE.value
    assert app_010.is_valid is False
    assert "transcript" in app_010.missing_documents


def test_manifest_validation_gate_routes_error_queue(config_file):
    """Verify corrupted/magic-bytes/size violations route to ERROR -> Human Review."""
    gate = ManifestValidationGate(config_path=config_file)

    # Construct an application with a perimeter error
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


def test_hard_stop_enforcement_and_cli_exit_code(tmp_path):
    """Verify CLI runner halts execution with exit code 0 and prints hard stop notification."""
    report_file = tmp_path / "test_report.txt"
    cmd = [
        sys.executable,
        "run_ingestion_check.py",
        "--input-dir",
        "batch_01",
        "--output",
        str(report_file),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    assert proc.returncode == 0, f"CLI runner failed with return code {proc.returncode}:\n{proc.stderr}"
    stdout = proc.stdout
    assert "[HARD STOP] Ingestion and completeness check is complete." in stdout
    assert "[HARD STOP] Pipeline execution halted prior to the summarizing agent." in stdout
    assert report_file.exists()

    report_content = report_file.read_text(encoding="utf-8")
    assert "Total Applications Processed : 10" in report_content
    assert "Valid Applications (Ready)   : 9" in report_content
    assert "Incomplete Applications      : 1" in report_content
    assert "Error / Corrupted Packets    : 0" in report_content
    assert "PIPELINE HALT ENFORCEMENT" in report_content
    assert "Execution hard stop enforced immediately after Manifest Gate validation." in report_content


def test_no_downstream_agents_or_ocr_triggered(tmp_path):
    """Verify that neither ModelGateway, summarizers, nor DocumentParser are invoked during pipeline run."""
    report_file = tmp_path / "test_report.txt"

    with patch("gateway.client.ModelGateway", side_effect=RuntimeError("Downstream ModelGateway must NOT be called")), \
         patch("parsing.parser.DocumentParser", side_effect=RuntimeError("Downstream DocumentParser must NOT be called")):
        result = run_pipeline(
            input_dir="batch_01",
            config_file="config/policies.yaml",
            report_file=str(report_file),
        )

    assert result.total_processed == 10
    assert result.total_valid == 9
    assert result.total_incomplete == 1
    assert result.total_error == 0
