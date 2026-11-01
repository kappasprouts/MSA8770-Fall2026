# Validation hardening evidence - October 31, 2026

This update implements nested JSON-schema validation (`jsonschema`), targeted
numeric/citation support checks, conservative pre-render privacy filtering,
advisory-language guards, strict stream completion, and runtime chat boundaries.
The former diagnostic contracts are now part of normal pytest discovery.

| Check | Result / scope |
| --- | --- |
| Default Python suite | 153 passed, 3 skipped; [JUnit](python_suite.xml) |
| PostgreSQL tests executed separately | 3 passed: fresh/legacy migration, review lifecycle preservation, invalid-score receiver persistence; session-local TEMP tables |
| UI suite | 49 passed, including actual chat-route execution with controlled upstream responses and PostgreSQL TEMP-table checks |
| TypeScript / lint | Passed; one pre-existing unused `exportSummary` warning |
| Rendering preflight | All 16 intake-eligible fixture packets rendered; [results](render_preflight.json). Uses read-only stored metadata and local original PDFs; no model calls |
| Live Qwen academic probe | APP_012, 4 images, final run passed in one attempt; 94.0 model-reported seconds, 1,224 output tokens |
| Final output revalidation | Zero errors against final source and local original PDF page text; [validated output](academic_validation.json) |

The [initial live probe](academic_initial_failed.txt) failed both allowed attempts
because GPA quotations cited CommonApp page 1 instead of page 2. It was rejected;
no dossier was saved. Its running process had loaded the earlier smoke-script
version, which printed validation errors but exited zero. The script now returns
nonzero on failed validation. Actual errors, rather than that initial exit code,
determine its failed outcome.

The source prompt was clarified to distinguish original PDF page numbers from
image order. Retry feedback now supplies actual matching text-page locations and
requires removal of incorrect duplicates, without changing returned citations or
relaxing validation. A controlled regression exercises this correction path.
The [live rerun](academic_rerun.txt) then passed on its first attempt; this does not
isolate causality or establish a model-quality comparison.

The four final numeric fields are unweighted GPA 3.97, weighted GPA 4.4, SAT 1530
and ACT 35. Their CommonApp citations match page 2. Four transcript citations
retain `UNVERIFIED_IMAGE_SOURCE`; this text-based check does not verify scanned
images or completeness of the course list. The academic-only script uses an empty
essay-shingle guard and is not a complete privacy or six-section end-to-end test.
No shared applicant/dossier/object was changed, and no production build was run.

Recognized restricted regions and known excluded values are removed only in
memory before rendering. Original documents remain available to humans. The
previews for the fixture CommonApp contact page and supplement context were also
visually inspected. Unrecognized scanned layouts and general semantic correctness
remain limitations. Existing saved dossiers are not retroactively revalidated.
Durable approval, candidate versions, event deduplication and resume remain the
next implementation workstream.

Reproduce automated checks from the repository root with updated requirements:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

From `ui`, with the local test settings loaded:

```powershell
node --env-file=.env.local --test tests/*.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js src tests
```

The Python default run used an isolated fallback database and unused MinIO
endpoint. The separate PostgreSQL checks and UI database tests shadow tables in
their own sessions. The live academic script needs configured PostgreSQL, MinIO
and Ollama and calls the actual model; it reads sources and does not save dossiers.
