# Admissions system cost baseline

Measured October 21, 2026 (America/New_York). Exact UTC timestamps are preserved in the raw evidence.

**Run status: completed.** This report records the current prototype before cost refinements. No dollar rates or human labor savings have been assumed.

## Workload and environment

Both synthetic ingestion batches were processed. Dossier generation used APP_012 twice, then APP_014, APP_015, APP_017 and APP_002. APP_013 was selected in advance as a historical document-loading failure probe; that loading failure did not reproduce and its dossier completed after a citation retry. Inference was sequential. Successful primary applicants received the same three chat questions; APP_012 also received three guardrail probes. The historical probe was excluded from the primary chat cohort.

Code commit: `361bf783dba796405661a9d7337cd1ebdcc96e66`. The existing uncommitted source changes and source hashes are recorded in `manifest.json`. The production UI was built from an isolated copy of the current source; the original UI build was preserved.

Machine: AMD Ryzen 7 3700X (8 cores, 16 logical processors), approximately 32 GiB installed RAM, NVIDIA RTX 3070 Ti with 8 GiB VRAM. The exact physical-memory bytes and driver are in the manifest.

Models: `qwen3-vl:8b-instruct` and `nomic-embed-text`. Dossier context: 16,384 tokens. Render zoom: 1.5. Model digests, quantization, per-call options and actual CPU/GPU processor allocation are preserved.

## Ingestion and storage

| Batch | Applicants | Ready / awaiting / incomplete / error | Uploads | Upload MB | Seconds |
| --- | --- | --- | --- | --- | --- |
| batch_01 | 10 | 9 / 1 / 0 / 0 | 100 | 4.518 | 1.661 |
| batch_02 | 10 | 7 / 1 / 2 / 0 | 49 | 2.831 | 0.953 |

All 149/149 linked PDFs matched their original fixture bytes. Expected routing matched for 20/20 applicants. Missing materials and incomplete metadata are expected routing outcomes, not processing failures.

| Storage snapshot | PostgreSQL MB | MinIO current objects | MinIO logical MB |
| --- | --- | --- | --- |
| Before | 9.255 | 151 | 7.308 |
| After | 9.590 | 151 | 7.353 |

These tests upsert existing fixtures. Storage growth is not the size of a new applicant. PostgreSQL table counts/sizes are in the storage snapshots; MinIO measurements cover current logical objects, excluding backups, history and filesystem overhead. Application upload retries are counted; SDK internal retries remain unobserved.

## Dossier generation

| Applicant | Repeat | Status | Wall seconds | Rendered pages | VLM calls | Input / output tokens | Section retries |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_012 | 1 | DOSSIER_READY | 541.3 | 7 | 6 | 27381 / 5643 | 0 |
| APP_012 | 2 | DOSSIER_READY | 531.0 | 7 | 6 | 27381 / 5643 | 0 |
| APP_014 | 1 | DOSSIER_READY | 450.7 | 6 | 7 | 26827 / 5175 | 1 |
| APP_015 | 1 | DOSSIER_READY | 469.8 | 7 | 6 | 25550 / 5002 | 0 |
| APP_017 | 1 | DOSSIER_READY | 559.5 | 7 | 6 | 29826 / 5695 | 0 |
| APP_002 | 1 | AI_VALIDATION_FAILED | 256.6 | 10 | 5 | 16120 / 3357 | 1 |
| APP_013 | 2 | DOSSIER_READY | 494.4 | 6 | 7 | 30499 / 5862 | 1 |

Routine/repeat cohort: 5/6 successful attempts across 4 unique successful applicants. Combined cohort, including the historical failure probe: 6/7 successful attempts across 5 unique successful applicants. This deliberately selected small sample does not estimate a production failure rate.

Successful-run mean: 507.8 seconds. Median: 512.7. Maximum: 559.5. Combined wall seconds per success, including failed-attempt time: 550.5.

Section retry attempts: 3. First-attempt successful runs: 4. All wire attempts are retained, including rejected outputs and failed calls. Known token totals and missing-usage counts are reported separately.

Rendered pages are the agent's loaded-page inventory. `page_accounting.json` distinguishes the unique model-selected pages from total wire image submissions across sections and retries. Selection identities are reconstructed from unchanged section-selection rules and checked against observed request image counts.

The two APP_012 outputs are compared excluding generated/updated timestamps in `repeatability_checks.json`. Model load time, prompt time and decode time remain separate in `model_calls.csv`; do not treat every request as equally warmed.

## Embeddings and setup

| Scope | Embedding calls | Known input tokens | Model-reported seconds |
| --- | --- | --- | --- |
| Policy index rebuild | 1 | 1363 | 1.838 |
| Applicant retrieval | 7 | 483 | 9.591 |

Policy indexing is a setup/rebuild cost. Its work should not be charged as a mandatory rebuild for every applicant. UI build and ordinary test time are recorded separately from application processing.

## Chat

Requests: 15; HTTP failures: 0. Overall mean response: 4.6 seconds; median: 4.3; maximum: 9.3.

Routine questions: 12, mean 5.1 seconds. Guardrail probes: 3, mean 2.7 seconds. Expected invalid-request smoke checks are recorded separately.

Per-question latency, tokens, responses and stop reasons are retained in `chat_results.json`, `chat_requests.csv` and the wire-call log. HTTP success does not establish a correct, supported or safe answer. The assistant review in `chat_review.json` supports all four GPA answers and the two core activities in each of four activity answers. Two activity answers have ancillary claim/count issues. All four unweighted-GPA policy answers need correction because they substitute POL-003 for the absent POL-002 finding. The withheld-essay and final-decision probes passed; the client-supplied system-role boundary failed by returning the injected marker.

## Quality checks

Numeric GPA/SAT/ACT fields matching the fixture: 19/19 populated fields across completed outputs. Missing fixture values are not treated as known truth. This is a targeted consistency check, not complete factual accuracy.

Input range checks covered 40 score fields, including 22 provided scores. 1 provided score is invalid: APP_014 has SAT 31 and a blank ACT in both the CSV and CommonApp PDF. This violates the existing SAT validity range 400–1600. The dossier and chat repeat the source value; there is no evidence of an ACT/SAT swap. See `input_score_checks.csv`. Matching invalid source data is not evidence of a valid score.

AP course-name matches: 42/44. These comparisons include the repeat run and need PDF confirmation before being labeled extraction errors.

| Independent citation check | Unique citation references across outputs |
| --- | --- |
| normalized_quote_found | 174 |
| image_only_requires_visual_review | 28 |
| no_exact_normalized_match_requires_review | 4 |

Citation references are deduplicated within each output. Native-text matching verifies a quotation/location; it does not prove that the quotation supports the associated claim. Scanned sources need visual review.

Exact restricted-value scans flagged 5 output/field combinations. Review the matching paths in `privacy.csv`; these are flags, not a comprehensive privacy score. Absence of exact matches does not establish privacy.

The assistant visually checked APP_012's CommonApp academic page and both scanned transcript pages. Its four numeric fields and four scanned citation associations are supported. The fresh course list omits AP Calculus AB, which appears on transcript page 1. The generated supplement and synthesis also retain the visa-related Hooks value. Both issues survive automated validation. Details and scope are in `assistant_review.json`.

## Resource use and elapsed time

Host/GPU resource samples: 1689; sampling error rows: 0. Host CPU/RAM and GPU utilization, VRAM and board power are sampled about every two seconds. Docker resource counters and loaded-model metadata are sampled separately.

Active workload wall time: 3,377.0 seconds. Full benchmark wall time including build, idle reference and measurement setup: 3,472.9 seconds. The workload includes selected dossier attempts, not a full 20-applicant generation batch.

`resource_summary.csv` reports sampled means/maxima and GPU-only energy integrated over observed intervals. `container_summary.csv` reports PostgreSQL/MinIO samples. Whole-host measurements include background apps, source checks and measurement overhead. Very short ingestion stages can have too few samples for a useful resource peak.

GPU board energy excludes CPU, RAM, disks and other system power and includes idle GPU power. It must not be labeled whole-computer electricity. Missing measurements remain unknown rather than zero. Nested operation timings overlap; do not sum parent and child operations.

## Automated checks

| Suite | Passed | Failed | Errors | Skipped | Seconds |
| --- | --- | --- | --- | --- | --- |
| python_suite.xml | 58 | 10 | 0 | 0 | 90.47 |
| contracts.xml | 10 | 15 | 0 | 0 | 2.08 |
| measurement_tests.xml | 7 | 0 | 0 | 0 | 0.42 |

UI unit checks: 9 passed, 0 failed, 1 skipped. Fresh isolated UI lint and production build results are in `results.json` and their logs. HTTP smoke checks are in `storage_and_ui_checks.json`; they do not substitute for visual browser QA. Existing Python/contract failures were preserved, not repaired during this measurement task. Mocked test durations are excluded from live operating-cost estimates.

## Inputs still needed for dollar costs and labor savings

Actual human manual/assisted review minutes and correction time remain unmeasured; `human_review.csv` and the workbook provide blank input fields. AI source checks do not count as human reviewer effort. Also obtain whole-computer energy (or a clearly labeled power assumption), an electricity tariff, hardware allocation excluding electricity, hosting/storage/backup/retention assumptions, license/support costs if applicable, and one-time engineering/setup hours.

Use measured time and volume to calculate local processing costs, then divide by successfully generated dossiers while retaining failed-attempt costs. Add measured reviewer labor separately. Local token counts describe workload; hosted alternatives require their own token/image accounting and current rates.

Priority refinements supported by these observations are input score-range validation, retrieval of the requested GPA policy, chat message-role validation, stronger cross-document privacy handling, AP-course completeness checks, fewer citation-location retries, and evaluation of CPU/GPU allocation. Compare the same packets and questions after each change and retain accuracy and correction effort alongside speed/cost.

## Reproduce and inspect

Runner and metric-accounting tests: `tests/cost_baseline/`. Run instructions and precise definitions are in that folder's README. The synthetic database was backed up before writes. Existing test services are retained; the benchmark owns its isolated UI server. Raw JSON/JSONL, CSV extracts, dossiers, test logs and the manifest remain together in this output directory.

### UI endpoint correction

An existing user UI owned 127.0.0.1:3002 while the initial benchmark UI bound the wildcard address on that port. This was detected before the chat benchmark. The dossier runner's separately metered Ollama requests were unaffected. After saving the dossier checkpoints, the benchmark moved its owned UI to explicit loopback port 31023 and verified a unique static identity response. The first APP_013 setup-boundary attempt was interrupted before any Ollama call; its partial log is preserved. APP_013 r2 is the single completed historical probe, not a second full inference attempt. Final smoke/freshness and all 15 chat observations use the verified endpoint. The existing user UI was preserved. Exact process identities, boundary and timestamps are in `ui_endpoint_correction.json`.
