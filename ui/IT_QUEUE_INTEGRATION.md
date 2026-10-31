# M3 UI integration – IT queue

The `mi` UI includes `/error-queue` and `/error-queue/[id]`, integrated from `maya/it-error-queue` (commit `b872984d`). The new pages use `mi`'s shared shell, cards, controls, tables, semantic badges, and purple/beige theme. The API at `/api/exceptions` is read-only.

The IT Error Queue replaces the Tech Support placeholder on Home and in the sidebar. The sidebar remains active on exception detail routes, including in the compact layout. Existing processing, review tabs, recommendations, decisions, and statistics are preserved. The dossier action uses the canonical `/applicant-review?appId=...` route.

**Routing rule:** student-correctable `AWAITING_MATERIALS`, `INCOMPLETE`, and `REPLACEMENT_REQUESTED` are not surfaced as IT incidents. Technical ingest, processing and AI failures are surfaced; orphan uploads remain available for IT reconciliation. This is a conservative allowlist; extend it as the team's canonical status list evolves. The ingestion/processing dashboard continues to show missing-material statuses normally.

**Testing:** `npm test`, `npm run lint`, `npm run build`, `npm run dev`. The IT tests cover student/technical routing, API evidence mapping, combined queue filters and document search, loading/error/empty states, exception details, dossier availability, and encoded navigation. Open `/error-queue`; select View Details; use Back and Open Applicant; check `/review-queue` still displays student-facing statuses. Verify `/api/exceptions` against a running PostgreSQL instance. No approval, record mutation, or notification actions are implemented by this change.

**Scope:** Only the new IT feature and its navigation links are integrated; the older branch's shared UI files do not replace the current `mi` implementation. Local credentials and dependencies are unchanged.
