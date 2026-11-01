"""
summarizing_agent.py

EAOS - Summarizing Agent (RAG + VLM) → applicant dossier

Starts from test_summarizing_agent.py (PDF pages → PNG images → ONE
vision-language model) and adds the two steps it listed as "not yet":
policy retrieval (RAG) and saving the dossier to PostgreSQL.

The model only SUMMARIZES. Code controls every step, withholds
documents, checks the output, and saves the result. The admissions
officer makes every decision.

Pipeline (per applicant):

[1] CODE   Load applicant: PostgreSQL record (status COMPLETE) + Documents JSONB
[2] CODE   Withhold personal statement (POL-ESSAY-01) and Common App copy
           (restricted demographic/contact data)
[3] CODE   MinIO PDFs → PyMuPDF → PNG page images (memory only)
           transcript or a recommendation letter missing → HUMAN REVIEW
[4] RAG    nomic-embed-text + pgvector → relevant policy text from riverview_admissions_policy.txt
[5] MODEL  Qwen3-VL 8B Instruct, one call per dossier section:
           5a academic        transcript, test scores, AP record, application form
           5b engagement      activities & awards
           5c recommendation  recommendation letters
           5d supplement      university supplement
           5e policy (RAG)    retrieved policies + results of 5a-5d (text only)
           5f synthesis       results of 5a-5e (text only): strengths + holistic
[6] CODE   Validate each section: schema, citations point to pages sent,
           cited quotes appear on the cited page (PDF text, code only),
           retrieved policy IDs only, no decision wording, no restricted
           data, no personal-statement text → retry section once → else
           HUMAN REVIEW
[7] CODE   Assemble applicant_dossier (team schema) + evidence_map
[8] CODE   Save applicant_dossier, dossier_generation_runs,
           summary_audit_log, results/<APP_ID>_dossier.json
HARD STOP: the admissions officer reviews and decides.

Run (after the setup scripts in setup/):
    python summarizing_agent.py APP_001
    python summarizing_agent.py APP_001 --force   # summarize again
"""

import argparse
import base64
import json
import hashlib
import os
import re
import time
import sys
from pathlib import Path

import psycopg2
import pymupdf
import requests
from minio import Minio
from psycopg2.extras import Json, RealDictCursor

from dotenv import load_dotenv

# Support the documented direct-script command as well as module imports.
try:
    from .academic_inputs import current_test_scores
    from .output_validation import schema_errors, quote_matches, academic_fact_errors
    from .privacy import redact_fields, redact_known_values, restricted_pattern
    from . import review_checkpoint, generation_recovery
except ImportError:
    from academic_inputs import current_test_scores
    from output_validation import schema_errors, quote_matches, academic_fact_errors
    from privacy import redact_fields, redact_known_values, restricted_pattern
    import review_checkpoint
    import generation_recovery

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT.parent / "output/ai_agent"

# PostgreSQL
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "riverview_admissions")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

# MinIO
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "admissions-raw-docs")

# Ollama
OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", "http://localhost:11434/api/chat")
OLLAMA_EMBED_URL = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")

# Instruct variant: answers directly. The plain "qwen3-vl:8b" tag is the
# THINKING variant; it reasoned for thousands of hidden tokens and never
# finished a dossier in testing.
VLM_MODEL = os.getenv("VLM_MODEL", "qwen3-vl:8b-instruct")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# 1.5x ≈ 108 DPI: dense transcript tables stay readable; ~1,100 tokens/page.
RENDER_ZOOM = float(os.getenv("RENDER_ZOOM", "1.5"))

# One context size for every call, so the model is loaded only once.
NUM_CTX = int(os.getenv("VLM_NUM_CTX", "16384"))
VLM_TIMEOUT_SECONDS = int(os.getenv("VLM_TIMEOUT_SECONDS", "900"))

# A section that fails validation is retried once, then human review.
MAX_ATTEMPTS = 2


# ============================================================
# DOCUMENT RULES (ENFORCED IN CODE)
# ============================================================

ESSAY_REASON = "POL-ESSAY-01 personal statement (humans only)"
RESTRICTED_REASON = "restricted demographic/contact data"

# Never sent to the model.
WITHHELD_TYPES = {
    "personal_statement": ESSAY_REASON,
    "common_app": RESTRICTED_REASON,
}
WITHHELD_FILENAME_WORDS = {
    "personal_statement": ESSAY_REASON,
    "personal_essay": ESSAY_REASON,
    "common_app": RESTRICTED_REASON,
}

# Which documents each image section reads.
SECTION_DOCUMENT_TYPES = {
    "academic": ["application_form", "transcript", "standardized_test_score", "advanced_coursework"],
    "engagement": ["application_form", "activities_and_awards"],
    "recommendation": ["recommendation"],
    "supplement": ["university_supplement"],
}

# Applicant fields whose values must never appear in the output.
RESTRICTED_FIELDS = [
    "gender", "ethnicity", "date_of_birth",
    "mailing_address", "primary_phone_number", "phone_number", "email_address",
]

# ============================================================
# RAG SETTINGS
# ============================================================

POLICY_QUERIES = [
    "academic rigor AP IB dual enrollment GPA class rank",
    "standardized testing SAT ACT test optional academic index",
    "extracurricular activities awards leadership intellectual curiosity",
    "teacher recommendations counselor evaluations academic performance",
    "holistic academic review institutional contribution",
]

POLICIES_PER_QUERY = 3

INTERNATIONAL_QUERY = "international applicant English proficiency and credential evaluation"

# Never retrieved for now (all applicants are first-year).
INTERNATIONAL_POLICIES = []
TRANSFER_POLICIES = []

# Always given to the model so it knows its limits.
ALWAYS_INCLUDED_POLICIES = []

# Admission-decision wording the model must never produce.
DECISION_PATTERNS = [
    r"^\s*(?:accept|admit|reject|deny|decline|waitlist)(?:ed)?[.!]?\s*$",
    r"\b(?:final\s+)?(?:decision|recommendation)\s*(?:is\s*|:|=)\s*(?:accept|admit|reject|deny|decline|waitlist)\b",
    r"\badmit\s+(?:this|the)\s+(?:applicant|candidate|student)\b",
    r"\brecommend\s+(?:admitting|accepting|rejecting|denying|waitlisting)\b",
    r"\b(?:applicant|candidate|student|they|he|she)\s+(?:should|must|will|would)\s+be\s+admitted\b",
    r"\brecommend(?:ed)?\s+(?:the\s+)?(?:applicant|candidate|student)\s+for\s+admission\b",
    r"\badmission decision\b",
    r"\bden(y|ied)\b",
    r"\breject(ed|ion)?\b",
    r"\bwait-?list(ed)?\b",
    r"\bshould be accepted\b",
    r"\brecommend(ed)? (for )?(admission|acceptance)\b",
]

HUMAN_ONLY_POLICIES = [
    "POL-016",
    "POL-017",
    "POL-018",
    "POL-019",
    "POL-020",
    "POL-021",
]

# ============================================================
# OUTPUT SCHEMAS (one per model call)
# ============================================================

STRING_LIST = {"type": "array", "items": {"type": "string"}}

EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "document": {"type": "string"},
            "page": {"type": "integer", "minimum": 1},
            "quote": {"type": "string", "minLength": 1},
        },
        "required": ["document", "page", "quote"],
        "additionalProperties": False,
    },
}

NOTES = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["unclear", "unreadable", "missing_information", "other"]},
            "note": {"type": "string"},
        },
        "required": ["category", "note"],
        "additionalProperties": False,
    },
}

def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


SCHEMAS = {
    "academic": object_schema({
        "document_facts": object_schema({
            "unweighted_gpa": {"type": ["number", "null"]},
            "weighted_gpa": {"type": ["number", "null"]},
            "class_rank": {"type": ["string", "null"]},
            "sat_superscore": {"type": ["integer", "null"], "minimum": 400, "maximum": 1600},
            "act_superscore": {"type": ["integer", "null"], "minimum": 1, "maximum": 36},
            "intended_major": {"type": ["string", "null"]},
            "high_school": {"type": ["string", "null"]},
            "expected_graduation": {"type": ["string", "null"]},
        }),
        "ap_courses_on_transcript": {
            "type": "array",
            "items": object_schema({
                "course": {"type": "string"},
                "grade_level": {"type": "string"},
                "final_grade": {"type": "string"},
            }),
        },
        "ap_exam_scores": {
            "type": "array",
            "items": object_schema({
                "course": {"type": "string"},
                "score": {"type": "string"},
                "date": {"type": "string"},
            }),
        },
        "summary": {"type": "string"},
        "course_rigor": {"type": "string"},
        "performance_patterns": {"type": "string"},
        "strengths": STRING_LIST,
        "concerns": STRING_LIST,
        "notes": NOTES,
        "evidence": EVIDENCE,
    }),
    "engagement": object_schema({
        "activities": {
            "type": "array",
            "items": object_schema({
                "activity": {"type": "string"},
                "role_and_description": {"type": "string"},
                "years": {"type": "string"},
                "hours_per_week": {"type": "string"},
            }),
        },
        "awards": STRING_LIST,
        "summary": {"type": "string"},
        "leadership_service_employment": {"type": "string"},
        "themes": STRING_LIST,
        "assessment": {"type": "string"},
        "notes": NOTES,
        "evidence": EVIDENCE,
    }),
    "recommendation": object_schema({
        "recommenders": {
            "type": "array",
            "items": object_schema({
                "name": {"type": "string"},
                "role": {"type": "string"},
                "document": {"type": "string"},
                "relationship": {"type": "string"},
                "key_observations": STRING_LIST,
            }),
        },
        "summary": {"type": "string"},
        "common_themes": STRING_LIST,
        "strengths_identified": STRING_LIST,
        "notes": NOTES,
        "evidence": EVIDENCE,
    }),
    "supplement": object_schema({
        "responses": {
            "type": "array",
            "items": object_schema({
                "prompt": {"type": "string"},
                "summary": {"type": "string"},
            }),
        },
        "summary": {"type": "string"},
        "major_themes": STRING_LIST,
        "notes": NOTES,
        "evidence": EVIDENCE,
    }),
    "policy": object_schema({
        "policy_assessment": {
            "type": "array",
            "items": object_schema({
                "policy_id": {"type": "string"},
                "criterion": {"type": "string"},
                "alignment": {"type": "string", "enum": ["aligned", "not_aligned", "unclear", "not_applicable"]},
                "findings": {"type": "string"},
                "evidence_ids": STRING_LIST,
            }),
        },
    }),
    "synthesis": object_schema({
        "strengths": {
            "type": "array",
            "items": object_schema({
                "strength": {"type": "string"},
                "evidence": EVIDENCE,
            }),
        },
        "holistic_assessment": {"type": "string"},
    }),
}

# Narrative text that must not be empty, per section.
REQUIRED_TEXT = {
    "academic": ["summary"],
    "engagement": ["summary"],
    "recommendation": ["summary"],
    "supplement": ["summary"],
    "policy": [],
    "synthesis": ["holistic_assessment"],
}

# Output cap per call; also stops a looping answer.
NUM_PREDICT = {
    "academic": 3500,
    "engagement": 3000,
    "recommendation": 2500,
    "supplement": 1500,
    "policy": 3000,
    "synthesis": 2000,
}


# ============================================================
# CONNECTIONS AND TABLES
# ============================================================

def connect_postgres():

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def connect_minio():

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

    if not client.bucket_exists(MINIO_BUCKET):
        raise RuntimeError(
            f"MinIO bucket '{MINIO_BUCKET}' does not exist. Run ingestion."
        )

    return client


def ensure_output_tables(connection):

    with connection.cursor() as cursor:

        # Team schema (applicant_dossier table data.png).
        # Only successfully validated dossiers are stored here.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS applicant_dossier (
                app_id                      VARCHAR(64) PRIMARY KEY
                                            REFERENCES applicants (App_ID),
                applicant_demographics      JSONB NOT NULL,
                academic_profile            JSONB NOT NULL,
                engagement_profile          JSONB NOT NULL,
                recommendation_profile      JSONB NOT NULL,
                supplemental_essay_profile  JSONB NOT NULL,
                strengths                   JSONB,
                review_notes                JSONB,
                policy_assessment           JSONB NOT NULL,
                holistic_assessment         TEXT NOT NULL,
                evidence_map                JSONB,
                generated_at                TIMESTAMPTZ NOT NULL,
                updated_at                  TIMESTAMPTZ NOT NULL
            );
            """
        )

        # Every run, including failures that cannot fill the dossier.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dossier_generation_runs (
                id                  BIGSERIAL PRIMARY KEY,
                app_id              VARCHAR(64) NOT NULL,
                run_status          VARCHAR(40) NOT NULL,
                model               VARCHAR(60),
                attempts            INTEGER,
                runtime_seconds     NUMERIC(8,1),
                documents_sent      JSONB,
                documents_withheld  JSONB,
                policies_retrieved  JSONB,
                validation          JSONB,
                failed_output       JSONB,
                created_at          TIMESTAMPTZ DEFAULT now()
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_audit_log (
                id          BIGSERIAL PRIMARY KEY,
                app_id      VARCHAR(64),
                event       VARCHAR(40) NOT NULL,
                details     JSONB,
                created_at  TIMESTAMPTZ DEFAULT now()
            );
            """
        )

    connection.commit()
    review_checkpoint.ensure_review_schema(connection)


def write_audit(connection, app_id, event, details=None):

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO summary_audit_log (app_id, event, details) VALUES (%s, %s, %s);",
            (app_id, event, Json(details or {}))
        )

    connection.commit()


# ============================================================
# [1] LOAD APPLICANT
# ============================================================

def get_applicant(connection, app_id):

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT * FROM applicants WHERE app_id = %s;",
            (app_id,)
        )
        return cursor.fetchone()


def normalize_document(document):
    """Normalize ingestion document types for the summarizer."""

    doc_type = str(document.get("type") or document.get("doc_type") or "").lower().strip()
    doc_type = {
        "recommendation_letter_1": "recommendation", "recommendation_letter_2": "recommendation",
        "recommendation_letter": "recommendation", "official_transcript": "transcript",
        "advanced_coursework_and_ap_scores": "advanced_coursework", "ap_scores": "advanced_coursework",
        "activities": "activities_and_awards", "awards": "activities_and_awards",
    }.get(doc_type, doc_type)

    return {
        "type": doc_type,
        "filename": document.get("filename", ""),
        "object_key": document.get("object_key") or document.get("minio_key") or "",
        "minio_bucket": document.get("minio_bucket") or document.get("bucket") or MINIO_BUCKET,
        "sha256": document.get("sha256") or document.get("sha256_checksum"),
    }


# ============================================================
# [2] WITHHELD DOCUMENTS
# ============================================================

def withhold_reason(document):

    document_type = document["type"].lower()
    filename = document["filename"].lower()

    if document_type == "application_form" and filename == "commonapp.pdf":
        return None

    if document_type in WITHHELD_TYPES:
        return WITHHELD_TYPES[document_type]

    for word, reason in WITHHELD_FILENAME_WORDS.items():
        if word in filename:
            return reason

    return None


def split_documents(documents):

    allowed = [d for d in documents if withhold_reason(d) is None]
    withheld = [d for d in documents if withhold_reason(d) is not None]
    return allowed, withheld


# ============================================================
# [3] PAGES: MINIO → PNG (MEMORY ONLY)
# ============================================================

def download_pdf(minio_client, object_key, bucket=None):

    response = None

    try:
        response = minio_client.get_object(bucket or MINIO_BUCKET, object_key)
        return response.read()

    finally:
        if response is not None:
            response.close()
            response.release_conn()

ESSAY_HEADINGS = (
    "personal essay",
    "personal statement",
    "application essay",
)

def is_essay_page(text):
    """Identify a standalone essay section in the CommonApp PDF."""
    lines = [line.strip().lower() for line in text.splitlines()]

    return any(
        line in ESSAY_HEADINGS
        for line in lines
    )

RESTRICTED_LABELS = (
    "Date Of Birth",
    "Mailing Address",
    "Primary Phone Number",
    "Email Address",
    "Gender",
    "Ethnicity",
)

def redact_commonapp_page(page):
    return redact_fields(page)


def redact_hooks(page):
    return redact_fields(page, {"hooks"})


def render_pdf(pdf_bytes, zoom=RENDER_ZOOM, document_type=None, restricted=None):
    rendered_pages = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for index, page in enumerate(document):
            original_text = page.get_text()
            if document_type is not None and is_essay_page(original_text):
                continue
            if document_type == "application_form":
                if not original_text.strip():
                    raise ValueError("Application page has no verifiable text layer; human review required")
            found = redact_fields(page)
            if document_type == "application_form" and "applicant information" in original_text.casefold() and not found:
                raise ValueError("Cannot establish restricted field boundaries; human review required")
            redact_known_values(page, restricted)
            rendered_pages.append({
                "page_number": index + 1,
                "png_bytes": page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png"),
                "text": page.get_text(),
            })
    return rendered_pages


def load_pages(minio_client, documents, restricted=None):

    """Download and render documents. A failure is recorded, never silently skipped."""

    pages, problems = [], []

    for document in documents:
        try:

            pdf_bytes = download_pdf(minio_client, document["object_key"], document.get("minio_bucket"))
            if document.get("sha256") and hashlib.sha256(pdf_bytes).hexdigest() != str(document["sha256"]).lower():
                raise ValueError("Stored source bytes differ from the registered checksum; reconcile before generation")
            rendered = render_pdf(
                pdf_bytes,
                document_type=document["type"], restricted=restricted,
                )

            if not rendered:
                raise ValueError("PDF has no pages")
        except Exception as error:
            problems.append({"filename": document["filename"], "type": document["type"], "error": str(error)})
            print(f"    ✗ {document['filename']}: {error}")
            continue

        print(f"    ✓ {document['filename']:<40} {len(rendered)} page(s)")

        for page in rendered:
            pages.append(
                {
                    "document_type": document["type"],
                    "filename": document["filename"],
                    "page_number": page["page_number"],
                    "png_bytes": page["png_bytes"],
                    "text": page["text"],
                    "object_key": document["object_key"],
                    "minio_bucket": document.get("minio_bucket") or MINIO_BUCKET,
                    "sha256": document.get("sha256"),
                }
            )

    return pages, problems

def section_pages(pages, section):

    return [p for p in pages if p["document_type"] in SECTION_DOCUMENT_TYPES[section]]


def page_map(pages):

    return [
        {"image_number": n, "document_type": p["document_type"], "filename": p["filename"], "page_number": p["page_number"]}
        for n, p in enumerate(pages, start=1)
    ]


# ============================================================
# [4] RAG: RETRIEVE POLICIES FROM PGVECTOR
# ============================================================

def embed_queries(queries):

    response = requests.post(
        OLLAMA_EMBED_URL,
        json={"model": EMBED_MODEL, "input": ["search_query: " + q for q in queries]},
        timeout=120
    )

    if response.status_code != 200:
        raise RuntimeError(f"Ollama embed returned HTTP {response.status_code}: {response.text}")

    return response.json()["embeddings"]


def retrieve_policies(connection, applicant):

    queries = list(POLICY_QUERIES)
    not_applicable = list(HUMAN_ONLY_POLICIES)

    country = (applicant.get("country") or "").strip().upper()
    if country and country not in ("USA", "US", "UNITED STATES"):
        queries.append(INTERNATIONAL_QUERY)
    else:
        not_applicable += INTERNATIONAL_POLICIES

    retrieved = {}

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:

        for query, embedding in zip(queries, embed_queries(queries)):

            vector = "[" + ",".join(f"{value:.7f}" for value in embedding) + "]"

            # <=> is pgvector cosine distance; similarity = 1 - distance.
            cursor.execute(
                """
                SELECT policy_id, title, content, 1 - (embedding <=> %s::vector) AS similarity
                FROM policy_chunks
                WHERE NOT (policy_id = ANY(%s))
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector, not_applicable, vector, POLICIES_PER_QUERY)
            )

            for row in cursor.fetchall():
                best = retrieved.get(row["policy_id"])
                if best is None or row["similarity"] > best["similarity"]:
                    retrieved[row["policy_id"]] = dict(row, similarity=round(float(row["similarity"]), 3), query=query)

        missing = [p for p in ALWAYS_INCLUDED_POLICIES if p not in retrieved]

        if missing:
            cursor.execute(
                "SELECT policy_id, title, content FROM policy_chunks WHERE policy_id = ANY(%s);",
                (missing,)
            )
            for row in cursor.fetchall():
                retrieved[row["policy_id"]] = dict(row, similarity=None, query="always included")

    if not retrieved:
        raise RuntimeError("No policies retrieved. Run setup/3_create_policy_store.py.")

    return sorted(retrieved.values(), key=lambda p: p["policy_id"])


# ============================================================
# [5] PROMPTS (one per section)
# ============================================================

COMMON_RULES = """
RULES
- You SUMMARIZE what the documents say. You do not decide anything.
- Do NOT make or suggest an admission decision (no admit, deny, reject,
  waitlist, or "should be accepted").
- Do NOT invent information. Use only the supplied pages and, for the
  academic section, the explicitly supplied current database score facts.
  If something is not shown, use null, an empty list, or say so.
- Do NOT mention gender, ethnicity, date of birth, or contact details.
- Do NOT use outside knowledge or numbers absent from these supplied sources.

EVIDENCE
Each evidence item gives: document (exact filename from the image map),
page (page_number from the image map), and quote: a SHORT phrase copied

EXACTLY from that page (a few words, not a paraphrase).
Use the original PDF page_number, not image_number or the order of selected images.
For the academic section, include up to 8 evidence items so that
GPA, SAT, ACT, and transcript coursework can be cited separately.
For all other sections, include at most 4 evidence items.

NOTES
Use notes only for things you could not read clearly or that are
missing on the pages. Use an empty list if there are none.

Return one JSON object only. No Markdown.
""".strip()


SECTION_TASKS = {
"academic": """
TASK: summarize the applicant's ACADEMIC record from these documents:
application form, transcript, standardized test score report, and the
advanced coursework / AP record.

document_facts: copy these exactly as printed (null if not shown):
  unweighted_gpa, weighted_gpa (cumulative, from the transcript),
  class_rank, sat_superscore, act_superscore, intended_major,
  high_school, expected_graduation.

EVIDENCE REQUIREMENTS:
- Cite each available GPA and test score separately:
  unweighted GPA, weighted GPA, SAT, and ACT.
- Copy short, exact quotations from the corresponding pages.
- Every numeric GPA/SAT/ACT fact needs a quotation containing both its
  metric label and matching value (for example, "Unweighted GPA 3.97").
- Include the correct document name and page number.
- If a metric is absent, leave its value null and do not cite it.
- Also cite relevant transcript coursework when available.

ap_courses_on_transcript: go through the transcript Course Record row by
  row. List ONLY rows whose Level column says "AP": course name, grade
  level (9-12), final grade. Never list a course as AP otherwise.
ap_exam_scores: every row of the AP record's score table: course, score,
  date, exactly as printed.
summary, course_rigor, performance_patterns: grades and progression by
  year, based on the rows you read.

- REQUIRED: Write a nonempty factual academic summary.
- If the academic record cannot be read, explain that clearly
  instead of returning an empty summary.

strengths, concerns: academic only, from what is on the pages.
""".strip(),

"engagement": """
TASK: Summarize the applicant's ACTIVITIES and AWARDS
from the supplied CommonApp.pdf pages.

The CommonApp may contain activities, roles, descriptions,
participation years, hours per week, and honors or awards.

activities:
- Extract every activity explicitly documented.
- Include role, description, years, and hours when available.
- Do not invent missing details.

awards:
- Extract every explicitly documented award.
- Preserve award names exactly.
- Do not invent award descriptions.

summary:
- REQUIRED: Write a nonempty factual summary.
- Summarize the documented activities and awards.
- If only awards are documented, summarize those awards.
- If neither activities nor awards are documented, state:
  "No activities or awards could be established from
  the available CommonApp pages."

leadership_service_employment:
- Describe only documented leadership, service, or employment.
- Use an empty string if none is documented.

themes:
- Include only themes supported by the documents.
- Use an empty list if none can be established.

assessment:
- Describe the documented engagement without making
  an admissions recommendation.
- Do not infer accomplishments from award titles alone.

EVIDENCE:
- Cite the actual CommonApp page containing each fact.
- Do not invent quotations or page numbers.
- Do not use personal essays, Hooks, or restricted information.
""".strip(),

    "recommendation": """
TASK: summarize the RECOMMENDATION LETTERS.

recommenders: one entry per letter: name and role (from the signature),
  document filename, relationship (how and how long the writer knows
  the applicant, as stated), key_observations (what that letter says).
summary, common_themes, strengths_identified: what the letters say.
Do not invent traits or accomplishments.
""".strip(),

    "supplement": """
TASK: summarize the applicant's UNIVERSITY SUPPLEMENT answers.

responses: one entry per question heading on the page: the prompt
  (heading as printed) and a short summary of the answer.
summary, major_themes: what the answers say.
""".strip(),
}

def build_image_prompt(section, applicant, pages):
    score_context = ""
    if section == "academic":
        recorded, issues = current_test_scores(applicant)
        if issues:
            raise ValueError("Invalid score input: " + "; ".join(i["message"] for i in issues))
        score_context = """
CURRENT DATABASE TEST SCORES (separate from PDF observations):
""" + json.dumps(recorded, indent=2) + """
Use these current recorded SAT/ACT/AP facts in the summary with their database
provenance. document_facts and PDF evidence must still describe only the pages:
never invent a PDF quote/page for a database value. If sources differ, describe
the discrepancy in notes without assuming chronology or silently replacing a
document value. Missing database scores are unknown, not zero or a penalty.
Course-only AP entries do not establish exam scores. The backend attaches this
database snapshot separately as recorded_test_scores after your response.
"""
    return f"""
You are the document-understanding and summarization component of a
college admissions review system. An admissions officer will read your
summary and makes every decision.

APPLICATION: {applicant["app_id"]}

DOCUMENT IMAGE MAP (the images supplied, in order):
{json.dumps(page_map(pages), indent=2)}

{SECTION_TASKS[section]}

{COMMON_RULES}

{score_context}
""".strip()

def evaluate_test_score_policies(applicant, policies):
    """Evaluate SAT/ACT reference ranges using PostgreSQL scores."""

    recorded, issues = current_test_scores(applicant)
    if issues:
        raise ValueError("Invalid score input: " + "; ".join(i["message"] for i in issues))

    configurations = {
        "POL-004": ("superscored_sat_score", "SAT", 1500, 1600, 400, 1600),
        "POL-005": ("superscored_act_score", "ACT", 34, 36, 1, 36),
    }

    assessments = []

    for policy in policies:
        policy_id = policy["policy_id"]

        if policy_id not in configurations:
            continue

        field, test, lower, upper, minimum, maximum = configurations[policy_id]
        score = applicant.get(field)

        # Fail safely if the policy text no longer matches the configured range.
        content = policy["content"]
        if not re.search(
            rf"\bbetween\s+{lower}\s+and\s+{upper}\b",
            content,
            re.IGNORECASE
        ):
            raise ValueError(
                f"{policy_id}: Policy range has changed. "
                "Update the deterministic configuration."
            )

        criterion = f"{test} middle 50% reference range: {lower}–{upper}"

        if score is None:
            alignment = "not_applicable"
            findings = (
                f"No {test} superscore is recorded in PostgreSQL. "
                "No numerical comparison was performed."
            )
        else:
            if isinstance(score, bool) or not isinstance(score, int):
                raise ValueError(f"{field}: Expected an integer score.")

            if not minimum <= score <= maximum:
                raise ValueError(f"{field}: Invalid score {score}.")

            if score < lower:
                alignment = "not_aligned"
                position = "below"
            elif score > upper:
                alignment = "aligned"
                position = "above"
            else:
                alignment = "aligned"
                position = "within"

            findings = (
                f"The applicant's {test} superscore of {score} is "
                f"{position} the middle 50% reference range "
                f"of {lower}–{upper}. This range is not an "
                "automatic admission cutoff."
            )

        if policy_id == "POL-004":
            findings += (
                " SAT cross-section consistency was not evaluated "
                "by this total-score comparison."
            )

        assessments.append({
            "policy_id": policy_id,
            "criterion": criterion,
            "alignment": alignment,
            "findings": findings,
            "evidence_ids": [],
            "evidence": [],
            "source": recorded["scores"][field]["source"],
        })

    return assessments

def build_policy_prompt(applicant, policies, sections, pages, evidence_registry):

    policy_text = "\n\n".join(p["content"] for p in policies)
    policy_ids = ", ".join(p["policy_id"] for p in policies)

    return f"""
You are the policy-context component of a college admissions review
system. Below are admissions policies retrieved for this application
and section summaries already written from the applicant's documents.
You have NOT seen the documents themselves.

APPLICATION: {applicant["app_id"]}

AUTHORITATIVE STANDARDIZED TEST SCORES FROM POSTGRESQL
SAT Superscore: {applicant.get("superscored_sat_score")}
ACT Superscore: {applicant.get("superscored_act_score")}

STANDARDIZED TEST SCORE RULES:
1. Use the PostgreSQL SAT superscore when evaluating POL-004.
2. Use the PostgreSQL ACT superscore when evaluating POL-005.
3. Evaluate SAT and ACT independently when both are present.
4. A NULL score means that test score is unavailable.
5. Do not penalize a missing SAT when ACT is available,
   or a missing ACT when SAT is available.
6. Do not use PDF-extracted SAT or ACT values in policy comparisons.
7. For POL-004 and POL-005, use evidence_ids: [].
8. Do not invent scores or infer missing scores.

RETRIEVED POLICIES (use ONLY these IDs: {policy_ids})
{policy_text}

DOCUMENTS THAT WERE AVAILABLE (filename: pages)
{json.dumps(documents_available(pages), indent=2)}

WITHHELD BY DESIGN (not available to you; humans review them)
Personal essays, restricted personal information, and Hooks.
Only filtered CommonApp pages are available to the AI.

SECTION SUMMARIES
{json.dumps(sections, indent=2, default=str)}

APPROVED EVIDENCE REGISTRY
{json.dumps(evidence_registry, indent=2, default=str)}

TASK:
Create a policy_assessment containing one entry for each
retrieved policy relevant to this applicant.

For each entry:
- criterion: Explain what the retrieved policy requires.
- alignment: Use only aligned, not_aligned, unclear, or not_applicable.
- findings: Explain what the existing section summaries establish.
- evidence_ids: List the IDs of evidence supporting the findings.

STRICT EVIDENCE RULES:
1. Use ONLY evidence IDs from APPROVED EVIDENCE REGISTRY.
2. Never generate, rewrite, or paraphrase quotations.
3. Never invent evidence IDs.
4. Do not output document names, page numbers, or quotations
   inside evidence_ids.
5. If no evidence supports a finding, use evidence_ids: [].
6. If evidence is insufficient, use alignment: unclear.
7. Use only evidence relevant to the specific policy criterion.
8. Do not use evidence from withheld personal essays, Hooks,
   or restricted fields.
9. Evidence from image-only documents may require human verification.

EXAMPLE:
{{
  "policy_id": "POL-005",
  "criterion": "Academic preparation",
  "alignment": "aligned",
  "findings": "The applicant demonstrates academic preparation.",
  "evidence_ids": ["E001", "E004"]
}}

HUMAN DECISION RULES:
1. You are evaluating policy alignment, NOT making an admissions decision.
2. Never recommend admission, rejection, or waitlisting.
3. Do not describe the applicant as admitted, accepted, rejected, or waitlisted.
4. Describe only academic qualifications, documented evidence,
   and alignment with retrieved admissions policies.
5. The Admissions Officer and Dean retain responsibility for decisions.

{COMMON_RULES}
""".strip()


def build_synthesis_prompt(applicant, sections):

    return f"""
You are the summarization component of a college admissions review
system. Below are the section summaries already written from the
applicant's documents and the policy context.

APPLICATION: {applicant["app_id"]}

SECTION SUMMARIES
{json.dumps(sections, indent=2, default=str)}

TASK
strengths: the applicant's main strengths across academics, activities,
  recommendations, and supplement (3 to 6), each with evidence reused
  from the section summaries (same document, page, and quote).
holistic_assessment: a concise narrative (one paragraph) that summarizes
  the academic record, engagement, recommendations, supplement, and any
  notes. It does NOT make or suggest an admission decision.

{COMMON_RULES}
""".strip()


def documents_available(pages):

    available = {}
    for p in pages:
        available.setdefault(p["filename"], []).append(p["page_number"])
    return available


# ============================================================
# [5] MODEL CALL (Ollama, streamed)
# ============================================================

def call_model(prompt, schema, num_predict, images=None):

    """
    One Qwen3-VL call. Streams the answer so progress is visible.
    Returns (raw_text, usage).
    """

    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = [base64.b64encode(p["png_bytes"]).decode("utf-8") for p in images]

    payload = {
        "model": VLM_MODEL,
        "messages": [message],
        "stream": True,
        "format": schema,
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": num_predict},
    }

    response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=VLM_TIMEOUT_SECONDS)

    # Some model builds reject the "think" option; retry without it.
    if response.status_code == 400 and "think" in response.text.lower():
        payload.pop("think")
        response.close()
        response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=VLM_TIMEOUT_SECONDS)

    try:
        if response.status_code != 200:
            raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {response.text}")

        parts, final = [], {}

        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if "error" in data:
                raise RuntimeError(f"Ollama error: {data['error']}")
            piece = (data.get("message") or {}).get("content", "")
            if piece:
                parts.append(piece)
                if len(parts) % 200 == 0:
                    print(".", end="", flush=True)
            if data.get("done") is True:
                final = data
                break

        if final.get("done") is not True:
            raise RuntimeError("Model stream ended without a completion marker")

        if final.get("done_reason") == "length":
            raise RuntimeError(f"Output hit the {num_predict}-token cap (likely repeating).")

        return "".join(parts), {
            "prompt_tokens": final.get("prompt_eval_count"),
            "output_tokens": final.get("eval_count"),
            "seconds": round((final.get("total_duration") or 0) / 1e9, 1),
        }

    finally:
        response.close()


def parse_json(raw):

    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())


# ============================================================
# [6] VALIDATION (CODE ONLY)
# ============================================================

def normalize(text):

    return re.sub(r"[^a-z0-9.\s]", " ", str(text).lower().replace("–", "-")).split()


NUMBER = re.compile(r"\d")


def quote_on_page(quote, page_text):
    """Match a contiguous normalized passage, preserving word/number order."""
    return quote_matches(quote, page_text)


def iter_evidence(node, path=""):

    """Yield (path, item) for every evidence item anywhere in the output."""

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "evidence" and isinstance(value, list):
                for item in value:
                    yield path or "output", item
            else:
                yield from iter_evidence(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_evidence(value, f"{path}[{index}]")

def build_evidence_registry(sections):
    """Assign stable IDs to evidence from validated document sections."""

    registry = {}
    seen = {}

    for section_name in (
        "academic", "engagement", "recommendation", "supplement"
    ):
        for _, item in iter_evidence(sections[section_name]):
            key = (
                item.get("document"),
                item.get("page"),
                item.get("quote"),
            )

            if key in seen:
                continue

            evidence_id = f"E{len(registry) + 1:03d}"

            registry[evidence_id] = {
                "document": item.get("document"),
                "page": item.get("page"),
                "quote": item.get("quote"),
                "verification_status": item.get(
                    "verification_status", "NOT_VERIFIED"
                ),
                "source_section": section_name,
            }

            seen[key] = evidence_id

    return registry

def narrative_text(node):

    """All model-written text except evidence quotes."""

    if isinstance(node, dict):
        return " ".join(narrative_text(v) for k, v in node.items() if k != "evidence")
    if isinstance(node, list):
        return " ".join(narrative_text(v) for v in node)
    return node if isinstance(node, str) else ""


def output_text(node):
    """Raw leaf content, including quotes, without JSON newline escaping."""
    if isinstance(node, dict):
        return " ".join(output_text(value) for value in node.values())
    if isinstance(node, list):
        return " ".join(output_text(value) for value in node)
    return str(node)


def word_shingles(text, size=8):

    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def restricted_values(applicant):

    values = []
    for field in RESTRICTED_FIELDS:
        value = applicant.get(field)
        if value:
            text = value.isoformat() if hasattr(value, "isoformat") else str(value).strip()
            if len(text) >= 4:
                values.append(text)
    # Hooks are excluded even when repeated in a permitted supplement.
    for hook in applicant.get("hooks") or []:
        if isinstance(hook, str) and len(hook.strip()) >= 4 and hook.strip().casefold() not in {"not provided", "none", "unknown"}:
            values.append(hook.strip())
    birth_date = applicant.get("date_of_birth")
    if hasattr(birth_date, "strftime"):
        values.extend([birth_date.strftime("%m/%d/%Y"), birth_date.strftime("%m/%d/%y"),
                       f"{birth_date.month}/{birth_date.day}/{birth_date.year}",
                       f"{birth_date.month}/{birth_date.day}/{birth_date.year % 100:02d}"])
    return list(dict.fromkeys(values))

def validate_policy_evidence_match(entry, evidence_registry):
    """Check evidence relevance for GPA policies."""

    policy_id = entry.get("policy_id")
    evidence_ids = entry.get("evidence_ids", [])

    required_terms = {
        "POL-002": ("unweighted", "gpa")
    }

    if not isinstance(evidence_ids, list):
        return ["Policy evidence_ids must be a list."]

    if not evidence_ids:
        if entry.get("alignment") in ("aligned", "not_aligned"):
            return [
                f"{policy_id}: Cannot classify as "
                f"'{entry.get('alignment')}' without supporting evidence. "
                "Use alignment: unclear when evidence is insufficient."
            ]
        return []

    if entry.get("alignment") in ("aligned", "not_aligned") and not any(
        evidence_registry.get(eid, {}).get("verification_status") == "TEXT_VERIFIED" for eid in evidence_ids
    ):
        return [f"{policy_id}: Finding requires verified supporting evidence; use unclear pending human verification."]

    if policy_id not in required_terms:
        return []

    terms = required_terms[policy_id]

    for evidence_id in evidence_ids:
        source = evidence_registry.get(evidence_id)

        if not source:
            continue

        quote = str(source.get("quote") or "").lower()

        if all(
            re.search(r"\b" + re.escape(term) + r"\b", quote)
            for term in terms
        ):
            return []

    return [
        f"{policy_id}: No cited evidence directly supports "
        f"the required {' '.join(terms)} metric. "
        "Select an evidence ID containing the correct metric, "
        "or report insufficient evidence."
    ]

def validate_section(section, output, pages_by_location, policy_ids, guards):

    """
    pages_by_location: {(filename, page): text} for pages the citations
    may point to. Returns a list of errors (empty = valid).
    """

    if not isinstance(output, dict):
        return ["Output is not a JSON object."]

    # Run privacy checks first, so even malformed output cannot put sensitive
    # values into schema-error feedback that will be sent to the next attempt.
    content = output_text(output)
    privacy_errors = []
    if any(re.search(restricted_pattern(value), content, re.IGNORECASE) for value in guards["restricted"]):
        privacy_errors.append("Restricted applicant data in output.")
    if guards["essay_shingles"] & word_shingles(content):
        privacy_errors.append("Personal statement content detected in output.")
    if privacy_errors:
        return privacy_errors

    errors = schema_errors(SCHEMAS[section], output)
    if errors:
        return errors

    for field in REQUIRED_TEXT[section]:
        if not isinstance(output.get(field), str) or not output[field].strip():
            errors.append(f"'{field}' is empty.")

    # Image-only pages cannot support text-based quote verification.
    for path, item in iter_evidence(output):
        if not item["quote"].strip():
            errors.append(f"{path}: evidence quote is empty.")
            continue
        location = (item.get("document"), item.get("page"))

        if location not in pages_by_location:
            errors.append(
                f"{path}: cites {location[0]} page {location[1]}, "
                "which was not provided."
            )
            continue

        page_text = pages_by_location[location]

        if not page_text.strip():
            # Image-only page: quotation cannot be verified by PyMuPDF.
            # Preserve the citation but mark it as unverified.
            item["verification_status"] = "UNVERIFIED_IMAGE_SOURCE"
            continue

        if not quote_on_page(item.get("quote", ""), page_text):
            matching = [f"{name} page {page}" for (name, page), text in pages_by_location.items()
                        if text.strip() and quote_on_page(item["quote"], text)]
            hint = " Matching supplied location(s): " + "; ".join(matching) + "." if matching else " No supplied text page matches; remove the unsupported citation."
            errors.append(f"{path}: quotation is not on {location[0]} page {location[1]}." + hint)
        else:
            item["verification_status"] = "TEXT_VERIFIED"

    if section == "academic":
        errors.extend(academic_fact_errors(output))

    if section == "policy":
        for entry in output.get("policy_assessment", []):
            if entry.get("policy_id") not in policy_ids:
                errors.append(
                    f"Unknown policy ID '{entry.get('policy_id')}' (not retrieved)."
                )

            evidence_ids = entry.get("evidence_ids", [])

            if not isinstance(evidence_ids, list):
                errors.append("Policy evidence_ids must be a list.")
                continue

            for evidence_id in evidence_ids:
                if not isinstance(evidence_id, str):
                    errors.append(
                        f"Invalid evidence ID type: {evidence_id!r}"
                )

    text = narrative_text(output)

    for pattern in DECISION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            errors.append(f"Admission-decision language: '{match.group(0)}'.")

    return errors

# ============================================================
# [5] + [6] RUN ONE SECTION (call → validate → retry once)
# ============================================================

def run_section(section, prompt, images, pages_by_location, policy_ids, guards, log, evidence_registry=None, checkpoint=None):

    errors, output, attempts = [], None, 0
    history = []
    request_hash = None
    if checkpoint:
        request_hash = generation_recovery.digest({"section": section, "prompt": prompt,
            "images": [hashlib.sha256(p["png_bytes"]).hexdigest() for p in (images or [])],
            "locations": sorted((name, page, text) for (name, page), text in pages_by_location.items()),
            "policy_ids": sorted(policy_ids), "evidence_registry": evidence_registry,
            "guard_hash": generation_recovery.digest({"restricted": guards.get("restricted"), "essay_shingles": sorted(guards.get("essay_shingles", []))})})
        cached = checkpoint.attempt(section, request_hash)
        if cached:
            output, errors, history = cached["output"], cached["errors"], cached["attempts"]
            log.extend(history)
            attempts = len(history)
            if not errors or attempts >= MAX_ATTEMPTS:
                print(f"    {section}: recovered {attempts} saved attempt(s); no model call")
                return output, errors, attempts

    for attempts in range(attempts + 1, MAX_ATTEMPTS + 1):
        if checkpoint: checkpoint.assert_current()

        attempt_prompt = prompt
        if errors:
            attempt_prompt += (
                "\n\nYOUR PREVIOUS ANSWER WAS REJECTED FOR THESE REASONS:\n- "
                + "\n- ".join(errors)
                + "\n\nCorrect these errors without inventing evidence. "
                    "Use only evidence IDs from the provided registry. "

                    "If no evidence supports a finding, use evidence_ids: [] "
                    "and set alignment to unclear. Do not mark unsupported "
                    "findings as aligned or not_aligned. "
                    "Use original PDF page_number, never image_number. "
                    "Remove every incorrect citation, including incorrect duplicates "
                    "of otherwise valid quotations. Matching supplied locations are "
                    "correction hints, not permission to invent a different quotation."
            )

        label = f"{section} ({len(images)} page image(s))" if images else f"{section} (text only)"
        print(f"    [{attempts}/{MAX_ATTEMPTS}] {label} ", end="", flush=True)

        try:
            raw, usage = call_model(attempt_prompt, SCHEMAS[section], NUM_PREDICT[section], images)
            print(f" {usage['seconds']}s, {usage['output_tokens']} tokens", end="")
            output = parse_json(raw)
            errors = validate_section(section, output, pages_by_location, policy_ids, guards)

            if section == "policy" and not errors:
                if evidence_registry is None:
                    errors.append("Policy evidence registry is missing.")
                else:
                    for entry in output.get("policy_assessment", []):
                        for evidence_id in entry.get("evidence_ids", []):
                            if evidence_id not in evidence_registry:
                                errors.append(
                                    f"Unknown evidence ID '{evidence_id}' "
                                    f"for policy {entry.get('policy_id')}."
                                )
                        if all(eid in evidence_registry for eid in entry.get("evidence_ids", [])):
                            errors.extend(validate_policy_evidence_match(entry, evidence_registry))

        except json.JSONDecodeError as error:
            usage, output, errors = {}, {"raw_output": raw}, [f"Output is not valid JSON: {error}"]
        except Exception as error:
            usage, output, errors = {}, None, [f"Model call failed: {error}"]

        entry = {"section": section, "attempt": attempts, "usage": usage, "errors": errors}
        log.append(entry); history.append(entry)
        if checkpoint: checkpoint.save_attempt(section, request_hash, output, errors, history)

        if not errors:
            print("  ✓")
            return output, [], attempts

        print(f"  ✗ {len(errors)} problem(s)")
        for problem in errors[:5]:
            print(f"          - {problem}")

    return output, errors, attempts


# ============================================================
# [7] ASSEMBLE THE DOSSIER (team schema)
# ============================================================

def build_applicant_demographics(applicant):

    """Application context from the CSV-loaded record. No restricted fields."""

    return {
        "first_name": applicant.get("first_name"),
        "last_name": applicant.get("last_name"),
        "name_of_hs": applicant.get("name_of_hs"),
        "country": applicant.get("country"),
        "region": applicant.get("region"),
        "intended_major": applicant.get("intended_major"),
        "admission_year": applicant.get("admission_year"),
        "admission_term": applicant.get("admission_term"),
    }


def build_dossier(applicant, sections):

    def without_notes(section):
        return {k: v for k, v in section.items() if k != "notes"}

    # review_notes: what the model could not read clearly while
    # summarizing, collected from every section.
    review_notes = [
        dict(note, section=name)
        for name in ("academic", "engagement", "recommendation", "supplement")
        for note in sections[name].get("notes", [])
    ]

    model_output = {
        "academic_profile": without_notes(sections["academic"]),
        "engagement_profile": without_notes(sections["engagement"]),
        "recommendation_profile": without_notes(sections["recommendation"]),
        "supplemental_essay_profile": without_notes(sections["supplement"]),
        "strengths": sections["synthesis"]["strengths"],
        "policy_assessment": sections["policy"]["policy_assessment"],
    }

    return {
        "app_id": applicant["app_id"],
        "applicant_demographics": build_applicant_demographics(applicant),
        **model_output,
        "review_notes": review_notes,
        "holistic_assessment": sections["synthesis"]["holistic_assessment"],
        "evidence_map": [
            {
                "section": path.split(".")[0].split("[")[0],
                "document": item.get("document"),
                 "page": item.get("page"),
                "quote": item.get("quote"),
                "verification_status": item.get("verification_status", "NOT_VERIFIED"),
            }
            for path, item in iter_evidence(model_output)
        ],
    }

NO_SUPPLEMENT = {
    "responses": [],
    "summary": "No university supplement was included in the application packet.",
    "major_themes": [],
    "notes": [],  # An absent optional supplement is not an actionable exception.
    "evidence": [],
}

# ============================================================
# [8] SAVE
# ============================================================

JSON_COLUMNS = [
    "applicant_demographics", "academic_profile", "engagement_profile",
    "recommendation_profile", "supplemental_essay_profile", "strengths",
    "review_notes", "policy_assessment", "evidence_map",
]


def save_dossier(connection, dossier):
    raise RuntimeError("Direct publication is disabled; approve the saved dossier review request")


def stage_review_candidate(connection, app_id, dossier, run, snapshot, version, execution=None):
    return review_checkpoint.stage_candidate(connection, app_id, dossier, run, snapshot, version, save_run, execution)


def save_run(connection, run, commit=True):

    with connection.cursor() as cursor:
        execution = run.get("execution_id")
        execution_column = ", execution_id" if execution else ""
        execution_value = ", %s" if execution else ""
        conflict = """ON CONFLICT(execution_id) DO UPDATE SET run_status=EXCLUDED.run_status,
          attempts=EXCLUDED.attempts,runtime_seconds=EXCLUDED.runtime_seconds,documents_sent=EXCLUDED.documents_sent,
          documents_withheld=EXCLUDED.documents_withheld,policies_retrieved=EXCLUDED.policies_retrieved,
          validation=EXCLUDED.validation,failed_output=EXCLUDED.failed_output""" if execution else ""
        cursor.execute(
            f"""
            INSERT INTO dossier_generation_runs (
                app_id, run_status, model, attempts, runtime_seconds, documents_sent,
                documents_withheld, policies_retrieved, validation, failed_output{execution_column}
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s{execution_value}) {conflict} RETURNING id;
            """,
            (
                run["app_id"], run["run_status"], VLM_MODEL, run["attempts"], run["runtime_seconds"],
                Json(run["documents_sent"]), Json(run["documents_withheld"]),
                Json(run["policies_retrieved"]), Json(run["validation"]), Json(run.get("failed_output")),
            ) + ((execution,) if execution else ())
        )

        run_id = cursor.fetchone()[0]

        # Application_status is VARCHAR(32)

        cursor.execute(
            """UPDATE applicants SET status = CASE
                WHEN final_decision IS NOT NULL THEN 'FINAL_DECISION_RECORDED'
                WHEN officer_recommendation IS NOT NULL THEN 'REVIEWED'
                ELSE %s END WHERE app_id = %s""",
            (
                "DOSSIER_READY"
                if run["run_status"] == "DOSSIER_READY"
                else "REVIEW_PENDING" if run["run_status"] == "REVIEW_PENDING"
                else "ERROR" if run["run_status"] == "AGENT_ERROR" else "READY_FOR_REVIEW",
                    run["app_id"],
            ),
        )

    if commit:
        connection.commit()
    return run_id


def write_result_file(app_id, run, dossier):

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{app_id}_dossier.json"
    path.write_text(json.dumps({"run": run, "applicant_dossier": dossier}, indent=2, default=str), encoding="utf-8")
    return path


# ============================================================
# PROCESS ONE APPLICANT
# ============================================================

def generation_pipeline_version():
    return review_checkpoint.pipeline_version({"model": VLM_MODEL, "embedding_model": EMBED_MODEL,
        "num_ctx": NUM_CTX, "render_zoom": RENDER_ZOOM, "num_predict": NUM_PREDICT})


def configure_console():
    # Windows redirected streams can default to cp1252; progress symbols must not
    # interrupt a saved generation or prevent the recovery CLI from printing help.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try: stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError): pass


def process_applicant(connection, minio_client, app_id, force=False, generation_key=None, expected_input_hash=None):
    configure_console()
    return generation_recovery.run_applicant(sys.modules[__name__], connection, minio_client, app_id, force, generation_key, expected_input_hash)


def _process_applicant(connection, minio_client, app_id, force=False, checkpoint=None):

    print("\n========================================")
    print(f"PROCESSING {app_id}")
    print("========================================")

    started = time.time()

    # ---- [1] Load applicant ---------------------------------------------
    applicant = get_applicant(connection, app_id)

    if applicant is None:
        print(f"[1] ✗ {app_id} not found in PostgreSQL. Skipped.")
        write_audit(connection, app_id, "SKIPPED_NOT_FOUND")
        return "SKIPPED"

    status = applicant.get("status")
    print(f"[1] Applicant {applicant['app_id']}, status {status}")
    if status in {"INCOMPLETE", "AWAITING_MATERIALS", "REPLACEMENT_REQUESTED", "COUNSELOR_REVIEW"}:
        write_audit(connection, app_id, "SKIPPED_MANIFEST_NOT_READY", {"status": status})
        return "SKIPPED"

    if status != "READY_FOR_REVIEW" and not force:
        print("    Not COMPLETE. Skipped (use --force to summarize again).")
        write_audit(connection, app_id, "SKIPPED_NOT_COMPLETE", {"status": status})
        return "SKIPPED"

    recorded_scores, input_errors = current_test_scores(applicant)
    if input_errors:
        # Preserve the source record and any older dossier; never call a model
        # or numerical policy evaluation on known-invalid recorded scores.
        run = {
            "app_id": app_id, "run_status": "AGENT_ERROR", "attempts": 0,
            "runtime_seconds": round(time.time() - started, 1),
            "documents_sent": {}, "documents_withheld": {}, "policies_retrieved": [],
            "validation": {"passed": False, "failed_sections": {"input": [i["message"] for i in input_errors]},
                           "input_errors": input_errors, "calls": []},
            "failed_output": {"recorded_test_scores": recorded_scores},
        }
        save_run(connection, run)
        write_audit(connection, app_id, "INPUT_VALIDATION_FAILED", {"errors": input_errors})
        write_result_file(app_id, run, None)
        print("Input score validation failed; correction required. No inference performed.")
        return run["run_status"]

    if applicant.get("officer_recommendation") is not None or applicant.get("final_decision") is not None:
        write_audit(connection, app_id, "SKIPPED_HUMAN_DISPOSITION")
        return "SKIPPED"
    snapshot = review_checkpoint.capture_input_snapshot(connection, applicant)
    version = checkpoint.row["pipeline_version"] if checkpoint else generation_pipeline_version()
    if not force:
        cached = review_checkpoint.existing_review(connection, app_id, snapshot, version)
        if cached:
            print(f"Saved checkpoint: {cached}; no repeated inference")
            return cached

    write_audit(connection, app_id, "SUMMARY_STARTED", {"model": VLM_MODEL})

    # ---- [2] Withhold documents ------------------------------------------
    documents = [normalize_document(d) for d in (applicant.get("documents") or [])]
    allowed, withheld = split_documents(documents)

    print(f"[2] {len(documents)} documents: {len(allowed)} for the model, {len(withheld)} withheld")
    for d in withheld:
        print(f"    withheld: {d['filename']:<32} ({withhold_reason(d)})")

    withheld_log = {d["filename"]: withhold_reason(d) for d in withheld}
    write_audit(connection, app_id, "DOCUMENTS_WITHHELD", {"withheld": withheld_log})

    # ---- [3] Pages -------------------------------------------------------
    print(f"[3] Rendering pages at {RENDER_ZOOM}x (memory only)")

    pages, load_problems = load_pages(minio_client, allowed, restricted_values(applicant))
    if load_problems or not pages:
        raise RuntimeError(
            f"Document loading failed for {app_id}: {load_problems}"
            )

    run = {
        "app_id": app_id,
        "documents_sent": documents_available(pages),
        "documents_withheld": withheld_log,
        "policies_retrieved": [],
        "attempts": 0,
    }
    if checkpoint: run["execution_id"] = checkpoint.id

    # Code-only guards: the personal statement's text (for leak detection)
    # and the applicant's restricted values. Never sent to the model.
    essay_shingles = set()
    for d in withheld:
        if withhold_reason(d) == ESSAY_REASON:
            try:
                for page in render_pdf(download_pdf(minio_client, d["object_key"], d.get("minio_bucket")), zoom=0.2):
                    essay_shingles |= word_shingles(page["text"])
            except Exception as error:
                print(f"    (could not load {d['filename']} for the leak check: {error})")

    allowed_shingles = set().union(*(word_shingles(p["text"]) for p in pages))
    guards = {
        "essay_shingles": essay_shingles - allowed_shingles,
        "restricted": restricted_values(applicant),
    }

    all_locations = {(p["filename"], p["page_number"]): p["text"] for p in pages}

    # ---- [4] RAG ---------------------------------------------------------
    policies = checkpoint.policies(lambda: retrieve_policies(connection, applicant)) if checkpoint else retrieve_policies(connection, applicant)
    policy_ids = {p["policy_id"] for p in policies}
    run["policies_retrieved"] = [
        {k: p[k] for k in ("policy_id", "title", "similarity", "query")} for p in policies
    ]
    print(f"[4] RAG: retrieved {len(policies)} policies: {', '.join(sorted(policy_ids))}")
    write_audit(connection, app_id, "POLICIES_RETRIEVED", {"policy_ids": sorted(policy_ids)})

    # ---- [5] + [6] Section calls, each validated ---------------------------
    print(f"[5] {VLM_MODEL}: one call per section (each validated, retried once if needed)")

    sections, section_log, failed = {}, [], {}
    attempts_total = 0

    for section in ("academic", "engagement", "recommendation", "supplement"):

        images = section_pages(pages, section)

        if section == "supplement" and not images:
            sections[section] = NO_SUPPLEMENT
            print("    supplement: no document, recorded as missing")
            continue

        locations = {(p["filename"], p["page_number"]): p["text"] for p in images}
        output, errors, attempts = run_section(
            section, build_image_prompt(section, applicant, images), images,
            locations, policy_ids, guards, section_log, checkpoint=checkpoint
        )
        attempts_total += attempts

        if errors:
            failed[section] = {"errors": errors, "output": output}
        else:
            if section == "academic":
                output["recorded_test_scores"] = recorded_scores
                for field, document_field in (("superscored_sat_score", "sat_superscore"), ("superscored_act_score", "act_superscore")):
                    current = recorded_scores["scores"][field]["value"]
                    document_facts = output.get("document_facts")
                    observed = document_facts.get(document_field) if isinstance(document_facts, dict) else None
                    if current is not None and observed is not None and current != observed:
                        output.setdefault("notes", []).append({"category": "other", "note":
                            f"Source discrepancy: PostgreSQL {field} is {current}; document {document_field} is {observed}. Verify sources; record update time does not establish test date."})
            sections[section] = output

    if not failed:
        evidence_registry = build_evidence_registry(sections)

        # SAT/ACT are evaluated deterministically from PostgreSQL
        score_policy_ids = {"POL-004", "POL-005"}

        vlm_policies = [
            p for p in policies
            if p["policy_id"] not in score_policy_ids
        ]

        vlm_policy_ids = {
            p["policy_id"] for p in vlm_policies
        }

        score_assessments = evaluate_test_score_policies(
            applicant, policies
        )

        output, errors, attempts = run_section(
            "policy",
            build_policy_prompt(
                applicant, vlm_policies, sections, pages, evidence_registry
            ),
            None,
            all_locations,
            vlm_policy_ids,
            guards,
            section_log,
            evidence_registry=evidence_registry, checkpoint=checkpoint
        )

        attempts_total += attempts

        if not errors:
            for entry in output["policy_assessment"]:
                resolved_evidence = []

                for evidence_id in entry["evidence_ids"]:
                    source = evidence_registry[evidence_id]

                    resolved_evidence.append({
                        "document": source["document"],
                        "page": source["page"],
                        "quote": source["quote"],
                        "verification_status": source["verification_status"]
                    })

                entry["evidence"] = resolved_evidence

        if errors:
            failed["policy"] = {"errors": errors, "output": output}
        else:
            # Add PostgreSQL-derived SAT/ACT policy assessments.
            output["policy_assessment"].extend(score_assessments)
            sections["policy"] = output

    if not failed:
        output, errors, attempts = run_section(
            "synthesis", build_synthesis_prompt(applicant, sections), None,
            all_locations, policy_ids, guards, section_log, checkpoint=checkpoint
        )
        attempts_total += attempts
        if errors:
            failed["synthesis"] = {"errors": errors, "output": output}
        else:
            sections["synthesis"] = output

    # ---- [7] + [8] Assemble and save ----------------------------------------
    run.update(
        attempts=attempts_total,
        runtime_seconds=round(time.time() - started, 1),
        validation={
            "passed": not failed,
            "failed_sections": {k: v["errors"] for k, v in failed.items()},
            "load_problems": load_problems,
            "calls": section_log,
            "recorded_test_scores": recorded_scores,
            "document_sources": documents,
            "requires_human_verification": any(
                item.get("verification_status") == "UNVERIFIED_IMAGE_SOURCE"
                for section_output in sections.values() for _, item in iter_evidence(section_output)
            ),
        },
    )

    dossier = None
    if failed:
        run["run_status"] = "AI_VALIDATION_FAILED"
        run["failed_output"] = {"completed_sections": sections, "failed_sections": failed}
        if checkpoint:
            run_id = save_run(connection, run, commit=False)
            checkpoint.finish_in_transaction(run["run_status"], run_id)
            connection.commit()
        else:
            save_run(connection, run)
    else:
        run["run_status"] = "REVIEW_PENDING"
        dossier = build_dossier(applicant, sections)
        try:
            if checkpoint: checkpoint.assert_current()
            review = stage_review_candidate(connection, app_id, dossier, run, snapshot, version, checkpoint)
            run["review_request_id"] = review["id"]
            run["candidate_hash"] = review["candidate_hash"]
            run["run_status"] = {"PUBLISHED": "DOSSIER_READY", "REJECTED": "REVIEW_REJECTED",
                "ESCALATED": "REVIEW_ESCALATED", "SUPERSEDED": "REVIEW_SUPERSEDED"}.get(review["state"], "REVIEW_PENDING")
            print(f"Validated candidate routed: {review['id']} ({review['state']}, {review.get('review_mode', 'LEGACY_MANUAL')})")
        except Exception as error:
            connection.rollback()
            if checkpoint: raise
            message = getattr(getattr(error, "diag", None), "message_primary", None) or "Checkpoint persistence failed"
            run["run_status"] = "AGENT_ERROR"
            run["validation"]["section_validation_passed"] = run["validation"]["passed"]
            run["validation"]["passed"] = False
            run["validation"]["failed_sections"]["checkpoint"] = [message]
            run["failed_output"] = {"withheld_candidate": dossier}
            save_run(connection, run)
            dossier = None
            print(f"Publication withheld: {message}")
    path = write_result_file(app_id, run, dossier if run["run_status"] == "DOSSIER_READY" else None)
    write_audit(connection, app_id, run["run_status"], {"attempts": attempts_total, "failed": list(failed),
        "review_request_id": run.get("review_request_id")})
    print(f"Saved {run['run_status']}; snapshot {path}. Flagged candidates require an explicit exception resolution.")
    print(f"Total time {run['runtime_seconds']}s")

    return run["run_status"]


# ============================================================
# MAIN
# ============================================================

def load_affected_ids(cli_ids):

    if cli_ids:
        return cli_ids

    handoff = ROOT.parent / "output/ingestion/affected_ids.json"
    if handoff.exists():
        return json.loads(handoff.read_text())

    return ["APP_001"]


def main():
    configure_console()
    parser = argparse.ArgumentParser(description="EAOS summarizing agent (RAG + Qwen3-VL) → applicant dossier")
    parser.add_argument("app_ids", nargs="*", help="Applicant IDs (default: output/ingestion/affected_ids.json, else APP_001)")
    parser.add_argument("--force", action="store_true", help="Intentionally regenerate an eligible applicant in a new retry scope")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--batch-event", help="Generate from a completed durable ingestion receipt")
    scope.add_argument("--batch-id", help="Resume an existing generation batch without changing its scope")
    scope.add_argument("--handoff", type=Path, help="Read the durable .batch.json handoff (or a legacy ID list)")
    parser.add_argument("--retry-key", help="Explicit, stable key for an intentional new attempt; reuse to recover it")
    parser.add_argument("--inspect", action="store_true", help="Inspect --batch-id receiving-system rows without inference")
    parser.add_argument("--verify-objects", action="store_true", help="With --inspect, read and hash the receiving MinIO objects")
    args = parser.parse_args()
    if args.app_ids and (args.batch_event or args.batch_id or args.handoff):parser.error("Use explicit IDs or one batch scope, not both")
    if args.inspect and not args.batch_id:parser.error("--inspect requires --batch-id")
    if args.verify_objects and not args.inspect:parser.error("--verify-objects requires --inspect")
    if args.batch_id and (args.force or args.retry_key):parser.error("Resuming a batch preserves its saved scope; omit --force and --retry-key")
    affected_ids = [] if args.batch_event or args.batch_id else load_affected_ids(args.app_ids)
    if args.handoff:
        handoff = json.loads(args.handoff.read_text(encoding="utf-8"))
        if isinstance(handoff, dict):args.batch_event = handoff["batch_event_id"]; affected_ids = []
        elif isinstance(handoff, list):affected_ids = handoff
        else:parser.error("Invalid handoff")

    print("\n========================================")
    print("EAOS SUMMARIZING AGENT (RAG + QWEN3-VL)")
    print("========================================")
    print(f"Model: {VLM_MODEL}   Embeddings: {EMBED_MODEL}")
    print(f"Applicants: {affected_ids}")

    connection = connect_postgres()

    try:
        ensure_output_tables(connection)
        if args.inspect:
            generation_recovery.ensure_schema(connection)
            inspected = generation_recovery.inspect_batch(connection,args.batch_id,connect_minio() if args.verify_objects else None)
            print(json.dumps(inspected,indent=2,default=str))
            return 0 if inspected and not any(m.get('objects_verified') is False for m in inspected['members']) else 1
        minio_client = connect_minio()

        results = {}
        if isinstance(connection, psycopg2.extensions.connection):
            try:
                batch_id,results = generation_recovery.run_batch(sys.modules[__name__],connection,minio_client,affected_ids,
                    event_id=args.batch_event,batch_id=args.batch_id,force=args.force,retry_key=args.retry_key)
            except (generation_recovery.GenerationBusy,generation_recovery.StaleGeneration,ValueError) as error:
                print(f"Batch not run: {error}")
                return 1
        for app_id in ([] if isinstance(connection, psycopg2.extensions.connection) else affected_ids):
            # One applicant's failure must not stop the batch.
            try:
                results[app_id] = process_applicant(connection, minio_client, app_id, args.force)
            except Exception as error:
                connection.rollback()
                print(f"✗ {app_id} failed: {error}")
                write_audit(connection, app_id, "AGENT_ERROR", {"error": str(error)})
                results[app_id] = "AGENT_ERROR"

        print("\n========================================")
        print("BATCH SUMMARY")
        print("========================================")
        for app_id, result in results.items():
            if isinstance(connection, psycopg2.extensions.connection):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT status FROM applicants WHERE app_id=%s",(app_id,))
                    received = cursor.fetchone()
                print(f"  {app_id:<10} generation={result}; applicant_status={received[0] if received else 'NOT_FOUND'}")
            else:
                print(f"  {app_id:<10} {result}")
        if isinstance(connection, psycopg2.extensions.connection):
            print(f"Inspect receiver rows and objects: --batch-id {batch_id} --inspect --verify-objects")

        print("\n[HARD STOP] Dossiers are advisory. An admissions officer makes every decision.")
        return 1 if any(value in {"AGENT_ERROR", "AI_VALIDATION_FAILED", "REVIEW_REJECTED", "REVIEW_ESCALATED", "INTERRUPTED", "INPUTS_CHANGED", "GENERATION_BUSY"} for value in results.values()) else 0

    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
