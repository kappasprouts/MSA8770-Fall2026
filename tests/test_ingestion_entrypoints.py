"""Regression tests for the API and overnight ingestion entry points."""

import importlib
import json
from pathlib import Path

import pytest

from ingestion.pipeline import BatchIngestionPipeline
from ingestion import scheduler
from storage.storage_manager import StorageManager


REQUIRED_DOCUMENTS = (
    "application_form.pdf",
    "transcript.pdf",
    "personal_statement.pdf",
    "recommendation_letter_1.pdf",
    "recommendation_letter_2.pdf",
)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config/policies.yaml"


def _write_batch(batch_dir: Path, missing_transcript_for_first: bool = False) -> None:
    batch_dir.mkdir()
    (batch_dir / "applicant_data.csv").write_text(
        "App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Name_of_HS,"
        "Intended_Major,Admission_Year,Admission_Term\n"
        "APP_101,Ada,West,2008-03-15,ada@example.com,North High,Physics,2026,Fall\n"
        "APP_102,Ben,East,2008-04-16,ben@example.com,South High,Math,2026,Fall\n",
        encoding="utf-8",
    )
    for applicant_id in ("APP_101", "APP_102"):
        packet_dir = batch_dir / applicant_id
        packet_dir.mkdir()
        for index, filename in enumerate(REQUIRED_DOCUMENTS):
            if missing_transcript_for_first and applicant_id == "APP_101" and filename == "transcript.pdf":
                continue
            (packet_dir / filename).write_bytes(
                b"%PDF-1.4\n" + bytes([65 + index]) * 2048
            )


def _storage(tmp_path: Path) -> StorageManager:
    return StorageManager(
        database_url=f"sqlite:///{tmp_path / 'applicants.db'}",
        minio_endpoint="127.0.0.1:1",
        use_sqlite_fallback=False,
    )


def _pipeline(tmp_path: Path, source_dir: Path, storage: StorageManager, strict: bool = False) -> BatchIngestionPipeline:
    return BatchIngestionPipeline(
        source_dir=source_dir,
        config_path=CONFIG_PATH,
        report_path=tmp_path / "audit.txt",
        affected_ids_path=tmp_path / "affected_ids.json",
        storage_manager=storage,
        require_object_storage=strict,
        require_postgresql=False,
    )


def test_batch_entrypoint_runs_canonical_gate_and_exports_handoff(tmp_path):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir, missing_transcript_for_first=True)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage)

    summary = pipeline.run_batch()

    assert summary["status"] == "COMPLETED"
    assert summary["total_packets_discovered"] == 2
    assert summary["status_breakdown"] == {"READY_FOR_REVIEW": 1, "INCOMPLETE": 1, "ERROR": 0}
    assert summary["affected_ids"] == ["APP_102"]
    assert json.loads(Path(summary["affected_ids_file"]).read_text()) == ["APP_102"]
    assert Path(summary["report_file"]).is_file()
    assert summary["hard_stop"] is True
    assert summary["storage_mode"] in {"sqlite", "sqlite_fallback"}
    assert summary["minio_available"] is False
    assert summary["object_storage_required"] is False
    assert summary["postgresql_required"] is False
    assert summary["handoff_ready"] is False
    assert all(item["documents_parsed"] == 0 and not item["ai_evaluated"] for item in summary["results"])
    assert storage.get_applicant("APP_101").status == "INCOMPLETE"
    assert storage.get_applicant("APP_102").status == "READY_FOR_REVIEW"

    # Configured paths are base names; each API or scheduler run gets its own
    # immutable handoff so a later run cannot replace this ID list.
    repeat = pipeline.run_batch()
    assert repeat["affected_ids_file"] != summary["affected_ids_file"]
    assert repeat["report_file"] != summary["report_file"]
    assert json.loads(Path(summary["affected_ids_file"]).read_text()) == ["APP_102"]


def test_strict_entrypoint_refuses_offline_minio_before_artifacts(tmp_path):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage, strict=True)

    with pytest.raises(RuntimeError, match="MinIO is unavailable"):
        pipeline.run_batch()

    assert not (tmp_path / "audit.txt").exists()
    assert not (tmp_path / "affected_ids.json").exists()
    assert storage.get_applicant("APP_101") is None


def test_strict_entrypoint_refuses_sqlite_before_artifacts(tmp_path):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir)
    storage = _storage(tmp_path)
    pipeline = BatchIngestionPipeline(
        source_dir=source_dir,
        config_path=CONFIG_PATH,
        report_path=tmp_path / "audit.txt",
        affected_ids_path=tmp_path / "affected_ids.json",
        storage_manager=storage,
        require_object_storage=False,
        require_postgresql=True,
    )

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        pipeline.run_batch()

    assert not list(tmp_path.glob("affected_ids_*.json"))
    assert storage.get_applicant("APP_101") is None


def test_single_packet_scope_links_late_transcript_without_updating_sibling(tmp_path):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir, missing_transcript_for_first=True)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage)
    first = pipeline.run_batch()

    assert first["affected_ids"] == ["APP_102"]
    assert storage.update_applicant_status("APP_102", "HOLD", "Manual Hold")
    (source_dir / "APP_101" / "transcript.pdf").write_bytes(b"%PDF-1.4\n" + b"T" * 2048)
    result = pipeline.process_packet("app101")

    assert result is not None
    assert result["applicant_id"] == "APP_101"
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["affected_ids"] == ["APP_101"]
    assert json.loads(Path(result["affected_ids_file"]).read_text()) == ["APP_101"]
    assert result["affected_ids_file"] != first["affected_ids_file"]
    assert json.loads(Path(first["affected_ids_file"]).read_text()) == ["APP_102"]
    assert storage.get_applicant("APP_102").status == "HOLD"
    assert len(storage.get_applicant("APP_101").documents) == 5


def test_overnight_scheduler_uses_canonical_pipeline_and_publishes_summary(tmp_path, monkeypatch):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage)
    monkeypatch.setattr(scheduler, "BatchIngestionPipeline", lambda: pipeline)
    monkeypatch.setattr(scheduler, "_latest_batch_summary", None)

    summary = scheduler.run_overnight_batch()

    assert summary["affected_ids"] == ["APP_101", "APP_102"]
    assert scheduler.get_latest_batch_summary() is summary
    assert Path(summary["affected_ids_file"]).is_file()


def test_legacy_packet_limit_is_rejected_before_storage_changes(tmp_path):
    source_dir = tmp_path / "batch"
    _write_batch(source_dir)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage)

    with pytest.raises(ValueError, match="max_packets is unsupported"):
        pipeline.run_batch(max_packets=1)

    assert storage.get_applicant("APP_101") is None
    with pytest.raises(ValueError, match="Invalid applicant ID"):
        pipeline.process_packet("../APP_101")


def test_api_pipeline_requires_shared_storage_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("INGESTION_REQUIRE_OBJECT_STORAGE", raising=False)
    monkeypatch.delenv("INGESTION_REQUIRE_POSTGRESQL", raising=False)
    pipeline = BatchIngestionPipeline(source_dir=tmp_path)
    assert pipeline.require_object_storage is True
    assert pipeline.require_postgresql is True


def test_http_routes_use_canonical_pipeline_when_fastapi_is_available(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    api = importlib.import_module("ingestion.app")
    source_dir = tmp_path / "batch"
    _write_batch(source_dir)
    storage = _storage(tmp_path)
    pipeline = _pipeline(tmp_path, source_dir, storage)
    monkeypatch.setattr(api, "BatchIngestionPipeline", lambda: pipeline)
    monkeypatch.setattr(scheduler, "_latest_batch_summary", None)

    summary = api.trigger_batch()
    assert api.batch_status() is summary
    single = api.ingest_single_packet("APP_101")
    assert single["affected_ids"] == ["APP_101"]
    assert single["affected_ids_file"] != summary["affected_ids_file"]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as invalid:
        api.trigger_batch(max_packets=1)
    assert invalid.value.status_code == 400

    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    http_summary = client.post("/ingestion/batch/trigger")
    assert http_summary.status_code == 200
    assert http_summary.json()["affected_ids"] == ["APP_101", "APP_102"]
    assert client.get("/ingestion/batch/status").json()["affected_ids_file"] == http_summary.json()["affected_ids_file"]
    assert client.post("/ingestion/batch/trigger?max_packets=1").status_code == 400
