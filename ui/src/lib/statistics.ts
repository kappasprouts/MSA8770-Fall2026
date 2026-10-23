/** Deterministic aggregates. Only the aggregate payload leaves the server. */
export const UNKNOWN = "__unknown__";
export const UNKNOWN_LABEL = "Unknown / not reported";
export const EMPTY_FILTERS: StatisticsFilters = { year: "", term: "", major: "", decision: "" };
export interface StatisticsFilters { year: string; term: string; major: string; decision: string }
export interface FilterOption { value: string; label: string }
export interface CountItem { label: string; count: number }
export interface StatisticsRow {
  admission_year?: unknown; admission_term?: unknown; intended_major?: unknown;
  status?: unknown; final_decision?: unknown; gender?: unknown; ethnicity?: unknown;
  country?: unknown; region?: unknown; name_of_hs?: unknown;
  unweighted_gpa?: unknown; weighted_gpa?: unknown; superscored_sat_score?: unknown;
  sat_math?: unknown; sat_ebrw?: unknown; superscored_act_score?: unknown; act_composite?: unknown;
  total_aps?: unknown; total_ibs?: unknown; create_date_time?: unknown;
  gate?: { missing_documents?: unknown; missing_fields?: unknown; error_count?: unknown; ready_for_review?: unknown } | null;
}
export interface AcademicMetric {
  key: string; label: string; count: number; missing: number;
  mean: number | null; median: number | null; q1: number | null; q3: number | null;
  histogram: CountItem[];
}
export interface CohortSummary {
  label: string; count: number; complete: number; recorded: number; accepted: number;
  gpaMedian: number | null; gpaCount: number; satMedian: number | null; satCount: number;
}
export interface StatisticsPayload {
  generatedAt: string; filters: StatisticsFilters; totalRecords: number; total: number;
  options: Record<"years" | "terms" | "majors", FilterOption[]>;
  complete: number; recorded: number; accepted: number; withoutDecision: number; testSubmitters: number;
  decisions: CountItem[]; completeness: CountItem[]; missingDocuments: CountItem[]; missingDetailsCount: number;
  academics: AcademicMetric[]; coverage: CountItem[];
  programs: CountItem[]; genders: CountItem[]; ethnicities: CountItem[];
  countries: CountItem[]; regions: CountItem[]; schools: number;
  trend: CountItem[]; trendUndated: number;
  cohorts: Record<"cycle" | "program", CohortSummary[]>;
}

function text(value: unknown): string { return typeof value === "string" ? value.trim() : ""; }
function category(value: unknown): string { return text(value) || UNKNOWN_LABEL; }
function key(value: unknown): string { return text(value) || UNKNOWN; }
function numeric(value: unknown, min = 0, max = Infinity, integer = false): number | null {
  if (value === null || value === undefined || (typeof value !== "number" && typeof value !== "string") || String(value).trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= min && n <= max && (!integer || Number.isInteger(n)) ? n : null;
}
export function termLabel(value: string): string {
  return ({ F: "Fall", S: "Spring", U: "Summer", W: "Winter" } as Record<string, string>)[value] ?? (value === UNKNOWN ? UNKNOWN_LABEL : value);
}
function yearKey(row: StatisticsRow): string { return row.admission_year == null ? UNKNOWN : String(row.admission_year); }
function decisionKey(row: StatisticsRow): string {
  const value = text(row.final_decision).toUpperCase();
  return !value ? "UNRECORDED" : ["ACCEPT", "DECLINE", "WAITLIST"].includes(value) ? value : "OTHER";
}
const DECISIONS = [
  ["ACCEPT", "Accepted"], ["DECLINE", "Declined"], ["WAITLIST", "Waitlisted"],
  ["UNRECORDED", "No decision recorded"], ["OTHER", "Other recorded decision"],
] as const;
const PACKETS = ["Complete packets", "Awaiting documents", "Missing required fields", "Needs attention", "Not evaluated / unknown"];
function packetState(row: StatisticsRow): string {
  const status = text(row.status).toUpperCase();
  if (status === "AWAITING_MATERIALS") return PACKETS[1];
  if (status === "INCOMPLETE") return PACKETS[2];
  if (["ERROR", "STOPPED", "COUNSELOR_REVIEW", "REPLACEMENT_REQUESTED"].includes(status)) return PACKETS[3];
  const gate = row.gate;
  if (gate) {
    if ((numeric(gate.error_count) ?? 0) > 0) return PACKETS[3];
    if (Array.isArray(gate.missing_fields) && gate.missing_fields.length) return PACKETS[2];
    if (Array.isArray(gate.missing_documents) && gate.missing_documents.length) return PACKETS[1];
    if (gate.ready_for_review === true || (Array.isArray(gate.missing_fields) && Array.isArray(gate.missing_documents) && numeric(gate.error_count) === 0)) return PACKETS[0];
  }
  if (["VALID", "READY_FOR_REVIEW", "DOSSIER_READY", "AGENT_ERROR", "AI_VALIDATION_FAILED", "HUMAN_REVIEW_AI_FAILED"].includes(status)) return PACKETS[0];
  return PACKETS[4];
}
function gpa(row: StatisticsRow) { return numeric(row.unweighted_gpa, 0, 4); }
function sat(row: StatisticsRow): number | null {
  const score = numeric(row.superscored_sat_score, 400, 1600, true);
  if (score !== null) return score;
  const math = numeric(row.sat_math, 200, 800, true), reading = numeric(row.sat_ebrw, 200, 800, true);
  return math !== null && reading !== null ? math + reading : null;
}
function act(row: StatisticsRow) { return numeric(row.superscored_act_score, 1, 36, true) ?? numeric(row.act_composite, 1, 36, true); }
function quantile(sorted: number[], p: number): number | null {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * p, low = Math.floor(position), fraction = position - low;
  return sorted[low] + ((sorted[low + 1] ?? sorted[low]) - sorted[low]) * fraction;
}
function metric(rows: StatisticsRow[], name: string, label: string, get: (row: StatisticsRow) => number | null, bins: [string, number][]): AcademicMetric {
  const values = rows.map(get).filter((v): v is number => v !== null).sort((a, b) => a - b);
  return {
    key: name, label, count: values.length, missing: rows.length - values.length,
    mean: values.length ? values.reduce((sum, n) => sum + n, 0) / values.length : null,
    median: quantile(values, .5), q1: quantile(values, .25), q3: quantile(values, .75),
    histogram: bins.map(([label, upper], i) => ({ label, count: values.filter(n => n >= (i ? bins[i - 1][1] : -Infinity) && n < upper).length })),
  };
}
function group(rows: StatisticsRow[], get: (row: StatisticsRow) => string): CountItem[] {
  const counts = new Map<string, number>();
  rows.forEach(row => { const value = get(row); counts.set(value, (counts.get(value) ?? 0) + 1); });
  return [...counts].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
function options(rows: StatisticsRow[], get: (row: StatisticsRow) => string, label = (v: string) => v): FilterOption[] {
  return [...new Set(rows.map(get))].sort((a, b) => a === UNKNOWN ? 1 : b === UNKNOWN ? -1 : a.localeCompare(b, undefined, { numeric: true }))
    .map(value => ({ value, label: value === UNKNOWN ? UNKNOWN_LABEL : label(value) }));
}
export function parseStatisticsFilters(params: URLSearchParams): StatisticsFilters {
  const filters = { ...EMPTY_FILTERS };
  for (const field of Object.keys(filters) as (keyof StatisticsFilters)[]) {
    const value = params.get(field) ?? "";
    if (value.length > 150) throw new Error("A statistics filter is too long.");
    filters[field] = value.trim();
  }
  if (filters.year && filters.year !== UNKNOWN && !/^\d{4}$/.test(filters.year)) throw new Error("Choose a valid admission year.");
  if (filters.decision && !DECISIONS.some(([value]) => value === filters.decision)) throw new Error("Choose a valid decision filter.");
  return filters;
}
function matches(row: StatisticsRow, filters: StatisticsFilters) {
  return (!filters.year || yearKey(row) === filters.year) && (!filters.term || key(row.admission_term) === filters.term)
    && (!filters.major || key(row.intended_major) === filters.major) && (!filters.decision || decisionKey(row) === filters.decision);
}
function cohorts(rows: StatisticsRow[], get: (row: StatisticsRow) => string): CohortSummary[] {
  const groups = new Map<string, StatisticsRow[]>();
  rows.forEach(row => { const label = get(row); const values = groups.get(label) ?? []; values.push(row); groups.set(label, values); });
  return [...groups].map(([label, values]) => {
    const gpas = values.map(gpa).filter((n): n is number => n !== null).sort((a, b) => a - b);
    const sats = values.map(sat).filter((n): n is number => n !== null).sort((a, b) => a - b);
    return { label, count: values.length, complete: values.filter(row => packetState(row) === PACKETS[0]).length,
      recorded: values.filter(row => decisionKey(row) !== "UNRECORDED").length,
      accepted: values.filter(row => decisionKey(row) === "ACCEPT").length,
      gpaMedian: quantile(gpas, .5), gpaCount: gpas.length, satMedian: quantile(sats, .5), satCount: sats.length };
  }).sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
}
/** Source application-created month, never database ingestion time. Reject ambiguous dates. */
function sourceMonth(value: unknown): string | null {
  const s = text(value), match = /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(s);
  if (!match || !Number.isFinite(Date.parse(s))) return null;
  const day = Number(match[3]), month = Number(match[2]), year = Number(match[1]);
  if (year < 1900 || year > 2200 || month < 1 || month > 12 || day < 1 || day > new Date(Date.UTC(year, month, 0)).getUTCDate()) return null;
  return `${match[1]}-${match[2]}`;
}
export function buildStatistics(allRows: StatisticsRow[], filters: StatisticsFilters = EMPTY_FILTERS, now = new Date()): StatisticsPayload {
  const rows = allRows.filter(row => matches(row, filters)), total = rows.length;
  const academics = [
    metric(rows, "gpa", "Unweighted GPA", gpa, [["< 2.0", 2], ["2.0–2.49", 2.5], ["2.5–2.99", 3], ["3.0–3.49", 3.5], ["3.5–4.0", Infinity]]),
    metric(rows, "sat", "SAT", sat, [["400–799", 800], ["800–999", 1000], ["1000–1199", 1200], ["1200–1399", 1400], ["1400–1600", Infinity]]),
    metric(rows, "act", "ACT", act, [["1–15", 16], ["16–20", 21], ["21–25", 26], ["26–30", 31], ["31–36", Infinity]]),
    metric(rows, "ap", "AP courses", r => numeric(r.total_aps, 0, Infinity, true), [["0", 1], ["1–3", 4], ["4–6", 7], ["7–9", 10], ["10+", Infinity]]),
    metric(rows, "ib", "IB courses", r => numeric(r.total_ibs, 0, Infinity, true), [["0", 1], ["1–3", 4], ["4–6", 7], ["7–9", 10], ["10+", Infinity]]),
    metric(rows, "weighted", "Weighted GPA", r => numeric(r.weighted_gpa), []),
  ];
  const completeness = PACKETS.map(label => ({ label, count: rows.filter(row => packetState(row) === label).length }));
  const decisions = DECISIONS.map(([value, label]) => ({ label, count: rows.filter(row => decisionKey(row) === value).length }));
  const missingDocuments = new Map<string, number>();
  let missingDetailsCount = 0;
  for (const row of rows) {
    if (packetState(row) === PACKETS[0] || !Array.isArray(row.gate?.missing_documents)) continue;
    missingDetailsCount++;
    const documents = new Set(row.gate.missing_documents.filter((v): v is string => typeof v === "string" && !!v.trim()));
    documents.forEach(doc => {
      const label = doc.trim().replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
      missingDocuments.set(label, (missingDocuments.get(label) ?? 0) + 1);
    });
  }
  const months = new Map<string, number>();
  let trendUndated = 0;
  rows.forEach(row => { const month = sourceMonth(row.create_date_time); if (month) months.set(month, (months.get(month) ?? 0) + 1); else trendUndated++; });
  const datedMonths = [...months.keys()].sort();
  // Include empty months between observations so the chart never bridges a gap silently.
  if (datedMonths.length) {
    const cursor = new Date(`${datedMonths[0]}-01T00:00:00Z`), end = new Date(`${datedMonths.at(-1)}-01T00:00:00Z`);
    while (cursor <= end) {
      const month = cursor.toISOString().slice(0, 7);
      if (!months.has(month)) months.set(month, 0);
      cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    }
  }
  return {
    generatedAt: now.toISOString(), filters: { ...filters }, totalRecords: allRows.length, total,
    options: { years: options(allRows, yearKey).reverse(), terms: options(allRows, r => key(r.admission_term), termLabel), majors: options(allRows, r => key(r.intended_major)) },
    complete: completeness[0].count, recorded: total - decisions[3].count, accepted: decisions[0].count,
    withoutDecision: decisions[3].count, testSubmitters: rows.filter(r => sat(r) !== null || act(r) !== null).length,
    decisions, completeness, missingDocuments: [...missingDocuments].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)), missingDetailsCount,
    academics, coverage: [...academics.map(m => ({ label: m.label, count: m.count })),
      { label: "Gender", count: rows.filter(r => !!text(r.gender)).length }, { label: "Ethnicity", count: rows.filter(r => !!text(r.ethnicity)).length },
      { label: "Country", count: rows.filter(r => !!text(r.country)).length }, { label: "Region", count: rows.filter(r => !!text(r.region)).length }],
    programs: group(rows, r => category(r.intended_major)), genders: group(rows, r => category(r.gender)), ethnicities: group(rows, r => category(r.ethnicity)),
    countries: group(rows, r => category(r.country)), regions: group(rows, r => category(r.region)), schools: new Set(rows.map(r => text(r.name_of_hs)).filter(Boolean)).size,
    trend: [...months].sort(([a], [b]) => a.localeCompare(b)).map(([label, count]) => ({ label, count })), trendUndated,
    cohorts: { cycle: cohorts(rows, r => `${yearKey(r) === UNKNOWN ? "Unknown year" : yearKey(r)} · ${termLabel(key(r.admission_term))}`), program: cohorts(rows, r => category(r.intended_major)) },
  };
}

export function percentage(value: number, total: number): number | null { return total ? value / total * 100 : null; }
function csvCell(value: unknown): string {
  let s = value == null ? "" : String(value);
  // Prevent spreadsheet formula evaluation in category labels from source records.
  if (/^\s*[=+@\-]/.test(s) || /^[\t\r]/.test(s)) s = `'${s}`;
  return `"${s.replaceAll('"', '""')}"`;
}
export function statisticsCsv(data: StatisticsPayload): string {
  const rows: unknown[][] = [
    ["Summary statistics", "Generated at", data.generatedAt],
    ["Filters", "Admission year", data.filters.year || "All"], ["Filters", "Term", data.filters.term || "All"],
    ["Filters", "Program", data.filters.major || "All"], ["Filters", "Decision", data.filters.decision || "All"],
    ["Section", "Metric / category", "Count / value", "Denominator"],
    ["Overview", "Applications", data.total], ["Overview", "Complete packets", data.complete, data.total],
    ["Overview", "Decisions recorded", data.recorded, data.total], ["Overview", "SAT or ACT reported", data.testSubmitters, data.total],
  ];
  for (const [section, items] of Object.entries({ Decisions: data.decisions, Completeness: data.completeness, Programs: data.programs, Gender: data.genders, Ethnicity: data.ethnicities, Countries: data.countries, Regions: data.regions, Coverage: data.coverage, "Missing documents": data.missingDocuments, "Source application creation month": data.trend })) {
    items.forEach(item => rows.push([section, item.label, item.count, data.total]));
  }
  for (const m of data.academics) {
    for (const [label, value] of [["Average", m.mean], ["Median", m.median], ["25th percentile", m.q1], ["75th percentile", m.q3]] as const) rows.push(["Academics", `${m.label}: ${label}`, value, m.count]);
    m.histogram.forEach(bin => rows.push(["Distribution", `${m.label}: ${bin.label}`, bin.count, m.count]));
  }
  for (const [group, cohorts] of Object.entries(data.cohorts)) {
    rows.push(["Cohort grouping", group, "Applications", "Complete packets", "Decisions recorded", "Accepted", "Median GPA", "GPA n", "Median SAT", "SAT n"]);
    cohorts.forEach(c => rows.push(["Cohort", c.label, c.count, c.complete, c.recorded, c.accepted, c.gpaMedian, c.gpaCount, c.satMedian, c.satCount]));
  }
  return "\uFEFF" + rows.map(row => row.map(csvCell).join(",")).join("\r\n");
}
