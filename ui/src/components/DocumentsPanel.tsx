"use client";

import { useEffect, useRef, useState } from "react";
import type { OriginalDocument } from "@/lib/types";
import type { DocumentSelection } from "@/lib/review-workspace";
import styles from "./eaos.module.css";

export default function DocumentsPanel({ appId, documents, selection, onSelect }: { appId: string; documents: OriginalDocument[]; selection: DocumentSelection | null; onSelect: (value: DocumentSelection) => void }) {
  const viewer = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [expandError, setExpandError] = useState("");
  useEffect(() => {
    const update = () => setExpanded(document.fullscreenElement === viewer.current);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);
  const active = documents.find(item => item.file === selection?.file) ?? documents[0];
  if (!active) return <div className={styles.card}><h2>Original documents</h2><p className={styles.help} role="status">No source documents are listed for this applicant.</p></div>;
  const page = selection?.file === active.file ? selection.page : 1;
  const url = active.sourceUrl || `/api/documents?appId=${encodeURIComponent(appId)}&file=${encodeURIComponent(active.file)}`;
  async function toggleExpanded() {
    setExpandError("");
    try {
      if (document.fullscreenElement === viewer.current) await document.exitFullscreen();
      else await viewer.current?.requestFullscreen();
    } catch { setExpandError("Full-screen view is unavailable here. Use Open PDF to view the document in a new tab."); }
  }
  return <div ref={viewer} className={styles.documentViewer}>
    <div className={styles.documentToolbar}>
      <label className={styles.selectorLabel} htmlFor="review-document">Original document<select id="review-document" className={styles.select} value={active.file} onChange={event => onSelect({ file: event.target.value, page: 1 })}>{documents.map(item => <option key={item.file} value={item.file}>{item.label}</option>)}</select></label>
      <div className={styles.documentActions}><a className={styles.secondaryButton} href={`${url}#page=${page}`} target="_blank" rel="noreferrer" aria-label={`Open ${active.label} PDF in a new tab`}>Open PDF ↗</a><button type="button" className={styles.secondaryButton} onClick={toggleExpanded}>{expanded ? "Exit full screen" : "Expand viewer"}</button></div>
    </div>
    <p className={styles.help}>{documents.length} document(s) available · Opened at page {page}. Use the PDF toolbar to zoom or change pages.</p>
    {active.access === "withheld" && <div className={styles.notice}>Reserved for human review. {active.reason || "This document was withheld from AI."}</div>}
    {expandError && <p className={styles.help} role="status">{expandError}</p>}
    <iframe className={styles.documentFrame} title={`${active.label} PDF`} src={`${url}#page=${page}&zoom=page-width&toolbar=1&navpanes=0`} />
  </div>;
}
