"""Verify the real agent CLI's handling of a ready fixture with unrenderable Hooks."""
import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

from reproduce_backend import agent, rows, SimulatedObjects, ROOT, WORK

objects = SimulatedObjects()
for filename in (ROOT / "batch_02/APP_013").glob("*.pdf"):
    objects.objects[(agent.MINIO_BUCKET, f"APP_013/{filename.name}")] = filename.read_bytes()
connection = agent.connect_postgres()
before = rows(connection, "SELECT count(*) AS count FROM dossier_generation_runs WHERE app_id='APP_013';")[0]["count"]
connection.close()
stdout = io.StringIO()
with patch.object(sys, "argv", ["summarizing_agent.py", "APP_013"]), \
     patch.object(agent, "connect_minio", lambda: objects), contextlib.redirect_stdout(stdout):
    returned = agent.main()  # A normally returning main means process exit code 0.
connection = agent.connect_postgres()
result = {"main_return": returned, "normal_process_exit_code": 0,
          "generation_runs_added": rows(connection, "SELECT count(*) AS count FROM dossier_generation_runs WHERE app_id='APP_013';")[0]["count"] - before,
          "applicant": rows(connection, "SELECT status FROM applicants WHERE app_id='APP_013';"),
          "latest_audit": rows(connection, "SELECT event,details FROM summary_audit_log WHERE app_id='APP_013' ORDER BY id DESC LIMIT 1;")}
connection.close()
(WORK / "cli_failure_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
(WORK / "cli_failure_output.txt").write_text(stdout.getvalue(), encoding="utf-8")
print(json.dumps(result, indent=2))
