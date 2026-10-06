"""Unit tests for College Board (SAT/AP) and ACT delta test score ingestion.

Verifies:
1. Matching logic (case-insensitive email matching and DOB fallback).
2. SAT subscore parsing (typed integer columns for sat_math and sat_ebrw).
3. AP score parsing and duplicate prevention in ap_test_scores JSONB array.
4. ACT composite and section scores parsing.
5. Orphan test score staging in OrphanTestScore when unmatched.
6. Manifest Gate re-evaluation and promotion from INCOMPLETE to READY_FOR_REVIEW.
7. Append to affected_ids.json on status promotion.
8. Asynchronous ingestor methods.
9. Standalone CLI runner (run_score_ingest.py).
"""

import json
from pathlib import Path
import subprocess
import sys
import pytest

from ingestion.test_score_ingest import (
    ScoreIngestResult,
    TestScoreIngestor,
    re_evaluate_applicant,
)
from storage.models import Applicant, OrphanTestScore
from storage.storage_manager import StorageManager
from validation.manifest_gate import GateStatus, ManifestValidationGate


@pytest.fixture
def temp_affected_ids(tmp_path):
    """Temporary affected_ids.json seeded with existing IDs."""
    ids_file = tmp_path / "affected_ids.json"
    ids_file.write_text(json.dumps(["APP_001", "APP_002"]), encoding="utf-8")
    return ids_file


@pytest.fixture
def mock_storage():
    """In-memory dry-run StorageManager."""
    storage = StorageManager()
    storage.db_available = False
    storage.dry_run_applicants = {}
    storage.dry_run_orphans = []
    storage.dry_run_orphan_scores = []
    return storage


def test_match_by_email_case_insensitive(tmp_path, mock_storage):
    """Verify applicant matching by email is case-insensitive and ignores surrounding whitespace."""
    # Seed applicant
    app = Applicant(
        app_id="APP_101",
        first_name="Jordan",
        last_name="Lee",
        email_address="jordan.lee@example.com",
        date_of_birth="2008-04-12",
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    # Create College Board CSV with uppercase and spaced email
    cb_csv = tmp_path / "cb_scores.csv"
    cb_csv.write_text(
        "Email,Date_Of_Birth,SAT_Math,SAT_EBRW\n"
        "  JORDAN.LEE@EXAMPLE.COM  ,2008-04-12,740,710\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    result = ingestor.ingest_college_board(cb_csv)

    assert result.total_records == 1
    assert result.matched_count == 1
    assert result.orphan_count == 0
    assert "APP_101" in result.matched_app_ids

    updated = mock_storage.get_applicant("APP_101")
    assert updated.sat_math == 740
    assert updated.sat_ebrw == 710


def test_match_by_dob_fallback(tmp_path, mock_storage):
    """Verify applicant matching falls back to Date of Birth when email is absent or mismatched."""
    app = Applicant(
        app_id="APP_102",
        first_name="Taylor",
        last_name="Smith",
        email_address="tsmith_old@school.edu",
        date_of_birth="2007-09-25",
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    # Create ACT CSV without matching email, but with matching DOB (MM/DD/YYYY format)
    act_csv = tmp_path / "act_scores.csv"
    act_csv.write_text(
        "Student_Email,DOB,ACT_Composite,ACT_English,ACT_Math\n"
        "different_email@gmail.com,09/25/2007,33,35,32\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    result = ingestor.ingest_act(act_csv)

    assert result.total_records == 1
    assert result.matched_count == 1
    assert result.orphan_count == 0
    assert "APP_102" in result.matched_app_ids

    updated = mock_storage.get_applicant("APP_102")
    assert updated.act_composite == 33
    assert updated.act_english == 35
    assert updated.act_math == 32


def test_college_board_sat_subscores_typed_integer(tmp_path, mock_storage):
    """Verify College Board SAT Math and EBRW subscores are stored as typed integers."""
    app = Applicant(
        app_id="APP_103",
        first_name="Casey",
        last_name="Rivera",
        email_address="casey.r@example.com",
        date_of_birth="2008-02-14",
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    cb_csv = tmp_path / "cb_sat.csv"
    cb_csv.write_text(
        "email,sat_math,sat_ebrw\n"
        "casey.r@example.com,780,720\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    ingestor.ingest_college_board(cb_csv)

    updated = mock_storage.get_applicant("APP_103")
    assert isinstance(updated.sat_math, int)
    assert updated.sat_math == 780
    assert isinstance(updated.sat_ebrw, int)
    assert updated.sat_ebrw == 720
    assert updated.superscored_sat_score == 1500.0


def test_duplicate_ap_scores_prevention(tmp_path, mock_storage):
    """Verify AP scores are appended to ap_test_scores without duplicating existing subject/score pairs."""
    # Seed applicant with an existing AP score
    app = Applicant(
        app_id="APP_104",
        first_name="Sam",
        last_name="Kim",
        email_address="sam.kim@example.com",
        date_of_birth="2008-06-30",
        ap_test_scores=[{"subject": "AP Calculus BC", "score": 5}],
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    # College Board feed contains AP Calculus BC: 5 (duplicate) and AP Physics C: 4 (new)
    cb_csv = tmp_path / "cb_ap.csv"
    cb_csv.write_text(
        "Email,AP_1_Subject,AP_1_Score,AP_2_Subject,AP_2_Score\n"
        "sam.kim@example.com,AP Calculus BC,5,AP Physics C: Mechanics,4\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    ingestor.ingest_college_board(cb_csv)

    updated = mock_storage.get_applicant("APP_104")
    assert len(updated.ap_test_scores) == 2
    subjects = [item["subject"] for item in updated.ap_test_scores]
    assert subjects.count("AP Calculus BC") == 1
    assert "AP Physics C: Mechanics" in subjects

    # Re-ingest the exact same file again
    ingestor.ingest_college_board(cb_csv)
    updated_again = mock_storage.get_applicant("APP_104")
    assert len(updated_again.ap_test_scores) == 2, "Duplicate ingestion must not increase AP test score count"


def test_act_composite_and_section_scores(tmp_path, mock_storage):
    """Verify ACT composite and all section scores are parsed and updated."""
    app = Applicant(
        app_id="APP_105",
        first_name="Morgan",
        last_name="Davis",
        email_address="morgan.d@example.com",
        date_of_birth="2008-01-19",
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    act_csv = tmp_path / "act_full.csv"
    act_csv.write_text(
        "Email,Composite,English,Math,Reading,Science,Writing\n"
        "morgan.d@example.com,34,35,34,35,32,10\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    result = ingestor.ingest_act(act_csv)

    assert result.matched_count == 1
    updated = mock_storage.get_applicant("APP_105")
    assert isinstance(updated.act_composite, int)
    assert updated.act_composite == 34
    assert updated.act_english == 35
    assert updated.act_math == 34
    assert updated.act_reading == 35
    assert updated.act_science == 32
    assert updated.act_writing == 10


def test_orphan_test_score_staging_unmatched(tmp_path, mock_storage):
    """Verify unmatched test score records are staged in OrphanTestScore table."""
    unmatched_csv = tmp_path / "unmatched.csv"
    unmatched_csv.write_text(
        "Email,Date_Of_Birth,SAT_Math,SAT_EBRW\n"
        "unknown_student@future.edu,2009-12-01,710,690\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    result = ingestor.ingest_college_board(unmatched_csv)

    assert result.total_records == 1
    assert result.matched_count == 0
    assert result.orphan_count == 1
    assert "unknown_student@future.edu" in result.orphan_identifiers

    orphans = mock_storage.get_all_orphan_scores()
    assert len(orphans) == 1
    assert orphans[0].source == "COLLEGE_BOARD"
    assert orphans[0].identifier == "unknown_student@future.edu"
    assert "sat_math" in orphans[0].payload or "SAT_Math" in orphans[0].payload


def test_manifest_gate_re_evaluate_promotion(tmp_path, mock_storage, temp_affected_ids):
    """Verify applicant in INCOMPLETE status is promoted to READY_FOR_REVIEW upon receiving scores and added to affected_ids.json."""
    # Seed applicant with all required documents and metadata, but initially marked INCOMPLETE
    docs = [
        {"doc_type": "application_form", "filename": "app.pdf", "exists": True, "is_readable": True},
        {"doc_type": "transcript", "filename": "trans.pdf", "exists": True, "is_readable": True},
        {"doc_type": "personal_statement", "filename": "ps.pdf", "exists": True, "is_readable": True},
        {"doc_type": "recommendation_letter_1", "filename": "lor1.pdf", "exists": True, "is_readable": True},
        {"doc_type": "recommendation_letter_2", "filename": "lor2.pdf", "exists": True, "is_readable": True},
    ]

    app = Applicant(
        app_id="APP_200",
        first_name="Avery",
        last_name="Brooks",
        date_of_birth="2008-05-10",
        email_address="avery.b@example.com",
        name_of_hs="Riverview High",
        intended_major="Computer Science",
        admission_year=2026,
        admission_term="Fall",
        status="INCOMPLETE",
        routing_destination="Applicant Packet Update",
        documents=docs,
    )
    mock_storage.stage_applicant(app.to_dict())

    # Ingest SAT scores
    score_csv = tmp_path / "avery_scores.csv"
    score_csv.write_text(
        "Email,SAT_Math,SAT_EBRW\n"
        "avery.b@example.com,790,750\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(
        storage_manager=mock_storage,
        affected_ids_path=temp_affected_ids,
    )
    result = ingestor.ingest_college_board(score_csv)

    assert "APP_200" in result.matched_app_ids
    assert "APP_200" in result.promoted_app_ids

    # Check updated applicant status
    updated = mock_storage.get_applicant("APP_200")
    assert updated.status == "READY_FOR_REVIEW"
    assert updated.routing_destination == "READY_FOR_REVIEW"

    # Check affected_ids.json
    with open(temp_affected_ids, "r", encoding="utf-8") as f:
        affected_list = json.load(f)
    assert "APP_200" in affected_list
    assert "APP_001" in affected_list  # Original IDs preserved


@pytest.mark.asyncio
async def test_async_delta_ingestion(tmp_path, mock_storage):
    """Verify asynchronous ingest methods operate correctly with asyncio."""
    app = Applicant(
        app_id="APP_300",
        first_name="Riley",
        last_name="Chen",
        email_address="riley.chen@example.com",
        date_of_birth="2008-08-08",
        status="INCOMPLETE",
    )
    mock_storage.stage_applicant(app.to_dict())

    score_csv = tmp_path / "async_scores.csv"
    score_csv.write_text(
        "Email,SAT_Math,SAT_EBRW\n"
        "riley.chen@example.com,800,770\n",
        encoding="utf-8",
    )

    ingestor = TestScoreIngestor(storage_manager=mock_storage, affected_ids_path=tmp_path / "affected_ids.json")
    result = await ingestor.ingest_college_board_async(score_csv)

    assert result.matched_count == 1
    assert "APP_300" in result.matched_app_ids
    updated = mock_storage.get_applicant("APP_300")
    assert updated.sat_math == 800


def test_cli_runner_college_board_and_act(tmp_path, temp_affected_ids):
    """Verify run_score_ingest.py CLI execution works for both college_board and act feeds."""
    cli_path = Path("run_score_ingest.py").resolve()

    # College Board test CSV
    cb_csv = tmp_path / "cli_cb.csv"
    cb_csv.write_text(
        "Email,Date_Of_Birth,SAT_Math,SAT_EBRW\n"
        "orphan.cb@test.com,2008-03-01,700,680\n",
        encoding="utf-8",
    )

    cmd_cb = [
        sys.executable,
        str(cli_path),
        "--source",
        "college_board",
        "--file",
        str(cb_csv),
        "--affected-ids",
        str(temp_affected_ids),
    ]
    res_cb = subprocess.run(cmd_cb, capture_output=True, text=True)
    assert res_cb.returncode == 0, f"CLI error: {res_cb.stderr}"
    assert "DELTA TEST SCORE INGESTION SUMMARY" in res_cb.stdout
    assert "COLLEGE_BOARD" in res_cb.stdout

    # ACT test CSV
    act_csv = tmp_path / "cli_act.csv"
    act_csv.write_text(
        "Email,Composite,English,Math\n"
        "orphan.act@test.com,32,34,31\n",
        encoding="utf-8",
    )

    cmd_act = [
        sys.executable,
        str(cli_path),
        "--source",
        "act",
        "--file",
        str(act_csv),
        "--affected-ids",
        str(temp_affected_ids),
    ]
    res_act = subprocess.run(cmd_act, capture_output=True, text=True)
    assert res_act.returncode == 0, f"CLI error: {res_act.stderr}"
    assert "ACT" in res_act.stdout
