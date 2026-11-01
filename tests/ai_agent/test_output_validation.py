"""Regression cases beyond the promoted integration contracts."""

import json
from unittest.mock import Mock

import pymupdf
import pytest

from ai_agent import summarizing_agent as agent
from ai_agent.output_validation import schema_errors
from test_input_handoff import schema_fixture


def page_pdf(lines):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        for index, line in enumerate(lines):
            page.insert_text((50, 50 + index * 22), line)
        return pdf.tobytes()


@pytest.mark.parametrize("change", [
    lambda out: out.update(final_decision="ACCEPT"),
    lambda out: out["document_facts"].update(sat_superscore=True),
    lambda out: out["document_facts"].update(unweighted_gpa=float("nan")),
    lambda out: out.update(ap_exam_scores=[{"course": "AP Biology", "score": 5, "date": "unknown"}]),
])
def test_nested_schema_and_nonfinite_numbers_are_rejected(change):
    output = schema_fixture(agent.SCHEMAS["academic"])
    change(output)
    assert schema_errors(agent.SCHEMAS["academic"], output)


def test_schema_feedback_does_not_echo_rejected_values():
    output = schema_fixture(agent.SCHEMAS["academic"])
    output["document_facts"]["sat_superscore"] = "private@example.test"
    errors = schema_errors(agent.SCHEMAS["academic"], output)
    assert errors and "private@example.test" not in " ".join(errors)


def test_privacy_checks_handle_newlines_before_structural_errors():
    errors = agent.validate_section("academic", {"document_facts": "608\n555\n0111"}, {}, set(),
        {"restricted": ["608-555-0111"], "essay_shingles": set()})
    assert errors == ["Restricted applicant data in output."]


@pytest.mark.parametrize("quote,value,passes", [
    ("Unweighted GPA 3.97", 3.97, True),
    ("Weighted GPA 4.40", 4.4, False),
    ("Unweighted GPA 3.97 Weighted GPA 4.40", 4.4, False),
])
def test_numeric_evidence_checks_metric_value_association(quote, value, passes):
    output = schema_fixture(agent.SCHEMAS["academic"])
    output["document_facts"]["unweighted_gpa"] = value
    output["evidence"] = [{"document": "grades.pdf", "page": 1, "quote": quote}]
    errors = agent.validate_section("academic", output, {("grades.pdf", 1): quote}, set(), {"restricted": [], "essay_shingles": set()})
    assert (not errors) == passes


def test_normalized_quotes_allow_layout_breaks_but_not_reordering():
    assert agent.quote_on_page("Unweighted GPA 3.97", "Unweighted\nGPA: 3.97")
    assert not agent.quote_on_page("GPA Unweighted 3.97", "Unweighted GPA: 3.97")
    assert not agent.quote_on_page("score 1530", "score 15300")


@pytest.mark.parametrize("text", ["ACCEPT", "Final decision: ACCEPT"])
def test_standalone_or_explicit_decisions_are_rejected(text):
    assert agent.validate_section("synthesis", {"strengths": [], "holistic_assessment": text}, {}, set(),
        {"restricted": [], "essay_shingles": set()})


def test_scanned_policy_evidence_requires_human_verification():
    entry = {"policy_id": "POL-001", "alignment": "aligned", "evidence_ids": ["E001"]}
    registry = {"E001": {"quote": "Relevant rigor evidence", "verification_status": "UNVERIFIED_IMAGE_SOURCE"}}
    assert agent.validate_policy_evidence_match(entry, registry)
    entry["alignment"] = "unclear"
    assert not agent.validate_policy_evidence_match(entry, registry)


def test_privacy_filters_cross_document_context_and_phone_formats():
    data = page_pdf(["Academic interest statement", "Contact (608) 555 0111", "international student on visa"])
    pages = agent.render_pdf(data, zoom=.2, document_type="university_supplement",
        restricted=["608-555-0111", "international student on visa"])
    assert "555" not in pages[0]["text"] and "on visa" not in pages[0]["text"]


def test_multiline_contact_redaction_preserves_next_known_field():
    pages = agent.render_pdf(page_pdf(["Applicant Information", "Mailing Address", "123 Test Road", "Unit 42", "Country", "USA"]),
        zoom=.2, document_type="application_form")
    assert "Unit 42" not in pages[0]["text"]
    assert "USA" in pages[0]["text"]


def test_opaque_application_page_stops_and_combined_supplement_essay_is_withheld():
    with pymupdf.open() as pdf:
        pdf.new_page()
        blank = pdf.tobytes()
    with pytest.raises(ValueError, match="human review"):
        agent.render_pdf(blank, zoom=.2, document_type="application_form")
    assert not agent.render_pdf(page_pdf(["Personal Statement", "private story"]), zoom=.2, document_type="university_supplement")


def test_retry_error_does_not_echo_restricted_content_to_model(monkeypatch):
    prompts = []
    def model(prompt, *args):
        prompts.append(prompt)
        return json.dumps({"strengths": [], "holistic_assessment": "Phone (608) 555 0111"}), {"seconds": 0, "output_tokens": 5}
    monkeypatch.setattr(agent, "call_model", model)
    _, errors, attempts = agent.run_section("synthesis", "Safe prompt", None, {}, set(),
        {"restricted": ["608-555-0111"], "essay_shingles": set()}, [])
    assert errors and attempts == 2
    assert all("608" not in prompt for prompt in prompts)


def test_complete_stream_is_required_and_response_closed(monkeypatch):
    response = Mock(status_code=200)
    response.iter_lines.return_value = [json.dumps({"message": {"content": '{}'}, "done": True, "done_reason": "stop"}).encode()]
    monkeypatch.setattr(agent.requests, "post", lambda *args, **kwargs: response)
    assert agent.call_model("test", {}, 20)[0] == '{}'
    response.close.assert_called_once()


def test_retry_hints_verified_matching_page_without_rewriting_citation(monkeypatch):
    prompts = []
    def model(prompt, *args):
        prompts.append(prompt)
        output = schema_fixture(agent.SCHEMAS["academic"])
        output["document_facts"]["unweighted_gpa"] = 3.97
        output["evidence"] = [{"document": "CommonApp.pdf", "page": 1 if len(prompts) == 1 else 2,
                               "quote": "Unweighted GPA 3.97"}]
        return json.dumps(output), {"seconds": 0, "output_tokens": 5}
    monkeypatch.setattr(agent, "call_model", model)
    output, errors, attempts = agent.run_section("academic", "Base prompt", [],
        {("CommonApp.pdf", 1): "Applicant information", ("CommonApp.pdf", 2): "Unweighted GPA 3.97"},
        set(), {"restricted": [], "essay_shingles": set()}, [])
    assert not errors and attempts == 2
    assert "Matching supplied location(s): CommonApp.pdf page 2" in prompts[1]
    assert output["evidence"][0]["page"] == 2
