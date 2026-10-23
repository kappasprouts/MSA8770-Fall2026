"use client";

import { useState } from "react";
import { percentage, type CountItem } from "@/lib/statistics";
import styles from "./statistics.module.css";

export const COLORS = ["#7041b5", "#287867", "#a66b1e", "#9d5365", "#6c778c", "#507b9a"];
export function formatNumber(value: number | null, digits = 0): string {
  return value === null ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function formatPercent(count: number, total: number): string {
  const p = percentage(count, total);
  return p === null ? "—" : `${formatNumber(p, 1)}%`;
}

/** Values stay visible in text; interpreting a chart never depends on color or hover. */
export function BarList({ items, total, limit = 6, colorful = false, onSelect, valueLabel = "of cohort" }: {
  items: CountItem[]; total: number; limit?: number; colorful?: boolean;
  onSelect?: (label: string) => void; valueLabel?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? items : items.slice(0, limit);
  if (!items.length) return <p className={styles.emptyChart}>No data reported for this cohort.</p>;
  return <>
    <ul className={styles.barList}>
      {visible.map((item, i) => <li key={item.label}>
        <div className={styles.barHeading}>
          {onSelect ? <button className={styles.categoryButton} onClick={() => onSelect(item.label)} type="button" title={`Filter by ${item.label}`}>{item.label}<span aria-hidden="true"> ↗</span></button> : <span>{item.label}</span>}
          <span className={styles.barValue}><strong>{formatNumber(item.count)}</strong><small>{formatPercent(item.count, total)}</small><span className={styles.srOnly}> {valueLabel}</span></span>
        </div>
        <div className={styles.barTrack} aria-hidden="true"><div style={{ width: `${percentage(item.count, total) ?? 0}%`, background: colorful ? COLORS[i % COLORS.length] : undefined }} /></div>
      </li>)}
    </ul>
    {items.length > limit && <button type="button" className={styles.textButton} onClick={() => setExpanded(!expanded)}>{expanded ? "Show fewer" : `View all ${items.length} categories`}</button>}
  </>;
}

export function DecisionChart({ items, total, recorded }: { items: CountItem[]; total: number; recorded: number }) {
  let offset = 0;
  const segments = items.map((item, i) => {
    const start = offset;
    offset += percentage(item.count, total) ?? 0;
    return `${COLORS[i % COLORS.length]} ${start}% ${offset}%`;
  });
  return <div className={styles.decisionChart}>
    <div className={styles.donut} role="img" aria-label={`${formatNumber(recorded)} of ${formatNumber(total)} applications have a recorded decision. ${items.map(i => `${i.label}: ${i.count}`).join(". ")}`} style={{ background: total ? `conic-gradient(${segments.join(",")})` : "var(--color-border)" }}>
      <div><strong>{formatPercent(recorded, total)}</strong><span>decisions recorded</span></div>
    </div>
    <BarList items={items.filter(item => item.count > 0 || item.label !== "Other recorded decision")} total={total} colorful />
  </div>;
}

export function Histogram({ items, count, label }: { items: CountItem[]; count: number; label: string }) {
  const max = Math.max(1, ...items.map(i => i.count));
  if (!count) return <p className={styles.emptyChart}>No valid {label.toLowerCase()} values reported.</p>;
  return <div className={styles.histogram} role="img" aria-label={`${label} distribution. ${items.map(i => `${i.label}: ${i.count} applicants`).join(". ")}`}>
    {items.map(item => <div key={item.label} className={styles.histogramColumn}>
      <span>{formatNumber(item.count)}</span>
      <div className={styles.histogramTrack}><div style={{ height: `${item.count / max * 100}%` }} /></div>
      <small>{item.label}</small>
    </div>)}
  </div>;
}

function monthLabel(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
}
export function TrendChart({ items }: { items: CountItem[] }) {
  const [showTable, setShowTable] = useState(false);
  if (!items.length) return <p className={styles.emptyChart}>No valid source application dates are available for this cohort.</p>;
  const width = 800, height = 200, left = 42, right = 18, top = 18, bottom = 32;
  const max = Math.max(2, Math.ceil(Math.max(...items.map(item => item.count)) / 2) * 2);
  const points = items.map((item, i) => [left + (items.length === 1 ? .5 : i / (items.length - 1)) * (width - left - right), top + (1 - item.count / max) * (height - top - bottom)]);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
  const baseline = height - bottom;
  const labelIndexes = [...new Set([0, Math.floor((items.length - 1) / 2), items.length - 1])];
  return <>
    <svg className={styles.trendSvg} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Applications by source creation month, ${monthLabel(items[0].label)} to ${monthLabel(items.at(-1)!.label)}. Data table available below.`}>
      {[0, .5, 1].map(fraction => <g key={fraction}>
        <line x1={left} x2={width - right} y1={top + fraction * (baseline - top)} y2={top + fraction * (baseline - top)} stroke="var(--color-border)" strokeDasharray="4 5" />
        <text x={left - 10} y={top + fraction * (baseline - top) + 4} textAnchor="end">{formatNumber(max * (1 - fraction))}</text>
      </g>)}
      <path d={`${line} L${points.at(-1)![0]},${baseline} L${points[0][0]},${baseline} Z`} fill="#7041b5" fillOpacity=".08" />
      <path d={line} fill="none" stroke="#7041b5" strokeWidth="3" strokeLinejoin="round" />
      {points.map(([x, y], i) => <circle key={items[i].label} cx={x} cy={y} r="4" fill="#7041b5"><title>{`${monthLabel(items[i].label)}: ${items[i].count} applications`}</title></circle>)}
      {labelIndexes.map(i => <text key={i} x={points[i][0]} y={height - 5} textAnchor={i === 0 && items.length > 1 ? "start" : i === items.length - 1 && items.length > 1 ? "end" : "middle"}>{monthLabel(items[i].label)}</text>)}
    </svg>
    <button className={styles.textButton} type="button" aria-expanded={showTable} onClick={() => setShowTable(!showTable)}>{showTable ? "Hide monthly values" : "View monthly values"}</button>
    {showTable && <div className={styles.monthlyValues}><BarList items={items.map(i => ({ ...i, label: monthLabel(i.label) }))} total={items.reduce((n, i) => n + i.count, 0)} limit={12} valueLabel="of dated applications" /></div>}
  </>;
}
