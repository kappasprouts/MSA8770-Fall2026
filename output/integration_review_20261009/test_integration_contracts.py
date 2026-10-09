"""Review probes for intended integration behavior; failures expose current gaps.

Run from the repository root:
  .venv/Scripts/python -m pytest output/integration_review_20261009/test_integration_contracts.py -v
No live services, applicant-record changes, or real model calls are required.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest

from ingestion.batch_ingest import BatchIngestor
from storage.storage_manager import StorageManager
from summarizing_agent import summarizing_agent as agent

ROOT = Path(__file__).resolve().parents[2]
GUARDS = {"restricted": [], "essay_shingles": set()}


def schema_value(schema):
    kind = schema.get("type")
    if isinstance(kind, list):
        return None if "null" in kind else schema_value({**schema, "type": kind[0]})
    if kind == "object":
        return {k: schema_value(v) for k, v in schema["properties"].items()}
    if kind == "array":
        return []
    if kind == "string":
        return schema.get("enum", ["Documented factual summary."])[0]
    return 0


def academic():
    return schema_value(agent.SCHEMAS["academic"])


def pdf_with_lines(lines):
    doc = pymupdf.open()
    page = doc.new_page()
    for index, line in enumerate(lines):
        page.insert_text((50, 50 + 22 * index), line)
    result = doc.tobytes()
    doc.close()
    return result


def test_agent_consumes_ingestion_handoff_in_repository_directory(tmp_path, monkeypatch):
    agent_dir = tmp_path / "summarizing_agent"
    agent_dir.mkdir()
    (tmp_path / "affected_ids.json").write_text(json.dumps(["APP_012", "APP_013"]))
    monkeypatch.setattr(agent, "ROOT", agent_dir)
    assert agent.load_affected_ids([]) == ["APP_012", "APP_013"]


@pytest.mark.parametrize("filename,section", [
    ("activities_and_awards.pdf", "engagement"),
    ("advanced_coursework_and_ap_scores.pdf", "academic"),
])
def test_ingested_document_types_reach_correct_model_section(filename, section):
    storage = StorageManager(database_url="sqlite:///:memory:", minio_endpoint="127.0.0.1:1")
    ingestor = BatchIngestor(storage_manager=storage)
    normalized = agent.normalize_document({"doc_type": ingestor.classify_document(filename), "filename": filename})
    pages = [{"document_type": normalized["type"], "filename": filename, "page_number": 1}]
    assert agent.section_pages(pages, section) == pages


def test_current_score_feed_values_reach_academic_prompt():
    applicant = {"app_id": "APP_012", "superscored_sat_score": 1599,
                 "superscored_act_score": 36, "ap_test_scores": [{"subject": "AP Biology", "score": 5}]}
    prompt = agent.build_image_prompt("academic", applicant, [])
    assert "1599" in prompt and "AP Biology" in prompt


def test_quote_verification_rejects_swapped_gpa_values():
    page = "Unweighted GPA 3.97\nWeighted GPA 4.40"
    assert not agent.quote_on_page("Unweighted GPA 4.40", page)


def test_academic_numeric_fact_requires_matching_evidence():
    output = academic()
    output["document_facts"]["sat_superscore"] = 1600
    output["evidence"] = [{"document": "scores.pdf", "page": 1, "quote": "SAT Score 1200"}]
    assert agent.validate_section("academic", output, {("scores.pdf", 1): "SAT Score 1200"}, set(), GUARDS)


def test_schema_validation_rejects_invalid_nested_types():
    output = academic()
    output["document_facts"] = "invalid instead of an object"
    assert agent.validate_section("academic", output, {}, set(), GUARDS)


def test_unknown_policy_alignment_is_rejected():
    output = {"policy_assessment": [{"policy_id": "POL-001", "criterion": "Rigor",
             "alignment": "definitely_admit", "findings": "Prepared.", "evidence_ids": []}]}
    assert agent.validate_section("policy", output, {}, {"POL-001"}, GUARDS)


def test_missing_optional_sat_can_remain_unclear_without_evidence():
    entry = {"policy_id": "POL-004", "criterion": "SAT", "alignment": "unclear",
             "findings": "No SAT score documented.", "evidence_ids": []}
    assert agent.validate_policy_evidence_match(entry, {}) == []


def test_unsupported_non_numeric_policy_is_not_accepted(monkeypatch):
    output = {"policy_assessment": [{"policy_id": "POL-001", "criterion": "Rigor",
              "alignment": "aligned", "findings": "Meets all course rigor criteria.", "evidence_ids": []}]}
    monkeypatch.setattr(agent, "call_model", lambda *args: (json.dumps(output), {"seconds": 0, "output_tokens": 20}))
    _, errors, _ = agent.run_section("policy", "probe", None, {}, {"POL-001"}, GUARDS, [], evidence_registry={})
    assert errors


@pytest.mark.parametrize("text", ["Admit this applicant.", "I recommend admitting the applicant."])
def test_admissions_recommendation_is_rejected(text):
    output = {"strengths": [], "holistic_assessment": text}
    assert agent.validate_section("synthesis", output, {}, set(), GUARDS)


def test_phone_number_is_in_restricted_values_from_ingestion_schema():
    assert "555-867-5309" in agent.restricted_values({"phone_number": "555-867-5309"})


def test_unrecognized_application_header_does_not_release_contact_data():
    data = pdf_with_lines(["Applicant Information", "Email Address", "private@example.test"])
    rendered = agent.render_pdf(data, zoom=0.2, document_type="application_form")
    assert all("private@example.test" not in page["text"] for page in rendered)


def test_multiline_hooks_are_fully_redacted():
    data = pdf_with_lines(["Education", "Hooks", "First-generation", "Legacy donor family"])
    rendered = agent.render_pdf(data, zoom=0.2, document_type="application_form")
    assert all("Legacy donor family" not in page["text"] for page in rendered)


def test_model_stream_requires_final_completion_marker(monkeypatch):
    response = Mock(status_code=200)
    response.iter_lines.return_value = [json.dumps({"message": {"content": '{"summary":"partial"}'}}).encode()]
    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError):
        agent.call_model("probe", {}, 100)


def test_retry_reports_invalid_summary_and_accepts_corrected_output(monkeypatch):
    invalid = academic()
    invalid["summary"] = ""
    valid = academic()
    prompts = []
    def model(prompt, *args):
        prompts.append(prompt)
        return json.dumps(invalid if len(prompts) == 1 else valid), {"seconds": 0, "output_tokens": 20}
    monkeypatch.setattr(agent, "call_model", model)
    _, errors, attempts = agent.run_section("academic", "probe", [], {}, set(), GUARDS, [])
    assert not errors and attempts == 2
    assert "'summary' is empty" in prompts[1]


def test_retry_stops_after_two_invalid_outputs(monkeypatch):
    invalid = academic()
    invalid["summary"] = ""
    calls = []
    monkeypatch.setattr(agent, "call_model", lambda *args: (json.dumps(invalid), {"seconds": 0, "output_tokens": 20}))
    _, errors, attempts = agent.run_section("academic", "probe", [], {}, set(), GUARDS, calls)
    assert errors and attempts == 2 and len(calls) == 2


def test_batch_012_commonapp_excludes_essay_hooks_and_contact_data():
    rendered = agent.render_pdf((ROOT / "batch_02/APP_012/CommonApp.pdf").read_bytes(), zoom=0.2,
                                document_type="application_form")
    assert [p["page_number"] for p in rendered] == [1, 2]
    text = "\n".join(p["text"] for p in rendered)
    assert "drew.young.012@example.com" not in text
    assert "international student on visa" not in text
    assert "The second version" not in text


@pytest.mark.parametrize("app_id", ["APP_013", "APP_016", "APP_020"])
def test_ready_batch_02_packets_with_absent_hooks_can_render(app_id):
    rendered = agent.render_pdf((ROOT / f"batch_02/{app_id}/CommonApp.pdf").read_bytes(), zoom=0.2,
                                document_type="application_form")
    assert [p["page_number"] for p in rendered] == [1, 2]


def test_standalone_personal_statement_is_withheld():
    document = agent.normalize_document({"doc_type": "personal_statement", "filename": "personal_statement.pdf"})
    assert agent.split_documents([document]) == ([], [document])


def test_image_only_citation_retains_unverified_status():
    output = academic()
    output["evidence"] = [{"document": "transcript.pdf", "page": 1, "quote": "Physics A"}]
    assert agent.validate_section("academic", output, {("transcript.pdf", 1): ""}, set(), GUARDS) == []
    assert output["evidence"][0]["verification_status"] == "UNVERIFIED_IMAGE_SOURCE"


def test_document_bucket_is_preserved_for_downstream_downloads():
    document = agent.normalize_document({"doc_type": "transcript", "filename": "transcript.pdf",
                "minio_key": "APP_012/transcript.pdf", "minio_bucket": "prior-batch-bucket"})
    assert document.get("minio_bucket") == "prior-batch-bucket"
