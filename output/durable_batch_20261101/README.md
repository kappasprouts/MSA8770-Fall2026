# Durable batch and generation verification — November 1, 2026

[Operation guide](../../docs/ai_agent/DURABLE_BATCH_RECOVERY.md) ·
[Summary](summary.json) · [Python JUnit](python_suite.xml) · [UI TAP](ui_tests.tap) ·
[Intake/MinIO receiver snapshots](batch_receiver_evidence.json) ·
[Generation checkpoints](generation_receiver_evidence.json) · [Receiving-system case table](receiving_system_cases.md)

All **209 Python tests and 63 UI tests passed**, with PostgreSQL configured and no
skips. Ten end-to-end cases use actual MinIO plus PostgreSQL; eleven generation cases
use actual PostgreSQL and controlled source/model responses. The suite also verifies
per-applicant progress, live object checksums and two-decimal GPA scope linking.
Python emits one existing Starlette/httpx deprecation warning. No UI source changed
in this phase, so the prior production build/type/lint verification remains applicable.

Key actual effects:

- Identical batch copied to a second directory: one intake event, two applicants,
  one orphan row, eleven MinIO objects and eleven initial uploads; zero new uploads
  on replay. One generation batch, two generation runs, two dossiers, two receipts.
- Interrupted generation after applicant one and two sections of applicant two:
  a new connection completes only unfinished sections. Academic/engagement are
  called once per applicant. Final status is DOSSIER_READY for both, one receipt
  each; all ten applicant PDF objects pass actual SHA-256 checks.
- Report-delivery failure resumes from the saved receiver receipt without uploads.
  Intake failure before a receipt requires an explicit repair scope.
- Missing/changed objects, unconfirmed handoff, changed inputs/policies, competing
  owners and stale ownership cannot authorize a new publication.
- Exhausted invalid model attempts keep their retry budget. Lost post-publication
  confirmation does not duplicate the dossier/run/receipt. Human dispositions and
  missing-material gates remain protected.

The additive migration was applied twice to `rsu_live_test` to check idempotence.
Existing application/dossier/audit records were compared before/after and preserved;
the only existing-row shape addition is nullable `dossier_generation_runs.execution_id`.
Tests use private schemas and uniquely named `batch-recovery-*` buckets, capture
effects before cleanup and remove their own data. Shared intake/generation ledgers
remain empty; no live/shared applicant generation or human decision was submitted.

These tests include real MinIO reads/writes for synthetic PDFs and controlled model
responses. They do not constitute new live-model quality or timing evidence. An
unsaved in-flight model call may repeat after a crash; published effects remain
protected by saved scope and receipts. See the guide for the pre-receipt intake
repair limit and other boundaries.
