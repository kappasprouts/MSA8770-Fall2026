# Riverview Admissions — End-to-End System Overview

**Status:** Updated for the APP_012 summarizing-agent validation (October 2026).  
**Scope:** Summarizing pipeline, its storage and policy dependencies, and the Next.js review UI. UI behavior described below is the intended behavior from the existing project documentation; the October APP_012 test verified the summarizing pipeline, **not** an end-to-end UI test.

## 1. Architecture at a glance

```text
Simulated applicant ingestion (separate pipeline)
  CommonApp CSV + applicant PDF folders
           |
           v
PostgreSQL: applicants (base record, document metadata, status)
MinIO: original applicant PDFs
           |
           v
ai_agent/summarizing_agent.py
  - Select permitted documents and pages; withhold restricted material
  - Render PDFs as page images (Qwen3-VL)
  - Retrieve applicable policies from PostgreSQL/pgvector
  - Academic, engagement, recommendation, supplement sections
  - Build a verified evidence registry
  - Policy alignment assessment using the registry
  - Holistic synthesis (advisory only)
  - Validate structure, citations, content, and policy-evidence relevance
  - Retry rejected sections once; stop and flag unresolved failures
           |
           v
PostgreSQL: applicant_dossier, dossier_generation_runs,
            summary_audit_log; applicant status
Local: output/ai_agent/<APP_ID>_dossier.json (snapshot)
           |
           |
           v
Next.js ui/: dossier + PDF viewer + evidence-based Q&A
           |
           v
Human review: admissions officers retain decisions
```

The summarizing agent is a **scheduled/batch-compatible backend component**, not an admissions decision maker. The wider project's ingestion scheduler is separate. The local result JSON is a debugging/export artifact; the UI designs use live PostgreSQL data, and the Next.js document viewer uses MinIO.

## 2. Current components and responsibilities

| Component | Responsibility | Main dependencies / outputs |
|---|---|---|
| `summarizing_agent.py` | Produces and validates a policy-grounded dossier from one applicant's permitted PDF pages | PostgreSQL `applicants` and policy chunks; MinIO PDFs; Ollama `qwen3-vl:8b-instruct`; writes dossier, run history, audit events, and local JSON |
| `create_pgvector_once.py` | Current one-time policy-store loader, replacing Theresa's earlier setup for this branch | `policy/riverview_admissions_policy.txt`; PostgreSQL/pgvector policy store |
| `tests/ai_agent/test_academic_only.py` | Isolated academic extraction and validation script | Reads applicant and MinIO PDFs; calls Qwen; prints output; does not save dossier or update applicant status |
| `ui/` | Next.js applicant dossier, original document viewer, and Q&A prototype | PostgreSQL for dossier/applicant data, MinIO for PDF bytes, Ollama for Q&A |
| `SYSTEM_OVERVIEW.md` | Architectural overview | This file |
| `TESTING_GUIDE.md` | Reproducible backend and UI checks | Companion guide |

**Do not use in this branch:** `setup/3_create_policy_store.py` and `data/policies.yaml`. Those are Theresa's older policy-store approach; they are not part of the current setup. The source policy for the replacement loader is `policy/riverview_admissions_policy.txt`.

## 3. Data flow and guardrails

1. **Applicant selection:** Fetch an applicant from PostgreSQL. Normally process only `READY_FOR_REVIEW`; use `--force` when deliberately regenerating an existing dossier.
2. **Document selection:** Normalize the applicant's document metadata, split allowed/withheld documents, download allowed PDFs from MinIO, and render page images. For APP_012, the successful run used five PDFs and seven rendered pages; the CommonApp personal-essay page was not sent to Qwen.
3. **Policy retrieval:** Retrieve relevant policy chunks from pgvector. APP_012 retrieved 12 policies in the verified run.
4. **Section extraction:** Qwen3-VL produces academic, engagement, recommendation, and supplement JSON. The academic prompt separately requests unweighted GPA, weighted GPA, SAT, ACT, and relevant coursework evidence.
5. **Evidence registry:** Preserve the source document, page, exact quotation, and verification status. `TEXT_VERIFIED` indicates a quotation checked against available text; `UNVERIFIED_IMAGE_SOURCE` indicates evidence from image-only content requiring human caution.
6. **Policy assessment:** Assess alignment using retrieved policies and section evidence. The policy step receives evidence IDs and is checked for valid IDs and metric relevance for `POL-002` (unweighted GPA), `POL-004` (SAT), and `POL-005` (ACT). This targeted check does not prove every policy finding semantically correct.
7. **Synthesis:** Produce a non-decisional holistic assessment. The agent must not recommend admit/deny/waitlist or use excluded personal-essay content.
8. **Validation and failure handling:** Validate required fields, nonempty narratives, evidence/source references, restricted content, and relevant policy citations. A failed section is retried once with the specific validation errors. Persistent failure results in a validation-failed run for human review rather than a ready dossier.
9. **Persistence:** On success, upsert `applicant_dossier`, record `dossier_generation_runs` and `summary_audit_log`, write a local JSON snapshot, and mark the applicant `DOSSIER_READY`. A failed run is logged and must not be mistaken for a ready dossier.

## 4. How to run the verified summarizing-agent path

Use the project root `MSA8770-Fall2026` as the working directory. Ensure PostgreSQL, MinIO, and Ollama are already running and populated by the separate ingestion process. Configuration and credentials must come from the project's existing environment; do not commit real `.env` files.

```bash
# Check that Ollama has the required local models
ollama list

# Syntax check
python -m py_compile ai_agent/summarizing_agent.py

# Focused academic extraction test (read-only with respect to dossier/status)
python tests/ai_agent/test_academic_only.py

# Full dossier generation for an already-processed applicant
python ai_agent/summarizing_agent.py APP_012 --force
```

Use the full `--force` run intentionally: it writes a new run record and replaces the local `output/ai_agent/APP_012_dossier.json` snapshot. The earlier successful backup in `output/ai_agent/APP_012_dossier_before_fix.json` is a **local test artifact**, not a file to commit.

For a new eligible applicant, use the standard invocation without `--force`:

```bash
python ai_agent/summarizing_agent.py APP_012
```

This will skip an applicant that is not `READY_FOR_REVIEW`. Use an appropriate real applicant ID for other cases. See `TESTING_GUIDE.md` for expected outputs and policy-citation verification.

### One-time policy store

The active loader is `ai_agent/create_pgvector_once.py`, using `policy/riverview_admissions_policy.txt`. Run it only when initializing/rebuilding the policy store, after reviewing its configuration and ensuring the database is available. Do **not** run the unused `setup/3_create_policy_store.py` or use `data/policies.yaml` for this branch.

> **UI Testing Status — NOT TESTED**
>
> The Streamlit and Next.js UI components are documented for architectural
> context only. They were not developed, modified, or tested as part of
> this summarizing agent implementation.
>
> The successful APP_012 validation applies only to the summarizing agent
> backend, including document processing, Qwen3-VL summarization,
> pgvector policy retrieval, evidence validation, and dossier persistence.
>
> UI integration and end-to-end functionality remain unverified.

## 5. Review UI

From the repository root, run `cd ui && npm run dev` (typically port 3000). The Next.js UI shows saved dossiers, opens original PDFs from MinIO, and answers evidence-grounded questions through Ollama. Configure `ui/.env.local` from `ui/.env.local.example` without committing credentials.

The October APP_012 pipeline success does not by itself verify UI behavior. Follow the UI checks in `TESTING_GUIDE.md` before claiming that integration is complete.

## 6. Verified October 2026 baseline and limitations

For **APP_012**, the full run completed in **449.1 seconds** (~7m 29s). All six sections passed on their first attempt, **121 citations were checked**, and the dossier had **zero review notes**. The saved status was `DOSSIER_READY`.

The following targeted policy references were manually inspected in the generated JSON:

| Policy | Finding | Evidence ID | Quotation | Source |
|---|---|---|---|---|
| `POL-002` | Unweighted GPA 3.97 | `E001` | `Unweighted GPA 3.97` | `CommonApp.pdf`, p. 2 |
| `POL-004` | SAT superscore 1530 | `E003` | `Superscored SAT Score 1530` | `CommonApp.pdf`, p. 2 |
| `POL-005` | ACT superscore 35 | `E004` | `Superscored ACT Score 35` | `CommonApp.pdf`, p. 2 |

These quotes were marked `TEXT_VERIFIED`. They demonstrate that the earlier **wrong-metric citation** problem was corrected for APP_012. They do not establish accuracy across all applicants or every policy. The PostgreSQL collation-version warning seen during testing was nonblocking; it should be addressed separately by the database owner after evaluating the proper rebuild/refresh procedure.

## 7. Related documents

- `TESTING_GUIDE.md` — backend validation and UI acceptance tests.
- `ui/README.md` — Next.js setup and troubleshooting (review against current code).
- The repository-level README — ingestion and infrastructure setup; verify its instructions against the active branch before use.
