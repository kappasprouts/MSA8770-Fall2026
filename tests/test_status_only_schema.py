"""The database stores status while queue names remain derived output."""

import sqlite3

from sqlalchemy import inspect, text

from storage.models import Applicant
from storage.storage_manager import StorageManager


def test_applicant_route_is_derived_from_persisted_status(tmp_path):
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'applicants.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    columns = {column["name"] for column in inspect(storage.engine).get_columns("applicants")}
    assert "routing_destination" not in columns
    assert "routing_destination" not in Applicant.__table__.columns

    storage.stage_applicant({
        "app_id": "APP_050", "first_name": "A", "last_name": "B",
        "status": "INCOMPLETE", "routing_destination": "stale external value",
    })
    assert storage.get_applicant("APP_050").routing_destination == "Applicant Packet Update"

    assert storage.update_applicant_status("APP_050", "READY_FOR_REVIEW")
    persisted = storage.get_applicant("APP_050")
    assert persisted.status == "READY_FOR_REVIEW"
    assert persisted.routing_destination == "READY_FOR_REVIEW"
    assert persisted.to_dict()["routing_destination"] == "READY_FOR_REVIEW"


def test_existing_sqlite_store_migrates_to_status_only(tmp_path):
    db_path = tmp_path / "old_applicants.db"
    storage = StorageManager(
        database_url=f"sqlite:///{db_path}", minio_endpoint="127.0.0.1:1"
    )
    storage.stage_applicant({
        "app_id": "APP_051", "first_name": "A", "last_name": "B", "status": "INCOMPLETE",
    })
    storage.engine.dispose()

    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE applicants DROP COLUMN ib_test_scores")
        connection.execute("ALTER TABLE applicants ADD COLUMN ib_courses TEXT")
        connection.execute("UPDATE applicants SET ib_courses = 'IB Biology, IB History'")
        connection.execute(
            "ALTER TABLE applicants ADD COLUMN routing_destination TEXT NOT NULL "
            "DEFAULT 'Applicant Packet Update'"
        )

    upgraded = StorageManager(
        database_url=f"sqlite:///{db_path}", minio_endpoint="127.0.0.1:1"
    )
    columns = {column["name"] for column in inspect(upgraded.engine).get_columns("applicants")}
    assert "routing_destination" not in columns
    assert "ib_test_scores" in columns
    app = upgraded.get_applicant("APP_051")
    assert app.ib_test_scores == ["IB Biology", "IB History"]
    assert app.routing_destination == "Applicant Packet Update"


def test_audit_insert_failure_rolls_back_status_change(tmp_path):
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'applicants.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    storage.stage_applicant({
        "app_id": "APP_052", "first_name": "A", "last_name": "B", "status": "INCOMPLETE",
    })
    with storage.engine.begin() as connection:
        connection.execute(text(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        ))

    assert not storage.update_applicant_status(
        "APP_052", "READY_FOR_REVIEW", audit_action="MANIFEST_EVALUATED"
    )
    assert storage.get_applicant("APP_052").status == "INCOMPLETE"
