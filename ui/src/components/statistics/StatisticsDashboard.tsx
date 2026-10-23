"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import EaosShell from "@/components/EaosShell";
import RequestState from "@/components/RequestState";
import { requestJson } from "@/lib/http";
import { EMPTY_FILTERS, UNKNOWN, UNKNOWN_LABEL, statisticsCsv, termLabel, type FilterOption, type StatisticsFilters, type StatisticsPayload } from "@/lib/statistics";
import { BarList, DecisionChart, Histogram, TrendChart, formatNumber, formatPercent } from "./Charts";
import styles from "./statistics.module.css";

const sections = [["overview", "Overview"], ["academics", "Academics"], ["representation", "Representation"], ["comparisons", "Cohort comparisons"]] as const;

function Panel({ title, description, children, className = "" }: { title: string; description?: string; children: ReactNode; className?: string }) {
  return <div className={`${styles.panel} ${className}`}><div className={styles.panelHeading}><h3>{title}</h3>{description && <p>{description}</p>}</div>{children}</div>;
}
function Metric({ label, value, detail, accent = false }: { label: string; value: string; detail: string; accent?: boolean }) {
  return <div className={`${styles.metric} ${accent ? styles.accentMetric : ""}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}
function Filter({ label, allLabel, options, value, onChange }: { label: string; allLabel: string; options: FilterOption[]; value: string; onChange: (value: string) => void }) {
  return <label className={styles.filter}>{label}<select value={value} onChange={event => onChange(event.target.value)}>
    <option value="">{allLabel}</option>
    {value && !options.some(o => o.value === value) && <option value={value}>{value === UNKNOWN ? UNKNOWN_LABEL : value}</option>}
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select></label>;
}

export default function StatisticsDashboard({ initialFilters = EMPTY_FILTERS }: { initialFilters?: StatisticsFilters }) {
  const [filters, setFilters] = useState<StatisticsFilters>(initialFilters);
  const [data, setData] = useState<StatisticsPayload | null>(null);
  const [options, setOptions] = useState<StatisticsPayload["options"]>({ years: [], terms: [], majors: [] });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [academicKey, setAcademicKey] = useState("gpa");
  const [geography, setGeography] = useState<"regions" | "countries">("regions");
  const [comparison, setComparison] = useState<"cycle" | "program">("cycle");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const controller = new AbortController(), params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    const query = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
    requestJson<StatisticsPayload>(`/api/statistics${query ? `?${query}` : ""}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) { setData(result); setOptions(result.options); } })
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Statistics could not be loaded."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, attempt]);

  function changeFilters(next: StatisticsFilters) { setLoading(true); setData(null); setError(""); setNotice(""); setFilters(next); }
  function refresh() { setLoading(true); setData(null); setError(""); setNotice(""); setAttempt(n => n + 1); }
  function exportSummary() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([statisticsCsv(data)], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a");
    link.href = url; link.download = `admissions-summary-${data.generatedAt.slice(0, 10)}.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Summary CSV downloaded for the selected filters.");
  }
  const selected = [filters.year && `${filters.year === UNKNOWN ? "Unknown year" : filters.year}`, filters.term && termLabel(filters.term), filters.major && (filters.major === UNKNOWN ? "Unknown program" : filters.major), filters.decision && ({ ACCEPT: "Accepted", DECLINE: "Declined", WAITLIST: "Waitlisted", UNRECORDED: "No decision", OTHER: "Other decision" }[filters.decision])].filter(Boolean).join(" · ") || "All admission cohorts";
  const activeFilters = Object.values(filters).some(Boolean);

  return <EaosShell title="Summary statistics" subtitle="A clear view of your applicant pool, admissions progress, and academic profile." role="Admissions insights">
    <div className={styles.toolbar}>
      <div className={styles.cohortLabel}><span className={styles.liveDot} aria-hidden="true" />{selected}</div>
      <div className={styles.toolbarActions}><button type="button" onClick={refresh} disabled={loading}>↻ Refresh</button><button type="button" className={styles.exportButton} onClick={exportSummary} disabled={loading || !data}>↓ Export CSV</button></div>
    </div>
    <section className={styles.filters} aria-label="Filter summary statistics">
      <Filter label="Admission year" allLabel="All years" options={options.years} value={filters.year} onChange={year => changeFilters({ ...filters, year })} />
      <Filter label="Admission term" allLabel="All terms" options={options.terms} value={filters.term} onChange={term => changeFilters({ ...filters, term })} />
      <Filter label="Major / program" allLabel="All programs" options={options.majors} value={filters.major} onChange={major => changeFilters({ ...filters, major })} />
      <Filter label="Final decision" allLabel="All decisions" options={[{ value: "ACCEPT", label: "Accepted" }, { value: "DECLINE", label: "Declined" }, { value: "WAITLIST", label: "Waitlisted" }, { value: "UNRECORDED", label: "No decision recorded" }, { value: "OTHER", label: "Other recorded decision" }]} value={filters.decision} onChange={decision => changeFilters({ ...filters, decision })} />
      <button type="button" className={styles.resetButton} disabled={!activeFilters} onClick={() => changeFilters({ ...EMPTY_FILTERS })}>Reset filters</button>
    </section>
    <nav className={styles.sectionNav} aria-label="Statistics sections">{sections.map(([id, label], i) => <a key={id} href={`#${id}`}><span>{String(i + 1).padStart(2, "0")}</span>{label}</a>)}</nav>
    <div aria-live="polite" className={styles.resultStatus}>{loading ? "Updating statistics…" : data ? `${formatNumber(data.total)} of ${formatNumber(data.totalRecords)} applications · Refreshed ${new Date(data.generatedAt).toLocaleString()}` : "Statistics unavailable"}{notice && <span> · {notice}</span>}</div>
    <div aria-busy={loading}>
      {loading ? <><div className={styles.skeletons} aria-hidden="true">{[0, 1, 2, 3].map(i => <div key={i} />)}</div><RequestState kind="loading" title="Loading applicant statistics…" description="Preparing the selected cohort and its distributions." /></>
        : error ? <RequestState kind="error" title="Statistics could not be loaded" description={error} onRetry={refresh} />
          : data && data.total === 0 ? <RequestState kind="empty" title={data.totalRecords ? "No applications match these filters" : "No applications yet"} description={data.totalRecords ? "Try another admission year, term, program, or decision." : "Statistics will appear after applicant records are ingested."} onRetry={activeFilters ? () => changeFilters({ ...EMPTY_FILTERS }) : undefined} actionLabel="Reset filters" />
            : data && <StatisticsContent data={data} academicKey={academicKey} onAcademicChange={setAcademicKey} geography={geography} onGeographyChange={setGeography} comparison={comparison} onComparisonChange={setComparison} onProgramSelect={label => changeFilters({ ...filters, major: label === UNKNOWN_LABEL ? UNKNOWN : label })} />}
    </div>
  </EaosShell>;
}

/** Kept separate so populated views can also be verified with synthetic fixtures. */
export function StatisticsContent({ data, academicKey, onAcademicChange, geography, onGeographyChange, comparison, onComparisonChange, onProgramSelect }: {
  data: StatisticsPayload; academicKey: string; onAcademicChange: (key: string) => void;
  geography: "regions" | "countries"; onGeographyChange: (key: "regions" | "countries") => void;
  comparison: "cycle" | "program"; onComparisonChange: (key: "cycle" | "program") => void; onProgramSelect: (label: string) => void;
}) {
  const academic = data.academics.find(m => m.key === academicKey) ?? data.academics[0];
  const completePercent = formatPercent(data.complete, data.total);
  const comparisonRows = data.cohorts[comparison];
  const waitingForMaterials = data.completeness.filter(i => ["Awaiting documents", "Missing required fields"].includes(i.label)).reduce((sum, i) => sum + i.count, 0);
  return <>
    <section id="overview" className={styles.section} aria-labelledby="overview-title">
      <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>THE BIG PICTURE</span><h2 id="overview-title">Admissions overview</h2></div><Link href="/review-queue" className={styles.workspaceLink}>Open processing dashboard →</Link></div>
      <div className={styles.metrics}>
        <Metric label="Applications received" value={formatNumber(data.total)} detail="Unique applicant records in this cohort" accent />
        <Metric label="Complete packets" value={formatNumber(data.complete)} detail={`${completePercent} of selected applications`} />
        <Metric label="Decisions recorded" value={formatNumber(data.recorded)} detail={`${formatNumber(data.withoutDecision)} application${data.withoutDecision === 1 ? "" : "s"} without a decision`} />
        <Metric label="SAT or ACT reported" value={formatPercent(data.testSubmitters, data.total)} detail={`${formatNumber(data.testSubmitters)} of ${formatNumber(data.total)} applicants`} />
      </div>
      <div className={styles.twoColumns}>
        <Panel title="Decision progress" description="Recorded admissions outcomes · percentages of this cohort">
          <DecisionChart items={data.decisions} total={data.total} recorded={data.recorded} />
          <div className={styles.panelFooter}><span>Accepted among recorded decisions <strong>{formatPercent(data.accepted, data.recorded)}</strong></span><Link href="/final-decisions">Open final decisions →</Link></div>
        </Panel>
        <Panel title="Application completeness" description="Packet readiness from checklist results and processing status">
          <BarList items={data.completeness} total={data.total} />
          <p className={styles.callout}><strong>{formatNumber(waitingForMaterials)}</strong> applications need documents or required fields before they can move forward.</p>
        </Panel>
      </div>
      <div className={styles.twoColumns}>
        <Panel title="Application volume over time" description="Monthly counts using the source application creation date">
          <TrendChart items={data.trend} />
          <p className={styles.note}>{formatNumber(data.total - data.trendUndated)} dated application{data.total - data.trendUndated === 1 ? "" : "s"} · {formatNumber(data.trendUndated)} missing or invalid source dates. Each application is counted once; database import dates are excluded.</p>
        </Panel>
        <Panel title="Missing required documents" description="Applicants affected, using each packet’s latest checklist evaluation">
          {data.missingDocuments.length ? <BarList items={data.missingDocuments} total={data.total} /> : <p className={styles.emptyChart}>{data.missingDetailsCount ? "No missing documents listed in available checklist results." : "No missing-document findings available for this cohort."}</p>}
          <p className={styles.note}>A packet may be missing more than one document. Details are available for {formatNumber(data.missingDetailsCount)} packets that are not complete.</p>
        </Panel>
      </div>
    </section>

    <section id="academics" className={styles.section} aria-labelledby="academics-title">
      <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>ACADEMIC PROFILE</span><h2 id="academics-title">Academic statistics</h2></div><span className={styles.sectionHint}>Valid reported values only</span></div>
      <div className={styles.academicCards}>{data.academics.filter(m => ["gpa", "sat", "act", "ap"].includes(m.key)).map(m => <div key={m.key} className={styles.academicCard}><span>Average {m.label}</span><strong>{formatNumber(m.mean, m.key === "gpa" ? 2 : ["ap", "act"].includes(m.key) ? 1 : 0)}</strong><small>{formatNumber(m.count)} reported · {formatNumber(m.missing)} missing / invalid</small></div>)}</div>
      <div className={styles.twoColumns}>
        <Panel title="Academic distributions" description="See the spread of scores and coursework across the selected pool.">
          <div className={styles.metricPicker} role="group" aria-label="Choose academic distribution">{data.academics.filter(m => m.histogram.length).map(m => <button key={m.key} type="button" aria-pressed={academic.key === m.key} onClick={() => onAcademicChange(m.key)}>{m.key === "gpa" ? "GPA" : m.key.toUpperCase()}</button>)}</div>
          <div className={styles.distributionSummary}><div><small>Median {academic.label}</small><strong>{formatNumber(academic.median, academic.key === "gpa" ? 2 : 1)}</strong></div><div><small>Middle 50%</small><strong>{formatNumber(academic.q1, academic.key === "gpa" ? 2 : 1)} – {formatNumber(academic.q3, academic.key === "gpa" ? 2 : 1)}</strong></div></div>
          <Histogram items={academic.histogram} count={academic.count} label={academic.label} />
          <p className={styles.note}>Based on {formatNumber(academic.count)} valid values; {formatNumber(academic.missing)} missing or invalid. GPA uses the unweighted 0–4 scale. AP/IB use recorded course totals.</p>
        </Panel>
        <Panel title="Test submission & data coverage" description="The share of the cohort with a usable value for each field.">
          <div className={styles.coverageLead}><strong>{formatPercent(data.testSubmitters, data.total)}</strong><span>have a valid SAT or ACT score<br /><small>{formatNumber(data.total - data.testSubmitters)} have neither reported</small></span></div>
          <BarList items={data.coverage} total={data.total} limit={6} />
          <p className={styles.note}>SAT and ACT coverage can overlap. Missing scores are excluded from averages. SAT uses a valid superscore, then a complete section total; ACT uses a valid superscore, then composite.</p>
        </Panel>
      </div>
      <p className={styles.sectionNote}>Weighted GPA average: <strong>{formatNumber(data.academics.find(m => m.key === "weighted")?.mean ?? null, 2)}</strong>. Schools may use different weighting scales. Academic values come from structured applicant records.</p>
    </section>

    <section id="representation" className={styles.section} aria-labelledby="representation-title">
      <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>THE APPLICANT POOL</span><h2 id="representation-title">Programs & representation</h2></div><span className={styles.sectionHint}>{formatNumber(data.schools)} high schools represented</span></div>
      <div className={styles.twoColumns}>
        <Panel title="Major / program interest" description="Select an entry to filter the dashboard. Combined program choices stay together as reported."><BarList items={data.programs} total={data.total} onSelect={onProgramSelect} /></Panel>
        <Panel title="Geographic representation" description="Reported school geographic context, grouped by region or country.">
          <div className={styles.metricPicker} role="group" aria-label="Geographic grouping"><button type="button" aria-pressed={geography === "regions"} onClick={() => onGeographyChange("regions")}>Region</button><button type="button" aria-pressed={geography === "countries"} onClick={() => onGeographyChange("countries")}>Country</button></div>
          <BarList key={geography} items={data[geography]} total={data.total} />
        </Panel>
        <Panel title="Gender" description="Reported categories, including unknown or unreported values."><BarList items={data.genders} total={data.total} colorful /></Panel>
        <Panel title="Ethnicity" description="Reported categories, including unknown or unreported values."><BarList items={data.ethnicities} total={data.total} colorful /></Panel>
      </div>
    </section>

    <section id="comparisons" className={styles.section} aria-labelledby="comparisons-title">
      <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>SIDE BY SIDE</span><h2 id="comparisons-title">Cohort comparisons</h2></div><label className={styles.comparisonSelect}>Compare by<select value={comparison} onChange={e => onComparisonChange(e.target.value as "cycle" | "program")}><option value="cycle">Admission year & term</option><option value="program">Major / program</option></select></label></div>
      <div className={`${styles.panel} ${styles.comparisonPanel}`}>
        <p className={styles.note}>All filters above apply. Cohorts show their current state, and may be at different stages of the admissions cycle.</p>
        {comparisonRows.length < 2 && <p className={styles.callout}>Only one cohort is available. Broaden the filters or compare by another grouping to see more cohorts.</p>}
        <div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Cohort statistics comparison">
          <table className={styles.comparisonTable}><caption>{comparison === "cycle" ? "Admission year and term" : "Major / program"} · {formatNumber(comparisonRows.length)} cohorts</caption><thead><tr><th scope="col">Cohort</th><th scope="col">Applications</th><th scope="col">Complete</th><th scope="col">Decisions</th><th scope="col">Accepted / decided</th><th scope="col">Median GPA</th><th scope="col">Median SAT</th></tr></thead><tbody>{comparisonRows.map(c => <tr key={c.label}><th scope="row">{c.label}</th><td><strong>{formatNumber(c.count)}</strong><div className={styles.miniTrack} aria-hidden="true"><span style={{ width: `${c.count / Math.max(...comparisonRows.map(r => r.count), 1) * 100}%` }} /></div></td><td>{formatPercent(c.complete, c.count)}<small>{c.complete} of {c.count}</small></td><td>{formatPercent(c.recorded, c.count)}<small>{c.recorded} of {c.count}</small></td><td>{formatPercent(c.accepted, c.recorded)}<small>{c.accepted} of {c.recorded}</small></td><td>{formatNumber(c.gpaMedian, 2)}<small>n = {c.gpaCount}</small></td><td>{formatNumber(c.satMedian)}<small>n = {c.satCount}</small></td></tr>)}</tbody></table>
        </div>
      </div>
    </section>
    <footer className={styles.dataNote}><strong>About these statistics</strong><p>Counts represent unique applicant records in the selected cohort. Decision figures use recorded human decisions. Complete packets have passed the ingestion checklist; that does not mean a human review is finished. Unknown values remain visible, and missing or invalid academic values are excluded from averages and percentiles. Percentiles use linear interpolation. Trends show application creation dates; decision counts show the latest recorded outcomes.</p></footer>
  </>;
}
