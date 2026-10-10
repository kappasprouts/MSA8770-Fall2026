# Live test results — October 9, 2026

Tested the supplied synthetic Batch 02 with PostgreSQL/pgvector, licensed MinIO AIStor, Ollama `qwen3-vl:8b-instruct`, and the Next.js review UI. Application source was unchanged. These results supplement the [earlier integration assessment](../integration_review_20261009/REVIEW.md), whose backend model and object-storage probes used mocks.

| Check | Observed result | Evidence and limits |
|---|---|---|
| Strict live ingestion | 10 applicants; 7 ready, 1 awaiting materials, 2 incomplete; 49 PDFs stored | `ingestion_report.txt`, `affected_ids.json`, `service_verification.json` |
| MinIO document round trip | APP_012 transcript matched the source SHA-256 and opened as a two-page PDF | `service_verification.json` |
| Live academic generation | 4 input pages, 1 attempt, 112.5 seconds, 8 evidence items; no reported validation errors; expected GPA/SAT/ACT values | `academic_verification.json` |
| Full live APP_012 generation | All 6 sections passed the agent's validation; 88 citations checked; reported saving `DOSSIER_READY`; 520.3 seconds total | User-executed run recorded in local `full_run.log`; this table summarizes that log, without an independent post-run database query |
| Review UI | Page and applicants endpoint returned HTTP 200; APP_012 was listed; user confirmed seeing the UI | Live server observations |
| Documents and chat | Dossier and document requests returned HTTP 200; chat returned HTTP 200 with a completed Ollama response | Server observations; answer accuracy and all chat guardrails were not independently evaluated |
| Shutdown | UI, Ollama, PostgreSQL, and MinIO stopped; ports 3001, 11434, 25432, 29000, and 29001 no longer listened | Process, Docker, and socket checks after shutdown; data volumes and model downloads retained |

The successful academic output claims 12 AP courses in prose while listing 11 course entries. Passing schema/citation validation does not establish complete factual accuracy. The earlier assessment still records 9 failures in the original 61-test suite and 20 failures in 25 added diagnostic cases. No repairs to those application defects were made during this setup work, and a passing APP_012 run does not establish success for the other applicants.

Full-run section timings from the user's retained console log:

| Section | Seconds | Output tokens | Attempt |
|---|---:|---:|---:|
| Academic | 104.6 | 1107 | 1 |
| Engagement | 52.3 | 757 | 1 |
| Recommendation | 76.4 | 1094 | 1 |
| Supplement | 38.6 | 615 | 1 |
| Policy | 128.5 | 1215 | 1 |
| Synthesis | 93.7 | 891 | 1 |

The setup guide and verification summaries are included for sharing. Licenses, full generated applicant dossiers, and raw live console logs stay local and are ignored by Git. The Compose/settings credentials are defaults for the isolated local test services.
