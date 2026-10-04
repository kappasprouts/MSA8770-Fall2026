#!/usr/bin/env python3
"""Admissions Ingestion & Completeness Gate CLI Runner.

Executes Component 2 (Pure Ingestion Layer) and Component 3 (Deterministic Manifest Validation Gate)
as specified in Architecture Section 4:
- Ingests applicant records and documents from batch directory.
- Enforces Trust Boundary 1 perimeter hygiene (existence, format, 1KB-15MB size, b'%PDF-' magic bytes).
- Applies 3-way deterministic routing (VALID -> READY_FOR_REVIEW, INCOMPLETE, ERROR).
- Displays formatted summary tables on stdout.
- Produces an audit log report file (ingestion_batch_01_report.txt).
- Hard stop enforcement: explicitly halts execution prior to downstream summarizers/agents.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Pure Component 2 & Component 3 imports ONLY.
# Strictly NO OCR parsers, DocumentParser, ModelGateway, VLM agents, or downstream summarizers.
from ingestion.batch_ingest import BatchIngestor
from validation.manifest_gate import GateStatus, ManifestValidationGate, ManifestGateResult


def format_table_row(cols, widths, fillchar=" ", align="<"):
    """Format columns into a padded table row."""
    cells = []
    for col, width in zip(cols, widths):
        val = str(col)
        if len(val) > width:
            val = val[: width - 3] + "..."
        cells.append(f"{val:<{width}}" if align == "<" else f"{val:>{width}}")
    return " | ".join(cells)


def generate_report_text(
    input_dir: Path,
    config_path: Path,
    result: ManifestGateResult,
    execution_time: datetime,
) -> str:
    """Generate comprehensive audit report text."""
    lines = []
    sep = "=" * 80
    subsep = "-" * 80

    lines.append(sep)
    lines.append("RIVERVIEW STATE UNIVERSITY ADMISSIONS PIPELINE")
    lines.append("COMPONENT 2 (INGESTION) & COMPONENT 3 (MANIFEST VALIDATION GATE) AUDIT REPORT")
    lines.append(sep)
    lines.append(f"Execution Timestamp : {execution_time.isoformat()}")
    lines.append(f"Target Input Batch  : {input_dir.resolve()}")
    lines.append(f"Configuration File  : {config_path.resolve()}")
    lines.append(f"Trust Boundary Check: Trust Boundary 1 (Inbound Perimeter Constraints)")
    lines.append(subsep)
    lines.append("")

    # Aggregate Summary
    lines.append("BATCH PROCESSING SUMMARY")
    lines.append("------------------------")
    lines.append(f"Total Applications Processed : {result.total_processed}")
    lines.append(f"Valid Applications (Ready)   : {result.total_valid} (-> Application packet complete, ready for handoff)")
    lines.append(f"Incomplete Applications      : {result.total_incomplete} (-> Routed to 'Applicant Packet Update')")
    lines.append(f"Error / Corrupted Packets    : {result.total_error} (-> Routed to 'Human Review')")
    lines.append("")

    # Summary Breakdown Table
    lines.append("ROUTING DISPOSITION TABLE")
    lines.append("--------------------------------------------------------------------------------")
    headers = ["Applicant ID", "Status", "Routing Destination", "Documents", "Issues / Notes"]
    widths = [14, 18, 25, 10, 40]
    header_str = " | ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    lines.append(header_str)
    lines.append("-+-".join("-" * w for w in widths))

    for app in result.routed_applicants:
        notes = []
        if app.missing_documents:
            notes.append(f"Missing docs: {', '.join(app.missing_documents)}")
        if app.missing_fields:
            notes.append(f"Missing fields: {', '.join(app.missing_fields)}")
        if app.errors:
            notes.append(f"Errors: {'; '.join(app.errors)}")
        notes_str = "; ".join(notes) if notes else "All checks passed"

        row = [
            app.applicant_id,
            app.status.value,
            app.routing_destination,
            str(app.total_documents),
            notes_str,
        ]
        lines.append(format_table_row(row, widths))

    lines.append("--------------------------------------------------------------------------------")
    lines.append("")

    # Detailed Per-Applicant Audit Trails
    lines.append("DETAILED APPLICANT AUDIT TRAILS")
    lines.append("================================================================================")
    for idx, app in enumerate(result.routed_applicants, 1):
        lines.append(f"[{idx:02d}] APPLICANT: {app.applicant_id}")
        lines.append(f"     Status              : {app.status.value}")
        lines.append(f"     Routing Destination : {app.routing_destination}")
        lines.append(f"     Valid for Pipeline  : {app.is_valid}")
        lines.append(f"     Total Documents     : {app.total_documents}")
        lines.append(f"     Documents Present   : {', '.join(app.documents_present)}")

        if app.missing_documents:
            lines.append(f"     Missing Documents   : {', '.join(app.missing_documents)}")
        if app.missing_fields:
            lines.append(f"     Missing Metadata    : {', '.join(app.missing_fields)}")
        if app.errors:
            lines.append(f"     Perimeter/TB1 Errors: {', '.join(app.errors)}")
        lines.append(subsep)

    lines.append("")
    lines.append("PIPELINE HALT ENFORCEMENT")
    lines.append("================================================================================")
    lines.append("Execution hard stop enforced immediately after Manifest Gate validation.")
    lines.append("No downstream OCR parsers, LLM gateways, VLM agents, or summarizers invoked.")
    lines.append("================================================================================")
    lines.append("")
    lines.append("END OF AUDIT LOG")
    lines.append(sep)
    return "\n".join(lines)


def print_console_summary(result: ManifestGateResult, input_dir: Path, execution_time: datetime):
    """Print clean formatted summary to stdout."""
    bold = "\033[1m"
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"
    reset = "\033[0m"

    print("\n" + "=" * 80)
    print(f"{bold}RIVERVIEW ADMISSIONS: INGESTION & COMPLETENESS GATE SUMMARY{reset}")
    print("=" * 80)
    print(f"Batch Directory : {input_dir}")
    print(f"Timestamp       : {execution_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("-" * 80)

    # Summary box
    print(f"{bold}Total Processed :{reset} {result.total_processed}")
    print(f"{green}{bold}Valid           :{reset} {result.total_valid}  (Application packet complete -> READY_FOR_REVIEW)")
    print(f"{yellow}{bold}Incomplete      :{reset} {result.total_incomplete}  (Missing Documents/Fields -> Applicant Packet Update)")
    print(f"{red}{bold}Error           :{reset} {result.total_error}  (Corrupted/Magic Bytes/Size -> Human Review)")
    print("-" * 80)

    # Detail Table
    headers = ["Applicant ID", "Status", "Routing Target", "Docs", "Action Details"]
    widths = [14, 18, 25, 6, 40]
    header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    print(header_line)
    print("-+-".join("-" * w for w in widths))

    for app in result.routed_applicants:
        color = green if app.status == GateStatus.READY_FOR_REVIEW else (yellow if app.status == GateStatus.INCOMPLETE else red)
        
        detail_msg = ""
        if app.status == GateStatus.READY_FOR_REVIEW:
            detail_msg = "Complete - Ready for handoff"
        elif app.status == GateStatus.INCOMPLETE:
            missing = app.missing_documents + app.missing_fields
            detail_msg = f"Missing: {', '.join(missing)}"
        else:
            detail_msg = f"Alert: {app.errors[0]}" if app.errors else "Integrity failure"

        row = [
            app.applicant_id,
            f"{color}{app.status.value}{reset}",
            app.routing_destination,
            str(app.total_documents),
            detail_msg,
        ]
        # Pad accounting for ANSI codes
        cells = []
        for i, (val, w) in enumerate(zip(row, widths)):
            if i == 1:  # Status column with ANSI
                clean_val = app.status.value
                pad = w - len(clean_val)
                cells.append(f"{val}{' ' * max(0, pad)}")
            else:
                v = str(val)
                if len(v) > w:
                    v = v[: w - 3] + "..."
                cells.append(f"{v:<{w}}")
        print(" | ".join(cells))

    print("=" * 80 + "\n")


def run_pipeline(
    input_dir: str = "batch_01",
    config_file: Optional[str] = None,
    report_file: Optional[str] = None,
) -> ManifestGateResult:
    """Execute pure batch ingestion and manifest completeness gate with hard stop."""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Target input directory does not exist: {input_path}", file=sys.stderr)
        raise FileNotFoundError(f"Target input directory does not exist: {input_path}")

    config_path = Path(config_file) if config_file else Path("config/policies.yaml")
    execution_time = datetime.now(timezone.utc)

    # 1. Component 2: Pure Ingestion & Linking
    ingestor = BatchIngestor(config_path=config_path)
    applications = ingestor.ingest_batch(input_path)

    # 2. Component 3: Manifest Validation Gate
    gate = ManifestValidationGate(config_path=config_path)
    result = gate.evaluate_batch(applications)

    # 3. Print Summary to stdout
    print_console_summary(result, input_path, execution_time)

    # 4. Generate and save Audit Report
    out_file = Path(report_file) if report_file else Path("ingestion_batch_01_report.txt")
    report_text = generate_report_text(input_path, config_path, result, execution_time)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"Audit log successfully written to: {out_file.resolve()}\n")

    # 5. Hard Stop Enforcement Message
    print("=" * 80)
    print("[HARD STOP] Ingestion and completeness check is complete.")
    print(f"[HARD STOP] Audit report generated at: {out_file.resolve()}")
    print("[HARD STOP] Pipeline execution halted prior to the summarizing agent.")
    print("=" * 80 + "\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run Admissions Ingestion & Manifest Completeness Gate across an applicant batch."
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        default="batch_01",
        help="Path to the input batch directory containing applicant subfolders and/or CSV (default: batch_01)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config/policies.yaml",
        help="Path to institutional policies YAML configuration file (default: config/policies.yaml)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="ingestion_batch_01_report.txt",
        help="Path to output audit log report file (default: ingestion_batch_01_report.txt)",
    )

    args = parser.parse_args()
    try:
        run_pipeline(input_dir=args.input_dir, config_file=args.config, report_file=args.output)
        sys.exit(0)
    except Exception as e:
        print(f"Error during ingestion pipeline: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
