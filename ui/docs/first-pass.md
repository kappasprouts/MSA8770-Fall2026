# Shared layout and correctness pass

The original `ui/` remains the application. Maya's separate prototype is unchanged.

## Navigation and loading

All workspace screens use `EaosShell`, the existing RSU logo and purple/warm-neutral theme, shared controls, status badges, and keyboard focus styling. Navigation becomes a compact horizontal row at narrow widths. The home page at `/` links to the three workspaces. Applicant review now lives at `/applicant-review`; existing `/?appId=...` dossier bookmarks redirect to `/applicant-review?appId=...`. Applicant selection updates the canonical URL without reloading the page.

Applicant changes immediately remove the previous payload, documents, and conversation. Outstanding requests are aborted, and response identity is checked before content is displayed. Failed requests, genuine empty results, and loading have distinct messages. JSON requests time out after 15 seconds and expose retry actions for data loading. The chat log scrolls internally without scrolling the whole page on mount.

## Validation provenance

`applicant_dossier` does not store a generation-run foreign key. Its content must not be presented as validated by whichever run happens to be latest. The snapshot therefore displays **Saved dossier validation: Unknown**, the **latest stored run's** explicit validation result separately, and the saved/update and run timestamps. It does not infer a relationship from matching timestamps.

Section counts use the final recorded attempt per section. Absent metadata is unknown, and failure states take precedence over a success flag. A failed latest run is called out when a saved dossier is available. This reports stored runs; failures that the agent never persisted still require an upstream fix.

## Counts and batch status

`GET /api/applicants/final-decision-queue` retains its `applicants` array and adds `totals: { awaiting, recorded, total }`. A single SQL statement reads both the pending queue and all-applicant aggregates from one snapshot. Recorded decisions include all processing statuses. External API overrides without these totals show unavailable metrics rather than zero.

The batch-status proxy has a five-second timeout. The dashboard distinguishes service failure, no previous run in the ingestion server's current session, a completed batch, and other reported states. Its application counts cover all records rather than a hardcoded academic year or latest batch.

## Checks

From `ui/`, with Node dependencies installed:

```powershell
npm run lint
npm test
npm run build
```

The tests use the installed TypeScript compiler and Node's built-in runner; no extra test dependency is needed. With `POSTGRES_*` variables set, they also exercise the actual decision aggregation query against a session-local temporary table and roll it back. Without those variables, that database check is explicitly skipped. No real applicant decisions are changed by this test.

On this checkout, npm is absent from PATH; equivalent commands are:

```powershell
node node_modules/eslint/bin/eslint.js .
node --test tests/first-pass.test.mjs
node node_modules/next/dist/bin/next build
```

Browser checks should cover Home and all three workspaces, desktop and narrow widths, legacy dossier redirects, rapid applicant switching, an unknown dossier, retry/refresh behavior, and keyboard navigation. Temporary switching fixtures must be removed afterward.

The document viewer redesign, clickable evidence navigation, persistent review notes, authentication, and pipeline repairs remain subsequent work. This pass does not submit a decision during browser verification.
