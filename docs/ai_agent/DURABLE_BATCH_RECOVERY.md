# Durable batch identity and interrupted generation recovery

PostgreSQL now owns intake receipts, generation batch membership, per-applicant
execution scopes and completed section attempts. Ingestion still stops before AI;
generation is started explicitly. Existing human exception checkpoints, publication
receipts and admissions dispositions remain authoritative.

## Run, stop, resume and inspect

Use the same PostgreSQL/MinIO environment for ingestion, generation, IT worker and
UI (`DATABASE_URL` for StorageManager plus matching `POSTGRES_*` for the agent).
Existing databases can apply `storage/migrations/20261101_durable_batch_generation.sql`.
The runner also initializes missing durable tables. The migration is additive and
idempotent; it does not regenerate or approve existing dossiers.

```powershell
.\.venv\Scripts\python.exe -m ingestion.run_ingestion_check --input-dir data/batches/batch_01 --require-postgresql --require-object-storage
```

Intake prints a stable **batch event UUID** and writes the existing ready-ID list
plus a `.batch.json` sidecar. The API/scheduler summary includes `batch_event_id`,
`deduplicated` and `handoff_file`. Start generation using either:

```powershell
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py --batch-event INTAKE_EVENT_UUID
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py --handoff PATH_TO_HANDOFF.batch.json
```

The generator prints its **generation batch UUID before model calls**. If it stops,
restart with that UUID. Do not add `--force` to a resume command:

```powershell
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py --batch-id GENERATION_BATCH_UUID
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py --batch-id GENERATION_BATCH_UUID --inspect --verify-objects
```

Inspection does not invoke a model. It reports saved member/execution states,
completed section checks, current applicant status and human dispositions, run and
review IDs, current published pointer, receipts, and (with `--verify-objects`) actual
MinIO existence/SHA-256 checks. A failed object check returns a nonzero exit code.
The generation summary distinguishes the generation outcome from current applicant
status, so a later human decision is not reported as merely DOSSIER_READY.

Explicit applicant IDs remain supported and now form a durable batch scoped to
their current inputs. The no-argument legacy fallback remains the old fixed ready-ID
path; use `--handoff` or `--batch-event` for the new unique intake artifacts.

## Batch deduplication

An intake event hashes relative filenames, file bytes, applicant scope, manifest
rules, ingestion code/schema version, storage endpoint/bucket and strict-mode flags.
Absolute directory name and timestamps are excluded. Copying identical files into
another drop directory therefore finds the same event. Changed bytes, routing
filenames, rules, scope or pipeline version create a new event.

The PostgreSQL session lock serializes intake across processes. A completed receipt
is reused after verifying applicant rows and receiving object checksums; the CSV
and PDFs are not ingested/uploaded again. Old packets do not restore old workflow
statuses or overwrite newer applicant facts on a completed replay. Missing/changed
objects cause a repair error; an old batch is not silently reapplied.

The receiver receipt is saved as INGESTED before report/ID delivery. If artifact
publication fails, replay recreates delivery from that receipt without repeating
ingestion. Generation from an event is allowed only after COMPLETED and a confirmed
strict PostgreSQL/MinIO handoff. The current canonical manifest-rule hash must match.
Scheduler/API status can recover the saved delivery summary after process restart.

If intake stops **before** a receiver receipt exists, automatic replay is refused:
partial SQL/object effects might already exist. Inspect them, correct the source and
use an explicit repair scope rather than automatically reapplying an uncertain batch:

```powershell
.\.venv\Scripts\python.exe -m ingestion.run_ingestion_check --input-dir PATH_TO_CORRECTED_BATCH --require-postgresql --require-object-storage --retry-key repair-20261101-1
```

The IT worker supplies its saved job ID as the explicit retry key. SQLite/offline
demonstrations retain their existing behavior and do not claim durable shared-system
deduplication or a verified AI handoff.

## Generation checkpoints and ownership

Each execution is uniquely scoped to applicant ID, the canonical applicant/policy
snapshot hash, pipeline/model configuration fingerprint and retry key. The scope
hash is calculated directly in PostgreSQL, preserving numeric representation
such as two-decimal GPA while linking members to the correct execution. A session
advisory lock permits one generator per applicant. Its owner UUID fences checkpoint
and publication writes. A live competing owner returns a busy conflict; it is not
assumed dead because a large model call takes a long time. Process/connection death
releases the lock, allowing another process to reclaim RUNNING/INTERRUPTED work.

Retrieved policy context is saved once. Each model attempt saves output, validation
errors and usage/log data. Section request hashes bind prompts, rendered page bytes,
source locations, evidence IDs and privacy guards. Restart reloads/renders sources
for verification but reuses completed attempts, including their retry budget.
Model images/prompts are not stored as new checkpoint blobs. Registered source-byte
checksums are checked before rendering.

The last model call can repeat if the process died before its result was saved.
This is recovery at committed attempt/section boundaries, not token-stream recovery
or exactly-once HTTP inference. Saved successful sections are not called again.
Fully exhausted validation failures remain failed; ordinary restart does not grant
them more retries. Prepare corrected input/code or an explicit new attempt:

```powershell
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py APP_015 --force --retry-key corrected-attempt-1
```

Record the batch UUID to recover that attempt. `--force` without a key intentionally
creates a new retry scope each invocation. It does not override missing-material
gates, saved officer recommendations/final decisions, evidence validation or human
approval requirements. IT dossier retries use the saved job UUID as a stable key.

Batch members bind the first saved input version. Resume skips finished members,
continues interrupted ones and marks changed input as STALE instead of generating
new facts under an old batch. Pipeline changes likewise require a new batch. An
intentional new direct-ID batch or new intake event can use the corrected version.

One `dossier_generation_runs` row is linked to each durable execution. That link,
the candidate/review request, execution completion and any automatic publication
commit together. Lost confirmation recovers the saved effect. Clean dossiers become
available automatically; flagged dossiers remain REVIEW_PENDING for the conditional
Exceptions tab. A batch resume never supplies human approval.

## Stored records and evidence

| Table | Durable responsibility |
| --- | --- |
| `ingestion_batch_events` | Content identity, receiver effect manifest, gate result, report and delivered summary |
| `generation_batches` | Stable batch scope, intake link and aggregate state |
| `generation_batch_members` | Applicant input version, progress, outcome and execution link |
| `generation_executions` | Input/pipeline/retry scope, owner, saved policies and final receiver links |
| `generation_section_checkpoints` | Committed attempts, outputs, validation errors and request hashes |
| `dossier_generation_runs.execution_id` | Unique link preventing duplicate final run rows for a resumed execution |

The [verification evidence](../../output/durable_batch_20261101/README.md) captures
actual PostgreSQL rows and actual MinIO objects in disposable schemas/buckets.
Model responses are controlled in these interruption tests; this is evidence of
workflow recovery, not a new live-Qwen accuracy benchmark.

Object storage and filesystem delivery are outside the database transaction.
Checksums detect drift; this implementation does not add immutable/versioned MinIO
retention or reconstruct missing historical objects. No filesystem watcher, streaming
model resume, production authentication, automatic approval or deployment supervisor
is added. Services must restart after code/config deployment.
