# Integrated applicant review and durable exception checkpoint

Officers review an application once in `/applicant-review`: summary, original
documents, identified exceptions and recommendation are in the same workspace.
There is no mandatory release review for every dossier. The former
`/dossier-reviews` page redirects to Applicant Review; request bookmarks preserve
the applicant selection. Identity remains simulated for this prototype.

## Routing and the officer's work

| Generation result | Saved state and availability | Human action |
| --- | --- | --- |
| All sections validate; no identified exceptions | DOSSIER_READY; advisory dossier automatically available | Normal applicant review and recommendation |
| Validated output with source uncertainty, review notes/conflicts, or unclear policy evidence | REVIEW_PENDING; immutable draft visible only in the human workspace | Check flagged sources and save resolution with the recommendation |
| Invalid/incomplete output or input loading failure | AI_VALIDATION_FAILED / AGENT_ERROR; no new usable dossier | Correct inputs or generation upstream and rerun |

Exception classification is deterministic and saved with the candidate. It checks
`requires_human_verification`, evidence statuses other than `TEXT_VERIFIED`,
nonempty review notes, and policy alignment `unclear`. A below-threshold result
(`not_aligned`) alone is a normal admissions consideration, not an extraction
exception. An absent optional university supplement alone is not an exception.
These checks do not prove every generated claim correct; normal human admissions
review remains required for every applicant.

For a flagged draft the officer uses the existing Overview, Dossier and Documents
tabs plus a conditional **Exceptions** tab. Exceptions contains the reasons,
deadline, reviewer name, resolution reason, confirmation and evidence attestation.
It also offers the correction/withhold action. The tab is absent for applicants
without an outstanding draft checkpoint and disappears after successful resolution.
Resolution fields remain in memory when switching tabs; leaving the applicant warns
about unsaved review changes. **Continue to recommendation** does not publish or
persist the resolution. The Recommendation tab contains the recommendation form;
**Save resolution and recommendation** commits
the resolution, exact dossier publication, effect receipt, recommendation, status
and audits in one transaction. The officer does not repeat this work on a separate
release screen. The saved resolution remains visible on subsequent visits.

**Needs correction — withhold draft** saves a reason and closes the request without
publishing or recording an admissions recommendation. This does not reject the
applicant. Invalid model sections cannot be approved through this form. The final
admissions decision remains a separate existing role/workflow.

## Durability, version scope and receiving-system effects

The PostgreSQL migration retains the immutable candidate, source/policy snapshot,
pipeline fingerprint, generation run, deadline and owner. A clean automatic
publication has `review_mode=AUTOMATIC`, a unique receipt, a system audit event,
and **no invented human approval, reviewer or decision timestamp**. Flagged requests
have `review_mode=EXCEPTION`. Older requests retain `LEGACY_MANUAL` provenance.

Pending requests survive process/browser restarts. Missing decisions never resolve
exceptions. Requests expire after 24 hours, become ESCALATED and withhold publication.
Registered source/policy changes supersede pending authorization. Reads, decisions,
CLI reconciliation and the ingestion scheduler's 60-second timer enforce these
rules. The timer never approves or sends messages. Closed requests cannot be
silently reopened or granted a later deadline; correction/new validated versions
are required. No in-place reopening workflow is implemented.

Applicant/request row locks and a shared policy-table lock protect the freshness
check and commit. Recommendation writes require the exact request/hash displayed;
a newer version, expired request or changed registered inputs causes a conflict.
The UI also prevents independently refreshed recommendation metadata from
authorizing a draft different from the one on screen. Approval publication and
recommendation roll back together if any receiver/audit write fails. Matching
decision retries recover the saved receipt; there is one publication effect per
request. An identical generation input/pipeline reuses its saved outcome without
repeating model calls.

Unpublished drafts are loaded only by the human dossier endpoint. Q&A is disabled
for them and uses published data only. Linked draft and published source links use
the saved bucket/key and check SHA-256 bytes. Human-only essays remain available
to the officer and withheld from AI. Legacy dossiers retain unknown provenance.

## Setup and demonstration

Use the same PostgreSQL environment for the agent and UI. The schema command
initializes output tables, the base checkpoint migration and the integrated
exception-routing migration when missing:

```powershell
.\.venv\Scripts\python.exe -m ai_agent.review_checkpoint schema
.\.venv\Scripts\python.exe ai_agent/summarizing_agent.py APP_015
```

Existing installations can apply, in order:

1. `storage/migrations/20261031_durable_dossier_review.sql`
2. `storage/migrations/20261101_integrated_exception_review.sql`

Both are additive/idempotent and preserve existing dossiers/dispositions. No old
dossier is silently revalidated or placed into a new review. Rebuild/restart the UI
after changing source. Open `/applicant-review` and choose the applicant. Clean
generation returns DOSSIER_READY. Flagged validated generation returns REVIEW_PENDING.

For the M3 demonstration, show a controlled clean case, then a flagged case paused
in the same applicant workspace. Reconnect/restart and show the same saved pending
request. Resolve with a recommendation and inspect the request, publication pointer,
receipt, recommendation and audits in PostgreSQL. Also show that an unanswered or
expired request and a stale version cannot advance. Model responses in automated
checkpoint tests are controlled; they are not new live-model accuracy evidence.

Administrative inspection/recovery remains available:

```powershell
.\.venv\Scripts\python.exe -m ai_agent.review_checkpoint list
.\.venv\Scripts\python.exe -m ai_agent.review_checkpoint show REQUEST_UUID
.\.venv\Scripts\python.exe -m ai_agent.review_checkpoint reconcile
```

The lower-level CLI/decision API remains available for explicit administrative
decisions and historical recovery. Normal officer work uses the integrated form.

## Verification and remaining limits

`tests/test_durable_review.py` runs actual PostgreSQL functions in disposable schemas,
including clean automatic publication, exception routing, actual generator routing
with controlled responses, restart/replay, rejection, timeout, stale inputs, policy
write serialization and rollback. `ui/tests/dossier-review.test.mjs` runs the actual
combined recommendation endpoint against PostgreSQL and verifies atomic receiver
effects, stale scopes, required human decisions, saved source selection, draft
isolation, displayed-version binding and provenance text. PostgreSQL tests require
`POSTGRES_*` and explicitly skip without it. Tests do not change shared applicant
outcomes or MinIO objects.

Durable batch deduplication and committed model-attempt/section recovery are now
implemented; see the [recovery guide](../ai_agent/DURABLE_BATCH_RECOVERY.md).
Object storage is outside the database transaction: source reads
detect mismatched bytes, but database snapshots cannot detect object changes when
registered metadata is unchanged. Production authentication, role enforcement and
immutable object retention are not implemented.

| Design decision | Reason | Trade-off |
| --- | --- | --- |
| Automatically make clean advisory dossiers available | Avoid duplicate officer reading/release approval | Automated classification may miss a problem; normal human review remains necessary |
| Resolve exceptions with the recommendation | One applicant review session, one transactional save | A disputed/invalid draft must be corrected before recommending through this path |
| Preserve immutable scope and unique receipts | Prevent stale decisions and duplicate publication effects | Additional stored versions and explicit handling of closed requests |
