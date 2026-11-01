"""Document routing, recorded score provenance, and pre-inference hard stops."""

import copy
import hashlib
from datetime import datetime, timezone
import json
import os
from unittest.mock import Mock

import pymupdf
import pytest

from ai_agent import summarizing_agent as agent
from ai_agent.academic_inputs import current_test_scores


@pytest.mark.parametrize("kind,section", [
    ("activities_and_awards", "engagement"), ("activities", "engagement"),
    ("advanced_coursework_and_ap_scores", "academic"), ("advanced_coursework", "academic"),
    ("official_transcript", "academic"), ("recommendation_letter", "recommendation"),
])
def test_document_handoff_routes_to_section_and_retains_location(kind, section):
    document = agent.normalize_document({"doc_type": kind, "filename": "source.pdf",
        "minio_bucket": "archived", "minio_key": "APP_012/source.pdf", "sha256_checksum": "abc"})
    assert (document["minio_bucket"], document["object_key"], document["sha256"]) == ("archived", "APP_012/source.pdf", "abc")
    assert agent.section_pages([{"document_type": document["type"]}], section)


def test_actual_download_and_render_use_recorded_bucket():
    pdf = pymupdf.open()
    pdf.new_page().insert_text((50, 50), "AP Biology 5")
    response = Mock()
    response.read.return_value = pdf.tobytes()
    checksum = hashlib.sha256(response.read.return_value).hexdigest()
    pdf.close()
    client = Mock()
    client.get_object.return_value = response
    document = agent.normalize_document({"doc_type": "advanced_coursework_and_ap_scores", "filename": "ap.pdf",
        "minio_bucket": "old-bucket", "minio_key": "APP_012/ap.pdf", "sha256": checksum})
    pages, errors = agent.load_pages(client, [document])
    assert not errors
    client.get_object.assert_called_once_with("old-bucket", "APP_012/ap.pdf")
    assert pages[0]["minio_bucket"] == "old-bucket" and pages[0]["sha256"] == checksum
    assert agent.section_pages(pages, "academic") == pages
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    assert agent.normalize_document({"doc_type": "transcript"})["minio_bucket"] == agent.MINIO_BUCKET


def test_changed_object_bytes_are_withheld_before_rendering(monkeypatch):
    response = Mock(); response.read.return_value = b'changed source'
    client = Mock(); client.get_object.return_value = response
    monkeypatch.setattr(agent, "render_pdf", Mock(side_effect=AssertionError("Do not render changed bytes")))
    document = agent.normalize_document({"doc_type": "transcript", "filename": "transcript.pdf",
        "minio_key": "APP_012/transcript.pdf", "sha256": "a" * 64})
    pages, errors = agent.load_pages(client, [document])
    assert not pages and "registered checksum" in errors[0]["error"]
    response.close.assert_called_once(); response.release_conn.assert_called_once()


def test_current_scores_are_allowlisted_and_separate_from_pdf_evidence():
    applicant = {"app_id": "APP_012", "superscored_sat_score": 1599, "superscored_act_score": 36,
        "updated_at": datetime(2026, 10, 31, tzinfo=timezone.utc),
        "ap_test_scores": ["AP History", {"subject": "AP Biology", "score": 5, "email": "private@example.test"}],
        "email_address": "private@example.test", "hooks": ["private hook"]}
    original = copy.deepcopy(applicant)
    facts, errors = current_test_scores(applicant)
    assert not errors and applicant == original
    assert facts["scores"]["superscored_sat_score"]["source"]["field"] == "superscored_sat_score"
    assert facts["ap_courses"][0]["course"] == "AP History"
    assert facts["ap_exam_scores"][0]["score"] == 5
    prompt = agent.build_image_prompt("academic", applicant, [])
    assert "1599" in prompt and "AP Biology" in prompt and "not recorded at field level" in prompt
    assert "private@example.test" not in prompt and "private hook" not in prompt
    assert "never invent a PDF quote/page" in prompt
    assert "CURRENT DATABASE TEST SCORES" not in agent.build_image_prompt("engagement", applicant, [])


@pytest.mark.parametrize("field,value", [
    ("superscored_sat_score", 31), ("superscored_sat_score", True),
    ("sat_math", 801), ("superscored_act_score", 37), ("act_writing", 13),
    ("superscored_sat_score", "1530"),
    ("ap_test_scores", [{"subject": "AP Biology", "score": 6}]),
    ("ap_test_scores", [{"subject": "AP Biology", "score": True}]),
])
def test_invalid_recorded_scores_block_prompts_and_policy_comparisons(field, value):
    applicant = {"app_id": "APP_014", field: value}
    _, errors = current_test_scores(applicant)
    assert errors[0]["value"] == (value[0] if field == "ap_test_scores" else value)
    with pytest.raises(ValueError, match="correction required"):
        agent.build_image_prompt("academic", applicant, [])
    with pytest.raises(ValueError, match="correction required"):
        agent.evaluate_test_score_policies(applicant, [])


def test_missing_optional_scores_remain_unknown_and_essays_stay_withheld():
    facts, errors = current_test_scores({"app_id": "APP_012"})
    assert not errors
    assert all(item["value"] is None for item in facts["scores"].values())
    assert not facts["ap_exam_scores"]
    essay = agent.normalize_document({"doc_type": "personal_statement", "filename": "essay.pdf"})
    assert agent.split_documents([essay]) == ([], [essay])


def test_real_score_feed_update_reaches_academic_prompt(tmp_path):
    from ingestion.score_ingest import TestScoreIngestor
    from storage.storage_manager import StorageManager
    store = StorageManager(database_url=f"sqlite:///{tmp_path / 'feed.db'}", minio_endpoint="127.0.0.1:1")
    store.stage_applicant({"app_id": "APP_012", "email_address": "test@example.test", "superscored_sat_score": 1530})
    feed = tmp_path / "scores.csv"
    feed.write_text("email,sat_math,sat_ebrw,ap_subject,ap_score\ntest@example.test,800,799,AP Biology,5\n")
    TestScoreIngestor(storage_manager=store, affected_ids_path=tmp_path / "ready.json").ingest_college_board(feed)
    updated = store.get_applicant("APP_012")
    prompt = agent.build_image_prompt("academic", updated.to_dict(), [])
    assert '"value": 1599' in prompt and '"subject": "AP Biology"' in prompt
    assert "test@example.test" not in prompt
    store.engine.dispose()


@pytest.mark.parametrize("outcome,expected", [("AGENT_ERROR", 1), ("AI_VALIDATION_FAILED", 1), ("DOSSIER_READY", 0)])
def test_cli_reports_unsuccessful_batch(monkeypatch, outcome, expected):
    monkeypatch.setattr("sys.argv", ["summarizing_agent.py", "APP_014"])
    connection = Mock()
    monkeypatch.setattr(agent, "connect_postgres", lambda: connection)
    monkeypatch.setattr(agent, "connect_minio", lambda: None)
    monkeypatch.setattr(agent, "ensure_output_tables", Mock())
    monkeypatch.setattr(agent, "process_applicant", lambda *args: outcome)
    assert agent.main() == expected
    connection.close.assert_called_once()


def test_invalid_scores_stop_process_before_io_and_preserve_source(monkeypatch):
    applicant = {"app_id": "APP_014", "status": "READY_FOR_REVIEW", "superscored_sat_score": 31}
    original = copy.deepcopy(applicant)
    monkeypatch.setattr(agent, "get_applicant", lambda *args: applicant)
    save, audit = Mock(), Mock()
    monkeypatch.setattr(agent, "save_run", save)
    monkeypatch.setattr(agent, "write_audit", audit)
    monkeypatch.setattr(agent, "write_result_file", Mock())
    for name in ("load_pages", "retrieve_policies", "call_model", "save_dossier"):
        monkeypatch.setattr(agent, name, Mock(side_effect=AssertionError(f"Unexpected {name}")))
    assert agent.process_applicant(None, None, "APP_014") == "AGENT_ERROR"
    assert applicant == original
    run = save.call_args.args[1]
    assert run["attempts"] == 0 and run["validation"]["input_errors"][0]["value"] == 31
    assert run["validation"]["failed_sections"]["input"]
    assert audit.call_args.args[2] == "INPUT_VALIDATION_FAILED"


def schema_fixture(schema):
    kind = schema["type"]
    if isinstance(kind, list):
        return None
    if kind == "object":
        return {name: schema_fixture(value) for name, value in schema["properties"].items()}
    if kind == "array":
        return []
    if kind == "string":
        return schema.get("enum", ["Factual summary."])[0]
    return 0


def test_full_process_retains_current_scores_and_flags_pdf_conflict(monkeypatch):
    applicant = {"app_id": "APP_012", "status": "READY_FOR_REVIEW", "superscored_sat_score": 1599,
        "ap_test_scores": [{"subject": "AP Biology", "score": 5}], "documents": []}
    monkeypatch.setattr(agent, "get_applicant", lambda *args: applicant)
    monkeypatch.setattr(agent, "load_pages", lambda *args: ([{"filename": "transcript.pdf", "page_number": 1,
        "document_type": "transcript", "text": "SAT 1530", "png_bytes": b"image"}], []))
    monkeypatch.setattr(agent, "retrieve_policies", lambda *args: [])
    monkeypatch.setattr(agent, "write_audit", Mock())
    monkeypatch.setattr(agent, "write_result_file", Mock())
    save_run = Mock()
    stage = Mock(return_value={"id": "request-id", "candidate_hash": "version", "state": "REVIEW_PENDING"})
    monkeypatch.setattr(agent.review_checkpoint, "capture_input_snapshot", lambda *args: {})
    monkeypatch.setattr(agent.review_checkpoint, "existing_review", lambda *args: None)
    monkeypatch.setattr(agent, "stage_review_candidate", stage)
    monkeypatch.setattr(agent, "save_run", save_run)
    prompts = []
    def model(prompt, schema, *args):
        prompts.append(prompt)
        output = schema_fixture(schema)
        if "document_facts" in output:
            output["document_facts"]["sat_superscore"] = 1530
            output["evidence"] = [{"document": "transcript.pdf", "page": 1, "quote": "SAT 1530"}]
        return json.dumps(output), {"seconds": 0, "output_tokens": 10}
    monkeypatch.setattr(agent, "call_model", model)
    assert agent.process_applicant(None, None, "APP_012") == "REVIEW_PENDING"
    dossier = stage.call_args.args[2]
    assert dossier["academic_profile"]["document_facts"]["sat_superscore"] == 1530
    assert dossier["academic_profile"]["recorded_test_scores"]["scores"]["superscored_sat_score"]["value"] == 1599
    assert any("Source discrepancy" in note["note"] for note in dossier["review_notes"])
    assert "1599" in prompts[0] and "AP Biology" in prompts[0]
    assert "1599" in prompts[-1]  # synthesis sees server-attached current facts
    assert stage.call_args.args[3]["validation"]["recorded_test_scores"]


@pytest.mark.skipif(not os.getenv("POSTGRES_DB"), reason="Requires test PostgreSQL")
def test_invalid_input_persists_in_isolated_postgresql_receiver(monkeypatch, tmp_path):
    import psycopg2
    connection = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE applicants (app_id text PRIMARY KEY, status text, superscored_sat_score integer, officer_recommendation text, final_decision text)")
            cursor.execute("INSERT INTO applicants VALUES ('APP_014','READY_FOR_REVIEW',31,NULL,NULL)")
            cursor.execute("CREATE TEMP TABLE dossier_generation_runs (id BIGSERIAL PRIMARY KEY, app_id text,run_status text,model text,attempts integer,runtime_seconds numeric,documents_sent jsonb,documents_withheld jsonb,policies_retrieved jsonb,validation jsonb,failed_output jsonb)")
            cursor.execute("CREATE TEMP TABLE summary_audit_log (app_id text,event text,details jsonb)")
        connection.commit()
        monkeypatch.setattr(agent, "RESULTS_DIR", tmp_path)
        monkeypatch.setattr(agent, "call_model", Mock(side_effect=AssertionError("No inference allowed")))
        assert agent.process_applicant(connection, None, "APP_014") == "AGENT_ERROR"
        with connection.cursor() as cursor:
            cursor.execute("SELECT status,superscored_sat_score FROM pg_temp.applicants")
            assert cursor.fetchone() == ("ERROR", 31)
            cursor.execute("SELECT run_status,attempts,validation FROM pg_temp.dossier_generation_runs")
            status, attempts, validation = cursor.fetchone()
            assert status == "AGENT_ERROR" and attempts == 0
            assert validation["input_errors"][0]["value"] == 31
            cursor.execute("SELECT event FROM pg_temp.summary_audit_log")
            assert cursor.fetchone() == ("INPUT_VALIDATION_FAILED",)
    finally:
        connection.close()
