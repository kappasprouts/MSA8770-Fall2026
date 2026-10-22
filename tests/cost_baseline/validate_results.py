"""Reconcile delivered summaries with raw metering and source identities."""
import hashlib
import json
from pathlib import Path
import sys

out = Path(sys.argv[1]).resolve()
root = Path(__file__).resolve().parents[2]
read = lambda name: json.loads((out / name).read_text(encoding="utf-8"))
results, summary, manifest = read("results.json"), read("summary.json"), read("manifest.json")
calls = [json.loads(s) for s in (out / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
agent_calls = [c for c in calls if c["stage"].startswith("agent_") and c["endpoint"] == "/api/chat"]
chat_calls = [c for c in calls if c["stage"].startswith("chat_") and c["endpoint"] == "/api/chat"]
pages = read("page_accounting.json")
fresh = read("freshness_checks.json")
checks = {
    "run_completed": results["status"] == "completed",
    "agent_wire_calls_match_per_run": len(agent_calls) == sum(r["llm_vlm_calls"] for r in results["agent"]),
    "agent_input_tokens_match": sum(c["prompt_eval_count"] for c in agent_calls) == sum(r["known_input_tokens"] or 0 for r in results["agent"]),
    "agent_output_tokens_match": sum(c["eval_count"] for c in agent_calls) == sum(r["known_output_tokens"] or 0 for r in results["agent"]),
    "chat_wire_calls_match_requests": len(chat_calls) == len(results["chat"]),
    "chat_input_tokens_match": sum(c["prompt_eval_count"] for c in chat_calls) == summary["chat_model_usage"]["known_input_tokens"],
    "chat_output_tokens_match": sum(c["eval_count"] for c in chat_calls) == summary["chat_model_usage"]["known_output_tokens"],
    "all_streams_have_final_completion": all(c.get("stream_completed") is True for c in agent_calls),
    "all_page_selection_counts_match_wire": all(p["wire_count_matches_selection"] for p in pages),
    "all_fresh_ui_dossiers_match_saved_outputs": all(r["dossier_matches_fresh_snapshot"] for r in fresh["fresh_ui_dossiers"]),
    "all_linked_objects_match_sources": summary["source_objects_matching"] == summary["source_objects_checked"],
    "all_expected_routing_matches": summary["fixture_routing_matches"] == summary["fixture_routing_checks"],
    "human_reviewer_time_not_fabricated": summary["human_reviewer_minutes"] is None,
    "whole_system_energy_not_fabricated": summary["whole_system_energy_kwh"] is None,
}
source_changes = []
for name, expected in manifest["source_sha256"].items():
    if name.startswith(("ai_agent/", "ingestion/", "storage/", "ui/src/")):
        if not (root / name).exists() or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            source_changes.append(name)
checks["existing_application_source_unchanged"] = not source_changes
result = {"checks": checks, "all_passed": all(checks.values()), "source_changes": source_changes,
          "input_csv_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "data/batches").glob("*/*.csv")},
          "notes": "These are measurement-integrity checks. Existing failing application/contract tests remain reported separately."}
(out / "measurement_integrity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
if not result["all_passed"]:
    raise SystemExit(1)
