
"""Event consumer: file-based handoff with durable checkpoints."""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "output" / "ingestion" / "event_state.json"
AGENT = ROOT / "ai_agent" / "summarizing_agent.py"

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "ai_agent" / ".env")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def connect_db():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "riverview_admissions"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        connect_timeout=10,
    )


def load_state():
    if not STATE_FILE.exists():
        return {}
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid checkpoint format")
    return data


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_name(
        f".{STATE_FILE.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def database_state(app_id):
    with connect_db() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.status, a.final_decision,
                       EXISTS (
                           SELECT 1 FROM applicant_dossier d
                           WHERE d.app_id = a.app_id
                       )
                FROM applicants a
                WHERE a.app_id = %s
                """,
                (app_id,),
            )
            return cursor.fetchone()


def update_checkpoint(state, key, status, error=None):
    record = state[key]
    record["status"] = status
    record["updated_at"] = timestamp()
    record["error"] = error
    save_state(state)


def process_one(state, key, app_id):
    row = database_state(app_id)

    if row is None:
        update_checkpoint(state, key, "ESCALATED", "Applicant not found")
        return

    status, final_decision, dossier_exists = row

    # Database is authoritative after a lost checkpoint acknowledgment.
    if status == "DOSSIER_READY" and dossier_exists:
        update_checkpoint(state, key, "COMPLETED")
        return

    if final_decision is not None:
        update_checkpoint(
            state, key, "ESCALATED",
            "Final decision exists but dossier state is inconsistent"
        )
        return

    if status in ("INCOMPLETE", "AWAITING_MATERIALS"):
        update_checkpoint(state, key, "WAITING_FOR_MATERIALS")
        return

    if status != "READY_FOR_REVIEW":
        update_checkpoint(
            state, key, "ESCALATED",
            f"Unexpected applicant status: {status}"
        )
        return

    # A saved dossier with an unfinished status requires reconciliation,
    # not automatic regeneration.
    if dossier_exists:
        update_checkpoint(
            state, key, "ESCALATED",
            "Dossier exists but applicant status is not DOSSIER_READY"
        )
        return

    record = state[key]
    record["attempts"] += 1
    update_checkpoint(state, key, "PROCESSING")

    try:
        result = subprocess.run(
            [sys.executable, str(AGENT), app_id],
            cwd=str(ROOT),
            check=False,
        )

        # The agent can exit 0 despite an individual validation failure.
        row = database_state(app_id)
        if row and row[0] == "DOSSIER_READY" and row[2]:
            update_checkpoint(state, key, "COMPLETED")
        elif result.returncode != 0:
            update_checkpoint(
                state, key, "RETRY_PENDING",
                f"Agent exited with code {result.returncode}"
            )
        else:
            update_checkpoint(
                state, key, "ESCALATED",
                "Agent did not produce a completed dossier; inspect audit logs"
            )

    except Exception as error:
        update_checkpoint(state, key, "RETRY_PENDING", str(error))


def process_event(event_file):
    event_file = Path(event_file).resolve()
    if not event_file.is_file():
        raise FileNotFoundError(event_file)

    if not (
        event_file.name.startswith("affected_ids_")
        and event_file.suffix == ".json"
    ):
        raise ValueError("Expected an affected_ids_<runid>.json file")

    ids = json.loads(event_file.read_text(encoding="utf-8"))
    if not isinstance(ids, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in ids
    ):
        raise ValueError("Event must contain a JSON array of applicant IDs")

    state = load_state()
    event_id = event_file.name

    for app_id in dict.fromkeys(ids):
        key = f"{event_id}:{app_id}"

        if key not in state:
            state[key] = {
                "event_id": event_id,
                "app_id": app_id,
                "status": "PENDING",
                "attempts": 0,
                "updated_at": timestamp(),
                "error": None,
            }
            save_state(state)

        current = state[key]["status"]

        if current in ("COMPLETED", "ESCALATED", "WAITING_FOR_MATERIALS"):
            print(f"{app_id}: {current} — skipping")
            continue

        if state[key]["attempts"] >= 2:
            update_checkpoint(
                state, key, "ESCALATED", "Maximum attempts reached"
            )
            print(f"{app_id}: ESCALATED")
            continue

        process_one(state, key, app_id)
        print(f"{app_id}: {state[key]['status']}")


def main():
    parser = argparse.ArgumentParser(description="EAOS event consumer")
    parser.add_argument("event_file", help="Path to affected_ids_<runid>.json")
    args = parser.parse_args()
    process_event(args.event_file)


if __name__ == "__main__":
    main()
