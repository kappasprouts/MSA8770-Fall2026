# Cost baseline protocol

This harness measures the current prototype against synthetic fixtures. It does
not alter production source files, model outputs, prompts, or validation logic.
It writes new synthetic dossiers and run/audit records to `rsu_live_test` only.
Existing PostgreSQL/MinIO services remain running. The harness owns and stops an
isolated production UI server on loopback port 31023. A free-port check and unique
static identity response confirm that requests reach the owned source snapshot.
Existing UI source/builds are preserved.

## Run

With the existing `rsu-live-test` services and local Ollama running:

```powershell
powershell -NoProfile -File tests/cost_baseline/run_baseline.ps1 -OutputDirectory output/cost_baseline_NEW_RUN
```

Use a new output directory each time. The runner refuses to overwrite an existing
manifest. It backs up the synthetic database before writes. Dossier snapshots are
written into each run's own folder, preserving the ordinary `output/ai_agent/` files.

## Workload selected before inference

- Ingest the complete Batch 01 and Batch 02 fixtures, using strict PostgreSQL and
  object-storage flags. Expected routing: 9 ready / 1 awaiting, then 7 ready /
  1 awaiting / 2 incomplete. Missing materials are workflow outcomes, not crashes.
- Rebuild the policy index once and measure its embedding work separately.
- Generate APP_012 twice, then APP_014, APP_015, APP_017, APP_002 once each.
  These six runs cover five eligible applicants and a repeatability check.
- Attempt APP_013 as an explicitly selected historical document-loading failure
  probe. Record the actual outcome; do not assume the historical failure persists.
  Report both routine-cohort results and combined results so this deliberately
  selected negative case is not mistaken for an unbiased production failure rate.
- Ask each successfully generated applicant the same three questions about GPA,
  activities, and policy evidence. For APP_012, also probe withheld-essay handling,
  final-decision refusal, and client-supplied system-role handling.
- Keep inference sequential. Record model load time and loaded models rather than
  assuming every request is warm or that having a GPU means full GPU inference.

## Measurement definitions

`calls.jsonl` records actual HTTP attempts through a local Ollama forwarding proxy.
It captures final token/timing fields before application parsing and validation.
It never stores request prompts, images, embeddings, or full model responses.
Generated dossiers and chat answers are retained separately as synthetic test
evidence. A proxy is measurement overhead; its wall time and Ollama's reported
time are both available. API failures, incomplete streams, and unknown token
counts remain visible. An unknown count is not zero.

Unique PDF pages in a dossier differ from image page submissions across model
calls and retries. Upload attempts differ from unique uploaded objects. SDK
internal upload retries are not instrumented and remain unknown. All explicit
application retries and failed model attempts remain in measured totals.

Operation timings identify downloads, rendering, retrieval, and persistence.
Some timings are nested: `load_pages` includes download/render operations. Do not
sum parent and child timings. Full agent wall time includes persistence; the
agent's own recorded runtime ends before some persistence work.

Host CPU/RAM and GPU utilization/VRAM/board power are sampled about every two
seconds. Docker resource counters and loaded-model metadata are sampled about
every ten seconds. Scope is the entire host/GPU; unrelated machine activity and
the measurement tools can contribute. Short ingestion stages may have too few
samples to characterize resource peaks. Container counters are snapshots, not
application-only costs.

GPU energy is trapezoidal integration over observed intervals no longer than six
seconds. It includes idle GPU power and excludes CPU, RAM, disks and other system
power. It must not be labeled whole-system electricity. No dollar rates are
invented. Human reviewer time, manual-review baseline, electricity tariff, and
hardware cost allocation remain unmeasured inputs.

Storage measurements show PostgreSQL database/table sizes and current logical
MinIO object bytes. They exclude backups, object history, and filesystem overhead.
These runs reuse/upsert existing fixtures, so before/after growth does not equal
the storage required for entirely new applicants. Uploaded byte volume and final
stored bytes are reported separately.

## Accuracy and human review

`summarize_baseline.py` independently compares four academic numeric fields with
the CSV fixtures, checks quoted text/page locations in native PDF text, and scans
for exact restricted fixture values in generated output. These checks are limited:
CSV and PDFs may disagree; quotation presence does not establish claim entailment;
and scanned pages require visual review. They do not prove complete accuracy,
privacy, fairness, or guardrail compliance.

`human_review.csv` is an unfilled measurement form. Actual humans should time
manual and assisted review of matched packets and record corrections. Assistant
review notes and automated source checks are labeled separately and do not count
as human labor savings.

Run ordinary Python/UI checks separately from the live benchmark, and save their
logs/JUnit files. Do not mix mocked unit-test timings into real operating costs.
Benchmarks report individual observations, median, mean, and maximum; this sample
is too small and deliberately selected for a reliable production p95 or failure
rate. Preserve source hashes, configuration, hardware and data identities with
the results for reproducibility.
