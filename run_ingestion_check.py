#!/usr/bin/env python3
"""Admissions Ingestion & Completeness Gate CLI Runner.

Executes Component 2 (Two-Pass Ingestion Layer) and Component 3 (Deterministic Manifest Validation Gate)
as specified in Architecture Section 4:
- Pass 1: Parse CSV applicant records, map explicit 33-column schema, and stage in PostgreSQL (or dry run).
- Pass 2: Traverse documents, link to applicants, upload raw PDFs to MinIO ('admissions-raw-docs'),
          attach metadata to documents JSONB, and archive orphan documents in OrphanDocument table.
- Manifest Gate: Distinguishes missing documents (AWAITING_MATERIALS) from missing fields (INCOMPLETE).
- Updates PostgreSQL applicant statuses.
- Generates affected_ids.json containing all applicant IDs marked READY_FOR_REVIEW.
- Hard stop enforcement: explicitly halts execution prior to downstream summarizers/agents.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Optional, Set
import uuid

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingestion.batch_ingest import BatchIngestor, BatchIngestionResult
from storage.storage_manager import StorageManager
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
    orphans_count: int,
    execution_time: datetime,
    affected_ids_file: Path,
    run_id: str,
    database_mode: str,
    object_storage_mode: str,
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
    lines.append(f"Run ID              : {run_id}")
    lines.append(f"Target Input Batch  : {input_dir.resolve()}")
    lines.append(f"Configuration File  : {config_path.resolve()}")
    lines.append(f"Trust Boundary Check: Trust Boundary 1 (Inbound Perimeter Constraints)")
    lines.append(f"Storage Persistence : {database_mode} applicant records; {object_storage_mode} raw documents")
    lines.append(subsep)
    lines.append("")

    # Aggregate Summary
    lines.append("BATCH PROCESSING SUMMARY")
    lines.append("------------------------")
    lines.append(f"Total Applications Processed : {result.total_processed}")
    lines.append(f"Valid Applications (Ready)   : {result.total_valid} (-> Application packet complete, ready for handoff)")
    lines.append(f"Awaiting Materials           : {result.total_awaiting_materials} (-> Missing required documents)")
    lines.append(f"Incomplete Applications      : {result.total_incomplete} (-> Missing required metadata fields)")
    lines.append(f"Error / Corrupted Packets    : {result.total_error} (-> Routed to 'Human Review')")
    lines.append(f"Orphan Documents Recorded    : {orphans_count} (-> Stored in OrphanDocument table & MinIO orphans/)")
    lines.append(f"Affected IDs (Ready)         : {', '.join(result.affected_ids) if result.affected_ids else 'None'}")
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
    lines.append("PIPELINE HALT ENFORCEMENT & HANDOFF")
    lines.append("================================================================================")
    lines.append(f"Affected IDs for Summarizing Agent: {result.affected_ids}")
    lines.append(f"Saved to: {affected_ids_file.resolve()}")
    lines.append("Execution hard stop enforced immediately after Manifest Gate validation.")
    lines.append("No downstream OCR parsers, LLM gateways, VLM agents, or summarizers invoked.")
    lines.append("================================================================================")
    lines.append("")
    lines.append("END OF AUDIT LOG")
    lines.append(sep)
    return "\n".join(lines)


def print_console_summary(
    result: ManifestGateResult,
    orphans_count: int,
    input_dir: Path,
    execution_time: datetime,
    affected_ids_file: Path,
):
    """Print clean formatted summary to stdout."""
    bold = "\033[1m"
    green = "\033[32m"
    yellow = "\033[33m"
    red = "\033[31m"
    cyan = "\033[36m"
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
    print(f"{yellow}{bold}Awaiting Materials:{reset} {result.total_awaiting_materials}  (Missing required documents -> Applicant Packet Update)")
    print(f"{yellow}{bold}Incomplete      :{reset} {result.total_incomplete}  (Missing required fields -> Applicant Packet Update)")
    print(f"{red}{bold}Error           :{reset} {result.total_error}  (Corrupted/Magic Bytes/Size -> Human Review)")
    if orphans_count > 0:
        print(f"{cyan}{bold}Orphans Recorded:{reset} {orphans_count}  (OrphanDocument table & MinIO 'orphans/')")
    print("-" * 80)

    # Detail Table
    headers = ["Applicant ID", "Status", "Routing Target", "Docs", "Action Details"]
    widths = [14, 18, 25, 6, 40]
    header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    print(header_line)
    print("-+-".join("-" * w for w in widths))

    for app in result.routed_applicants:
        color = green if app.status == GateStatus.READY_FOR_REVIEW else (yellow if app.status in (GateStatus.AWAITING_MATERIALS, GateStatus.INCOMPLETE) else red)
        
        detail_msg = ""
        if app.status == GateStatus.READY_FOR_REVIEW:
            detail_msg = "Complete - Ready for handoff"
        elif app.status in (GateStatus.AWAITING_MATERIALS, GateStatus.INCOMPLETE):
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

    print("-" * 80)
    print(f"{bold}Affected IDs (READY_FOR_REVIEW):{reset} {cyan}{result.affected_ids}{reset}")
    print(f"{bold}Exported Affected IDs File     :{reset} {affected_ids_file.resolve()}")
    print("=" * 80 + "\n")


def run_pipeline(
    input_dir: str = "batch_01",
    config_file: Optional[str] = None,
    report_file: Optional[str] = None,
    affected_ids_file: Optional[str] = None,
    storage_manager: Optional[StorageManager] = None,
    applicant_ids: Optional[Set[str]] = None,
    require_object_storage: bool = False,
    require_postgresql: bool = False,
    run_id: Optional[str] = None,
) -> ManifestGateResult:
    """Execute two-pass batch ingestion, manifest completeness gate, and hard stop."""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Target input directory does not exist: {input_path}", file=sys.stderr)
        raise FileNotFoundError(f"Target input directory does not exist: {input_path}")

    config_path = Path(config_file) if config_file else Path("config/policies.yaml")
    execution_time = datetime.now(timezone.utc)
    run_id = run_id or execution_time.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
    out_affected = Path(affected_ids_file) if affected_ids_file else Path(f"affected_ids_{run_id}.json")
    out_file = Path(report_file) if report_file else Path("ingestion_batch_01_report.txt")
    if out_affected.resolve() == out_file.resolve():
        raise ValueError("The audit report and affected-ID file must use different paths")
    storage = storage_manager or StorageManager()
    if require_postgresql and (not storage.db_available or storage.is_sqlite_fallback):
        raise RuntimeError("PostgreSQL is unavailable; refusing to export a summary-agent handoff")
    if require_object_storage and not storage.minio_available:
        raise RuntimeError("MinIO is unavailable; refusing to export a summary-agent handoff")

    # 1. Component 2: Two-Pass Batch Ingestion & Linking
    ingestor = BatchIngestor(config_path=config_path, storage_manager=storage)
    ingest_result = ingestor.ingest_batch(input_path, applicant_ids=applicant_ids, audit_run_id=run_id)

    # 2. Component 3: Manifest Validation Gate
    gate = ManifestValidationGate(config_path=config_path)
    result = gate.evaluate_batch(ingest_result.applications)

    if require_object_storage:
        by_id = {app.applicant_id: app for app in ingest_result.applications}
        for routed in result.routed_applicants:
            if not routed.is_valid:
                continue
            for document in by_id[routed.applicant_id].documents:
                if storage.object_exists(document.minio_key, document.minio_bucket):
                    continue
                if not storage.update_applicant_status(
                    app_id=routed.applicant_id,
                    status=GateStatus.ERROR.value,
                    audit_action="OBJECT_STORAGE_UNAVAILABLE",
                    audit_details={"document_type": document.doc_type},
                ):
                    raise RuntimeError(f"Could not persist storage error for {routed.applicant_id}")
                raise RuntimeError(
                    f"Document object is unavailable for {routed.applicant_id}: "
                    f"s3://{document.minio_bucket}/{document.minio_key}"
                )

    # 3. Confirm the final gate status. Pass 2 has already persisted each
    # applicant's status, documents, and audit row in one transaction.
    for routed in result.routed_applicants:
        if not storage.update_applicant_status(
            app_id=routed.applicant_id,
            status=routed.status.value,
        ):
            raise RuntimeError(f"Could not persist manifest status for {routed.applicant_id}")

    # Prepare the report and handoff paths. Publish the ID file only after the
    # report is complete, because a watcher may treat the ID file as a trigger.
    # 4. Save the audit report atomically.
    report_text = generate_report_text(
        input_dir=input_path,
        config_path=config_path,
        result=result,
        orphans_count=len(ingest_result.orphans),
        execution_time=execution_time,
        affected_ids_file=out_affected,
        run_id=run_id,
        database_mode=(
            "PostgreSQL"
            if storage.db_available and not storage.is_sqlite_fallback
            else "SQLite" if storage.db_available else "In-memory"
        ),
        object_storage_mode="MinIO" if storage.minio_available else "Simulated",
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = out_file.with_name(f".{out_file.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_report.write_text(report_text, encoding="utf-8")
        os.replace(temporary_report, out_file)
    finally:
        temporary_report.unlink(missing_ok=True)

    # 5. Publish the ready IDs last for the downstream summarizing agent.
    out_affected.parent.mkdir(parents=True, exist_ok=True)
    temporary_affected = out_affected.with_name(f".{out_affected.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary_affected, "w", encoding="utf-8") as f:
            json.dump(result.affected_ids, f, indent=2)
        os.replace(temporary_affected, out_affected)
    finally:
        temporary_affected.unlink(missing_ok=True)

    # 6. Print the completed run summary.
    print_console_summary(
        result=result,
        orphans_count=len(ingest_result.orphans),
        input_dir=input_path,
        execution_time=execution_time,
        affected_ids_file=out_affected,
    )
    print(f"Audit log successfully written to: {out_file.resolve()}\n")

    # 7. Hard Stop Enforcement Message
    print("=" * 80)
    print("[HARD STOP] Ingestion and completeness check is complete.")
    print(f"[HARD STOP] Audit report generated at: {out_file.resolve()}")
    print(f"[HARD STOP] Affected IDs ({len(result.affected_ids)}) exported to: {out_affected.resolve()}")
    print("[HARD STOP] Pipeline execution halted prior to the summarizing agent.")
    print("=" * 80 + "\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run Admissions Two-Pass Ingestion & Manifest Completeness Gate across an applicant batch."
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
    parser.add_argument(
        "--affected-ids",
        "-a",
        default=None,
        help="Exact output path for this run (default: unique affected_ids_<timestamp>_<id>.json)",
    )
    parser.add_argument(
        "--require-object-storage",
        action="store_true",
        help="Fail instead of exporting a handoff when MinIO is unavailable.",
    )
    parser.add_argument(
        "--require-postgresql",
        action="store_true",
        help="Fail instead of exporting a handoff when PostgreSQL falls back to SQLite.",
    )

    args = parser.parse_args()
    try:
        run_pipeline(
            input_dir=args.input_dir,
            config_file=args.config,
            report_file=args.output,
            affected_ids_file=args.affected_ids,
            require_object_storage=args.require_object_storage,
            require_postgresql=args.require_postgresql,
        )
        sys.exit(0)
    except Exception as e:
        print(f"Error during ingestion pipeline: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
