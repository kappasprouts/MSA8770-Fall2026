"""Human review milestones survive automated packet updates and regeneration."""

import json
import os

import pytest
from sqlalchemy import text

from policy import derive_routing_destination
from storage.storage_manager import StorageManager


@pytest.mark.parametrize("recommendation,decision,expected,queue", [
    (None, None, "DOSSIER_READY", "Applicant Review"),
    ("REJECT", None, "REVIEWED", "Final Decisions"),
    ("REJECT", "ACCEPT", "FINAL_DECISION_RECORDED", "Final Decision Recorded"),
    (None, "WAITLIST", "FINAL_DECISION_RECORDED", "Final Decision Recorded"),
])
def test_review_progress_survives_reingestion_and_gate_updates(tmp_path, recommendation, decision, expected, queue):
    storage = StorageManager(database_url=f"sqlite:///{tmp_path / 'review.db'}", minio_endpoint="127.0.0.1:1")
    storage.stage_applicant({
        "app_id": "APP_050", "admission_year": 2026, "admission_term": "F",
        "status": "DOSSIER_READY", "officer_recommendation": recommendation, "final_decision": decision,
    })
    assert storage.get_applicant("APP_050").status == expected
    assert derive_routing_destination(expected) == queue
    if recommendation is None and decision is None:
        assert storage.update_applicant_status("APP_050", "READY_FOR_REVIEW")
        assert storage.get_applicant("APP_050").status == "READY_FOR_REVIEW"
        return
    storage.stage_applicant({"app_id": "APP_050", "first_name": "Updated", "status": "PENDING"})
    assert storage.update_applicant_status("APP_050", "READY_FOR_REVIEW", audit_action="MANIFEST_REEVALUATED")
    app = storage.get_applicant("APP_050")
    assert app.status == expected
    assert app.to_dict()["final_decision"] == decision
    assert app.officer_recommendation == recommendation
    assert app.routing_destination == queue
    with storage.engine.connect() as connection:
        audit = connection.execute(text("SELECT details FROM audit_logs")).scalar_one()
    assert json.loads(audit)["status"] == expected


def test_sqlite_upgrade_backfills_existing_review_without_changing_outcomes(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    storage = StorageManager(database_url=url, minio_endpoint="127.0.0.1:1")
    storage.stage_applicant({"app_id": "APP_050", "admission_year": 2026, "admission_term": "F", "status": "DOSSIER_READY"})
    with storage.engine.begin() as connection:
        connection.execute(text("UPDATE applicants SET officer_recommendation='WAITLIST'"))
    storage.engine.dispose()
    upgraded = StorageManager(database_url=url, minio_endpoint="127.0.0.1:1")
    assert upgraded.get_applicant("APP_050").status == "REVIEWED"
    with upgraded.engine.begin() as connection:
        connection.execute(text("UPDATE applicants SET status='DOSSIER_READY', final_decision='DECLINE'"))
    upgraded.engine.dispose()
    finalized = StorageManager(database_url=url, minio_endpoint="127.0.0.1:1").get_applicant("APP_050")
    assert finalized.status == "FINAL_DECISION_RECORDED"
    assert finalized.officer_recommendation == "WAITLIST"
    assert finalized.final_decision == "DECLINE"


@pytest.mark.skipif(not os.environ.get("POSTGRES_DB"), reason="Requires local PostgreSQL")
def test_generation_run_preserves_human_progress_in_postgresql():
    import psycopg2
    from ai_agent.summarizing_agent import save_run

    connection = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
    )
    try:
        # Temporary tables shadow the real application data for this connection.
        with connection.cursor() as cursor:
            cursor.execute("""CREATE TEMP TABLE applicants (
                app_id text PRIMARY KEY, status text, officer_recommendation text, final_decision text
            )""")
            cursor.execute("""CREATE TEMP TABLE dossier_generation_runs (id BIGSERIAL PRIMARY KEY,
                app_id text, run_status text, model text, attempts integer, runtime_seconds numeric,
                documents_sent jsonb, documents_withheld jsonb, policies_retrieved jsonb, validation jsonb, failed_output jsonb
            )""")
            cursor.execute("""INSERT INTO applicants VALUES
                ('NEW', 'READY_FOR_REVIEW', NULL, NULL), ('REVIEW', 'REVIEWED', 'WAITLIST', NULL),
                ('FINAL', 'FINAL_DECISION_RECORDED', 'REJECT', 'ACCEPT')""")
        for run_status in ["DOSSIER_READY", "AI_VALIDATION_FAILED"]:
            for app_id in ["NEW", "REVIEW", "FINAL"]:
                save_run(connection, {"app_id": app_id, "run_status": run_status, "attempts": 1, "runtime_seconds": 0,
                    "documents_sent": {}, "documents_withheld": {}, "policies_retrieved": [], "validation": {}})
            with connection.cursor() as cursor:
                cursor.execute("SELECT app_id, status FROM applicants ORDER BY app_id")
                assert dict(cursor.fetchall()) == {
                    "NEW": "DOSSIER_READY" if run_status == "DOSSIER_READY" else "READY_FOR_REVIEW",
                    "REVIEW": "REVIEWED", "FINAL": "FINAL_DECISION_RECORDED",
                }
    finally:
        connection.close()
