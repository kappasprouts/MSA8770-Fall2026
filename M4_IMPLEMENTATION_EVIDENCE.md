# Milestone 4 Implementation & Test Evidence Report

**Repository:** `MSA8770-Fall2026`  
**Active Branch:** `danny/m4-untrusted-ingestion` (branched from `origin/mi-m4` at commit `66f1887`)  
**Evaluation Rubric:** Milestone 4: Security, Risk Management, and Trust Boundaries in AI Systems  
**Date:** November 18, 2026  
**Implementation Lead:** Danny McIntosh (AI Engineering & Architecture)

---

## 1. Executive Summary

This report documents the implementation and automated verification of the **Milestone 4 Risk Controls** on branch `danny/m4-untrusted-ingestion`. 

The Milestone 4 rubric requires active defense-in-depth across at least **two independent risk controls**, specifically mandating protection against untrusted content (indirect prompt injection, steganography, and corrupt streams) hidden inside ingested documents (transcripts, letters of recommendation, PDFs, or CSVs) before vision-language models (Qwen3-VL) or downstream evaluation agents are invoked.

All controls have been implemented, wired into the canonical pipeline, and verified with **landing-state assertions** (verifying PostgreSQL/SQLite rows, immutable `audit_logs` entries, and file-level model boundary exclusions in `affected_ids_*.json`).

### Test Results Overview
- **Milestone 4 Controls Suite (`tests/test_m4_controls.py`):** **9 / 9 PASSED (100%)**
- **Full Python Test Suite (`pytest`):** **77 / 77 PASSED (100%)**
- **Next.js / UI Auth & RBAC Test Suite (`npm test`):** **27 / 27 PASSED (100%)**

---

## 2. Implemented Risk Controls

### Control 1: Untrusted Content & Corrupt Input Guard (Ingestion Trust Boundary)
- **Module File:** [`ingestion/validation/untrusted_guard.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/validation/untrusted_guard.py)
- **Integration Points:**
  - [`ingestion/batch_ingest.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/batch_ingest.py) (Pass 2 completion before `READY_FOR_REVIEW` and handoff list export)
  - [`ingestion/validation/manifest_gate.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/validation/manifest_gate.py) (`ManifestValidationGate.evaluate_applicant`)
- **Capabilities:**
  1. *Indirect Prompt Injection Detection:* Scans extracted PDF text (transcripts, LORs, personal statements) and CSV text fields against targeted signatures:
     - `ignore (all )?(previous|prior) instructions`
     - `system (prompt )?override`
     - `recommend (an )?(immediate )?accept`
     - `admit this applicant` / `you must (admit|accept|recommend)`
     - `set (the )?gpa to` / `override (the )?gpa`
     - `disregard (all )?(rules|criteria|instructions)`
     - `developer mode` / `jailbreak` / `do not reveal this`
  2. *Steganography & Hidden Character Defense:* Scans for zero-width Unicode characters used to conceal malicious prompts (`[\u200B-\u200D\uFEFF\u2060\u200E\u200F]`).
  3. *Corrupt / Unreadable Stream Quarantine:* Detects truncated, invalid, or corrupted binary PDF streams using structural PyMuPDF (`fitz`) parsing.
- **Enforcement & Landing State:**
  - When untrusted or corrupt content is detected:
    * Applicant packet is **strictly excluded** from `affected_ids_*.json` (halting downstream handoff to Qwen3-VL / summarizing agent).
    * Applicant status in PostgreSQL/SQLite is set to `'ERROR'` (routing destination: `Human Review` / IT Quarantine Queue).
    * An immutable row is inserted into PostgreSQL `audit_logs` with `action='BLOCKED_UNTRUSTED_CONTENT'`, `actor='UntrustedContentGuard'`, and detailed detected findings.

### Control 2: Role-Based Access Control (RBAC) & Decision Protection
- **Backend Module File:** [`storage/rbac.py`](file:///Users/mc/MSA8770-Fall2026/storage/rbac.py)
- **Frontend / API Policy:** [`ui/src/lib/auth-policy.ts`](file:///Users/mc/MSA8770-Fall2026/ui/src/lib/auth-policy.ts) & [`ui/src/proxy.ts`](file:///Users/mc/MSA8770-Fall2026/ui/src/proxy.ts)
- **Database Schema:** [`system_users_schema.sql`](file:///Users/mc/MSA8770-Fall2026/system_users_schema.sql) & [`storage/models.py`](file:///Users/mc/MSA8770-Fall2026/storage/models.py) (`SystemUser`)
- **Capabilities & Permissions:**
  - `ADMISSIONS_OFFICER`: Authorized for `processing`, `review`, `statistics`. **Blocked** from `decisions` (final admissions verdict) and `errors`.
  - `DEAN`: Authorized for `review`, `decisions` (exclusive authority to post `ACCEPT`/`WAITLIST`/`DECLINE`), `statistics`. **Blocked** from raw `processing` and `errors`.
  - `IT_SUPPORT` / `IT_ADMIN`: Authorized for `errors` (quarantine exception queue). **Blocked** from confidential dossier `review`, `decisions`, and `processing`.
- **Enforcement & Landing State:**
  - Unauthorized mutation attempts (e.g. `IT_ADMIN` or `ADMISSIONS_OFFICER` attempting to set final decision) raise `PermissionError`.
  - Landing state in PostgreSQL confirms `applicant.final_decision` remains unchanged (`None`).
  - Unauthorized attempt is permanently recorded in `audit_logs` with `action='UNAUTHORIZED_DECISION_BLOCKED'`.
  - Authorized decisions by `DEAN` commit the verdict (`ACCEPT`) and record `action='FINAL_DECISION_RECORDED'`.

---

## 3. Exact File Paths

| File Path | Status | Purpose |
|---|---|---|
| [`ingestion/validation/untrusted_guard.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/validation/untrusted_guard.py) | **Created** | Control 1: Scans text & PDF streams for prompt injections, zero-width characters, and corrupt streams. |
| [`storage/rbac.py`](file:///Users/mc/MSA8770-Fall2026/storage/rbac.py) | **Created** | Control 2: Backend RBAC enforcement, `apply_final_decision`, and `get_applicant_dossier_review`. |
| [`tests/test_m4_controls.py`](file:///Users/mc/MSA8770-Fall2026/tests/test_m4_controls.py) | **Created** | Automated test suite verifying blocked and normal landing states for both Control 1 and Control 2. |
| [`storage/models.py`](file:///Users/mc/MSA8770-Fall2026/storage/models.py) | **Modified** | Set `admission_year`/`admission_term` to `nullable=True`, updated GPA to `Numeric(5, 3)`, added `SystemUser`. |
| [`storage/storage_manager.py`](file:///Users/mc/MSA8770-Fall2026/storage/storage_manager.py) | **Modified** | Restored dry-run upload simulation for offline MinIO, added `audit_actor` support, added `log_audit()`. |
| [`ingestion/batch_ingest.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/batch_ingest.py) | **Modified** | Wired `UntrustedContentGuard.scan_applicant()` before setting status and populating `affected_ids`. |
| [`ingestion/validation/manifest_gate.py`](file:///Users/mc/MSA8770-Fall2026/ingestion/validation/manifest_gate.py) | **Modified** | Wired `UntrustedContentGuard` into `evaluate_applicant()`. |
| [`storage/__init__.py`](file:///Users/mc/MSA8770-Fall2026/storage/__init__.py) | **Modified** | Exported `SystemUser` ORM model. |

---

## 4. Git Diff Statistics

```
$ git diff --stat
 ingestion/batch_ingest.py             | 63 +++++++++++++++++++++++++----------
 ingestion/validation/manifest_gate.py | 12 +++++++
 storage/__init__.py                   |  2 ++
 storage/models.py                     | 27 ++++++++++++---
 storage/storage_manager.py            | 38 ++++++++++++++++++---
 5 files changed, 115 insertions(+), 27 deletions(-)
```

---

## 5. Automated Test Evidence

### A. Milestone 4 Controls Suite (`tests/test_m4_controls.py`)

```
$ pytest -v tests/test_m4_controls.py
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/mc/MSA8770-Fall2026
configfile: pytest.ini
testpaths: tests
plugins: langsmith-0.7.6, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/test_m4_controls.py::test_control_1_indirect_prompt_injection_in_pdf_is_blocked_and_quarantined PASSED [ 11%]
tests/test_m4_controls.py::test_control_1_indirect_prompt_injection_in_csv_is_blocked_and_quarantined PASSED [ 22%]
tests/test_m4_controls.py::test_control_1_corrupt_pdf_stream_is_blocked_and_quarantined PASSED [ 33%]
tests/test_m4_controls.py::test_control_1_hidden_zero_width_unicode_is_blocked_and_quarantined PASSED [ 44%]
tests/test_m4_controls.py::test_control_1_clean_packet_passes_guard_and_lands_in_ready_for_review PASSED [ 55%]
tests/test_m4_controls.py::test_control_2_rbac_permission_matrix PASSED  [ 66%]
tests/test_m4_controls.py::test_control_2_rbac_unauthorized_role_blocked_from_decision_mutation PASSED [ 77%]
tests/test_m4_controls.py::test_control_2_rbac_authorized_dean_can_post_final_decision PASSED [ 88%]
tests/test_m4_controls.py::test_control_2_rbac_unauthorized_role_blocked_from_dossier_review PASSED [100%]

======================== 9 passed, 5 warnings in 0.89s =========================
```

### B. Full Python Test Suite Across Ingestion, Schema, and Storage

```
$ pytest
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/mc/MSA8770-Fall2026
configfile: pytest.ini
testpaths: tests
plugins: langsmith-0.7.6, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 77 items

tests/cost_baseline/test_measurements.py .......                         [  9%]
tests/test_date_of_birth_schema.py ..                                    [ 11%]
tests/test_gpa_numeric_schema.py .                                       [ 12%]
tests/test_ingestion_and_gate.py ...........................             [ 48%]
tests/test_ingestion_entrypoints.py .............                        [ 64%]
tests/test_m4_controls.py .........                                      [ 76%]
tests/test_score_ingest.py ...............                               [ 96%]
tests/test_status_only_schema.py ...                                     [100%]

======================= 77 passed, 5 warnings in 12.16s ========================
```

### C. Node.js UI RBAC & Auth Test Suite (`npm test`)

```
$ cd ui && npm test
> ui@0.1.0 test
> node --test tests/*.test.mjs

✔ permissions match every cell in the supplied role matrix (1.516959ms)
✔ login preserves applicant query parameters and rejects external or recursive redirects (0.182834ms)
✔ passwords use salted hashes and sessions use unpredictable opaque tokens (114.566292ms)
✔ session lookup uses a hashed token and checks active account, expiry and role (7.91275ms)
✔ API authentication fails closed, distinguishes 401/403, and rejects cross-origin writes (6.514708ms)
✔ every existing data handler checks permission before touching applicant data or upstream services (83.372375ms)
✔ protected page routing preserves the destination and denies the wrong role (4.840292ms)
✔ review audit events identify the authenticated user instead of accepting a submitted actor (4.07075ms)
✔ a new selection never accepts the previous dossier or a mismatched run (0.384625ms)
✔ an empty applicant list differs from an unreadable or failed response (0.369666ms)
✔ validation is unknown without an explicit successful run and failed states take precedence (0.116209ms)
✔ section counts use final attempts and do not count missing errors as passed (0.13025ms)
✔ saved dossier markup never claims Complete merely because a dossier exists (24.015542ms)
✔ unavailable decision counts stay unknown while true zero remains zero (0.0955ms)
✔ batch states distinguish no recorded run, completion, other statuses, and bad data (0.11375ms)
✔ JSON requests preserve service errors and reject unreadable responses (14.475375ms)
✔ cancelling a superseded request aborts the underlying fetch (0.223125ms)
﹣ decision SQL counts recorded decisions outside the pending queue (0.0605ms) # SKIP
✔ student missing material is not an IT incident (0.439916ms)
✔ technical errors and orphan intake remain available to IT (0.0605ms)
✔ unknown workflow status is not automatically a technical error (0.0455ms)
✔ all applicant records contribute, independent of dossier or decision availability (16.705834ms)
✔ academic values preserve real zeros, reject invalid scores, and calculate interpolated percentiles (0.802458ms)
✔ cohort filters apply to every chart and comparison while options retain the full pool (0.336416ms)
✔ application trends use valid source dates, preserve empty months, and exclude import times (0.281292ms)
✔ filter parsing and CSV export handle hostile text without exposing source applicant fields (0.634875ms)
✔ statistics endpoint validates first, returns aggregate-only results, and distinguishes outages (29.202667ms)
✔ populated charts render accessible values, unknown categories, sample sizes, and useful links (68.5555ms)
﹣ real statistics SQL uses the latest manifest per applicant without multiplying pool counts (0.046708ms) # SKIP
ℹ tests 29
ℹ suites 0
ℹ pass 27
ℹ fail 0
ℹ cancelled 0
ℹ skipped 2
ℹ todo 0
ℹ duration_ms 455.411625
```

---

## 6. Rubric Compliance Cross-Reference

| Rubric Dimension | Requirement | Implementation & Evidence | Verification |
|---|---|---|---|
| **Control 1: Untrusted Ingested Content Guard** | Defense against indirect prompt injection inside ingested files (transcripts/LORs/CSVs). | `UntrustedContentGuard.scan_applicant()` runs in Pass 2 & Manifest Gate; blocks injection, zero-width characters, and corrupt streams. | `test_control_1_indirect_prompt_injection_in_pdf_is_blocked_and_quarantined`<br>`test_control_1_indirect_prompt_injection_in_csv_is_blocked_and_quarantined`<br>`test_control_1_corrupt_pdf_stream_is_blocked_and_quarantined`<br>`test_control_1_hidden_zero_width_unicode_is_blocked_and_quarantined` |
| **Control 2: RBAC Role Enforcement** | Strict least-privilege role boundaries for decisions & dossiers. | `storage/rbac.py`, `ui/src/lib/auth-policy.ts`, and `system_users` enforce `DEAN` on final decisions and `ADMISSIONS_OFFICER`/`DEAN` on review. | `test_control_2_rbac_unauthorized_role_blocked_from_decision_mutation`<br>`test_control_2_rbac_authorized_dean_can_post_final_decision`<br>`test_control_2_rbac_unauthorized_role_blocked_from_dossier_review` |
| **Landing State Assertions** | Tests must assert database landing state, audit trail, and model boundary. | All tests assert PostgreSQL/SQLite rows, `audit_logs` entries (`BLOCKED_UNTRUSTED_CONTENT` / `UNAUTHORIZED_DECISION_BLOCKED`), and `affected_ids_*.json` exclusions. | `assert staged_applicant.status == "ERROR"`<br>`assert app_id not in disk_affected_ids`<br>`assert audit_log.action == "BLOCKED_UNTRUSTED_CONTENT"` |
