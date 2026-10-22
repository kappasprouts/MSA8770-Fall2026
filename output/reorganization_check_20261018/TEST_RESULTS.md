# Repository reorganization verification — October 18, 2026

Tested checkout `2383eb2e328a3d901c55bb87d6b0d87910fc14ba` on Windows with Python 3.14, Node 24.19, PostgreSQL/pgvector, MinIO, and local Ollama. Live checks use a newly generated dossier, not just the older saved dossier.

**Verdict: the APP_012 ingestion → live agent → production UI → PDF → chat path completes after one output-path fix. The system does not pass its full correctness checks.** The new validated dossier still contains visa-related Hooks text from the supplement. A live probe also confirms that client-supplied system messages can override the chat instructions. Schema, document handling, evidence, and failure-reporting defects remain.

| Check | Result | Evidence |
| --- | --- | --- |
| Standard Python suite | **52 passed, 9 failed** | [JUnit output](python_initial.xml) |
| Explicit integration/guardrail probes | **6 passed, 19 failed** | [Failure summaries](contracts.txt), [JUnit output](contracts.xml) |
| Relocated Python modules | 40 tracked Python files parsed; API, gateway, parsing, validation imports passed | [Import check](import_checks.txt) |
| CLI entry points | Batch ingestion, score ingestion, and agent help load with UTF-8 output | `*_cli_help.txt` |
| PDF fixture integrity | 156 files / 207 pages open successfully | [Integrity check](pdf_integrity.txt) |
| Strict Batch 01 ingestion | 10 applicants: **9 ready / 1 awaiting** | [Report](batch_01_report.txt) |
| Strict Batch 02 ingestion | 10 applicants: **7 ready / 1 awaiting / 2 incomplete** | [Report](batch_02_report.txt), [handoff](affected_ids.json) |
| Authenticated object downloads | **149/149 uploaded applicant PDFs match the source bytes and SHA-256** | [Live preflight](live_preflight.json) |
| Live policy embeddings | **21 chunks, 768 dimensions**, using `nomic-embed-text` | [Loader output](policy_loader.txt), [preflight](live_preflight.json) |
| Ready-packet rendering | 13 of 16 ready applicants load; **APP_013, APP_016, APP_020 fail** | [Preflight](live_preflight.json) |
| UI lint | Passed | [Lint output (empty on success)](ui_lint.txt) |
| UI standard production build | **Passed with Turbopack**, including TypeScript and all four API routes; styling verified visually | [Build output](ui_build_turbopack.txt) |
| Documented webpack fallback | Compiles, but **omits Tailwind utility styles**; not a visually equivalent fallback | [Build output](ui_build.txt) |
| Fresh full dossier | **DOSSIER_READY**, validation true; run ID **2**, created **2026-10-18 22:43:16 UTC**; 531.6 seconds / 7 attempts | [Agent log](full_agent.txt), [snapshot](APP_012_dossier.json) |
| Production UI API checks | **14 passed**, including all five original PDFs, unknown records, and malformed/empty requests | [Checks and fresh DB run](live_ui_checks.json) |
| Original PDF in browser | Transcript opens as a real two-page PDF, displaying GPA 3.97 | [Browser screenshot](transcript_browser.png) |
| Live browser chat | Correct **3.97**, citing **CommonApp.pdf p.2** and recommendation evidence | [Screenshot](gpa_chat.png), [DOM](gpa_chat_dom.txt) |
| Applicant switching | Draft and completed conversation clear on switching and remain clear when switching back | [Fixture view](switch_fixture_dom.txt), [return view](switch_return_dom.txt) |
| Chat boundary probes | Decision request refused; absent personal statement was not invented; **client system-role override succeeded** | [Requests and responses](chat_probes.json) |

## Fresh agent and browser details

The first academic response cited GPA on CommonApp page 1. Validation rejected it; the built-in retry corrected the citations to page 2. Engagement, recommendation, supplement, policy, and synthesis all passed on their first attempt. The final academic facts match the fixture: unweighted GPA **3.97**, weighted GPA **4.4**, SAT **1530**, ACT **35**. Only CommonApp pages **1 and 2** were sent; its personal essay page was excluded.

The agent saved a new dossier, a new successful generation run, and the expected output snapshot. The completion message and batch summary both report `DOSSIER_READY`, confirming the relocated-output fix. The existing validator accepted 87 evidence-map entries; some transcript quotes retain `UNVERIFIED_IMAGE_SOURCE`. This run does not establish the factual accuracy of every generated claim or resolve the failing evidence-validation probes.

**Privacy failure in this fresh validated output:** `supplemental_essay_profile.responses[3].summary`, the supplement summary, and its evidence retain “international student on visa.” The same value appears in the supplement's “Additional applicant context” and the applicant's Hooks data. Redacting the CommonApp Hooks region does not prevent the duplicated value from entering through another permitted document. See the [saved dossier](APP_012_dossier.json) and [privacy probe](privacy_probe.json).

Browser checks used the standard Turbopack production build. The dossier, controls, styling, GPA answer, and applicant switching work. **Embedded PDF previews appear blank/dark in the in-app browser**, while all five PDF endpoints return exact original bytes and **View Full** opens a correctly rendered PDF. No second connected browser was available, so embedded-preview behavior in Chrome/Edge remains unverified.

Switch testing temporarily added a clearly labeled, minimal APP_014 dossier using an existing synthetic applicant. That fixture was removed after testing; it was not generated by the agent. The fixture also exposed misleading `Validated sections: Complete` text despite absent run/validation metadata.

## Regression corrected

Moving dossier snapshots from `summarizing_agent/results/` to `output/ai_agent/` left `path.relative_to(ROOT)` in the completion message, where `ROOT` now points at `ai_agent/`. The output is outside that directory, so logging raises `ValueError` after the dossier and generation run have already been saved. The CLI then reports `AGENT_ERROR` despite the saved success. The completion message now prints the output path directly. No model prompt or validation policy was changed.

## Remaining failures

- Seven standard test failures occur because the storage schema requires `admission_year`/`admission_term` although ingestion supports incomplete records and its configured required fields omit them. This schema behavior predates the reorganization.
- GPA storage remains `NUMERIC(3, 2)` while the regression test requires `NUMERIC(5, 3)`.
- One test expects `IsADirectoryError` when publishing a report over a directory; Windows raises `PermissionError`. The report/handoff publication test fails on this platform.
- Three otherwise ready Batch 02 packets fail Hooks redaction because the ordinary value “Not provided” appears elsewhere on the page. A real CLI run for APP_013 records `AGENT_ERROR` and exits **0**, without adding a failed generation run.
- Batch 01 activities and AP files upload and render, but their document types do not reach their intended agent sections. The optional exception document is also unused.
- The fresh handoff is still manual. In this test, the default agent loader reads an older `output/ingestion/affected_ids.json` containing Batch 01 IDs instead of this run's Batch 02 handoff. Explicit `APP_012` selection was used.
- The 19 diagnostic failures also reproduce stale score-feed prompts, weak quote/fact matching and nested schema checks, incomplete recommendation/privacy guards, incomplete stream detection, and lost per-document bucket metadata. See [the exact failures](contracts.txt); these were already described in the October 9 review and were not repaired during this verification.
- **Chat system-role injection:** `/api/chat` accepts a client message with `role: system` and passes it after the server's own system prompt. The live model returned the injected marker `UI_ROLE_OVERRIDE_OK`. The TypeScript message type is not runtime validation. This existing route code was unchanged by the reorganization.
- **Hooks content survives through the supplement:** the fresh dossier's validation is true even though its supplement summary/evidence include the visa-related value that CommonApp processing withholds. Output privacy checks must cover duplicated restricted context across permitted documents.
- **Transient applicant mismatch:** immediately after selecting APP_014, the UI displayed `APP_014 | Drew Young` with the previous dossier while the new request was pending. It then loaded the correct fixture. [Captured transition](switch_transition_dom.txt). The previous payload should not be presented under a newly selected applicant ID.
- **Build/preview limitations:** the webpack fallback loses styling, and embedded PDF previews were blank in the available browser, as described above.

## Environment and scope

The existing `rsu-live-test` containers were started with their existing volumes. Test writes target `rsu_live_test` on port 25432 and MinIO on 29000. Both installed Ollama models were used locally; no model output or storage was mocked for the live pipeline checks. Both batch ingestions deliberately reset their applicant statuses; APP_012 is then regenerated explicitly.

At completion, the temporary APP_014 dossier was removed and the UI server and both test containers were stopped, restoring the original service state. Database/object volumes and the new APP_012 dossier were retained. The only application-source edit is the agent's output-path completion message; the remaining additions are verification scripts and evidence.

The old ignored pnpm dependencies remained under `chat-ui/node_modules` after the source-folder move. Their Windows junctions contain absolute paths, so moving that directory breaks resolution. A temporary root junction enabled the initial webpack check, but Turbopack correctly rejected the link outside its project root. The temporary junction was removed and dependencies were installed directly into `ui/node_modules` with bundled pnpm, the existing workspace package store, and `--lockfile=false --ignore-scripts`. One uncached package needed npm-registry access. The original dependency directory was preserved. The source and dependency lockfile were unchanged; a clean `npm ci` was not tested because npm is not installed on this machine. [Install output](ui_install.txt).

Next.js needed network permission to download its configured Google fonts. Standard lint/build then passed. The first PostgreSQL connection through `localhost` was slow; subsequent strict ingestion used `127.0.0.1` with a connect timeout. Python CLI output was set to UTF-8 to support the existing status symbols.

## Reproduce

From the repository root, load `tests/live_test_setup/settings.ps1`, set `POSTGRES_HOST=127.0.0.1` and `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:25432/rsu_live_test?connect_timeout=10`, and start the two existing test containers.

1. Run `.venv/Scripts/python.exe -m pytest tests -q` and the explicit `tests/integration_review_20261009/test_integration_contracts.py` suite separately.
2. Run strict ingestion for both `data/batches/batch_01` and `batch_02`, with explicit report and affected-ID paths.
3. Run `ai_agent/create_pgvector_once.py` against the test database.
4. Run `tests/reorganization_check_20261018/verify_live_pipeline.py` to verify all object bytes and preflight rendering.
5. Record the UTC run-start time in `agent_started_at.txt`, then run `ai_agent/summarizing_agent.py APP_012` and capture its output in `full_agent.log`.
6. Load the same settings before building and starting the standard UI from `ui/` on port 3001. Run `verify_live_pipeline.py --ui` for fresh-run and API assertions, then perform the browser chat checks. `chat_probes.py` records the live boundary responses; it uses only the local synthetic dossier.

`verify_live_pipeline.py` is read-only. `ui_switch_fixture.py create/remove` manages only the owned temporary fixture in `rsu_live_test`; `chat_probes.py` invokes local inference without writing dossier records. Standard tests use temporary fixtures; ingestion, indexing, and the agent intentionally write synthetic test records. The UI remains read-only.
