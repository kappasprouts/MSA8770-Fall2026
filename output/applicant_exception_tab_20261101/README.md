# Conditional Applicant Review Exceptions tab

The Exceptions tab appears only when the dossier endpoint returns an outstanding
review checkpoint. Its panel owns the reasons, source-document navigation, deadline,
resolution fields, evidence attestation and correction/withhold action. Clean and
resolved published dossiers have no Exceptions tab or panel. Closed withheld drafts
retain a read-only explanation in Exceptions until corrected/regenerated.

Resolution draft state is shared with the recommendation form and stays mounted
across tab changes. Continuing does not persist or approve anything. The final
recommendation save records the same scoped resolution and recommendation atomically.
Unsaved review changes still trigger the applicant-switch/unload guard. Keyboard
navigation follows only visible tabs and falls back to Overview if Exceptions disappears.

All **63 UI tests passed with PostgreSQL configured**, with no failures/skips.
They cover conditional visibility, dynamic keyboard order, draft retention, source
navigation, incomplete-draft blocking, final payload scope, expired/closed drafts,
version mismatch and the actual existing receiver transaction. TypeScript, lint
and production webpack build passed; lint retains one existing unused-variable warning.
No Python code changed; the preceding 187-test backend verification remains recorded
in [IT-action evidence](../it_actions_20261031/README.md).

[UI TAP](ui_tests.tap) · [Verification summary](summary.json) ·
[Workflow guide](../../docs/review_console/durable_checkpoint.md)

No live inference, MinIO writes or shared applicant decisions were required.
PostgreSQL integration tests use disposable schemas. The preview runs at
`http://127.0.0.1:31040/applicant-review`; existing dossiers are preserved.
