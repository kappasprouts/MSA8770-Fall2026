"""
test_summarizer_checks.py

Tests for the CODE-level controls in summarizing_agent.py.
No model, MinIO, or PostgreSQL needed:

    python -m pytest test_summarizer_checks.py -v
"""

import copy

import summarizing_agent as agent


TRANSCRIPT_P1 = "Official Academic Transcript Raleigh High School Cumulative unweighted GPA 3.86 Cumulative weighted GPA 4.68"
LETTER_P1 = "I have seen a thoughtful student who prepares carefully, responds constructively to feedback. Avery James School Counselor"

LOCATIONS = {
    ("transcript.pdf", 1): TRANSCRIPT_P1,
    ("recommendation_letter_1.pdf", 1): LETTER_P1,
}

ESSAY = (
    "The first afternoon I joined the environmental club I expected to complete "
    "a task and go home but instead I found a reason to ask better questions"
)

GUARDS = {
    "essay_shingles": agent.word_shingles(ESSAY),
    "restricted": ["Female", "Asian", "2008-11-21", "919-555-0100", "alex.bennett.001@example.com"],
}

POLICY_IDS = {"POL-FT-01", "POL-LOR-01", "POL-ESSAY-01", "POL-HUMAN-01"}


def academic():
    return {
        "document_facts": {
            "unweighted_gpa": 3.86, "weighted_gpa": 4.68, "class_rank": "Not reported",
            "sat_superscore": 1500, "act_superscore": None, "intended_major": "Studio Art, Illustration",
            "high_school": "Raleigh High School", "expected_graduation": "June 2026",
        },
        "ap_courses_on_transcript": [{"course": "AP World History", "grade_level": "11", "final_grade": "A"}],
        "ap_exam_scores": [{"course": "AP World History", "score": "3", "date": "May 2025"}],
        "summary": "Strong grades across four years.",
        "course_rigor": "Several AP courses in grades 11-12.",
        "performance_patterns": "Mostly A and A- grades.",
        "strengths": ["Consistent grades"],
        "concerns": [],
        "notes": [],
        "evidence": [{"document": "transcript.pdf", "page": 1, "quote": "Cumulative unweighted GPA 3.86"}],
    }


def validate(section, output):
    return agent.validate_section(section, output, LOCATIONS, POLICY_IDS, GUARDS)


# ------------------------------------------------------------
# [2] Withheld documents
# ------------------------------------------------------------

def test_personal_statement_and_common_app_withheld_supplement_sent():
    documents = [
        {"type": "transcript", "filename": "transcript.pdf", "object_key": "x"},
        {"type": "personal_statement", "filename": "personal_statement.pdf", "object_key": "x"},
        {"type": "common_app", "filename": "common_app_application.pdf", "object_key": "x"},
        {"type": "university_supplement", "filename": "university_supplement.pdf", "object_key": "x"},
        {"type": "other", "filename": "personal_essay_final.pdf", "object_key": "x"},  # mislabeled
    ]
    allowed, withheld = agent.split_documents(documents)
    assert [d["filename"] for d in allowed] == ["transcript.pdf", "university_supplement.pdf"]
    assert {agent.withhold_reason(d) for d in withheld} == {agent.ESSAY_REASON, agent.RESTRICTED_REASON}


def test_danny_ingestion_keys_are_understood():
    document = agent.normalize_document(
        {"doc_type": "personal_statement", "filename": "personal_statement.pdf", "minio_key": "APP_001/personal_statement.pdf"}
    )
    assert agent.withhold_reason(document) == agent.ESSAY_REASON
    assert document["object_key"] == "APP_001/personal_statement.pdf"


# ------------------------------------------------------------
# [3] Required documents and section routing
# ------------------------------------------------------------

def page(doc_type, filename, number=1):
    return {"document_type": doc_type, "filename": filename, "page_number": number, "text": "", "png_bytes": b""}


def test_missing_second_letter_blocks_model_call():
    pages = [page("transcript", "transcript.pdf"), page("recommendation", "recommendation_letter_1.pdf")]
    assert agent.missing_required_documents(pages) == ["recommendation (1 of 2)"]


def test_multi_page_document_counts_once():
    pages = [page("transcript", "transcript.pdf", 1), page("transcript", "transcript.pdf", 2),
             page("recommendation", "r1.pdf"), page("recommendation", "r2.pdf")]
    assert agent.missing_required_documents(pages) == []


def test_each_section_sees_only_its_own_documents():
    pages = [page("transcript", "transcript.pdf"), page("activities_and_awards", "activities_and_awards.pdf"),
             page("recommendation", "r1.pdf"), page("university_supplement", "university_supplement.pdf")]
    assert [p["filename"] for p in agent.section_pages(pages, "academic")] == ["transcript.pdf"]
    assert [p["filename"] for p in agent.section_pages(pages, "engagement")] == ["activities_and_awards.pdf"]
    assert [p["filename"] for p in agent.section_pages(pages, "supplement")] == ["university_supplement.pdf"]


# ------------------------------------------------------------
# [6] Citation checks (code only)
# ------------------------------------------------------------

def test_exact_quote_passes():
    assert agent.quote_on_page("Cumulative weighted GPA 4.68", TRANSCRIPT_P1)


def test_invented_number_fails():
    assert not agent.quote_on_page("Cumulative weighted GPA 4.86", TRANSCRIPT_P1)


def test_quote_from_another_page_fails():
    assert not agent.quote_on_page("prepares carefully, responds constructively", TRANSCRIPT_P1)


def test_good_section_passes():
    assert validate("academic", academic()) == []


def test_citation_to_page_not_provided_is_rejected():
    output = academic()
    output["evidence"][0]["page"] = 2
    assert any("not provided" in e for e in validate("academic", output))


def test_citation_to_withheld_document_is_rejected():
    output = academic()
    output["evidence"].append({"document": "personal_statement.pdf", "page": 1, "quote": "environmental club"})
    assert any("personal_statement.pdf" in e for e in validate("academic", output))


def test_paraphrased_quote_is_rejected():
    output = academic()
    output["evidence"][0]["quote"] = "The student achieved excellent marks overall"
    assert any("is not on transcript.pdf" in e for e in validate("academic", output))


def test_missing_key_is_rejected():
    output = academic()
    del output["notes"]
    assert validate("academic", output) == ["Missing key: notes"]


def test_empty_summary_is_rejected():
    output = academic()
    output["summary"] = " "
    assert any("'summary' is empty" in e for e in validate("academic", output))


# ------------------------------------------------------------
# [6] Policy IDs (RAG)
# ------------------------------------------------------------

def test_unretrieved_policy_id_is_rejected():
    output = {"policy_assessment": [
        {"policy_id": "POL-MADE-UP", "criterion": "x", "alignment": "aligned", "findings": "y", "evidence": []}
    ]}
    assert any("Unknown policy ID" in e for e in validate("policy", output))


def test_policy_alignment_is_not_a_decision():
    output = {"policy_assessment": [
        {"policy_id": "POL-LOR-01", "criterion": "Two letters", "alignment": "not_aligned",
         "findings": "Only one letter summarized.", "evidence": []}
    ]}
    assert validate("policy", output) == []


# ------------------------------------------------------------
# [6] No decisions, no restricted data, no personal statement
# ------------------------------------------------------------

def test_decision_language_is_rejected():
    for phrase in ["should be accepted", "We recommend admission.", "Deny.", "waitlisted", "admit this student"]:
        output = academic()
        output["summary"] = phrase
        assert any("decision language" in e for e in validate("academic", output)), phrase


def test_letter_wording_is_not_a_decision():
    output = academic()
    output["summary"] = "The counselor recommends the student with confidence."
    assert validate("academic", output) == []


def test_restricted_data_is_rejected():
    for value in ["female", "Asian", "919-555-0100"]:
        output = academic()
        output["summary"] = f"Applicant ({value}) has strong grades."
        assert any("Restricted applicant data" in e for e in validate("academic", output)), value


def test_personal_statement_text_is_rejected():
    output = academic()
    output["summary"] = ESSAY
    assert any("Personal statement text" in e for e in validate("academic", output))


def test_restricted_values_come_from_the_applicant_row():
    row = {"gender": "Female", "ethnicity": "Asian", "date_of_birth": None, "email_address": "a@b.co"}
    assert agent.restricted_values(row) == ["Female", "Asian", "a@b.co"]


# ------------------------------------------------------------
# [7] Dossier assembly (team schema)
# ------------------------------------------------------------

APPLICANT = {
    "app_id": "APP_001", "first_name": "Alex", "last_name": "Bennett", "name_of_hs": "Raleigh High School",
    "country": "USA", "region": "Southeast", "intended_major": "Studio Art, llustration",
    "admission_year": 2026, "admission_term": "F", "gender": "Female", "ethnicity": "Asian",
}


def sections():
    letter_evidence = [{"document": "recommendation_letter_1.pdf", "page": 1, "quote": "prepares carefully"}]
    return {
        "academic": academic(),
        "engagement": {"activities": [], "awards": [], "summary": "Clubs.", "leadership_service_employment": "",
                       "themes": [], "assessment": "", "evidence": [],
                       "notes": [{"category": "unclear", "note": "Hours column partly cut off."}]},
        "recommendation": {"recommenders": [], "summary": "Positive letters.", "common_themes": [],
                           "strengths_identified": [], "notes": [], "evidence": letter_evidence},
        "supplement": copy.deepcopy(agent.NO_SUPPLEMENT),
        "policy": {"policy_assessment": [{"policy_id": "POL-LOR-01", "criterion": "Two letters", "alignment": "aligned",
                                          "findings": "Two letters present.", "evidence": letter_evidence}]},
        "synthesis": {"strengths": [{"strength": "Consistent grades", "evidence": academic()["evidence"]}],
                      "holistic_assessment": "A consistent academic record and positive letters."},
    }


def test_dossier_has_every_team_schema_field():
    dossier = agent.build_dossier(APPLICANT, sections())
    assert set(dossier) == {
        "app_id", "applicant_demographics", "academic_profile", "engagement_profile",
        "recommendation_profile", "supplemental_essay_profile", "strengths",
        "review_notes", "policy_assessment", "holistic_assessment", "evidence_map",
    }


def test_demographics_never_include_restricted_fields():
    demographics = agent.build_dossier(APPLICANT, sections())["applicant_demographics"]
    assert "gender" not in demographics and "ethnicity" not in demographics
    assert demographics["region"] == "Southeast"


def test_review_notes_collect_section_notes():
    notes = agent.build_dossier(APPLICANT, sections())["review_notes"]
    assert {(n["section"], n["category"]) for n in notes} == {
        ("engagement", "unclear"), ("supplement", "missing_information")
    }
    assert all("notes" not in agent.build_dossier(APPLICANT, sections())[k]
               for k in ("academic_profile", "engagement_profile"))


def test_evidence_map_lists_every_citation():
    evidence_map = agent.build_dossier(APPLICANT, sections())["evidence_map"]
    # academic 1 + recommendation 1 + strengths 1 + policy 1
    assert len(evidence_map) == 4
    assert {e["section"] for e in evidence_map} == {
        "academic_profile", "recommendation_profile", "strengths", "policy_assessment"
    }
