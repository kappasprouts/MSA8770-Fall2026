# M3 UI integration – IT queue

The **main purple `ui/` application** now has `/error-queue` and `/error-queue/[id]`, using the original prototype queue/details components and the purple Riverview shell. The API at `/api/exceptions` is read-only.

**Routing rule:** student-correctable `AWAITING_MATERIALS`, `INCOMPLETE`, and `REPLACEMENT_REQUESTED` are not surfaced as IT incidents. Technical ingest, processing and AI failures are surfaced; orphan uploads remain available for IT reconciliation. This is a conservative allowlist; extend it as the team's canonical status list evolves. The ingestion/processing dashboard continues to show missing-material statuses normally.

**Testing:** `npm install`, `npm test`, `npm run build`, `npm run dev`. Open `/error-queue`; select View Details; use Back and Open Applicant; check `/review-queue` still displays student-facing statuses. Verify the `/api/exceptions` endpoint against your PostgreSQL schema. No approval, record mutation, or notification actions are implemented by this change.

**Git integration:** Apply the `ui/` directory changes to a feature branch in the main repository, review the diff, test, then merge via PR. Do not replace the whole repo or copy local credentials.
