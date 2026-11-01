# Interactive IT error queue

The IT queue at `/error-queue` saves operational actions. It handles processing
failures; admissions evidence interpretation remains in Applicant Review.
Identity is simulated. IT actions never record admissions recommendations/final
decisions and cannot approve invalid model output.

| Action | Saved effect |
| --- | --- |
| Claim investigation | IN_PROGRESS; staff member becomes owner; note and audit retained |
| Add investigation note | Append a note without changing applicant data or clearing the error |
| Assign follow-up owner | WAITING; explicit owner and handoff reason retained |
| Request processing retry | Durable QUEUED job for this applicant and failure/input version |
| Recheck receiving system / verify resolution | RESOLVED only when database evidence confirms correction |

Actions require name, note, command UUID, incident fingerprint and current case
revision. Retry/verification also require explicit confirmation. Matching command
replay returns the saved result; conflicting reuse/stale revisions return a conflict.
Case, job, action and applicant audit writes commit atomically. A queued job is not
a successful repair. An unanswered form does nothing.

The queue defaults to current detected issues. Use Records to view saved case
history. Details show notes, owner, retry state and receiver evidence. The prototype
lists up to 500 recent saved cases/jobs, 2,000 recent actions and 100 unmatched uploads;
complete records remain in PostgreSQL. New failure/input versions create distinct
incidents. Staff actions do not change the failure fingerprint.

Unmatched uploads support claim/notes/handoff. A guessed detected applicant ID
never becomes an approved match or receives that orphan's action audit. Verification
requires a unique registered document with the exact storage key, SHA-256, filename
and matching applicant metadata. Attaching an orphan remains an intake correction
outside this form.

## Setup and retry execution

Apply `storage/migrations/20261101_it_exception_actions.sql` after the existing
applicant/dossier schema. Use the same PostgreSQL, MinIO and model configuration
as the generator and UI:

```powershell
.\.venv\Scripts\python.exe -m ingestion.it_retry_worker --schema
.\.venv\Scripts\python.exe -m ingestion.it_retry_worker --watch
```

Omit `--watch` to process at most one queued job. A live worker heartbeat enables
its supported retry option. Without one, ownership/notes/handoff/verification remain
available, while retry is disabled. The local preview has a dossier retry worker running.

Summarizer retries call the existing generator for one failed applicant, rerunning
normal privacy/schema/evidence checks. Technical success can leave a validated
draft in REVIEW_PENDING for officer exception resolution. A newer generation,
changed source/policy snapshot or saved human disposition blocks stale execution.

Packet retries call canonical scoped `process_packet`, with a StorageManager
explicitly targeting the authorized database. They require an explicit worker-side
`INGESTION_INPUT_DIR` containing the intended corrected source batch. No default
batch or browser-supplied path is selected. The gate still requires PostgreSQL/object
storage and stops before model generation.

```powershell
$env:INGESTION_INPUT_DIR = (Resolve-Path '.\data\batches\batch_02').Path
.\.venv\Scripts\python.exe -m ingestion.it_retry_worker --watch
```

The current preview worker has no batch directory configured, so packet retries
are disabled. Other IT actions and dossier retries remain available.

## Durability and receiver verification

Workers claim jobs with row locks/SKIP LOCKED and hold a per-applicant advisory
lock during processing. There is one active/unconfirmed retry per applicant.
A stopped worker's RUNNING job becomes NEEDS_RECHECK after its heartbeat expires
(45 seconds) and a worker performs recovery; it is never blindly queued again.
Recheck either recovers a confirmed outcome or records no validated success,
keeps the case open and permits a new explicit retry. A failed new generation can
supersede the old incident; the new failure appears as a current issue.

Summarizer verification requires a newer validated run, fresh input snapshot,
saved review request and published pointer when published. Packet verification
requires canonical manifest audit/status; orphan verification requires the exact
registered match. A manual status flip or claimed correction is insufficient.
Applicant/policy locks protect freshness at outcome commit. If confirmation storage
fails after a dossier effect, the worker checks the receiver before repeating work.

## Verification and remaining limits

`tests/test_it_retry_worker.py` runs in isolated PostgreSQL schemas, including the
actual generator with controlled responses, interrupted recovery, stale scope,
human-disposition protection, serialization, lost confirmation and atomic result
audits. Its packet adapter test supplies a controlled gate result; existing ingestion
tests separately verify the canonical gate. `ui/tests/it-error-queue-ui.test.mjs`
executes the actual action endpoint against PostgreSQL, including rollback, replay,
worker availability, stale revisions, orphan handoff and verified closure.

Production authentication/roles, source-file editing/upload repair, direct orphan
matching, process supervision and token-stream recovery remain separate work.
Committed attempts/sections now recover through [durable generation](../ai_agent/DURABLE_BATCH_RECOVERY.md),
using the IT job UUID as a stable retry key. Jobs and receipts are durable; arbitrary external processing is not
claimed to be globally exactly once. Object bytes remain outside the DB transaction.
