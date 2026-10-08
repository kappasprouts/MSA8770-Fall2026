"""GPA columns retain three decimal places through CSV ingestion and storage."""

from decimal import Decimal
import json

from sqlalchemy.dialects import postgresql

from ingestion.batch_ingest import BatchIngestor
from storage.models import Applicant
from storage.storage_manager import StorageManager


def test_gpa_columns_and_csv_round_trip(tmp_path):
    for name in ("unweighted_gpa", "weighted_gpa"):
        assert Applicant.__table__.c[name].type.compile(
            dialect=postgresql.dialect()
        ) == "NUMERIC(5, 3)"

    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "applicant_data.csv").write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Unweighted_GPA,Weighted_GPA\n"
        "APP_080,Ada,West,2008-03-15,ada@example.com,3.8645,4.6765\n",
        encoding="utf-8",
    )
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'gpa.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    BatchIngestor(storage_manager=storage).pass_1_parse_and_stage_csv(batch)

    applicant = storage.get_applicant("APP_080")
    assert applicant.unweighted_gpa == Decimal("3.865")
    assert applicant.weighted_gpa == Decimal("4.677")
    serialized = applicant.to_dict()
    assert serialized["unweighted_gpa"] == 3.865
    assert serialized["weighted_gpa"] == 4.677
    json.dumps(serialized)
