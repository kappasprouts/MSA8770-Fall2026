# Summary statistics

Open **Summary statistics** from Home or the workspace navigation, at `/statistics`.

The page follows the existing university theme and provides four sections with sticky jump navigation:

- Overview: unique applicant records, packet completeness, recorded decisions, missing required documents, and application creation trends.
- Academics: averages, medians, middle 50%, histograms for unweighted GPA/SAT/ACT/AP/IB, and data coverage.
- Representation: program choices, region/country, gender, ethnicity, and number of high schools represented.
- Cohort comparisons: admission year/term or program, with counts, completeness, decision progress, acceptance among recorded decisions, median GPA/SAT, and sample sizes.

Year, term, program, and decision filters apply to every section and CSV export. The URL preserves the filters for sharing or bookmarking. Clicking a program entry applies that filter. Chart controls switch academic metrics or geographic grouping. Long category lists can be expanded. Monthly values provide a text alternative to the trend plot, and charts have accessible labels. The comparison table scrolls within its own region on small screens.

## Sources and definitions

`GET /api/statistics` reads the existing PostgreSQL configuration (`POSTGRES_*`) through the shared connection pool. No schema migration or new dependency is needed. The endpoint selects aggregate input fields from all `applicants`, joined to each applicant's latest `MANIFEST_EVALUATED` or `MANIFEST_REEVALUATED` audit entry. A single statement provides a consistent database snapshot; repeated ingestions/audit events do not multiply counts. Only aggregates and filter options are returned to the browser, with `Cache-Control: no-store`.

- **Applications received** counts unique `applicants` rows, including records without a generated dossier. The current schema represents one application per applicant ID, not an independent collection of applications per person.
- **Complete packets** uses the current missing-material/field/error statuses, then latest manifest findings, then statuses that indicate a passed ingestion gate. Dossier-generation failure does not itself make the packet incomplete. Pending/unknown records are kept separate. Missing-document counts use the latest available audit findings, deduplicated within each packet, rather than a hardcoded checklist.
- **Decisions recorded** counts nonblank `final_decision` values across all processing statuses. `ACCEPT`, `DECLINE`, and `WAITLIST` have named categories. Unexpected values remain visible as other recorded decisions. Accepted/decided uses all recorded decisions as its denominator; a zero denominator displays an em dash.
- **Academic metrics** exclude blank, nonnumeric, and invalid values. Unweighted GPA must be 0–4. SAT must be an integer 400–1600; a valid superscore takes precedence over a valid Math + EBRW total. ACT must be an integer 1–36; a valid superscore takes precedence over composite. AP/IB use nonnegative integer course totals, including real zero values. Weighted GPA uses the reported nonnegative value without attempting to normalize school weighting scales. Percentiles use linear interpolation between sorted observations.
- **Coverage** counts usable values; SAT/ACT coverage may overlap, while the combined test-submitter count counts each applicant once. An absent IB total is unknown, not zero.
- **Program and demographic entries** retain their recorded labels, with surrounding whitespace removed. Combined program choices stay together; spellings, casing differences, and demographic categories are not inferred or recoded. Country/region use the stored school/geographic-context fields, not inferred residency or citizenship. Unknown values remain visible. High school count excludes blank school names.
- **Monthly trends** use valid ISO source `create_date_time` values. Database creation/import timestamps are excluded. Missing/invalid dates are reported separately, and gaps between months are filled with zero. These are current-cohort application-creation counts, not historical decision counts. Comparison cohorts may be at different stages in the admissions cycle.
- **CSV** includes filters, generation time, all category counts (including expanded-list categories), academic summaries/distributions, and both comparison groupings. Formula-like labels are escaped for spreadsheet use. No applicant identifiers or contact fields are exported.

The API currently aggregates selected input columns in memory on the server, which fits this prototype. A much larger deployment should move aggregations into database queries with suitable indexes and caching.

## Verification

Run `npm test`, `npm run lint`, and `npm run build -- --webpack` from `ui`. If the build needs network access for the existing Google Fonts setup, allow that access. Tests cover valid zeros, missing data, score boundaries, interpolated percentiles, filter consistency, histogram totals, overlapping test submissions, invalid dates, missing-document deduplication, CSV escaping, endpoint errors, and accessible populated markup.

With the `POSTGRES_*` variables set, the tests also run the actual aggregation SQL against session-local temporary tables, inside rolled-back transactions. They verify that the newest manifest result wins and joins do not inflate totals, without changing stored applicant records.
