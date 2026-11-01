"""Durable review helpers and CLI; publication rules live in PostgreSQL."""

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from psycopg2.extras import Json, RealDictCursor

MIGRATION = Path(__file__).resolve().parents[1] / "storage/migrations/20261031_durable_dossier_review.sql"
EXCEPTION_MIGRATION = MIGRATION.with_name("20261101_integrated_exception_review.sql")


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")


def ensure_review_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='dossier_review_requests' AND relnamespace=current_schema()::regnamespace)")
        missing = not cursor.fetchone()[0]
    connection.commit()
    if missing:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname='route_dossier_candidate' AND pronamespace=current_schema()::regnamespace)")
        routing_missing = not cursor.fetchone()[0]
    connection.commit()
    if routing_missing:
        with connection.cursor() as cursor:
            cursor.execute(EXCEPTION_MIGRATION.read_text(encoding="utf-8"))


def capture_input_snapshot(connection, applicant):
    with connection.cursor() as cursor:
        cursor.execute("SELECT checkpoint_input_snapshot(%s), checkpoint_applicant_snapshot(%s::jsonb)",
            (applicant["app_id"], Json(applicant, dumps=lambda value: json.dumps(value, default=json_default))))
        snapshot, loaded_applicant = cursor.fetchone()
    if snapshot["applicant"] != loaded_applicant:
        raise RuntimeError("Applicant changed while loading; reload before generation")
    return snapshot


def pipeline_version(settings):
    root = Path(__file__).resolve().parents[1]
    files = ["ai_agent/summarizing_agent.py", "ai_agent/academic_inputs.py", "ai_agent/output_validation.py",
             "ai_agent/privacy.py", "ai_agent/review_checkpoint.py", "ai_agent/generation_recovery.py",
             "storage/migrations/20261101_durable_batch_generation.sql", "storage/migrations/20261101_integrated_exception_review.sql",
             "policy/ingestion_rules.yaml", "policy/riverview_admissions_policy.txt"]
    payload = {"settings": settings, "sources": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def existing_review(connection, app_id, snapshot, version):
    with connection.cursor() as cursor:
        cursor.execute("SELECT reconcile_dossier_reviews(%s)", (app_id,))
        cursor.execute("SELECT state FROM dossier_review_requests WHERE app_id=%s AND input_snapshot=%s::jsonb AND pipeline_version=%s ORDER BY requested_at DESC LIMIT 1",
            (app_id, Json(snapshot), version))
        row = cursor.fetchone()
        if row and row[0] != "SUPERSEDED":
            status = "DOSSIER_READY" if row[0] == "PUBLISHED" else "REVIEW_PENDING" if row[0] == "REVIEW_PENDING" else "REVIEW_" + row[0]
            cursor.execute("UPDATE applicants SET status=CASE WHEN final_decision IS NOT NULL THEN 'FINAL_DECISION_RECORDED' WHEN officer_recommendation IS NOT NULL THEN 'REVIEWED' ELSE %s END WHERE app_id=%s", (status, app_id))
    connection.commit()
    if not row:
        return None
    return {"PUBLISHED": "DOSSIER_READY", "REJECTED": "REVIEW_REJECTED", "ESCALATED": "REVIEW_ESCALATED", "SUPERSEDED": None}.get(row[0], row[0])


def stage_candidate(connection, app_id, dossier, run, snapshot, version, save_run, execution=None):
    try:
        run_id = save_run(connection, run, commit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT route_dossier_candidate(%s,%s,%s::jsonb,%s::jsonb,%s,%s)",
                (app_id, run_id, Json(dossier), Json(snapshot), version, datetime.now(timezone.utc) + timedelta(hours=24)))
            review = cursor.fetchone()[0]
        if execution:
            outcome = {"PUBLISHED": "DOSSIER_READY", "REVIEW_PENDING": "REVIEW_PENDING"}.get(review["state"], "REVIEW_" + review["state"])
            execution.finish_in_transaction(outcome, run_id, review["id"])
        connection.commit()
        return review
    except Exception:
        connection.rollback()
        raise


def main():
    from . import summarizing_agent as agent
    parser = argparse.ArgumentParser(description="Saved dossier publication review; reviewer identity is simulated")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    commands.add_parser("list")
    commands.add_parser("reconcile")
    show = commands.add_parser("show"); show.add_argument("request_id")
    decide = commands.add_parser("decide")
    decide.add_argument("request_id"); decide.add_argument("--hash", required=True)
    decide.add_argument("--decision", choices=["APPROVE", "REJECT"], required=True)
    decide.add_argument("--reviewer", required=True); decide.add_argument("--reason", required=True)
    decide.add_argument("--confirm", action="store_true"); decide.add_argument("--evidence-reviewed", action="store_true")
    args = parser.parse_args()
    connection = agent.connect_postgres()
    try:
        if args.command == "schema":
            agent.ensure_output_tables(connection)
            print("Review schema ready")
            return 0
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            if args.command == "decide":
                cursor.execute("SELECT decide_dossier_review(%s,%s,%s,%s,%s,%s,%s,%s) AS result",
                    (args.request_id,args.hash,"PUBLISH_ADVISORY_DOSSIER",args.decision,args.reviewer,args.reason,args.confirm,args.evidence_reviewed))
                result = cursor.fetchone()["result"]
            else:
                cursor.execute("SELECT reconcile_dossier_reviews() AS changed")
                result = dict(cursor.fetchone())
                if args.command == "show":
                    cursor.execute("SELECT * FROM dossier_review_requests WHERE id=%s", (args.request_id,))
                    result = dict(cursor.fetchone() or {})
                elif args.command == "list":
                    cursor.execute("SELECT id,app_id,state,candidate_hash,expires_at,review_owner,escalation_owner FROM dossier_review_requests ORDER BY requested_at DESC")
                    result = [dict(row) for row in cursor.fetchall()]
        connection.commit()
        print(json.dumps(result, indent=2, default=json_default))
        return 1 if isinstance(result, dict) and result.get("error") else 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
