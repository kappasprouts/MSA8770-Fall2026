# Ingestion API and overnight scheduler

The API and overnight scheduler invoke the same two-pass ingestion and manifest
gate as `run_ingestion_check.py`. Pass 1 upserts CSV-owned applicant fields; pass 2
links new and late documents to the stored applicant. The gate persists each
packet's status and writes an `affected_ids` JSON file containing IDs ready for
the downstream AI summary agent. Ingestion stops there: it does not perform OCR,
parse document text, or call the Model Gateway.

## Endpoints

| Method | Path | Action |
| :--- | :--- | :--- |
| `GET` | `/` | Service metadata |
| `GET` | `/health` | Service and scheduler availability |
| `POST` | `/ingestion/batch/trigger` | Run the entire configured batch synchronously |
| `GET` | `/ingestion/batch/status` | Return the latest successful API or overnight batch summary |
| `POST` | `/ingestion/packet/{applicant_id}` | Run the configured batch for one applicant ID only |

The source directory must be a two-pass batch directory: a CSV at its root and/or
applicant document subdirectories. A document-only batch can link a late document
to an applicant already in storage. The default source is the repository's
`batch_01` directory. The old packet-directory scanner is no longer used.

### `POST /ingestion/batch/trigger`

Returns HTTP 200 after ingestion, gate evaluation, status persistence, audit report,
and the affected IDs file are complete. The response is a JSON summary:

```json
{
  "status": "COMPLETED",
  "executed_at": "2026-10-06T02:00:15Z",
  "total_packets_discovered": 2,
  "status_breakdown": {
    "READY_FOR_REVIEW": 1,
    "INCOMPLETE": 1,
    "ERROR": 0
  },
  "affected_ids": ["APP_102"],
  "affected_ids_file": "/path/to/affected_ids_20261006T020015Z_ab12cd34.json",
  "report_file": "/path/to/ingestion_batch_01_report_20261006T020015Z_ab12cd34.txt",
  "hard_stop": true,
  "storage_mode": "postgresql",
  "minio_available": true,
  "object_storage_required": true,
  "postgresql_required": true,
  "handoff_ready": true,
  "results": [
    {
      "applicant_id": "APP_102",
      "status": "READY_FOR_REVIEW",
      "is_valid": true,
      "routing_destination": "READY_FOR_REVIEW",
      "findings_count": 0,
      "missing_documents": [],
      "missing_fields": [],
      "errors": [],
      "total_documents": 5,
      "documents_parsed": 0,
      "ai_evaluated": false
    }
  ]
}
```

`storage_mode` is `postgresql`, `sqlite`, `sqlite_fallback`, or `dry_run`.
`handoff_ready` is true when applicant storage is PostgreSQL and MinIO is
available. Pass the returned `affected_ids_file` to the summary agent; the API
does not invoke it.

The former `max_packets` query option is rejected with HTTP 400 because truncating
a two-pass batch can skip CSV rows or documents. To process a subset, use a
separate batch directory or the single-applicant endpoint.

With the default strict storage settings, unavailable MinIO or PostgreSQL causes
HTTP 503 before applicant staging or handoff export. Upload failures and missing
previously linked MinIO objects also fail the run.
No successful batch summary is published for a failed run.

### `GET /ingestion/batch/status`

Returns the latest successful on-demand or overnight batch summary in the shape
above. Before the first successful run, it returns:

```json
{"status": "NO_PREVIOUS_RUN", "message": "No batch run has been executed yet."}
```

This cache is in process memory; it resets when the service restarts.

### `POST /ingestion/packet/{applicant_id}`

Runs the same two-pass logic and gate with an applicant ID scope. It can process a
CSV repeat or a late document in the configured batch without updating unrelated
applicants. The response has the per-applicant fields shown in `results`, plus
`affected_ids`, `affected_ids_file`, `report_file`, `hard_stop`, storage fields,
and `handoff_ready`. The per-applicant artifacts have the normalized ID and a
unique run ID in their names, so they do not replace a full-batch handoff.

An invalid ID returns HTTP 400. An ID absent from both the batch and stored
applicants returns HTTP 404. A strict object-storage failure returns HTTP 503.

## Configuration

| Environment variable | Default | Purpose |
| :--- | :--- | :--- |
| `INGESTION_INPUT_DIR` | `<repo>/batch_01` | Two-pass batch root |
| `INGESTION_CONFIG_PATH` | `<repo>/config/policies.yaml` | Manifest policy |
| `INGESTION_REPORT_PATH` | `<repo>/ingestion_batch_01_report.txt` | Base path for uniquely named audit reports |
| `INGESTION_AFFECTED_IDS_PATH` | `<repo>/affected_ids.json` | Base path for uniquely named affected ID files |
| `INGESTION_REQUIRE_OBJECT_STORAGE` | `true` | Require live MinIO for a summary-agent handoff |
| `INGESTION_REQUIRE_POSTGRESQL` | `true` | Require shared PostgreSQL for a summary-agent handoff |
| `BATCH_CRON_HOUR` | `2` | Scheduled UTC hour |
| `BATCH_CRON_MINUTE` | `0` | Scheduled UTC minute |

Every API and scheduler run appends a unique run ID to its configured output base
paths. The single-applicant endpoint also includes the normalized applicant ID.
Callers using `BatchIngestionPipeline.run_batch(report_path=...,
affected_ids_path=...)` directly can pass exact run-specific paths.
Set both `INGESTION_REQUIRE_OBJECT_STORAGE=false` and
`INGESTION_REQUIRE_POSTGRESQL=false` only for local dry-run and testing. The
response reports `handoff_ready: false` unless both live services are available.
The CLI writes a unique affected-ID file by default and supports
`--require-object-storage --require-postgresql` for a live handoff.

The API does not implement authentication. Limit access to trusted internal
callers before deploying its write endpoints.

The scheduler invokes `BatchIngestionPipeline.run_batch()` daily at 02:00 UTC by
default. It stores the same summary returned by the on-demand batch endpoint.
