# Integrated ingestion, summarizing agent, and review UI assessment

Reviewed October 9, 2026, at commit `847ed1b7247257dc16d6394ec420f631f17bab81`. Source links now point to the reorganized folders; findings describe the reviewed commit.

**Verdict: the components can exchange data, but the integrated system does not yet work reliably as intended.** Ingestion can stage the supplied batches in PostgreSQL, and explicit applicant selection plus controlled model responses can produce a stored dossier that the UI reads. The default handoff, several supplied applicants, evidence validation, and failure visibility have reproducible defects. A successful APP_012 run does not establish success for the rest of the dataset.

This was a review and testing task. Application source was not changed. The new files here contain the assessment, reproducible probes, and test evidence.

## What was checked

Reviewed the executable ingestion, score-feed, validation, storage, parsing, gateway, summarizing-agent, policy-loader, and Next.js code; setup/configuration, migrations, architecture and testing documentation; and dataset/document contracts. Parsed all **37 tracked Python files** successfully. Opened all **157 tracked PDFs**, containing **210 pages**; none failed PDF opening, and 13 pages had no native text. Opening a PDF is not proof of accurate OCR or model interpretation.

| Check | Result | Scope |
|---|---|---|
| Original pytest suite | **52 passed, 9 failed** | 61 existing tests, collected before review probes were added |
| Added integration/guardrail tests | **5 passed, 20 failed** | 25 targeted cases; failures intentionally demonstrate unmet contracts, not 20 independent defects |
| Next.js production build | **Passed** | Next.js 16.4.0; compilation, TypeScript, static generation and route output |
| ESLint | **Passed** | Actual UI source |
| Batch 01 staging and gate | 10 processed: **9 ready, 1 awaiting materials** | Real temporary PostgreSQL; simulated object storage |
| Batch 02 staging and gate | 10 processed: **7 ready, 1 awaiting materials, 2 incomplete** | Same isolation |
| Policy table and vector retrieval | **Passed as a plumbing check** | Real pgvector; 21 policy chunks with deterministic test vectors, not real semantic embeddings |
| APP_012 dossier persistence | **Passed as a plumbing check** | Real PostgreSQL, real PDF rendering, mocked section responses |
| UI helper/route/component execution | **Completed** | Actual TypeScript code, real isolated PostgreSQL, mocked Ollama/PDF streams |

The passing guardrail controls include APP_012's essay/contact/Hooks filtering, standalone personal-statement withholding, retrying and stopping after two invalid responses, and retaining `UNVERIFIED_IMAGE_SOURCE` for image-only citations. UI controls returned 200 for the dossier, 404 for an unknown applicant, 400 for empty messages, and valid PDF bytes through the mocked document stream.

**Live MinIO and Qwen were not verified during this assessment.** No project containers were running initially. A temporary PostgreSQL/pgvector container was used on `127.0.0.1:25432`, with its own database. Both attempted official MinIO image downloads failed (Docker Hub unavailable; Quay unauthorized). Model responses, embeddings, and object-storage operations were therefore simulated. No real admissions decision was recorded. Browser interactions, GPU inference quality/latency, and live S3 authentication/TLS remain unverified. The temporary container was stopped after testing.

Subsequent live APP_012 testing is recorded in [the live test results](../live_test_setup/TEST_RESULTS.md). That later success does not resolve the defects below.

## Confirmed findings requiring correction

`P1` means it blocks ordinary integration or undermines an explicit factuality/privacy/human-review requirement. `P2` means a narrower correctness, reporting, or setup gap.

### 1. P1 — The default agent invocation does not consume ingestion's handoff

[Agent handoff loader](../../ai_agent/summarizing_agent.py#L1838) reads `output/ingestion/affected_ids.json`, while ingestion emits uniquely named files at the repository/configured output location. There is no `--affected-ids` file argument. With an ingestion artifact containing APP_012 and APP_013, the default loader returns **APP_001** instead. API and scheduler ingestion also deliberately stop before invoking the agent.

**Consequence:** ingestion success alone cannot generate the intended dossiers; a no-argument agent run may process the wrong applicant. Explicit positional applicant IDs work around selection, but do not repair the artifact contract. Provide a validated file-path input and a documented/manual or automatic orchestrator that passes the exact successful run artifact.

### 2. P1 — Supplied ready applicants fail Hooks redaction

[Hooks verification](../../ai_agent/summarizing_agent.py#L611) checks whether the removed value occurs anywhere else on the page. **APP_013, APP_016, and APP_020** have `Hooks: Not provided`, with the same ordinary text in another field. Rendering raises `Hooks redaction verification failed` although ingestion marks them ready. APP_018 also has this rendering problem, but its missing metadata already prevents ordinary handoff.

**Consequence:** three of Batch 02's seven ready applicants cannot reach model inference. Verify redaction of the identified field region; avoid treating another field's identical text as a privacy leak. Preserve conservative handling when actual sensitive material cannot be removed.

### 3. P1 — Separate activities and AP records never reach their model sections

[Section document types](../../ai_agent/summarizing_agent.py#L122) allow only `application_form` for engagement, and `advanced_coursework` for AP material. Ingestion classifies the actual files as `activities_and_awards` and `advanced_coursework_and_ap_scores`; normalization does not reconcile these values.

**Evidence:** both document-selection tests return an empty section input. Every Batch 01 packet's separate activities/AP files appear in the loaded-but-unused evidence. The allowed Batch 01 application form does not contain its separate activities record, and its Common App copy is withheld.

**Consequence:** summaries omit provided engagement/AP information, while `documents_sent` can imply those rendered files were used. Normalize canonical types and map each permitted document to its intended section before recording model inputs.

### 4. P1 — Score-feed changes persist but are invisible to dossier generation

[Image prompt construction](../../ai_agent/summarizing_agent.py#L945) uses the applicant record only for its ID. It does not include the updated SAT/ACT/AP values; policy and synthesis consume the generated document summaries rather than the score-feed record.

**Evidence:** a real PostgreSQL delta raised APP_012's SAT to **1599**, added AP Biology 5, and exported APP_012 for regeneration. Neither new value appeared in the academic prompt. Existing PDFs still contain the earlier information.

**Consequence:** a correctly triggered regeneration can return stale scores. Supply trusted score-feed facts with provenance and reconcile them with dated PDF evidence.

### 5. P1 — Incorrect factual claims can pass “verified” evidence checks

[Quote verification](../../ai_agent/summarizing_agent.py#L1153) compares sets of words/numbers on a page, not the quoted passage or its field association. It accepts **“Unweighted GPA 4.40”** on a page that actually says **“Unweighted GPA 3.97 / Weighted GPA 4.40.”** [Section validation](../../ai_agent/summarizing_agent.py#L1345) also accepts `sat_superscore: 1600` with evidence saying **SAT Score 1200**. Unsupported nonnumeric policies can be marked aligned without evidence.

**Consequence:** materially wrong metrics can enter a supposedly validated dossier. Check contiguous normalized quotations/field-value associations, validate facts against their supporting evidence, and require support or `unclear` for substantive policy findings.

### 6. P1 — Output schemas and admission-language guards are incomplete

[Validator](../../ai_agent/summarizing_agent.py#L1345) checks top-level required keys, not the full schema. It accepts a string in place of `document_facts` and an invalid policy alignment. [Decision patterns](../../ai_agent/summarizing_agent.py#L159) miss **“Admit this applicant”** and **“I recommend admitting the applicant.”** Both passed the validator.

**Consequence:** malformed output and explicit admissions recommendations can be saved as validated. Validate nested types/enums and enforce the human-decision boundary before persistence.

### 7. P1 — Privacy filtering depends on one template and misses an ingestion field

[Application rendering](../../ai_agent/summarizing_agent.py#L663) triggers contact redaction only for the exact case-sensitive heading `Applicant information`. A synthetic page headed `Applicant Information` retains its email address in both rendered content and extracted text. Multiline Hooks redaction removes only the first value line. [Restricted fields](../../ai_agent/summarizing_agent.py#L130) names `primary_phone_number`, whereas the active ingestion table stores `phone_number`.

**Consequence:** a permitted application variant can send restricted material to the model, and the output guard does not recognize the stored phone number. Identify and verify restricted field regions reliably; withhold uncertain pages, handle multiline values, and align field names with the actual schema. The provided APP_012 template passed; that result does not cover other layouts or scanned forms.

### 8. P1 — Failed generation is not a reliable human-review workflow

[Run persistence](../../ai_agent/summarizing_agent.py#L1593) stores an `AI_VALIDATION_FAILED` run but resets the applicant to `READY_FOR_REVIEW`. Document-loading/RAG errors happen before a complete run record exists. [CLI main](../../ai_agent/summarizing_agent.py#L1850) catches applicant errors and returns normally.

**Evidence:** APP_013's real rendering failure produced an `AGENT_ERROR` audit, **zero new generation runs**, and **exit code 0**, with applicant status still ready. A failed regeneration retained the old dossier. The [UI selector](../../ui/src/lib/dossier.ts#L91) selects only `applicant_dossier`, so failed-only applicants are invisible. [Snapshot rendering](../../ui/src/components/dossier/SnapshotCard.tsx#L24) labels sections “Complete” whenever an older dossier exists, even when the latest run failed. Unchanged ingestion replay also resets a previously `DOSSIER_READY` applicant to `READY_FOR_REVIEW` and exports it again.

**Consequence:** monitoring reports success, failures may never reach reviewers, and stale dossiers can be paired with unrelated latest-run metadata. Persist every outcome with an explicit error/review state, return unsuccessful CLI status when required work fails, expose failed applicants, and link dossier content to its successful generation run/input version.

### 9. P1 — Chat accepts a caller-supplied system message

[Chat route](../../ui/src/app/api/chat/route.ts#L28) checks only that `messages` is a nonempty array, then forwards its objects verbatim after its own system prompt. TypeScript interfaces do not validate JSON at runtime.

**Evidence:** a request containing `role: "system"` returned 200 and forwarded roles **system, system, user**. A controlled model reply **“Admit this applicant.”** was returned without rejection. The latter proves missing server-side output enforcement; it does not claim a real Qwen model produced that reply.

**Consequence:** callers can inject privileged instructions and receive responses violating the advisory requirement. Validate roles/content/size, reconstruct allowed user/assistant messages, and validate model replies before delivery. Also handle JSON `null`, which currently throws instead of returning 400.

### 10. P1 — Database constraints contradict the gate's required fields

[Applicant schema](../../storage/models.py#L90) requires admission year and term, while the configured gate requires only ID, first/last name, birth date, and email. Minimal valid records fail storage before gate evaluation. Eight of the nine original test failures hit this incompatibility.

**Evidence:** the same five-field fixture failed real PostgreSQL with `NotNullViolation: admission_year`. Decide whether these fields are required, then align schema, gate, CSV handling, tests, migrations, and documentation. Incomplete records should be storable if the intended behavior is to route them for updates.

### 11. P2 — Fresh schema loses documented GPA precision

[GPA columns](../../storage/models.py#L64) are `NUMERIC(3,2)`, although parsing, documentation, the migration, and the existing test specify `NUMERIC(5,3)`. A fresh PostgreSQL row stored input **3.8645** as **3.86**. The original GPA schema test fails.

**Consequence:** fresh and migrated databases behave differently and lose information. Align the ORM with the intended precision and verify fresh and upgraded schemas.

### 12. P1 — Document bucket configuration disagrees across components

Ingestion/agent use `admissions-raw-docs`; the [UI default](../../ui/src/lib/dossier.ts#L25) and `.env.local.example` use `applicant-documents`. Agent normalization and UI document lookup discard each document's stored bucket and download using one global bucket.

**Evidence:** the actual UI PDF route requested **applicant-documents** for metadata explicitly naming **admissions-raw-docs**. A contract test confirms the agent drops historical bucket metadata.

**Consequence:** copying the example configuration yields broken document viewing, and late/historical objects in other buckets are inaccessible. Unify defaults and preserve validated per-document bucket/key pairs.

### 13. P2 — The missing-score policy fallback is overwritten

`validate_policy_evidence_match` is defined twice ([first definition](../../ai_agent/summarizing_agent.py#L1256), [second definition](../../ai_agent/summarizing_agent.py#L1305)). The second removes handling for absent evidence with an `unclear` alignment. Consequently a legitimately missing optional SAT/GPA/ACT metric can fail both attempts even when the model follows its correction instructions.

**Consequence:** test-optional packets can be rejected when those policies are retrieved. Keep one implementation and test empty evidence for each permitted alignment.

### 14. P2 — Setup and policy/context contracts have drifted

[Requirements](D:/Users/miwi/git/MSA8770-Fall2026/requirements.txt) omits `psycopg2-binary`, `PyMuPDF`, and `python-dotenv`, all imported unconditionally by the new agent. The default [storage engine](../../storage/database.py#L8) also selects psycopg2 for a plain `postgresql://` URL although requirements declares psycopg v3. Testing needed additional packages. Ingestion reads `DATABASE_URL`; agent/UI use separate `POSTGRES_*` settings, so a custom URL alone does not connect all components to the same database.

The handbook/`policy/policies.yaml`, gate configuration, and RAG TXT are different policy sources. For example, the handbook requires an essay and one recommendation, while the current gate requires two recommendations and no essay. The RAG text introduces numeric GPA/SAT/ACT bands and sequential `POL-001` IDs rather than the handbook's stable IDs. Some documentation still refers to nonexistent Streamlit/setup paths. The new summarizer never loads the supplied school-profile links/AP caps, despite the stated contextual-rigor requirement.

**Consequence:** teammates cannot reproduce one agreed setup or meaning of “intended” policy compliance. Establish the authoritative policy/version and database configuration, include agent dependencies, and either implement school context or describe it as unsupported. These observations are source/configuration comparisons, not a claim that a real model made an unfair assessment.

### 15. P2 — UI omits useful evidence and mangles review notes

[Evidence card](../../ui/src/components/dossier/EvidenceCard.tsx#L23) renders strength text but no document/page/quotation/verification status. Actual component rendering confirmed that source and quote were absent. [Chat context](../../ui/src/lib/dossier.ts#L312) interpolates structured review-note objects as **`[object Object]`**; the agent emits `{category, note, section}`, while the UI type declares strings.

**Consequence:** officers cannot inspect the promised citations in that card, and the chatbot loses the substance of missing-information notes. Preserve the agent's note shape and display evidence/provenance, including image-only warnings.

### 16. P2 — Stream completion and scheduler time are unchecked

[Model streaming](../../ai_agent/summarizing_agent.py#L1072) accepts a stream ending without an Ollama `done` marker if the accumulated text parses. The interrupted-stream contract test fails. [Scheduler construction](../../ingestion/scheduler.py#L64) does not specify UTC, although environment documentation/logs promise 02:00 UTC; APScheduler therefore uses the host timezone.

**Consequence:** incomplete inference can look complete, and deployments outside UTC execute at a different time. Require a valid terminal model event and set the scheduler/trigger timezone explicitly.

## Reproduction and retained evidence

Run the original suite separately from the new diagnostic cases:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/integration_review_20261009 -q
.\.venv\Scripts\python.exe -m pytest tests/integration_review_20261009/test_integration_contracts.py -q --tb=short
```

The second command currently fails by design against the reviewed implementation. Its positive controls distinguish functioning guardrails from the defects. The backend/UI/CLI reproducer scripts require the isolated review database, which was removed when the temporary `--rm` container stopped; review their explicit configuration before recreating it. They must not be pointed at a shared admissions database.

Evidence in this directory:

- `existing_tests.xml` / `existing_tests.txt`: original 61-test results and failure traces.
- `contract_tests.xml` / `contract_tests.txt`: 25 intended-behavior checks.
- `backend_results.json` / `backend_execution.txt`: actual PostgreSQL, vector SQL, batch routing, document coverage, delta-score and failure-state probes.
- `ui_results.json`: actual route/helper/component behavior with explicit service mocks.
- `ui_build_lint_notes.txt`: successful build/lint tool results, lockfile comparison, and observed scheduler timezone.
- `cli_failure_results.json` / `cli_failure_output.txt`: APP_013's error, successful exit, audit-only failure, and unchanged ready state.
- `inventory_checks.json`: Python syntax and all-PDF opening inventory.
- [`tests/integration_review_20261009/`](../../tests/integration_review_20261009/): reproducible isolated checks and contract tests.

The UI remains an unauthenticated local prototype, as its README acknowledges. Authentication/RBAC and the architecture's officer-decision workflow are not implemented; this assessment does not treat those documented prototype limits as newly introduced regressions.

**Suggested repair order:** selection/handoff and real Batch 02 rendering failures; canonical document and score inputs; factual/schema/privacy/chat validation; persistent failure states and reviewer visibility; configuration/schema/policy alignment. After those repairs, rerun these cases and perform live MinIO + Qwen testing across both batches, including test-optional, scanned, outage, and applicant-switching cases.
