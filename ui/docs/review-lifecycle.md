# Application review statuses

The application lifecycle continues after dossier generation:

| Stored status | UI label | Trigger |
| --- | --- | --- |
| `DOSSIER_READY` | Dossier ready | A dossier is saved successfully. |
| `REVIEWED` | Reviewed | An officer recommendation is saved successfully. |
| `FINAL_DECISION_RECORDED` | Final decision recorded | A human-approved final decision is saved successfully. |

Recommendation and decision outcomes remain separate fields. Saving notes with a recommendation keeps the application Reviewed. Recommendation edits are permitted in Dossier ready and Reviewed until a final decision is recorded. Final decisions retain the existing eligibility rules: either of those statuses is eligible, so this change does not introduce a mandatory recommendation prerequisite.

Both save endpoints update the status, outcome, and audit event in the same transaction. Failed saves leave the prior status intact. Final decisions take precedence over recommendations, and applications with a final decision cannot be edited through these endpoints.

The processing dashboard has separate milestone counts, filter options, and badges. Dossier links remain available in all three statuses. Applicant Review shows the current status beside the applicant identity and updates it after a recommendation save. Reviewed applicants remain in the final-decision queue. Statistics continue to count reviewed and finalized packets as complete.

## Existing databases

After applying `storage/migrations/20261030_officer_recommendation.sql`, run `storage/migrations/20261031_review_lifecycle_statuses.sql` against the configured PostgreSQL database. The migration is idempotent: existing final decisions become Final decision recorded, otherwise saved recommendations become Reviewed. It preserves outcome fields and timestamps. Other applicants retain their statuses. SQLite fallback stores reconcile the same milestones during their existing startup migration.

Automated packet updates and dossier-run saves preserve human milestones when a recommendation or final decision already exists. A dedicated reopening/correction workflow is outside this change.

## Verification

`node --env-file=.env.local --test tests/*.test.mjs` from `ui` runs the PostgreSQL tests against session-local temporary tables as well as the UI regressions. The tests cover backfill precedence and idempotency, recommendation edits, final-decision eligibility, audit rollback, filtering, counts, and persistent dossier links. `tests/test_review_lifecycle.py` also exercises SQLite upgrades, packet updates, and actual dossier-run saves against PostgreSQL temporary tables when `POSTGRES_*` is configured.
