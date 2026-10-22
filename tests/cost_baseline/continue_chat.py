"""Finish chat on a uniquely identified loopback server after dossier checkpoints.

Stops only the benchmark's verified parent/child process pair at the planned
APP_013 boundary. Existing user UI listeners are never stopped.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

from run_baseline import (Recorder, ROOT, NODE, NO_WINDOW, start_proxy, monitor,
                          monitor_containers, database, storage_snapshot,
                          write_json, utc, run_app, install_agent_instrumentation,
                          chat_tests)
from minio import Minio
import requests


def process_info(pid):
    command = f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | Select-Object ProcessId,ParentProcessId,CommandLine,CreationDate | ConvertTo-Json"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, check=True, creationflags=NO_WINDOW)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--old-ui-pid", required=True, type=int)
    parser.add_argument("--port", type=int, default=31023)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    info = process_info(args.old_ui_pid)
    parent = process_info(info["ParentProcessId"])
    assert "next" in info["CommandLine"] and "3002" in info["CommandLine"], info
    assert "run_baseline.py" in parent["CommandLine"] and out.name in parent["CommandLine"], parent
    correction = {"identified_at_utc": utc(), "old_benchmark_ui": info, "old_benchmark_parent": parent,
                  "reason": "Existing user listener at 127.0.0.1:3002 took precedence over benchmark wildcard listener. Dossier calls use the separate metering proxy and are unaffected.",
                  "new_port": args.port, "user_ui_pid_preserved": 24144}
    write_json(out / "ui_endpoint_correction.json", correction)
    ctypes.windll.kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, parent["ProcessId"])
    if not handle:
        raise ctypes.WinError()
    print(f"Watching benchmark PID {parent['ProcessId']} for the APP_013 boundary", flush=True)
    while True:
        try:
            progress = json.loads((out / "progress.json").read_text(encoding="utf-8"))
            if progress["stage"] == "agent_APP_013_r1" or progress["stage"].startswith("chat_"):
                correction["boundary_observed"] = progress
                correction["stopped_at_utc"] = utc()
                if not ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(handle), 130):
                    raise ctypes.WinError()
                break
        except (json.JSONDecodeError, PermissionError):
            pass
        time.sleep(0.003)
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    # The node child is our own wildcard listener, verified above. Preserve the
    # older user's loopback listener and all PostgreSQL/MinIO services.
    subprocess.run(["taskkill", "/PID", str(args.old_ui_pid), "/F"], capture_output=True, text=True, creationflags=NO_WINDOW)
    time.sleep(2)
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    correction["checkpointed_dossier_runs"] = len(results["agent"])
    correction["checkpointed_chat_requests"] = len(results.get("chat", []))
    correction["any_legacy_chat_started"] = correction["boundary_observed"]["stage"].startswith("chat_")
    if correction["any_legacy_chat_started"]:
        correction["legacy_chat_usage"] = None
        correction["legacy_chat_note"] = "An unmetered setup request may have started on the older UI. Excluded from valid chat observations; usage unknown."
        # Allow a potentially started local response to settle before the valid
        # sequential chat workload. This is setup overhead, not a model metric.
        time.sleep(55)
    write_json(out / "ui_endpoint_correction.json", correction)
    os.environ["OLLAMA_CHAT_URL"] = "http://127.0.0.1:11435/api/chat"
    os.environ["OLLAMA_EMBED_URL"] = "http://127.0.0.1:11435/api/embed"
    recorder = Recorder(out)
    start = datetime.fromisoformat(json.loads((out / "manifest.json").read_text())["started_at_utc"])
    recorder.started = time.perf_counter() - (datetime.now(timezone.utc) - start).total_seconds()
    proxy = start_proxy(recorder)
    stop = threading.Event()
    connection = database()
    client = Minio("127.0.0.1:29000", access_key="minioadmin", secret_key="minioadmin", secure=False)
    ui = None
    try:
        # Refuse an occupied loopback port before starting Next, and use an
        # identity file so an unrelated server cannot pass readiness checks.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", args.port))
        target = ROOT / "tmp" / ("cost_baseline_ui_" + out.name)
        marker = "cost-baseline-identity-" + out.name + ".txt"
        token = out.name + ":isolated-production-ui"
        (target / "public" / marker).write_text(token, encoding="utf-8")
        log = (out / "ui_server_verified.log").open("w", encoding="utf-8")
        ui = subprocess.Popen([NODE, str(ROOT / "ui/node_modules/next/dist/bin/next"), "start", "-H", "127.0.0.1", "-p", str(args.port)],
                              cwd=target, env={**os.environ, "NODE_ENV": "production"}, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        correction["new_ui_pid"] = ui.pid
        for _ in range(60):
            try:
                response = requests.get(f"http://127.0.0.1:{args.port}/{marker}", timeout=2)
                if response.status_code == 200 and response.text == token:
                    break
            except requests.RequestException:
                pass
            if ui.poll() is not None:
                raise RuntimeError("Verified-port UI exited; see ui_server_verified.log")
            time.sleep(1)
        else:
            raise RuntimeError("UI identity verification failed")
        correction["identity_verified_at_utc"] = utc()
        write_json(out / "ui_endpoint_correction.json", correction)
        for fn in (monitor, monitor_containers):
            threading.Thread(target=fn, args=(recorder, stop), daemon=True).start()
        if not any(r["app_id"] == "APP_013" for r in results["agent"]):
            from ai_agent import summarizing_agent as agent
            install_agent_instrumentation(agent, recorder)
            # Preserve the deliberately stopped partial negative-probe log.
            repetition = 2 if (out / "agent_APP_013_r1.log").exists() else 1
            results["agent"].append(run_app(agent, recorder, connection, client, "APP_013", repetition))
            write_json(out / "results.json", results)
        recorder.stage("verified_ui_smoke")
        subprocess.run([sys.executable, str(ROOT / "tests/cost_baseline/check_storage_and_ui.py"), str(out), "--ui-url", f"http://127.0.0.1:{args.port}"],
                       stdout=(out / "storage_and_ui_checks_verified.log").open("w", encoding="utf-8"), stderr=subprocess.STDOUT, check=True, creationflags=NO_WINDOW)
        eligible = [a for a in ["APP_012", "APP_014", "APP_015", "APP_017", "APP_002"] if any(r["app_id"] == a and r["status"] == "DOSSIER_READY" for r in results["agent"])]
        results["chat"] = chat_tests(recorder, eligible, args.port)
        recorder.stage("storage_final")
        write_json(out / "storage_final.json", storage_snapshot(connection, client))
        results.update(status="completed", completed_at_utc=utc(), ui_endpoint_correction="ui_endpoint_correction.json")
        write_json(out / "results.json", results)
    except Exception as error:
        results.update(status="continuation_failed", exception=f"{type(error).__name__}: {error}")
        write_json(out / "results.json", results)
        raise
    finally:
        stop.set()
        if ui is not None:
            ui.terminate()
            ui.wait(timeout=20)
        connection.close()
        proxy.shutdown()
        recorder.stage("finished_" + results.get("status", "unknown"))


if __name__ == "__main__":
    main()
