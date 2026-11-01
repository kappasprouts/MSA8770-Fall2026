# Durable checkpoint verification - October 31, 2026

Historical checkpoint: the mandatory all-dossiers release workflow described here
is superseded by the [integrated exception workflow](../integrated_exception_review_20261031/README.md).
The underlying durability tests remain applicable.

The generator now saves validated candidates in `REVIEW_PENDING` rather than
publishing automatically. A saved explicit decision authorizes only
`PUBLISH_ADVISORY_DOSSIER` for the named applicant/version before expiry. Candidate,
input/policy snapshot, pipeline version and generating run are retained. Approval,
publication, audit, status and the unique effect receipt commit atomically.

Implementation/setup: [durable checkpoint guide](../../docs/review_console/durable_checkpoint.md).
Current checks: [summary](summary.json), [Python JUnit](python_suite.xml),
[actual receiving-system snapshots](receiver_evidence.json).

| Case | Expected / actual verified result | Interpretation |
| --- | --- | --- |
| Approved run | One published dossier, one receipt; matching candidate hash and request link | Exact scoped version published |
| Missing confirmation/decision or wrong hash | 400/409; no publication before a valid decision | Absence is never approval |
| Rejection | REJECTED; zero publications/receipts | Action withheld, reason retained |
| Timeout | ESCALATED; late approval returns 409; zero effects | Deadline cannot authorize publication |
| Duplicate stage/decision | Same request returned; repeated matching decision returns saved receipt | No duplicate publication |
| Concurrent approval | Two successful responses, one marked replay; one receipt | Database row locks serialize the effect |
| Restart | New connection reads the same pending request | State is outside process memory |
| Interrupted approval | Connection closes before commit; zero published rows/receipts | Pending review remains recoverable |
| Lost confirmation | Commit, reconnect, replay; same receipt and one publication | Receiver checked before repeating |
| Source/policy change | SUPERSEDED; old decision rejected | Stale authorization withheld |
| Concurrent policy update | Policy write waits for approval transaction to finish | Freshness check and publication share one protected policy version |
| Receiver failure | Controlled receipt-write failure rolls back publication and decision | No approval/publication commit gap |
| Scanned evidence | Approval without human evidence attestation fails | Image-source uncertainty remains explicit |
| Actual generator path | Controlled model responses -> actual saved candidate -> new connection -> actual approval -> one publication | Working connected checkpoint path; model responses explicitly simulated |

All **169 Python tests passed with PostgreSQL configured**, including 13 checkpoint
integration cases. Receiver snapshots are captured before each disposable schema
is removed. All **55 UI tests passed**, including the actual decision route against
PostgreSQL, scoped-input validation, saved bucket/key/checksum handling, candidate
review content, structured notes and linked publication-run loading. TypeScript
passed; lint had no errors and one pre-existing unused-variable warning. The final
isolated webpack production build passed.

The production preview serves `/dossier-reviews` on `127.0.0.1:31040`. The browser
showed the saved-review workspace and empty-state message; final HTTP checks
confirmed the page, queue API and existing APP_012 dossier return 200. The existing
server on port 3000 runs its older build and was preserved. The preview is a
snapshot; rebuild/restart the normal UI to use future source changes.

The additive checkpoint migration was applied to the configured synthetic
`rsu_live_test` database. Existing applicant dispositions and published dossiers
were preserved, and no real/shared release decision was submitted. The public
review queue is empty until a new validated generation saves a candidate. No new
model inference or MinIO writes were performed during this checkpoint phase.

This demonstrates durable review recovery and one publication effect per request.
In-progress model-section/batch recovery, immutable object retention and production
authentication remain separate work. Rejected/expired requests remain closed;
they are not silently reopened or granted an extended deadline.
