"""Applicant birth dates are stored as dates and serialized as ISO strings."""

from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from storage.models import Applicant
from storage.storage_manager import StorageManager


def test_date_column_and_score_lookup_round_trip(tmp_path):
    assert Applicant.__table__.c.date_of_birth.type.compile(
        dialect=postgresql.dialect()
    ) == "DATE"

    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'dates.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    storage.stage_applicant({
        "app_id": "APP_070", "first_name": "A", "last_name": "B",
        "date_of_birth": "07/21/2008",
    })

    applicant = storage.get_applicant("APP_070")
    assert applicant.date_of_birth == date(2008, 7, 21)
    assert applicant.to_dict()["date_of_birth"] == "2008-07-21"
    assert storage.find_applicant_by_email_or_dob(dob="2008-07-21").app_id == "APP_070"


def test_invalid_birth_date_is_rejected_before_storage(tmp_path):
    storage = StorageManager(
        database_url=f"sqlite:///{tmp_path / 'dates.db'}",
        minio_endpoint="127.0.0.1:1",
    )
    with pytest.raises(ValueError, match="Invalid date of birth"):
        storage.stage_applicant({
            "app_id": "APP_071", "first_name": "A", "last_name": "B",
            "date_of_birth": "02/30/2008",
        })
    assert storage.get_applicant("APP_071") is None
