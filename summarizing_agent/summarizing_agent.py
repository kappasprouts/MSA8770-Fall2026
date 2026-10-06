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
[4] RAG    nomic-embed-text + pgvector → relevant policies from policies.yaml
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
import os
import re
import time
from pathlib import Path

import psycopg2
import pymupdf
import requests
from minio import Minio
from psycopg2.extras import Json, RealDictCursor


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"

# PostgreSQL (same defaults as setup/2_create_simulated_postgres.py)
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "riverview_admissions")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

# MinIO (same defaults as setup/1_create_simulated_minio.py)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "applicant-documents")

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

# Without these the dossier would be misleading: no model call.
REQUIRED_DOCUMENT_TYPES = {"transcript": 1, "recommendation": 2}

# Which documents each image section reads.
SECTION_DOCUMENT_TYPES = {
    "academic": ["application_form", "transcript", "standardized_test_score", "advanced_coursework"],
    "engagement": ["activities_and_awards"],
    "recommendation": ["recommendation"],
    "supplement": ["university_supplement"],
}

# Applicant fields whose values must never appear in the output.
RESTRICTED_FIELDS = [
    "gender", "ethnicity", "date_of_birth",
    "mailing_address", "primary_phone_number", "email_address",
]


# ============================================================
# RAG SETTINGS
# ============================================================

POLICY_QUERIES = [
    "first-year required application materials transcript recommendation letters",
    "standardized test scores SAT ACT optional",
    "unreadable corrupted or obscured documents",
    "documents must match the applicant ID",
    "issue dates and graduation dates must be consistent",
]
INTERNATIONAL_QUERY = "international applicant English proficiency and credential evaluation"
POLICIES_PER_QUERY = 2

# Never retrieved when they cannot apply (all applicants are first-year).
INTERNATIONAL_POLICIES = ["POL-INT-01", "POL-INT-02"]
TRANSFER_POLICIES = ["POL-TR-01"]

# Always given to the model so it knows its limits.
ALWAYS_INCLUDED_POLICIES = ["POL-ESSAY-01", "POL-HUMAN-01"]

# Admission-decision wording the model must never produce.
DECISION_PATTERNS = [
    r"\badmit(ted)?\b",
    r"\badmission decision\b",
    r"\bden(y|ied)\b",
    r"\breject(ed|ion)?\b",
    r"\bwait-?list(ed)?\b",
    r"\bshould be accepted\b",
    r"\brecommend(ed)? (for )?(admission|acceptance)\b",
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
            "page": {"type": "integer"},
            "quote": {"type": "string"},
        },
        "required": ["document", "page", "quote"],
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
    },
}


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties)}


SCHEMAS = {
    "academic": object_schema({
        "document_facts": object_schema({
            "unweighted_gpa": {"type": ["number", "null"]},
            "weighted_gpa": {"type": ["number", "null"]},
            "class_rank": {"type": ["string", "null"]},
            "sat_superscore": {"type": ["integer", "null"]},
            "act_superscore": {"type": ["integer", "null"]},
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
                "evidence": EVIDENCE,
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
            f"MinIO bucket '{MINIO_BUCKET}' does not exist. Run setup/1_create_simulated_minio.py."
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
                                            REFERENCES simulated_applicant_data (App_ID),
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
            "SELECT * FROM simulated_applicant_data WHERE App_ID = %s;",
            (app_id,)
        )
        return cursor.fetchone()


def normalize_document(document):

    """Accept both the simulated JSONB keys and Danny's ingestion keys."""

    return {
        "type": document.get("type") or document.get("doc_type") or "",
        "filename": document.get("filename", ""),
        "object_key": document.get("object_key") or document.get("minio_key") or "",
    }


# ============================================================
# [2] WITHHELD DOCUMENTS
# ============================================================

def withhold_reason(document):

    document_type = document["type"].lower()
    filename = document["filename"].lower()

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

def download_pdf(minio_client, object_key):

    response = None

    try:
        response = minio_client.get_object(MINIO_BUCKET, object_key)
        return response.read()

    finally:
        if response is not None:
            response.close()
            response.release_conn()


def render_pdf(pdf_bytes, zoom=RENDER_ZOOM):

    """
    Returns a list of pages: PNG bytes for the model, and the page's
    text layer for CODE-ONLY citation checks (never sent to the model).
    """

    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    matrix = pymupdf.Matrix(zoom, zoom)

    try:
        return [
            {
                "page_number": index + 1,
                "png_bytes": document[index].get_pixmap(matrix=matrix, alpha=False).tobytes("png"),
                "text": document[index].get_text(),
            }
            for index in range(len(document))
        ]
    finally:
        document.close()


def load_pages(minio_client, documents):

    """Download and render documents. A failure is recorded, never silently skipped."""

    pages, problems = [], []

    for document in documents:
        try:
            rendered = render_pdf(download_pdf(minio_client, document["object_key"]))
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
                }
            )

    return pages, problems


def missing_required_documents(pages):

    missing = []

    for document_type, needed in REQUIRED_DOCUMENT_TYPES.items():
        found = len({p["filename"] for p in pages if p["document_type"] == document_type})
        if found < needed:
            missing.append(f"{document_type} ({found} of {needed})")

    return missing


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
    not_applicable = list(TRANSFER_POLICIES)

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
- Do NOT invent information. Use only what is visible on the pages.
  If something is not shown, use null, an empty list, or say so.
- Do NOT mention gender, ethnicity, date of birth, or contact details.
- Do NOT use outside knowledge or numbers that are not on the pages.

EVIDENCE
Each evidence item gives: document (exact filename from the image map),
page (page_number from the image map), and quote: a SHORT phrase copied
EXACTLY from that page (a few words, not a paraphrase). At most 4
evidence items.

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
ap_courses_on_transcript: go through the transcript Course Record row by
  row. List ONLY rows whose Level column says "AP": course name, grade
  level (9-12), final grade. Never list a course as AP otherwise.
ap_exam_scores: every row of the AP record's score table: course, score,
  date, exactly as printed.
summary, course_rigor, performance_patterns: grades and progression by
  year, based on the rows you read.
strengths, concerns: academic only, from what is on the pages.
""".strip(),

    "engagement": """
TASK: summarize the applicant's ACTIVITIES and AWARDS from the
"Activities and Awards" document.

activities: the Activities table has columns Activity | Role and
  description | Years | Hours/week. Each row's description wraps over
  several lines; keep each row's cells together. List EVERY row, in
  order, across all pages, with that row's own role, years, and hours.
awards: copy every bullet under "Honors and Awards" exactly. Awards
  have no descriptions; do not add any.
summary, leadership_service_employment, themes, assessment: based only
  on the rows you listed.
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

    return f"""
You are the document-understanding and summarization component of a
college admissions review system. An admissions officer will read your
summary and makes every decision.

APPLICATION: {applicant["app_id"]}

DOCUMENT IMAGE MAP (the images supplied, in order):
{json.dumps(page_map(pages), indent=2)}

{SECTION_TASKS[section]}

{COMMON_RULES}
""".strip()


def build_policy_prompt(applicant, policies, sections, pages):

    policy_text = "\n\n".join(p["content"] for p in policies)
    policy_ids = ", ".join(p["policy_id"] for p in policies)

    return f"""
You are the policy-context component of a college admissions review
system. Below are admissions policies retrieved for this application
and the section summaries already written from the applicant's
documents. You have NOT seen the documents themselves.

APPLICATION: {applicant["app_id"]}

RETRIEVED POLICIES (use ONLY these IDs: {policy_ids})
{policy_text}

DOCUMENTS THAT WERE AVAILABLE (filename: pages)
{json.dumps(documents_available(pages), indent=2)}

WITHHELD BY DESIGN (not available to you; humans review them)
personal statement (POL-ESSAY-01) and the Common App copy.

SECTION SUMMARIES
{json.dumps(sections, indent=2, default=str)}

TASK: policy_assessment: one entry per retrieved policy that relates to
this application: criterion (what the policy says), alignment (aligned /
not_aligned / unclear / not_applicable), findings (what the section
summaries show for this policy). Evidence: reuse evidence items from
the section summaries (same document, page, and quote); empty list if
none applies. "Unclear" is fine when the summaries do not show enough.

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
        response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=VLM_TIMEOUT_SECONDS)

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
        if data.get("done"):
            final = data
            break

    if final.get("done_reason") == "length":
        raise RuntimeError(f"Output hit the {num_predict}-token cap (likely repeating).")

    return "".join(parts), {
        "prompt_tokens": final.get("prompt_eval_count"),
        "output_tokens": final.get("eval_count"),
        "seconds": round((final.get("total_duration") or 0) / 1e9, 1),
    }


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

    """
    True if the cited quote appears on the page (PDF text layer, read
    by code only). Rules: every number in the quote must be on the
    page, and at least 80% of its words.
    """

    quote_words = [w.strip(".") for w in normalize(quote) if w.strip(".")]
    page_words = {w.strip(".") for w in normalize(page_text)}

    if not quote_words:
        return False

    numbers = [w for w in quote_words if NUMBER.search(w)]
    if any(n not in page_words for n in numbers):
        return False

    words = [w for w in quote_words if not NUMBER.search(w) and len(w) > 2]
    if not words:
        return True

    return sum(1 for w in words if w in page_words) / len(words) >= 0.8


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


def narrative_text(node):

    """All model-written text except evidence quotes."""

    if isinstance(node, dict):
        return " ".join(narrative_text(v) for k, v in node.items() if k != "evidence")
    if isinstance(node, list):
        return " ".join(narrative_text(v) for v in node)
    return node if isinstance(node, str) else ""


def word_shingles(text, size=8):

    words = re.findall(r"[a-z0-9']+", str(text).lower())
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def restricted_values(applicant):

    values = []
    for field in RESTRICTED_FIELDS:
        value = applicant.get(field)
        if value:
            text = value.isoformat() if hasattr(value, "isoformat") else str(value)
            if len(text) >= 4:
                values.append(text)
    return values


def validate_section(section, output, pages_by_location, policy_ids, guards):

    """
    pages_by_location: {(filename, page): text} for pages the citations
    may point to. Returns a list of errors (empty = valid).
    """

    if not isinstance(output, dict):
        return ["Output is not a JSON object."]

    errors = [f"Missing key: {k}" for k in SCHEMAS[section]["required"] if k not in output]
    if errors:
        return errors

    for field in REQUIRED_TEXT[section]:
        if not isinstance(output.get(field), str) or not output[field].strip():
            errors.append(f"'{field}' is empty.")

    # Citations: the page was available, and the quote is on it.
    for path, item in iter_evidence(output):
        location = (item.get("document"), item.get("page"))
        if location not in pages_by_location:
            errors.append(f"{path}: cites {location[0]} page {location[1]}, which was not provided.")
        elif not quote_on_page(item.get("quote", ""), pages_by_location[location]):
            errors.append(
                f"{path}: quote \"{str(item.get('quote'))[:80]}\" is not on {location[0]} page {location[1]}."
            )

    if section == "policy":
        for entry in output.get("policy_assessment", []):
            if entry.get("policy_id") not in policy_ids:
                errors.append(f"Unknown policy ID '{entry.get('policy_id')}' (not retrieved).")

    text = narrative_text(output)

    for pattern in DECISION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            errors.append(f"Admission-decision language: '{match.group(0)}'.")

    lowered = json.dumps(output).lower()
    for value in guards["restricted"]:
        if re.search(r"\b" + re.escape(value.lower()) + r"\b", lowered):
            errors.append(f"Restricted applicant data in output: '{value}'.")

    leaked = guards["essay_shingles"] & word_shingles(json.dumps(output))
    if leaked:
        errors.append(f"Personal statement text in output: '{sorted(leaked)[0]}...'")

    return errors


# ============================================================
# [5] + [6] RUN ONE SECTION (call → validate → retry once)
# ============================================================

def run_section(section, prompt, images, pages_by_location, policy_ids, guards, log):

    errors, output, attempts = [], None, 0

    for attempts in range(1, MAX_ATTEMPTS + 1):

        attempt_prompt = prompt
        if errors:
            attempt_prompt += (
                "\n\nYOUR PREVIOUS ANSWER WAS REJECTED FOR THESE REASONS. FIX THEM "
                "(copy quotes exactly from the cited page):\n- " + "\n- ".join(errors[:10])
            )

        label = f"{section} ({len(images)} page image(s))" if images else f"{section} (text only)"
        print(f"    [{attempts}/{MAX_ATTEMPTS}] {label} ", end="", flush=True)

        try:
            raw, usage = call_model(attempt_prompt, SCHEMAS[section], NUM_PREDICT[section], images)
            print(f" {usage['seconds']}s, {usage['output_tokens']} tokens", end="")
            output = parse_json(raw)
            errors = validate_section(section, output, pages_by_location, policy_ids, guards)
        except json.JSONDecodeError as error:
            usage, output, errors = {}, {"raw_output": raw}, [f"Output is not valid JSON: {error}"]
        except Exception as error:
            usage, output, errors = {}, None, [f"Model call failed: {error}"]

        log.append({"section": section, "attempt": attempts, "usage": usage, "errors": errors})

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
            {"section": path.split(".")[0].split("[")[0], "document": item.get("document"),
             "page": item.get("page"), "quote": item.get("quote")}
            for path, item in iter_evidence(model_output)
        ],
    }


NO_SUPPLEMENT = {
    "responses": [],
    "summary": "No university supplement was included in the application packet.",
    "major_themes": [],
    "notes": [{"category": "missing_information", "note": "No university supplement document was available."}],
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

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO applicant_dossier (
                app_id, {", ".join(JSON_COLUMNS)}, holistic_assessment, generated_at, updated_at
            )
            VALUES (%s, {", ".join(["%s"] * len(JSON_COLUMNS))}, %s, now(), now())
            ON CONFLICT (app_id) DO UPDATE SET
                {", ".join(f"{c} = EXCLUDED.{c}" for c in JSON_COLUMNS)},
                holistic_assessment = EXCLUDED.holistic_assessment,
                updated_at = now()
            RETURNING generated_at, updated_at;
            """,
            [dossier["app_id"]] + [Json(dossier[c]) for c in JSON_COLUMNS] + [dossier["holistic_assessment"]]
        )
        generated_at, updated_at = cursor.fetchone()

    connection.commit()
    return generated_at, updated_at


def save_run(connection, run):

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO dossier_generation_runs (
                app_id, run_status, model, attempts, runtime_seconds, documents_sent,
                documents_withheld, policies_retrieved, validation, failed_output
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                run["app_id"], run["run_status"], VLM_MODEL, run["attempts"], run["runtime_seconds"],
                Json(run["documents_sent"]), Json(run["documents_withheld"]),
                Json(run["policies_retrieved"]), Json(run["validation"]), Json(run.get("failed_output")),
            )
        )

        # Application_status is VARCHAR(15).
        cursor.execute(
            "UPDATE simulated_applicant_data SET Application_status = %s, Last_Updated = now() WHERE App_ID = %s;",
            ("DOSSIER_READY" if run["run_status"] == "DOSSIER_READY" else "HUMAN_REVIEW", run["app_id"])
        )

    connection.commit()


def write_result_file(app_id, run, dossier):

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{app_id}_dossier.json"
    path.write_text(json.dumps({"run": run, "applicant_dossier": dossier}, indent=2, default=str), encoding="utf-8")
    return path


# ============================================================
# PROCESS ONE APPLICANT
# ============================================================

def process_applicant(connection, minio_client, app_id, force=False):

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

    status = applicant.get("application_status")
    print(f"[1] Applicant {applicant['app_id']}, status {status}")

    if status != "COMPLETE" and not force:
        print("    Not COMPLETE. Skipped (use --force to summarize again).")
        write_audit(connection, app_id, "SKIPPED_NOT_COMPLETE", {"status": status})
        return "SKIPPED"

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
    pages, load_problems = load_pages(minio_client, allowed)
    missing = missing_required_documents(pages)

    run = {
        "app_id": app_id,
        "documents_sent": documents_available(pages),
        "documents_withheld": withheld_log,
        "policies_retrieved": [],
        "attempts": 0,
    }

    if missing:
        print(f"    ✗ Required documents unavailable: {missing}. Model NOT called → human review.")
        run.update(
            run_status="HUMAN_REVIEW_MISSING_DOCUMENTS",
            validation={"missing_required": missing, "load_problems": load_problems},
            runtime_seconds=round(time.time() - started, 1),
        )
        save_run(connection, run)
        write_result_file(app_id, run, None)
        write_audit(connection, app_id, run["run_status"], run["validation"])
        return run["run_status"]

    # Code-only guards: the personal statement's text (for leak detection)
    # and the applicant's restricted values. Never sent to the model.
    essay_shingles = set()
    for d in withheld:
        if withhold_reason(d) == ESSAY_REASON:
            try:
                for page in render_pdf(download_pdf(minio_client, d["object_key"]), zoom=0.2):
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
    policies = retrieve_policies(connection, applicant)
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
            locations, policy_ids, guards, section_log
        )
        attempts_total += attempts

        if errors:
            failed[section] = {"errors": errors, "output": output}
        else:
            sections[section] = output

    if not failed:
        output, errors, attempts = run_section(
            "policy", build_policy_prompt(applicant, policies, sections, pages), None,
            all_locations, policy_ids, guards, section_log
        )
        attempts_total += attempts
        if errors:
            failed["policy"] = {"errors": errors, "output": output}
        else:
            sections["policy"] = output

    if not failed:
        output, errors, attempts = run_section(
            "synthesis", build_synthesis_prompt(applicant, sections), None,
            all_locations, policy_ids, guards, section_log
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
        },
    )

    dossier = None

    if failed:
        run["run_status"] = "HUMAN_REVIEW_AI_FAILED"
        run["failed_output"] = {"completed_sections": sections, "failed_sections": failed}
        print(f"[6] ✗ Section(s) failed validation twice: {', '.join(failed)} → human review")
    else:
        run["run_status"] = "DOSSIER_READY"
        dossier = build_dossier(applicant, sections)
        generated_at, updated_at = save_dossier(connection, dossier)
        dossier["generated_at"], dossier["updated_at"] = generated_at, updated_at
        print(f"[6] ✓ All sections passed validation ({len(dossier['evidence_map'])} citations checked)")
        print(f"[7] Dossier assembled: {len(dossier['review_notes'])} review note(s)")

    save_run(connection, run)
    path = write_result_file(app_id, run, dossier)
    write_audit(connection, app_id, run["run_status"], {"attempts": attempts_total, "failed": list(failed)})

    target = "applicant_dossier + dossier_generation_runs" if dossier else "dossier_generation_runs only"
    print(f"[8] Saved {run['run_status']} → {target}, {path.relative_to(ROOT)}")
    print(f"    Total time {run['runtime_seconds']}s")

    return run["run_status"]


# ============================================================
# MAIN
# ============================================================

def load_affected_ids(cli_ids):

    if cli_ids:
        return cli_ids

    handoff = ROOT / "affected_ids.json"
    if handoff.exists():
        return json.loads(handoff.read_text())

    return ["APP_001"]


def main():

    parser = argparse.ArgumentParser(description="EAOS summarizing agent (RAG + Qwen3-VL) → applicant dossier")
    parser.add_argument("app_ids", nargs="*", help="Applicant IDs (default: affected_ids.json, else APP_001)")
    parser.add_argument("--force", action="store_true", help="Summarize even if status is not COMPLETE")
    args = parser.parse_args()

    affected_ids = load_affected_ids(args.app_ids)

    print("\n========================================")
    print("EAOS SUMMARIZING AGENT (RAG + QWEN3-VL)")
    print("========================================")
    print(f"Model: {VLM_MODEL}   Embeddings: {EMBED_MODEL}")
    print(f"Applicants: {affected_ids}")

    connection = connect_postgres()

    try:
        ensure_output_tables(connection)
        minio_client = connect_minio()

        results = {}

        for app_id in affected_ids:
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
            print(f"  {app_id:<10} {result}")

        print("\n[HARD STOP] Dossiers are advisory. An admissions officer makes every decision.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
