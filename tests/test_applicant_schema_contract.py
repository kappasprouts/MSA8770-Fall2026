"""Fresh/legacy schema parity and preservation of human review during upgrades."""

from decimal import Decimal
import os
from pathlib import Path

import pytest
from sqlalchemy import Column, Index, MetaData, Numeric, String, create_engine, inspect, text

from storage.models import Applicant
from storage.storage_manager import StorageManager
from storage.sqlite_migrations import migrate_applicant_contract


def test_sqlite_upgrade_preserves_rows_extensions_and_review(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    legacy = Applicant.__table__.to_metadata(MetaData())
    legacy.c.admission_year.nullable = False
    legacy.c.admission_term.nullable = False
    legacy.c.unweighted_gpa.type = Numeric(5, 3)
    legacy.c.weighted_gpa.type = Numeric(5, 3)
    legacy.append_column(Column("local_note", String))
    Index("legacy_note_index", legacy.c.local_note)
    legacy.create(engine)
    with engine.begin() as connection:
        connection.execute(legacy.insert().values(
            app_id="APP_050", admission_year=2026, admission_term="F",
            unweighted_gpa=Decimal("3.865"), weighted_gpa=Decimal("4.675"),
            status="FINAL_DECISION_RECORDED", officer_recommendation="WAITLIST",
            officer_recommendation_notes="Keep this note", final_decision="ACCEPT",
            documents=[{"filename": "transcript.pdf"}], local_note="keep",
        ))
        connection.execute(text("CREATE TABLE trigger_probe (value TEXT)"))
        connection.execute(text("CREATE TRIGGER legacy_note_trigger AFTER UPDATE OF local_note ON applicants BEGIN INSERT INTO trigger_probe VALUES (NEW.local_note); END"))
    engine.dispose()

    for _ in range(2):
        store = StorageManager(database_url=url, minio_endpoint="127.0.0.1:1", use_sqlite_fallback=False)
        assert store.db_available
        columns = {c["name"]: c for c in inspect(store.engine).get_columns("applicants")}
        assert columns["admission_year"]["nullable"]
        assert columns["admission_term"]["nullable"]
        assert str(columns["unweighted_gpa"]["type"]) == "NUMERIC(3, 2)"
        app = store.get_applicant("APP_050")
        assert (app.unweighted_gpa, app.weighted_gpa) == (Decimal("3.87"), Decimal("4.68"))
        assert (app.status, app.officer_recommendation, app.final_decision) == ("FINAL_DECISION_RECORDED", "WAITLIST", "ACCEPT")
        assert app.officer_recommendation_notes == "Keep this note"
        assert app.documents == [{"filename": "transcript.pdf"}]
        with store.engine.begin() as connection:
            assert connection.execute(text("SELECT local_note FROM applicants WHERE app_id='APP_050'")).scalar_one() == "keep"
            connection.execute(text("UPDATE applicants SET local_note='keep' WHERE app_id='APP_050'"))
        assert "legacy_note_index" in {i["name"] for i in inspect(store.engine).get_indexes("applicants")}
        store.stage_applicant({"app_id": "APP_051", "unweighted_gpa": "3.865", "weighted_gpa": "4.675"})
        added = store.get_applicant("APP_051")
        assert added.admission_year is None and added.admission_term is None
        assert (added.unweighted_gpa, added.weighted_gpa) == (Decimal("3.87"), Decimal("4.68"))
        store.engine.dispose()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM trigger_probe")).scalar_one() == 2


def test_failed_sqlite_upgrade_rolls_back_schema_and_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE applicants (app_id TEXT PRIMARY KEY, admission_year INTEGER NOT NULL, admission_term VARCHAR(1) NOT NULL, unweighted_gpa NUMERIC(5,3))"))
        connection.execute(text("INSERT INTO applicants VALUES ('OLD',2026,'F',99.999)"))
        connection.execute(text("CREATE TABLE linked (app_id TEXT REFERENCES applicants(app_id))"))
        connection.execute(text("INSERT INTO linked VALUES ('OLD')"))
    with pytest.raises(ValueError, match="NUMERIC"):
        migrate_applicant_contract(engine)
    with engine.connect() as connection:
        columns = {r[1]: r for r in connection.execute(text("PRAGMA table_info(applicants)"))}
        assert columns["admission_year"][3] == 1
        assert columns["unweighted_gpa"][2] == "NUMERIC(5,3)"
        assert connection.execute(text("SELECT unweighted_gpa FROM applicants")).scalar_one() == 99.999
        assert connection.execute(text("SELECT app_id FROM linked")).scalar_one() == "OLD"
        assert not connection.execute(text("SELECT name FROM sqlite_master WHERE name='_applicants_contract_upgrade'")).fetchall()
    engine.dispose()


@pytest.mark.skipif(not os.getenv("POSTGRES_DB"), reason="Requires configured test PostgreSQL")
def test_postgresql_fresh_and_legacy_contract():
    import psycopg2
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    connection = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
    )
    try:
        with connection.cursor() as cursor:
            ddl = str(CreateTable(Applicant.__table__).compile(dialect=postgresql.dialect()))
            cursor.execute(ddl.replace("CREATE TABLE applicants", "CREATE TEMP TABLE applicants"))
            cursor.execute("SELECT attname, attnotnull FROM pg_attribute WHERE attrelid='pg_temp.applicants'::regclass AND attname IN ('admission_year','admission_term')")
            assert dict(cursor.fetchall()) == {"admission_year": False, "admission_term": False}
            cursor.execute("DROP TABLE pg_temp.applicants")
            cursor.execute("CREATE TEMP TABLE applicants (app_id text PRIMARY KEY, admission_year integer NOT NULL, admission_term varchar(1) NOT NULL, unweighted_gpa numeric(5,3), weighted_gpa numeric(5,3), final_decision text)")
            cursor.execute("INSERT INTO applicants VALUES ('OLD',2026,'F',3.865,4.675,'ACCEPT')")
        connection.commit()
        migration = (Path(__file__).resolve().parents[1] / "storage/migrations/20261031_applicant_schema_contract.sql").read_text()
        for _ in range(2):
            with connection.cursor() as cursor:
                cursor.execute(migration)
        with connection.cursor() as cursor:
            cursor.execute("SELECT unweighted_gpa,weighted_gpa,final_decision FROM pg_temp.applicants WHERE app_id='OLD'")
            assert cursor.fetchone() == (Decimal("3.87"), Decimal("4.68"), "ACCEPT")
            cursor.execute("INSERT INTO pg_temp.applicants (app_id,unweighted_gpa) VALUES ('NEW',3.865)")
            cursor.execute("SELECT admission_year,admission_term,unweighted_gpa FROM pg_temp.applicants WHERE app_id='NEW'")
            assert cursor.fetchone() == (None, None, Decimal("3.87"))
    finally:
        connection.close()
