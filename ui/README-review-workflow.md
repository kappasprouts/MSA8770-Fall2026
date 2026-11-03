# Review Workflow Updates — Reviewer Recommendation & Navigation

This README covers the changes made on top of `maria/integration` (commit `fd50f77`). For general setup, running the UI, and the rest of the workspace, see the main [UI README](README.md).

## Contents

1. [What changed](#what-changed)
2. [Setup: database migration](#setup-database-migration)
3. [Reviewer recommendation](#reviewer-recommendation)
4. [Processing Dashboard and Final Decisions](#processing-dashboard-and-final-decisions)
5. [Back to Previous Screen](#back-to-previous-screen)
6. [API reference](#api-reference)
7. [Files changed](#files-changed)
8. [Testing checklist](#testing-checklist)
9. [Troubleshooting](#troubleshooting)
10. [Limitations](#limitations)

## What changed

| Area | Change |
|---|---|
| Applicant Review | New **Reviewer recommendation** panel: Recommend Accept / Waitlist / Decline, plus a required confirmation checkbox |
| PostgreSQL | Three new columns on `applicants`; each submission is also logged in `audit_logs` |
| Processing Dashboard | New **Recommendation** column and **Recommendations submitted** count |
| Final Decisions | The Dean sees the reviewer's recommendation in the queue and on the decision form |
| Navigation | **← Back to Previous Screen** follows a fixed workflow path instead of browser history |

## Setup: database migration

New databases get the columns automatically from `storage/models.py`. For an **existing** database, run the migration once from the repository root:

```bash
docker compose exec -T postgres psql -U postgres -d riverview_admissions \
  -v ON_ERROR_STOP=1 < storage/migrations/20261102_reviewer_recommendation.sql
```

It adds these columns to `applicants`:

| Column | Type | Purpose |
|---|---|---|
| `reviewer_recommendation` | `VARCHAR(10)` | `ACCEPT`, `WAITLIST`, or `DECLINE`; `NULL` until submitted |
| `reviewer_recommendation_note` | `TEXT` | Reserved for an optional rationale; the UI doesn't currently collect it |
| `reviewer_recommended_at` | `TIMESTAMPTZ` | When the recommendation was last saved |

The migration uses `ADD COLUMN IF NOT EXISTS`, so running it again is harmless. No other setup is needed: restart or refresh `npm run dev` as usual.

## Reviewer recommendation

On **Applicant Review**, select an applicant. The panel appears between the dossier/documents and the Q&A assistant.

1. **Choose an option.** There are three cards: **Recommend Accept** (green), **Recommend Waitlist** (amber), and **Recommend Decline** (red). The selected card is highlighted with a check mark.
2. **Confirm.** Tick **"I confirm I submitted a confidential recommendation."** The submit button stays disabled until this is ticked. The box clears whenever the choice changes and after each save, so every submission is confirmed again.
3. **Submit.** Click **Submit recommendation**, or **Update recommendation** if one is already saved. **Discard changes** returns to the saved choice.

The chip in the panel's top-right corner shows the saved recommendation and when it was saved, for example *Recommend Accept · Saved Nov 3, 2026, 12:19 AM*.

**When submitted**, the choice and timestamp are written to that applicant's row in `applicants`, and a `REVIEWER_RECOMMENDATION_RECORDED` event is added to `audit_logs`. The event records the new and previous recommendation.

**Rules**

- Recommendations are accepted only when the applicant's status is `DOSSIER_READY`.
- A recommendation can be revised until the Dean records a final decision. After that, the panel is locked and shows the recorded decision.
- The recommendation is **advisory**. It never sets or changes `final_decision`.

## Processing Dashboard and Final Decisions

- **Processing Dashboard** (`/review-queue`): the ledger has a **Recommendation** column between *Application Status* and *Final Decision*, with a coloured badge or *No recommendation*. The **Recommendations submitted** count is at the top. Click **Refresh** if the page was already open when the recommendation was submitted.
- **Final Decisions** (`/final-decisions`): the queue has a **Reviewer recommendation** column, and the *Record Dean's Decision* form shows it above the existing final decision.

## Back to Previous Screen

The **← Back to Previous Screen** button in the top bar no longer uses browser history. It always goes to:

| From | Goes to |
|---|---|
| Processing Dashboard | Home |
| Applicant Review | Processing Dashboard |
| Final Decisions | Home |
| Summary Statistics | Home |
| IT Error Queue | Home |
| IT error details (`/error-queue/[id]`) | IT Error Queue |

To change a destination, edit the `previousScreen` object in `src/components/EaosShell.tsx`. Unlisted top-level screens go to Home, and nested screens go to their parent list.

## API reference

### `GET /api/applicants/{id}/recommendation`

Returns the applicant's current recommendation state:

```json
{
  "appId": "APP_012",
  "applicationStatus": "DOSSIER_READY",
  "finalDecision": null,
  "recommendation": "WAITLIST",
  "note": null,
  "recommendedAt": "2026-11-03T05:19:16.880Z"
}
```

`404` if the applicant doesn't exist.

### `PUT /api/applicants/{id}/recommendation`

Request body:

```json
{ "recommendation": "ACCEPT" }
```

`recommendation` must be `ACCEPT`, `WAITLIST`, or `DECLINE`. An optional `note` string (up to 1,000 characters) is also accepted. On success, the endpoint returns the same shape as `GET`.

| Status | Meaning |
|---|---|
| `200` | Saved, and an audit event was written |
| `400` | Invalid JSON, recommendation value, or note |
| `409` | Applicant not found, not `DOSSIER_READY`, or already has a final decision |
| `500` | Database error; nothing was saved (the transaction is rolled back) |

The Processing Dashboard (`/api/applicants/review-queue`) and Final Decisions (`/api/applicants/final-decision-queue`) queue endpoints now also return `reviewerRecommendation`. The final-decision queue also returns `reviewerRecommendationNote`.

## Files changed

| File | Change |
|---|---|
| `storage/models.py` | New `Applicant` columns |
| `storage/migrations/20261102_reviewer_recommendation.sql` | **New.** Migration for existing databases |
| `ui/src/app/api/applicants/[id]/recommendation/route.ts` | **New.** `GET` / `PUT` endpoint with audit logging |
| `ui/src/components/RecommendationPanel.tsx` | **New.** The panel on Applicant Review |
| `ui/src/components/recommendation.module.css` | **New.** Panel styles (uses the theme tokens in `globals.css`) |
| `ui/src/components/ApplicantReview.tsx` | Places the panel on the page |
| `ui/src/components/StatusBadge.tsx` | New `RecommendationBadge` |
| `ui/src/components/EaosShell.tsx` | Fixed back-navigation map |
| `ui/src/app/review-queue/page.tsx` | Recommendation column and count |
| `ui/src/app/final-decisions/page.tsx` | Recommendation in queue and decision form |
| `ui/src/app/api/applicants/review-queue/route.ts` | Returns the recommendation |
| `ui/src/app/api/applicants/final-decision-queue/route.ts` | Returns the recommendation and note |
| `ui/src/lib/eaos-api.ts` | Client helpers and types |
| `ui/src/lib/review-state.ts` | `recommendationLabel()` |

## Testing checklist

- [ ] The migration has been run, and `\d applicants` shows the three new columns.
- [ ] On Applicant Review, **Submit recommendation** stays disabled until an option is chosen **and** the confirmation box is ticked.
- [ ] After submitting, `SELECT app_id, reviewer_recommendation, reviewer_recommended_at FROM applicants;` shows the new value.
- [ ] `audit_logs` has a `REVIEWER_RECOMMENDATION_RECORDED` row for that applicant.
- [ ] The Processing Dashboard **Recommendation** column and count update after **Refresh**.
- [ ] The Final Decisions queue and form show the recommendation.
- [ ] An applicant with a recorded final decision shows a locked panel.
- [ ] **Back to Previous Screen** follows the table above on every screen.
- [ ] `npx eslint src` and `npx tsc --noEmit` pass.

## Troubleshooting

**"Recommendation could not be loaded" or a server error on save:** The recommendation columns are probably missing. Run the [migration](#setup-database-migration).

**The panel is locked:** The applicant already has a final decision, or isn't `DOSSIER_READY` yet. This is intentional.

**Submit stays greyed out:** Choose an option that differs from the saved one, then tick the confirmation box.

**The dashboard doesn't show a new recommendation:** Click **Refresh** on the Processing Dashboard. The page loads its data once when it opens.

## Limitations

- Authentication is still simulated. Audit events use the actor `reviewer_simulated`, so "confidential" currently means the recommendation appears only on internal review screens. There is no per-user access control yet.
- One recommendation per applicant: a new submission replaces the previous one. Earlier values remain in `audit_logs`.
- The optional rationale (`reviewer_recommendation_note`) is supported by the database and API but isn't shown in the panel.
