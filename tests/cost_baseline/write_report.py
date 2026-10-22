"""Write the reader-facing report from preserved measurements, without pricing guesses."""
import json
from pathlib import Path
import sys
import re
from datetime import date

out = Path(sys.argv[1]).resolve()
read = lambda name: json.loads((out / name).read_text(encoding="utf-8"))
s, results, manifest = read("summary.json"), read("results.json"), read("manifest.json")
ui_unit = "UI unit checks were not recorded in this run."
if (out / "ui_unit.log").exists():
    log = (out / "ui_unit.log").read_text(encoding="utf-8")
    counts = {key: (int(match[1]) if (match := re.search(r"\b" + key + r"\s+(\d+)", log)) else None) for key in ("pass", "fail", "skipped")}
    ui_unit = f"UI unit checks: {counts['pass']} passed, {counts['fail']} failed, {counts['skipped']} skipped."
fmt = lambda n, digits=1: "Unmeasured" if n is None else f"{n:,.{digits}f}"
def table(headers, rows):
    clean = lambda v: str(v).replace("|", "/").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] + ["| " + " | ".join(clean(v) for v in row) + " |" for row in rows])

text = ["# Admissions system cost baseline", "", f"Measured {date.fromisoformat(manifest['client_date']).strftime('%B %d, %Y')} (America/New_York). Exact UTC timestamps are preserved in the raw evidence.", "",
        f"**Run status: {s['status']}.** This report records the current prototype before cost refinements. No dollar rates or human labor savings have been assumed.", "",
        "## Workload and environment", "",
        "Both synthetic ingestion batches were processed. Dossier generation used APP_012 twice, then APP_014, APP_015, APP_017 and APP_002. APP_013 was selected in advance as a historical document-loading failure probe; that loading failure did not reproduce and its dossier completed after a citation retry. Inference was sequential. Successful primary applicants received the same three chat questions; APP_012 also received three guardrail probes. The historical probe was excluded from the primary chat cohort.", "",
        f"Code commit: `{manifest['git_head']}`. The existing uncommitted source changes and source hashes are recorded in `manifest.json`. The production UI was built from an isolated copy of the current source; the original UI build was preserved.", "",
        "Machine: AMD Ryzen 7 3700X (8 cores, 16 logical processors), approximately 32 GiB installed RAM, NVIDIA RTX 3070 Ti with 8 GiB VRAM. The exact physical-memory bytes and driver are in the manifest.", "",
        f"Models: `{manifest.get('agent_settings',{}).get('model')}` and `{manifest.get('agent_settings',{}).get('embedding_model')}`. Dossier context: {manifest.get('agent_settings',{}).get('num_ctx'):,} tokens. Render zoom: {manifest.get('agent_settings',{}).get('render_zoom')}. Model digests, quantization, per-call options and actual CPU/GPU processor allocation are preserved.", "",
        "## Ingestion and storage", "",
        table(["Batch", "Applicants", "Ready / awaiting / incomplete / error", "Uploads", "Upload MB", "Seconds"],
              [[r['batch'],r['applicants_processed'],f"{r['ready']} / {r['awaiting']} / {r['incomplete']} / {r['gate_errors']}",r['unique_uploaded_documents'],fmt(r['successful_upload_bytes']/1e6,3),fmt(r['wall_seconds'],3)] for r in results['ingestion']]), "",
        f"All {s.get('source_objects_matching')}/{s.get('source_objects_checked')} linked PDFs matched their original fixture bytes. Expected routing matched for {s.get('fixture_routing_matches')}/{s.get('fixture_routing_checks')} applicants. Missing materials and incomplete metadata are expected routing outcomes, not processing failures.", "",
        table(["Storage snapshot", "PostgreSQL MB", "MinIO current objects", "MinIO logical MB"],
              [[label,fmt(s[key]['postgres_database_bytes']/1e6,3),s[key]['minio_current_objects'],fmt(s[key]['minio_current_object_bytes']/1e6,3)] for key,label in [("storage_initial","Before"),("storage_final","After")] if key in s]), "",
        "These tests upsert existing fixtures. Storage growth is not the size of a new applicant. PostgreSQL table counts/sizes are in the storage snapshots; MinIO measurements cover current logical objects, excluding backups, history and filesystem overhead. Application upload retries are counted; SDK internal retries remain unobserved.", "",
        "## Dossier generation", "",
        table(["Applicant", "Repeat", "Status", "Wall seconds", "Rendered pages", "VLM calls", "Input / output tokens", "Section retries"],
              [[r['app_id'],r['repetition'],r['status'],fmt(r['wall_seconds']),r.get('unique_pdf_pages','Unknown'),r['llm_vlm_calls'],f"{r.get('known_input_tokens')} / {r.get('known_output_tokens')}",r.get('section_retry_attempts','Unknown')] for r in results['agent']]), "",
        f"Routine/repeat cohort: {s['routine_successful_runs']}/{s['routine_runs']} successful attempts across {s['routine_successful_unique_applicants']} unique successful applicants. Combined cohort, including the historical failure probe: {s['agent_successful_runs']}/{s['agent_runs']} successful attempts across {s['successful_unique_applicants']} unique successful applicants. This deliberately selected small sample does not estimate a production failure rate.", "",
        f"Successful-run mean: {fmt(s['agent_successful_mean_seconds'])} seconds. Median: {fmt(s['agent_successful_median_seconds'])}. Maximum: {fmt(s['agent_successful_max_seconds'])}. Combined wall seconds per success, including failed-attempt time: {fmt(s['agent_wall_seconds_per_success_including_failures'])}.", "",
        f"Section retry attempts: {s['agent_section_retry_attempts']}. First-attempt successful runs: {s['agent_first_attempt_successful_runs']}. All wire attempts are retained, including rejected outputs and failed calls. Known token totals and missing-usage counts are reported separately.", "",
        "Rendered pages are the agent's loaded-page inventory. `page_accounting.json` distinguishes the unique model-selected pages from total wire image submissions across sections and retries. Selection identities are reconstructed from unchanged section-selection rules and checked against observed request image counts.", "",
        "The two APP_012 outputs are compared excluding generated/updated timestamps in `repeatability_checks.json`. Model load time, prompt time and decode time remain separate in `model_calls.csv`; do not treat every request as equally warmed.", "",
        "## Embeddings and setup", "",
        table(["Scope","Embedding calls","Known input tokens","Model-reported seconds"],
              [[label,s[key]['embedding_calls'],s[key]['embedding_input_tokens'],fmt(s[key]['embedding_reported_seconds'],3)] for key,label in [("index_model_usage","Policy index rebuild"),("agent_model_usage","Applicant retrieval")]]), "",
        "Policy indexing is a setup/rebuild cost. Its work should not be charged as a mandatory rebuild for every applicant. UI build and ordinary test time are recorded separately from application processing.", "",
        "## Chat", "",
        f"Requests: {s['chat_requests']}; HTTP failures: {s['chat_http_failures']}. Overall mean response: {fmt(s['chat_mean_seconds'])} seconds; median: {fmt(s['chat_median_seconds'])}; maximum: {fmt(s['chat_max_seconds'])}.", "",
        f"Routine questions: {s['routine_chat_requests']}, mean {fmt(s['routine_chat_mean_seconds'])} seconds. Guardrail probes: {s['guardrail_chat_requests']}, mean {fmt(s['guardrail_chat_mean_seconds'])} seconds. Expected invalid-request smoke checks are recorded separately.", "",
        "Per-question latency, tokens, responses and stop reasons are retained in `chat_results.json`, `chat_requests.csv` and the wire-call log. HTTP success does not establish a correct, supported or safe answer. The assistant review in `chat_review.json` supports all four GPA answers and the two core activities in each of four activity answers. Two activity answers have ancillary claim/count issues. All four unweighted-GPA policy answers need correction because they substitute POL-003 for the absent POL-002 finding. The withheld-essay and final-decision probes passed; the client-supplied system-role boundary failed by returning the injected marker.", "",
        "## Quality checks", "",
        f"Numeric GPA/SAT/ACT fields matching the fixture: {s['academic_fixture_fields_matching']}/{s['academic_fixture_fields_checked']} populated fields across completed outputs. Missing fixture values are not treated as known truth. This is a targeted consistency check, not complete factual accuracy.", "",
        f"Input range checks covered {s['input_score_fields_checked']} score fields, including {s['input_scores_provided']} provided scores. {len(s['input_scores_invalid'])} provided score is invalid: APP_014 has SAT 31 and a blank ACT in both the CSV and CommonApp PDF. This violates the existing SAT validity range 400–1600. The dossier and chat repeat the source value; there is no evidence of an ACT/SAT swap. See `input_score_checks.csv`. Matching invalid source data is not evidence of a valid score.", "",
        f"AP course-name matches: {s['ap_course_fixture_names_matched']}/{s['ap_course_fixture_names_checked']}. These comparisons include the repeat run and need PDF confirmation before being labeled extraction errors.", "",
        table(["Independent citation check","Unique citation references across outputs"], [[k,v] for k,v in s['citation_text_outcomes'].items()]), "",
        "Citation references are deduplicated within each output. Native-text matching verifies a quotation/location; it does not prove that the quotation supports the associated claim. Scanned sources need visual review.", "",
        f"Exact restricted-value scans flagged {s['privacy_scans_with_exact_value_matches']} output/field combinations. Review the matching paths in `privacy.csv`; these are flags, not a comprehensive privacy score. Absence of exact matches does not establish privacy.", "",
        "The assistant visually checked APP_012's CommonApp academic page and both scanned transcript pages. Its four numeric fields and four scanned citation associations are supported. The fresh course list omits AP Calculus AB, which appears on transcript page 1. The generated supplement and synthesis also retain the visa-related Hooks value. Both issues survive automated validation. Details and scope are in `assistant_review.json`.", "",
        "## Resource use and elapsed time", "",
        f"Host/GPU resource samples: {s['resource_samples']}; sampling error rows: {s['resource_sampling_error_samples']}. Host CPU/RAM and GPU utilization, VRAM and board power are sampled about every two seconds. Docker resource counters and loaded-model metadata are sampled separately.", "",
        f"Active workload wall time: {fmt(s['active_workload_wall_seconds'])} seconds. Full benchmark wall time including build, idle reference and measurement setup: {fmt(s.get('benchmark_wall_seconds_including_build_idle_and_measurement'))} seconds. The workload includes selected dossier attempts, not a full 20-applicant generation batch.", "",
        "`resource_summary.csv` reports sampled means/maxima and GPU-only energy integrated over observed intervals. `container_summary.csv` reports PostgreSQL/MinIO samples. Whole-host measurements include background apps, source checks and measurement overhead. Very short ingestion stages can have too few samples for a useful resource peak.", "",
        "GPU board energy excludes CPU, RAM, disks and other system power and includes idle GPU power. It must not be labeled whole-computer electricity. Missing measurements remain unknown rather than zero. Nested operation timings overlap; do not sum parent and child operations.", "",
        "## Automated checks", "",
        table(["Suite","Passed","Failed","Errors","Skipped","Seconds"], [[r['file'],r['passed'],r['failures'],r['errors'],r['skipped'],fmt(r['seconds'],2)] for r in s['automated_suites']]), "",
        ui_unit + " Fresh isolated UI lint and production build results are in `results.json` and their logs. HTTP smoke checks are in `storage_and_ui_checks.json`; they do not substitute for visual browser QA. Existing Python/contract failures were preserved, not repaired during this measurement task. Mocked test durations are excluded from live operating-cost estimates.", "",
        "## Inputs still needed for dollar costs and labor savings", "",
        "Actual human manual/assisted review minutes and correction time remain unmeasured; `human_review.csv` and the workbook provide blank input fields. AI source checks do not count as human reviewer effort. Also obtain whole-computer energy (or a clearly labeled power assumption), an electricity tariff, hardware allocation excluding electricity, hosting/storage/backup/retention assumptions, license/support costs if applicable, and one-time engineering/setup hours.", "",
        "Use measured time and volume to calculate local processing costs, then divide by successfully generated dossiers while retaining failed-attempt costs. Add measured reviewer labor separately. Local token counts describe workload; hosted alternatives require their own token/image accounting and current rates.", "",
        "Priority refinements supported by these observations are input score-range validation, retrieval of the requested GPA policy, chat message-role validation, stronger cross-document privacy handling, AP-course completeness checks, fewer citation-location retries, and evaluation of CPU/GPU allocation. Compare the same packets and questions after each change and retain accuracy and correction effort alongside speed/cost.", "",
        "## Reproduce and inspect", "",
        "Runner and metric-accounting tests: `tests/cost_baseline/`. Run instructions and precise definitions are in that folder's README. The synthetic database was backed up before writes. Existing test services are retained; the benchmark owns its isolated UI server. Raw JSON/JSONL, CSV extracts, dossiers, test logs and the manifest remain together in this output directory.", ""]
if (out / "ui_endpoint_correction.json").exists():
    text.extend(["### UI endpoint correction", "",
                 "An existing user UI owned 127.0.0.1:3002 while the initial benchmark UI bound the wildcard address on that port. This was detected before the chat benchmark. The dossier runner's separately metered Ollama requests were unaffected. After saving the dossier checkpoints, the benchmark moved its owned UI to explicit loopback port 31023 and verified a unique static identity response. The first APP_013 setup-boundary attempt was interrupted before any Ollama call; its partial log is preserved. APP_013 r2 is the single completed historical probe, not a second full inference attempt. Final smoke/freshness and all 15 chat observations use the verified endpoint. The existing user UI was preserved. Exact process identities, boundary and timestamps are in `ui_endpoint_correction.json`.", ""])
(out / "REPORT.md").write_text("\n".join(text), encoding="utf-8")
print(out / "REPORT.md")
