"""Read-only post-benchmark fixture, storage, and UI checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import psycopg2
from psycopg2.extras import RealDictCursor
from minio import Minio
import requests
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--ui-url", default="http://127.0.0.1:3002")
    args = parser.parse_args()
    out = Path(args.output)
    connection = psycopg2.connect(host="127.0.0.1", port=25432, dbname="rsu_live_test", user="postgres", password="postgres", connect_timeout=5)
    client = Minio("127.0.0.1:29000", access_key="minioadmin", secret_key="minioadmin", secure=False)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT app_id,status,documents FROM applicants ORDER BY app_id")
        applicants = cursor.fetchall()
    checks = []
    for applicant in applicants:
        app = applicant["app_id"]
        batch = "batch_01" if int(app.split("_")[1]) <= 10 else "batch_02"
        for doc in applicant["documents"]:
            name = doc["filename"]
            key = doc.get("minio_key", doc.get("object_key"))
            bucket = doc.get("minio_bucket", "admissions-raw-docs")
            row = {"app_id": app, "document": name, "key": key, "bucket": bucket, "document_type": doc.get("type") or doc.get("doc_type")}
            try:
                response = client.get_object(bucket, key)
                try:
                    content = response.read()
                finally:
                    response.close()
                    response.release_conn()
                expected = (ROOT / "data/batches" / batch / app / name).read_bytes()
                row.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), source_sha256=hashlib.sha256(expected).hexdigest(), matches_source=content == expected)
            except Exception as error:
                row.update(matches_source=False, error=str(error))
            checks.append(row)
    routing = []
    for batch in ("batch_01", "batch_02"):
        data = json.loads((out / ("ingestion_" + batch + ".json")).read_text(encoding="utf-8"))
        for row in data["applicants"]:
            expected = ("AWAITING_MATERIALS" if row["app_id"] in {"APP_010", "APP_011"} else
                        "INCOMPLETE" if row["app_id"] in {"APP_018", "APP_019"} else "READY_FOR_REVIEW")
            routing.append({"app_id": row["app_id"], "expected": expected, "observed": row["status"], "matches": row["status"] == expected})
    ui = []
    cases = [("home", "get", "/", None, 200),
             ("review_queue", "get", "/review-queue", None, 200),
             ("review_workspace", "get", "/applicant-review?appId=APP_012", None, 200),
             ("dossier", "get", "/api/dossier?appId=APP_012", None, 200),
             ("empty_chat", "post", "/api/chat", {}, 400),
             ("unknown_app_chat", "post", "/api/chat", {"appId": "COST_BASELINE_NOT_FOUND", "messages": [{"role": "user", "content": "GPA?"}]}, 404)]
    for name, method, route, body, expected_status in cases:
        started = time.perf_counter()
        try:
            response = requests.request(method, args.ui_url + route, json=body, timeout=20)
            ui.append({"check": name, "status": response.status_code, "expected_status": expected_status,
                       "passed": response.status_code == expected_status, "wall_seconds": time.perf_counter() - started})
        except Exception as error:
            ui.append({"check": name, "passed": False, "error": str(error), "wall_seconds": time.perf_counter() - started})
    output = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "objects_checked": len(checks),
              "objects_matching": sum(c["matches_source"] for c in checks), "documents": checks,
              "routing": routing, "routing_matches": sum(c["matches"] for c in routing), "ui_checks": ui,
              "scope": "Object bytes verified against original fixtures; routing uses explicit expected fixture statuses. UI GETs are HTTP smoke checks, not visual browser QA."}
    (out / "storage_and_ui_checks.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    from ai_agent import summarizing_agent as agent
    by_app = {a["app_id"]: {d["filename"]: d["type"] for raw in a["documents"] if (d := agent.normalize_document(raw))} for a in applicants}
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT id,app_id,run_status,runtime_seconds,created_at FROM dossier_generation_runs WHERE created_at >= %s::timestamptz ORDER BY id", (manifest["started_at_utc"],))
        new_runs = cursor.fetchall()
    fresh_ui = []
    latest = {r["app_id"]: r for r in results["agent"] if r.get("snapshot") and r["status"] == "DOSSIER_READY"}
    for app_id, run in latest.items():
        row = {"app_id": app_id}
        try:
            response = requests.get(args.ui_url + "/api/dossier", params={"appId": app_id}, timeout=20)
            data = response.json().get("data", response.json())
            actual = data.get("applicant_dossier", {})
            expected = json.loads((out / run["snapshot"]).read_text(encoding="utf-8"))["applicant_dossier"]
            strip_times = lambda value: {k: v for k, v in value.items() if k not in {"generated_at", "updated_at"}}
            row.update(http_status=response.status_code, dossier_matches_fresh_snapshot=strip_times(actual) == strip_times(expected),
                       dossier_updated_at=actual.get("updated_at"), ui_run_id=data.get("run", {}).get("id"),
                       ui_run_created_at=data.get("run", {}).get("created_at"))
        except Exception as error:
            row.update(dossier_matches_fresh_snapshot=False, error=str(error))
        fresh_ui.append(row)
    (out / "freshness_checks.json").write_text(json.dumps({"new_database_runs": new_runs, "fresh_ui_dossiers": fresh_ui}, indent=2, default=str), encoding="utf-8")
    wire_calls = [json.loads(line) for line in (out / "calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    accounting = []
    for run in results["agent"]:
        if not run.get("snapshot"):
            continue
        payload = json.loads((out / run["snapshot"]).read_text(encoding="utf-8"))
        loaded = {(name, page) for name, pages in payload["run"]["documents_sent"].items() for page in pages}
        submitted, predicted_submissions = set(), 0
        observed = [c for c in wire_calls if c["stage"] == run["stage"] and c["endpoint"] == "/api/chat" and c.get("images", 0) > 0]
        for call in observed:
            types = agent.SECTION_DOCUMENT_TYPES.get(call.get("section"), [])
            selected = {location for location in loaded if by_app[run["app_id"]].get(location[0]) in types}
            submitted.update(selected)
            predicted_submissions += len(selected)
        actual_submissions = sum(c["images"] for c in observed)
        accounting.append({"stage": run["stage"], "app_id": run["app_id"], "rendered_unique_pages": len(loaded),
                           "unique_model_pages_by_selection": len(submitted), "wire_image_submissions": actual_submissions,
                           "selection_image_submissions": predicted_submissions, "wire_count_matches_selection": actual_submissions == predicted_submissions,
                           "rendered_but_unused_pages": sorted(loaded - submitted),
                           "method": "Page identities reconstructed from saved loaded-page metadata and unchanged section-selection rules; submission count independently checked against wire requests"})
    (out / "page_accounting.json").write_text(json.dumps(accounting, indent=2), encoding="utf-8")
    connection.close()
    print(json.dumps({k: v for k, v in output.items() if k not in {"documents", "routing"}}, indent=2))


if __name__ == "__main__":
    main()
