"""Repeatable read-only checks after strict ingestion and a live dossier run.

Load tests/live_test_setup/settings.ps1 first and set POSTGRES_HOST=127.0.0.1.
Run with --ui after generating APP_012 and starting ui on port 3001.
No model responses, database queries, or object downloads are mocked.
"""

import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import requests
from psycopg2.extras import RealDictCursor
from ai_agent import summarizing_agent as agent

OUTPUT = ROOT / "output/reorganization_check_20261018"


def rows(connection, sql, params=()):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def source_file(app_id, filename):
    batch = "batch_01" if int(app_id.split("_")[1]) <= 10 else "batch_02"
    return ROOT / "data/batches" / batch / app_id / filename


def digest(data):
    return hashlib.sha256(data).hexdigest()


def preflight(connection):
    client = agent.connect_minio()
    result = {"database": rows(connection, "SELECT current_database() AS name")[0],
              "policies": rows(connection, "SELECT count(*) AS count, min(vector_dims(embedding)) AS dimensions FROM policy_chunks")[0],
              "documents": [], "ready_applicants": {}}
    applicants = rows(connection, "SELECT app_id, status, documents FROM applicants WHERE app_id BETWEEN 'APP_001' AND 'APP_020' ORDER BY app_id")
    result["applicants"] = [{"app_id": a["app_id"], "status": a["status"]} for a in applicants]
    for applicant in applicants:
        for document in applicant["documents"]:
            response = client.get_object(document.get("minio_bucket", agent.MINIO_BUCKET), document["minio_key"])
            try:
                downloaded = response.read()
            finally:
                response.close()
                response.release_conn()
            original = source_file(applicant["app_id"], document["filename"]).read_bytes()
            assert downloaded == original, document["minio_key"]
            result["documents"].append({"app_id": applicant["app_id"], "file": document["filename"],
                                        "bytes": len(downloaded), "sha256": digest(downloaded), "matches_source": True})
        if applicant["status"] not in {"READY_FOR_REVIEW", "DOSSIER_READY"}:
            continue
        allowed, withheld = agent.split_documents([agent.normalize_document(d) for d in applicant["documents"]])
        with contextlib.redirect_stdout(io.StringIO()):
            pages, problems = agent.load_pages(client, allowed)
        result["ready_applicants"][applicant["app_id"]] = {
            "load_problems": problems,
            "withheld": [d["filename"] for d in withheld],
            "section_documents": {section: sorted({p["filename"] for p in agent.section_pages(pages, section)})
                                  for section in agent.SECTION_DOCUMENT_TYPES},
            "loaded_but_unused": sorted({p["filename"] for p in pages if not any(
                p["document_type"] in types for types in agent.SECTION_DOCUMENT_TYPES.values())}),
        }
    result["actual_default_agent_ids"] = agent.load_affected_ids([])
    result["batch_02_ready_handoff"] = json.loads((OUTPUT / "affected_ids.json").read_text())
    result["uploaded_files_verified"] = len(result["documents"])
    result["render_failures"] = {key: value["load_problems"] for key, value in result["ready_applicants"].items() if value["load_problems"]}
    return result


def ui_checks(connection, base_url):
    log = (OUTPUT / "full_agent.log").read_text(encoding="utf-8-sig")
    assert "[8] Saved DOSSIER_READY" in log and "AGENT_ERROR" not in log, log[-1500:]
    start = (OUTPUT / "agent_started_at.txt").read_text(encoding="utf-8-sig").strip()
    run = rows(connection, "SELECT id, app_id, run_status, validation, created_at FROM dossier_generation_runs WHERE app_id='APP_012' AND created_at >= %s::timestamptz ORDER BY id DESC LIMIT 1", (start,))
    assert run and run[0]["run_status"] == "DOSSIER_READY" and run[0]["validation"]["passed"], run
    applicant = rows(connection, "SELECT status FROM applicants WHERE app_id='APP_012'")[0]
    assert applicant["status"] == "DOSSIER_READY", applicant
    session = requests.Session()
    checks = []

    def check(name, method, route, status, **kwargs):
        response = session.request(method, base_url + route, timeout=120, **kwargs)
        assert response.status_code == status, (name, response.status_code, response.text[:300])
        checks.append({"check": name, "status": response.status_code})
        return response

    check("page", "GET", "/", 200)
    applicants = check("applicants", "GET", "/api/applicants", 200).json()
    assert {"id": "APP_012"} in applicants["applicants"]
    dossier = check("fresh dossier", "GET", "/api/dossier?appId=APP_012", 200).json()
    assert dossier["data"]["run"]["run_status"] == "DOSSIER_READY"
    academic = dossier["data"]["applicant_dossier"]["academic_profile"]
    facts = academic["document_facts"]
    assert facts["unweighted_gpa"] == 3.97 and facts["weighted_gpa"] == 4.4, facts
    assert facts["sat_superscore"] == 1530 and facts["act_superscore"] == 35, facts
    assert dossier["data"]["run"]["documents_sent"]["CommonApp.pdf"] == [1, 2]
    for document in dossier["documents"]:
        file = document["file"]
        response = check(file, "GET", "/api/documents", 200, params={"appId": "APP_012", "file": file})
        assert response.headers["Content-Type"].startswith("application/pdf")
        assert response.content == source_file("APP_012", file).read_bytes(), file
    check("unknown dossier", "GET", "/api/dossier?appId=APP_999", 404)
    check("missing document", "GET", "/api/documents?appId=APP_012&file=absent.pdf", 404)
    check("invalid document", "GET", "/api/documents?appId=APP_012&file=notes.txt", 400)
    check("missing chat fields", "POST", "/api/chat", 400, json={})
    check("empty messages", "POST", "/api/chat", 400, json={"appId": "APP_012", "messages": []})
    check("unknown chat applicant", "POST", "/api/chat", 404, json={"appId": "APP_999", "messages": [{"role": "user", "content": "What is the GPA?"}]})
    return {"fresh_run": run[0], "applicant": applicant, "checks": checks,
            "academic": academic, "documents": dossier["documents"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3001")
    args = parser.parse_args()
    connection = agent.connect_postgres()
    try:
        result = ui_checks(connection, args.base_url) if args.ui else preflight(connection)
    finally:
        connection.close()
    path = OUTPUT / ("live_ui_checks.json" if args.ui else "live_preflight.json")
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(path)
    if not args.ui:
        print("Verified PDFs:", result["uploaded_files_verified"])
        print("Render failures:", json.dumps(result["render_failures"]))


if __name__ == "__main__":
    main()
