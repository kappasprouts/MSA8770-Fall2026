# Integrated exception review verification — October 31, 2026

The all-dossiers release queue is replaced with one Applicant Review workflow.
Fully validated dossiers without identified exceptions become available automatically.
Flagged validated drafts remain saved and are resolved with the officer recommendation
in a single transaction. Invalid/incomplete model output remains withheld.

[Workflow/setup guide](../../docs/review_console/durable_checkpoint.md) ·
[Machine-readable summary](summary.json) · [Python JUnit](python_suite.xml) ·
[Python receiver snapshots](receiver_evidence.json) · [UI TAP](ui_tests.tap) ·
[Combined-review receiver snapshot](integrated_receiver_evidence.json)

| Scenario | Verified receiving-system result |
| --- | --- |
| Clean validated candidate | PUBLISHED / AUTOMATIC, one dossier and receipt; human decision/reviewer/timestamp remain NULL |
| Notes/conflicts, uncertain source evidence or unclear policy evidence | REVIEW_PENDING / EXCEPTION; no published candidate or receipt |
| Optional supplement absent | Does not alone trigger exception review |
| Actual generator, controlled responses | Clean path automatically publishes; flagged path pauses; matching saved versions reuse without more model calls |
| Missing resolution, confirmation, evidence attestation or version | Request fails; no applicant recommendation or publication effect |
| Combined save | Saved resolution and exact dossier publication plus recommendation; applicant REVIEWED, final_decision still NULL |
| Recommendation audit failure | Entire transaction rolls back: pending request retained, no receipt/dossier/recommendation |
| Lost response and replay | Same receipt; one published dossier |
| Clean modern recommendation | Normal recommendation saves with version scope and no exception fields |
| Registered input changes or stale displayed version | Recommendation blocked until current dossier is reviewed |
| Restart, timeout, rejection, policy-change race | Existing durable-checkpoint guarantees continue to pass |
| Unpublished source access | Human endpoint loads exact saved draft and source bucket/key/checksum; published-only consumers receive no draft |

All **176 Python tests passed**, including **20 checkpoint integration cases**.
All **57 UI tests passed**, including the actual combined recommendation route
against isolated PostgreSQL tables. TypeScript and production webpack build passed.
Lint passed with one pre-existing unused-variable warning. Python emitted one
existing Starlette/httpx deprecation warning. Neither suite skipped tests.

The migration was applied to the configured synthetic `rsu_live_test` database.
All 20 shared applicant rows and five published dossiers were compared before/after
and preserved exactly. Shared review requests remain zero. Integration tests use
disposable schemas; receiver snapshots are captured before cleanup. The recorded
clean/flagged applications in test evidence are synthetic controlled cases, not
shared applicant decisions. No new live model inference or MinIO writes occurred.

The preview at `http://127.0.0.1:31040/applicant-review` serves an isolated build of
the updated source. Old `/dossier-reviews` links redirect there. Existing dossiers
have no new exceptions assigned automatically; new generation exercises the routing.
The older server on port 3000 is preserved. Rebuild/restart the normal UI for future
source edits.

Authentication is simulated. Batch-event deduplication, recovery within interrupted
model-section execution and immutable object retention remain separate work.
