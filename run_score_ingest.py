#!/usr/bin/env python3
"""Standalone CLI Runner for College Board and ACT Test Score Delta Ingestion.

Ingests external test scores (SAT/AP and ACT) from CSV feeds, links scores to
existing ApplicationRecords, archives orphans to OrphanTestScore, re-triggers
the Manifest Validation Gate, and writes a separate affected-ID handoff per run.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingestion.test_score_ingest import ScoreIngestResult, TestScoreIngestor
from storage.storage_manager import StorageManager


def print_score_summary(result: ScoreIngestResult):
    """Print clean ANSI-formatted console summary of score delta ingestion."""
    has_tty = sys.stdout.isatty()
    bold = "\033[1m" if has_tty else ""
    cyan = "\033[96m" if has_tty else ""
    green = "\033[92m" if has_tty else ""
    yellow = "\033[93m" if has_tty else ""
    magenta = "\033[95m" if has_tty else ""
    reset = "\033[0m" if has_tty else ""

    sep = "=" * 80
    subsep = "-" * 80

    print(f"\n{bold}{cyan}{sep}{reset}")
    print(f"{bold}RIVERVIEW ADMISSIONS: DELTA TEST SCORE INGESTION SUMMARY{reset}")
    print(f"{bold}{cyan}{sep}{reset}")
    print(f"Source               : {bold}{result.source}{reset}")
    print(f"Input File           : {result.file_path}")
    print(f"Executed At          : {result.executed_at}")
    print(subsep)
    print(f"Total Records Read   : {bold}{result.total_records}{reset}")
    print(f"Matched Applications : {green}{bold}{result.matched_count}{reset} (Linked to applicant records)")
    print(f"Orphan Records       : {yellow}{bold}{result.orphan_count}{reset} (Archived to OrphanTestScore)")
    print(f"Promoted to READY    : {magenta}{bold}{len(result.promoted_app_ids)}{reset} (Previously incomplete or awaiting materials)")
    print(subsep)

    if result.matched_app_ids:
        print(f"{bold}Matched Applicant IDs :{reset} {', '.join(result.matched_app_ids)}")
    else:
        print(f"{bold}Matched Applicant IDs :{reset} None")

    if result.orphan_identifiers:
        print(f"{bold}Orphan Identifiers    :{reset} {', '.join(result.orphan_identifiers)}")
    else:
        print(f"{bold}Orphan Identifiers    :{reset} None")

    if result.promoted_app_ids:
        print(f"{bold}{green}Newly Promoted Applicants :{reset} {bold}{result.promoted_app_ids}{reset}")
    else:
        print(f"{bold}Newly Promoted Applicants :{reset} None")

    print(f"{bold}Ready IDs Changed         :{reset} {result.affected_ids}")
    print(f"{bold}Affected IDs File         :{reset} {result.affected_ids_file}")
    print(f"{bold}Production Handoff Ready  :{reset} {result.handoff_ready}")
    print(f"{bold}{cyan}{sep}{reset}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest College Board or ACT test scores as delta feeds and re-evaluate manifest gates."
    )
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        choices=["college_board", "act", "COLLEGE_BOARD", "ACT"],
        help="Test score feed source: 'college_board' or 'act'",
    )
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to the input CSV file containing score records",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config/policies.yaml",
        help="Path to policies YAML configuration (default: config/policies.yaml)",
    )
    parser.add_argument(
        "--affected-ids",
        "-a",
        default="affected_ids.json",
        help="Base path for a uniquely named per-run handoff (default: affected_ids.json)",
    )
    parser.add_argument(
        "--require-object-storage",
        action="store_true",
        help="Require live MinIO and verify linked objects before a ready-ID handoff.",
    )
    parser.add_argument(
        "--require-postgresql",
        action="store_true",
        help="Require shared PostgreSQL rather than local SQLite fallback.",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: Input file does not exist: {file_path}", file=sys.stderr)
        sys.exit(1)

    config_path = Path(args.config)
    affected_ids_path = Path(args.affected_ids)

    storage = StorageManager()
    ingestor = TestScoreIngestor(
        storage_manager=storage,
        config_path=config_path,
        affected_ids_path=affected_ids_path,
        require_object_storage=args.require_object_storage,
        require_postgresql=args.require_postgresql,
    )

    source_norm = args.source.upper()
    try:
        if source_norm == "COLLEGE_BOARD":
            result = ingestor.ingest_college_board(file_path)
        elif source_norm == "ACT":
            result = ingestor.ingest_act(file_path)
        else:
            print(f"Error: Unsupported source: {args.source}", file=sys.stderr)
            sys.exit(1)

        print_score_summary(result)
        sys.exit(0)

    except Exception as e:
        print(f"Error executing delta score ingestion: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
