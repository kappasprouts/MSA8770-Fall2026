"""Officer recommendations survive ingestion and upgrades of local stores."""

from datetime import datetime, timezone
import sqlite3

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from storage.storage_manager import StorageManager


def test_recommendation_survives_applicant_reingestion(tmp_path):
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'review.db'}", minio_endpoint="127.0.0.1:1"
    )
    saved_at = datetime.now(timezone.utc)
    storage.stage_applicant({
        "app_id": "APP_050", "admission_year": 2026, "admission_term": "F",
        "status": "DOSSIER_READY", "officer_recommendation": "WAITLIST",
        "officer_recommendation_notes": "Review again after spring grades.\nDiscuss with Dean.",
        "officer_recommendation_updated_at": saved_at,
    })
    storage.stage_applicant({"app_id": "APP_050", "first_name": "Updated"})
    app = storage.get_applicant("APP_050")
    assert app.officer_recommendation == "WAITLIST"
    assert app.to_dict()["officer_recommendation_notes"] == "Review again after spring grades.\nDiscuss with Dean."
    assert app.to_dict()["officer_recommendation_updated_at"]
    assert app.final_decision is None
    with pytest.raises(IntegrityError), storage.engine.begin() as connection:
        connection.execute(text("UPDATE applicants SET officer_recommendation = 'INVALID'"))


def test_old_sqlite_store_adds_nullable_review_fields(tmp_path):
    db_path = tmp_path / "old.db"
    # A minimal legacy table is sufficient for the fallback's additive migration.
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE applicants (app_id TEXT PRIMARY KEY, ib_test_scores JSON)")
        connection.execute("INSERT INTO applicants VALUES ('APP_050', '[]')")
    storage = StorageManager(database_url=f"sqlite:///{db_path}", minio_endpoint="127.0.0.1:1")
    columns = {column["name"] for column in inspect(storage.engine).get_columns("applicants")}
    assert {"officer_recommendation", "officer_recommendation_notes", "officer_recommendation_updated_at"} <= columns
    with storage.engine.connect() as connection:
        assert connection.execute(text(
            "SELECT officer_recommendation, officer_recommendation_notes, officer_recommendation_updated_at FROM applicants"
        )).one() == (None, None, None)
