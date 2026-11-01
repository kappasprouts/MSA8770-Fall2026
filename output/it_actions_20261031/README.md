# IT action verification — October 31, 2026

[Operation guide](../../docs/review_console/it_error_actions.md) ·
[Summary](summary.json) · [Python JUnit](python_suite.xml) · [UI TAP](ui_tests.tap) ·
[Worker receiver snapshots](worker_receiver_evidence.json) ·
[Action-endpoint receiver snapshot](ui_receiver_evidence.json)

All **187 Python tests and 60 UI tests passed**, with PostgreSQL and no skips.
Eleven tests cover the IT worker. Production webpack build and TypeScript passed.
Lint passed with one existing unused-variable warning. Python reported one existing
Starlette/httpx deprecation warning.

Verified: persisted claim/owner/notes/handoff, explicit confirmed retry intent,
idempotent command replay, stale revision conflicts, atomic audit rollback, worker
availability, one active retry per applicant, source/human-disposition guards,
clean/flagged generator outcomes with controlled responses, receiver verification,
interrupted-worker recheck, lost result-save recovery and an exact orphan match.
Admissions evidence exceptions remain separate from technical resolution. No IT
test records an admissions recommendation or final decision.

The packet adapter uses a controlled gate result; existing ingestion tests verify
the canonical workflow separately. No new live model inference or MinIO writes
were performed for this implementation.

The additive migration was applied to `rsu_live_test`. In the initial test run,
an adapter used a process-wide database setting and two later CLI tests wrote
synthetic orphan-score rows to the shared test database. Those exact new rows were
removed; original rows were preserved. The adapter now constructs an explicit
StorageManager without changing environment settings. Final full suites passed
after correction. All rows in eight shared tables matched the restored baseline
after those suites. Shared IT cases/jobs remain zero. Tests use disposable schemas.

The production preview at `http://127.0.0.1:31040/error-queue` serves the interactive
queue/details page. A local worker runs explicitly requested dossier retries.
Packet retries await an explicitly configured batch directory. No shared IT action
was submitted merely to verify the page.
