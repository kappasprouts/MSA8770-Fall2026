# Full Pipeline Test — 2026-10-09

**Tester:** Tran Le
**Code tested:** `maria/pipeline` at commit `847ed1b` ("Add Next.js admissions review chat UI"). The test ran in a separate local checkout of `maria/pipeline`; this record is stored on `tran/summarizing-agent` for reference. The code on `tran/summarizing-agent` differs and was **not** what ran.
**Mode:** Live services (no dry-run). Ingestion ran with `--require-postgresql --require-object-storage`.

## Summary

| Stage | Result |
|---|---|
| Ingestion + manifest gate, `batch_01` | ✅ 10 processed: 9 `READY_FOR_REVIEW`, 1 `AWAITING_MATERIALS` |
| Ingestion + manifest gate, `batch_02` | ✅ 10 processed: 7 `READY_FOR_REVIEW`, 1 `AWAITING_MATERIALS`, 2 `INCOMPLETE` |
| Policy vector store rebuild | ✅ 21 chunks (`POL-001` – `POL-021`) |
| Summarizing agent (2 applicants) | ⚠️ Ran end to end; both runs `AI_VALIDATION_FAILED` on the academic section |
| Chat UI | ✅ Started and served `http://localhost:3000` (UI test cases in `TESTING_GUIDE.md` Part C not run) |

The pipeline works end to end against live PostgreSQL, MinIO and Ollama. The summarizer's validation guardrail correctly rejected academic sections whose quotes cited the wrong page; no unverified dossier was saved.

## Environment

| Service | How it ran | Endpoint |
|---|---|---|
| PostgreSQL 16 + pgvector | Docker container `msa8770-postgres` (`pgvector/pgvector:pg16`), DB `riverview_admissions` | `localhost:5432` |
| MinIO | Native Homebrew binary (`minio 2025-10-15T17-29-55Z`); `minio/minio` is no longer pullable from Docker Hub or Quay | `localhost:9000` (console `:9001`), bucket `admissions-raw-docs` |
| Ollama | `ollama serve` with `qwen3-vl:8b-instruct` and `nomic-embed-text` | `localhost:11434` |
| Python | 3.x virtualenv `.venv` with `requirements.txt` | — |
| Node.js | v24.12.0 for `chat-ui` | `localhost:3000` |

Host: macOS (Apple Silicon), local model inference.

## Steps and commands

Run from the repository root with `.venv` active.

```bash
# 1. Ingestion + manifest gate (strict, live storage)
python3 run_ingestion_check.py --input-dir batch_01 --require-postgresql --require-object-storage
python3 run_ingestion_check.py --input-dir batch_02 --require-postgresql --require-object-storage

# 2. Rebuild the policy store. The database still held the retired
#    POL-DATE-01-style chunks from policies.yaml; the agent expects POL-0xx.
python summarizing_agent/create_pgvector_once.py

# 3. Summarizing agent checks (TESTING_GUIDE.md A1)
python -m py_compile summarizing_agent/summarizing_agent.py
python -c "import summarizing_agent.tests.test_academic_only; print('Imports successful')"

# 4. Summarizing agent (stopped after two applicants to keep the test short)
python summarizing_agent/summarizing_agent.py APP_001 APP_002

# 5. Review UI
cd chat-ui && npm install && cp .env.local.example .env.local && npm run dev
```

## Ingestion results

Full reports: [`ingestion_batch_01_report.txt`](ingestion_batch_01_report.txt) (run `20261009T215053247148Z_dc6de64f`) and [`ingestion_batch_02_report.txt`](ingestion_batch_02_report.txt) (run `20261009T215101225729Z_73bbafa8`).

| Applicant | Status | Note |
|---|---|---|
| APP_001 – APP_009 | `READY_FOR_REVIEW` | Complete |
| APP_010 | `AWAITING_MATERIALS` | Missing transcript |
| APP_011 | `AWAITING_MATERIALS` | Missing transcript |
| APP_012 – APP_017, APP_020 | `READY_FOR_REVIEW` | Complete |
| APP_018 | `INCOMPLETE` | Missing `Email_Address` |
| APP_019 | `INCOMPLETE` | Missing `Last_Name` |

Verified after the run: all 20 applicants present in PostgreSQL `applicants`, and their PDFs present in MinIO under `admissions-raw-docs/{app_id}/`.

## Summarizing agent results

Both applicants: 10 documents, 8 sent to the model, 2 withheld (`personal_statement.pdf` under POL-ESSAY-01; `common_app_application.pdf` for restricted data). 9 policies retrieved: POL-001, 003, 006, 007, 009, 012, 013, 014, 015.

| Applicant | Runtime | Academic | Engagement | Recommendation | Supplement | Run status |
|---|---|---|---|---|---|---|
| APP_001 | 412.8 s | ✗ failed twice | ✓ | ✓ | ✓ | `AI_VALIDATION_FAILED` |
| APP_002 | 435.4 s | ✗ failed twice | ✓ | ✓ | ✓ | `AI_VALIDATION_FAILED` |

Policy and synthesis sections did not run because the academic section failed. The applicants remain `READY_FOR_REVIEW`.

**Validation errors (final attempt):**

- APP_001: quote `"Cumulative weighted GPA 4.68"` is not on `application_form.pdf` page 1.
- APP_002: quotes `"AP English Language Regular/Honors 1.0 B+"`, `"Calculus Regular/Honors 1.0 A-"`, `"U.S. History Regular/Honors 1.0 A-"` are not on `transcript.pdf` page 2.

**Root cause check (APP_001):** Extracted PDF text shows `Cumulative weighted GPA … 4.68`, `English I` and `Geometry` on **transcript page 1**. The model attributed them to the application form and transcript page 2. The validator was correct; the failure is a page-attribution error by `qwen3-vl:8b-instruct` on the two-page `batch_01` transcripts.

## Setup issues found (not fixed here)

1. On `maria/pipeline`, `requirements.txt` is missing `psycopg2-binary`, `pymupdf` and `python-dotenv`, which `summarizing_agent/summarizing_agent.py` imports. They were installed manually for this run.
2. On `maria/pipeline`, `chat-ui/.env.local.example` sets `MINIO_BUCKET=applicant-documents`, but ingestion writes to `admissions-raw-docs` (as `chat-ui/README.md` states). The local `.env.local` used `admissions-raw-docs`.

## Not covered

- Summarizer runs for the other 14 ready applicants (expected ~7 min each, ~1 h 50 min total).
- Reference applicant APP_012, which previously passed all 6 sections per `summarizing_agent/docs/SYSTEM_OVERVIEW.md`.
- Chat UI and Streamlit acceptance tests (`TESTING_GUIDE.md` Parts B and C).

## Suggested next steps

1. Run `python summarizing_agent/summarizing_agent.py APP_012` to confirm the known-good baseline still passes on this setup.
2. If it passes, improve page attribution for multi-page transcripts (for example, label each page image with its document and page number in the academic prompt).
