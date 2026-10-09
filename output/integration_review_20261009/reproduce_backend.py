"""Isolated PostgreSQL integration review with simulated object storage/model.

Requires the temporary review PostgreSQL container on 127.0.0.1:25432.
Never connects to the project's normal database or real Ollama endpoints.
Only the isolated test database and this review directory receive writes.
"""

import contextlib
import csv
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORK = Path(__file__).resolve().parent
os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:review-test-only@127.0.0.1:25432/rsu_integration_review"
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "25432"
os.environ["POSTGRES_DB"] = "rsu_integration_review"
os.environ["POSTGRES_PASSWORD"] = "review-test-only"

from ingestion.batch_ingest import BatchIngestor
from ingestion.test_score_ingest import TestScoreIngestor
from run_ingestion_check import run_pipeline
from storage.storage_manager import StorageManager
from summarizing_agent import summarizing_agent as agent
from summarizing_agent import create_pgvector_once as loader
from psycopg2.extras import RealDictCursor


class ObjectResponse(io.BytesIO):
    def release_conn(self):
        pass


class SimulatedObjects:
    def __init__(self):
        self.objects = {}
        self.lookups = []
    def fput_object(self, bucket_name, object_name, file_path, content_type):
        self.objects[(bucket_name, object_name)] = Path(file_path).read_bytes()
    def stat_object(self, bucket, key):
        if (bucket, key) not in self.objects:
            raise FileNotFoundError(key)
    def get_object(self, bucket, key):
        self.lookups.append((bucket, key))
        return ObjectResponse(self.objects[(bucket, key)])


def default_value(schema):
    kind = schema.get("type")
    if isinstance(kind, list):
        return None if "null" in kind else default_value({**schema, "type": kind[0]})
    if kind == "object":
        return {k: default_value(v) for k, v in schema["properties"].items()}
    if kind == "array":
        return []
    if kind == "string":
        return schema.get("enum", ["Factual test summary for human review."])[0]
    return 0


def mock_model(prompt, schema, num_predict, images=None):
    output = default_value(schema)
    if "document_facts" in output:
        output["document_facts"]["unweighted_gpa"] = 3.97
        output["document_facts"]["sat_superscore"] = 1530
        output["evidence"] = [{"document": "CommonApp.pdf", "page": 2, "quote": "Unweighted GPA 3.97"}]
    if "activities" in output:
        output["activities"] = [{"activity": "School art club member", "role_and_description": "Member",
                                  "years": "Not documented", "hours_per_week": "Not documented"}]
    return json.dumps(output), {"seconds": 0, "output_tokens": 100, "prompt_tokens": 100}


def rows(connection, sql, params=()):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def isolated_probe(connection):
    if rows(connection, "SELECT current_database() AS name;")[0]["name"] != "rsu_integration_review":
        raise RuntimeError("Refusing to write to a non-review database")
    results = {"commit": os.popen("git rev-parse HEAD").read().strip(),
               "services": {"postgresql": "real temporary PostgreSQL/pgvector",
                            "object_storage": "in-memory simulation; real MinIO unavailable",
                            "model": "deterministic mock; no real Qwen or embeddings"}, "probes": {}}
    objects = SimulatedObjects()
    def init_objects(storage):
        storage.minio_client = objects
        storage.minio_available = True
    with patch.object(StorageManager, "_init_minio_connection", init_objects):
        storage = StorageManager(use_sqlite_fallback=False)
    assert storage.db_available and not storage.is_sqlite_fallback
    for name in ("batch_01", "batch_02"):
        gate = run_pipeline(str(ROOT / name), report_file=str(WORK / f"{name}_report.txt"),
                            affected_ids_file=str(WORK / f"{name}_affected_ids.json"),
                            storage_manager=storage, require_postgresql=True, require_object_storage=True)
        results["probes"][name] = gate.to_dict()
    results["objects_simulated"] = len(objects.objects)

    # The real PostgreSQL schema and precision, rather than SQLite behavior.
    results["probes"]["schema"] = rows(connection,
        "SELECT column_name, data_type, is_nullable, numeric_precision, numeric_scale "
        "FROM information_schema.columns WHERE table_name='applicants' "
        "AND column_name IN ('admission_year','admission_term','unweighted_gpa','weighted_gpa') ORDER BY column_name;")
    for marker, extra in [("APP_090", {}), ("APP_091", {"admission_year": 2026, "admission_term": "F"})]:
        try:
            value = storage.stage_applicant({"app_id": marker, "first_name": "Review", "last_name": "Fixture",
                       "date_of_birth": "2008-03-15", "email_address": "review-fixture@example.test",
                       "unweighted_gpa": "3.8645", **extra})
            results["probes"][marker] = {"stored_gpa": str(value.unweighted_gpa)}
        except Exception as exc:
            results["probes"][marker] = {"error_type": type(exc).__name__, "summary": str(exc).splitlines()[0]}

    # Real policy SQL/vector retrieval; embedding vectors are controlled fixtures.
    loader.create_policy_table(connection)
    chunks, version = loader.load_policy_chunks()
    with patch.object(loader, "embed_texts", lambda values, task_prefix: [[1.0] + [0.0] * 767 for _ in values]):
        loader.store_policies(connection, chunks, version)
    with patch.object(agent, "embed_queries", lambda values: [[1.0] + [0.0] * 767 for _ in values]):
        policies = agent.retrieve_policies(connection, {"country": "USA"})
    results["probes"]["policy_storage"] = {"stored": len(chunks), "retrieved": [p["policy_id"] for p in policies]}
    agent.ensure_output_tables(connection)
    agent.ROOT = WORK  # Keep the agent's relative output logging inside the review directory.
    agent.RESULTS_DIR = WORK / "agent_results"
    with patch.object(agent, "retrieve_policies", lambda *args: policies), patch.object(agent, "call_model", mock_model):
        success = agent.process_applicant(connection, objects, "APP_012")
    results["probes"]["dossier_success"] = {"returned": success,
        "applicant": rows(connection, "SELECT app_id,status FROM applicants WHERE app_id='APP_012';"),
        "run": rows(connection, "SELECT run_status,attempts,validation FROM dossier_generation_runs WHERE app_id='APP_012' ORDER BY id DESC LIMIT 1;")}

    # Compare all real document types and rendered-page section inputs across both batches.
    processing = {}
    for db_app in storage.get_all_applicants():
        if db_app.app_id in {"APP_090", "APP_091"}:
            continue
        documents = [agent.normalize_document(d) for d in db_app.documents]
        allowed, withheld = agent.split_documents(documents)
        pages, problems = agent.load_pages(objects, allowed)
        processing[db_app.app_id] = {"load_problems": problems,
            "withheld": [d["filename"] for d in withheld],
            "by_section": {section: sorted({p["filename"] for p in agent.section_pages(pages, section)})
                           for section in agent.SECTION_DOCUMENT_TYPES},
            "loaded_but_unused": sorted({p["filename"] for p in pages if not any(
                p["document_type"] in types for types in agent.SECTION_DOCUMENT_TYPES.values())})}
    results["probes"]["document_coverage"] = processing

    # A score update really persists, but the next model prompt still omits it.
    db_app = storage.get_applicant("APP_012")
    delta = WORK / "score_delta_fixture.csv"
    with delta.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["email_address", "sat_math", "sat_ebrw", "ap_subject", "ap_score"])
        writer.writerow([db_app.email_address, 800, 799, "AP Biology", 5])
    ingestor = TestScoreIngestor(storage_manager=storage, affected_ids_path=WORK / "score_ids.json",
                              require_postgresql=True, require_object_storage=True)
    update = ingestor.ingest_college_board(delta)
    current = agent.get_applicant(connection, "APP_012")
    prompt = agent.build_image_prompt("academic", current, [])
    results["probes"]["delta_scores"] = {"affected_ids": update.affected_ids,
         "stored_sat": current["superscored_sat_score"], "new_sat_in_prompt": "1599" in prompt,
         "new_ap_in_prompt": "AP Biology" in prompt}

    def invalid_model(prompt, schema, *args):
        output = default_value(schema)
        if "document_facts" in output:
            output["summary"] = ""
        return json.dumps(output), {"seconds": 0, "output_tokens": 20}
    with patch.object(agent, "retrieve_policies", lambda *args: policies), patch.object(agent, "call_model", invalid_model):
        failed = agent.process_applicant(connection, objects, "APP_012")
    results["probes"]["validation_failure_after_success"] = {"returned": failed,
        "applicant": rows(connection, "SELECT app_id,status FROM applicants WHERE app_id='APP_012';"),
        "old_dossier_count": rows(connection, "SELECT count(*) AS count FROM applicant_dossier WHERE app_id='APP_012';"),
        "latest_run": rows(connection, "SELECT run_status,validation FROM dossier_generation_runs WHERE app_id='APP_012' ORDER BY id DESC LIMIT 1;")}

    # Infrastructure failures only get an audit entry; there is no generation-run failure record.
    old_runs = rows(connection, "SELECT count(*) AS count FROM dossier_generation_runs;")[0]["count"]
    with patch.object(agent, "load_pages", return_value=([], [{"error": "controlled object outage"}])):
        try:
            agent.process_applicant(connection, objects, "APP_013")
        except RuntimeError as exc:
            results["probes"]["document_outage"] = {"error": str(exc), "new_generation_runs":
                rows(connection, "SELECT count(*) AS count FROM dossier_generation_runs;")[0]["count"] - old_runs}

    # Replaying unchanged ingestion changes already-generated dossier workflow state.
    with patch.object(agent, "retrieve_policies", lambda *args: policies), patch.object(agent, "call_model", mock_model):
        agent.process_applicant(connection, objects, "APP_012")
    replay = run_pipeline(str(ROOT / "batch_02"), report_file=str(WORK / "replay_report.txt"),
                         affected_ids_file=str(WORK / "replay_affected_ids.json"), storage_manager=storage,
                         require_postgresql=True, require_object_storage=True)
    results["probes"]["unchanged_batch_replay"] = {"affected_ids": replay.affected_ids,
                 "applicant": rows(connection, "SELECT status FROM applicants WHERE app_id='APP_012';")}
    return results


if __name__ == "__main__":
    connection = agent.connect_postgres()
    try:
        with (WORK / "backend_execution.txt").open("w", encoding="utf-8") as handle, contextlib.redirect_stdout(handle):
            results = isolated_probe(connection)
        results["versions"] = {pkg: importlib.metadata.version(pkg) for pkg in
                              ("SQLAlchemy", "psycopg", "psycopg2-binary", "PyMuPDF", "pytest")}
        (WORK / "backend_results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"batches": {name: {key: results["probes"][name][key] for key in
                         ("total_processed", "total_valid", "total_awaiting_materials", "total_incomplete", "total_error")}
                         for name in ("batch_01", "batch_02")},
                         "mock_dossier": results["probes"]["dossier_success"]["returned"],
                         "delta_scores": results["probes"]["delta_scores"],
                         "failed_run_status": results["probes"]["validation_failure_after_success"]["applicant"],
                         "schema_precision": results["probes"]["APP_091"]}, indent=2))
    finally:
        connection.close()
