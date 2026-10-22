"""Create auditable benchmark summaries and independent fixture/source checks."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import unicodedata
import math
import xml.etree.ElementTree as ET

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()] if path.exists() else []


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def flat_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k, v in r.items() if not isinstance(v, (dict, list))))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: r.get(k) for k in fields} for r in rows)


def normalized(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).casefold().strip()


def contains_exact_value(text, value):
    value = normalized(value)
    return bool(value and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", normalized(text)))


def score_range_status(value, minimum, maximum):
    if value is None or not str(value).strip():
        return "missing_optional_score"
    try:
        number = float(value)
        return "valid" if math.isfinite(number) and number.is_integer() and minimum <= number <= maximum else "invalid_range_or_type"
    except (ValueError, TypeError):
        return "invalid_range_or_type"


def input_score_checks():
    result = []
    for path in sorted((ROOT / "data/batches").glob("*/*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                for field, low, high in [("Superscored_SAT_Score", 400, 1600), ("Superscored_ACT_Score", 1, 36)]:
                    value = row.get(field, "")
                    result.append({"batch": path.parent.name, "app_id": row["App_ID"], "field": field, "fixture_value": value,
                                   "minimum": low, "maximum": high, "status": score_range_status(value, low, high),
                                   "rule_source": "Existing agent's SAT/ACT validity ranges; optional missing scores are separate"})
    return result


def strings(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, path + "." + key)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from strings(child, path + f"[{i}]")


def source_data(app_id):
    batch = "batch_01" if int(app_id.split("_")[1]) <= 10 else "batch_02"
    folder = ROOT / "data/batches" / batch
    csvpath = next(folder.glob("*.csv"))
    with csvpath.open(encoding="utf-8-sig", newline="") as f:
        record = next(r for r in csv.DictReader(f) if r["App_ID"] == app_id)
    pages, metadata = {}, []
    for pdf in (folder / app_id).glob("*.pdf"):
        with pymupdf.open(pdf) as document:
            for i, page in enumerate(document):
                pages[(pdf.name, i + 1)] = page.get_text()
            metadata.append({"app_id": app_id, "document": pdf.name, "bytes": pdf.stat().st_size,
                             "pages": len(document), "native_text_pages": sum(bool(p.get_text().strip()) for p in document),
                             "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()})
    return record, pages, metadata


def quality_checks(out, agent_runs):
    facts, citations, privacy, documents, review, courses = [], [], [], [], [], []
    fields = [("unweighted_gpa", "Unweighted_GPA"), ("weighted_gpa", "Weighted_GPA"),
              ("sat_superscore", "Superscored_SAT_Score"), ("act_superscore", "Superscored_ACT_Score")]
    for row in agent_runs:
        review.append({"stage": row["stage"], "app_id": row["app_id"], "run_status": row["status"], "human_reviewer": None,
                       "review_mode_manual_or_assisted": None, "human_review_minutes": None,
                       "facts_checked": None, "factual_errors": None, "citations_checked": None,
                       "citation_errors": None, "correction_minutes": None, "notes": None})
        if not row.get("snapshot"):
            continue
        payload = load(out / row["snapshot"])
        dossier = payload.get("applicant_dossier")
        if not dossier:
            continue
        source, pages, docs = source_data(row["app_id"])
        documents.extend({"stage": row["stage"], **d} for d in docs)
        found = dossier.get("academic_profile", {}).get("document_facts", {})
        expected_courses = [c.strip() for c in source.get("AP_Courses", "").split(",") if c.strip()]
        extracted_courses = [c.get("course", "") for c in dossier.get("academic_profile", {}).get("ap_courses_on_transcript", [])]
        course_key = lambda value: re.sub(r"[^a-z0-9]", "", normalized(value))
        actual_keys = {course_key(c) for c in extracted_courses}
        missing_courses = [c for c in expected_courses if course_key(c) not in actual_keys]
        courses.append({"stage": row["stage"], "app_id": row["app_id"], "fixture_ap_courses": len(expected_courses),
                        "extracted_ap_courses": len(extracted_courses), "fixture_courses_matched": len(expected_courses) - len(missing_courses),
                        "missing_fixture_courses": "; ".join(missing_courses),
                        "scope": "Course-name match against fixture CSV; confirm PDF source before treating as an extraction error"})
        for field, column in fields:
            raw = source.get(column, "").strip()
            try:
                expected = float(raw) if raw else None
            except ValueError:
                expected = None
            observed = found.get(field)
            matches = None
            if expected is not None:
                try:
                    matches = abs(float(observed) - expected) < 0.0001
                except (ValueError, TypeError):
                    matches = False
            facts.append({"stage": row["stage"], "app_id": row["app_id"], "field": field,
                          "fixture_csv_expected": expected, "dossier_value": observed, "matches_fixture": matches,
                          "scope": "CSV fixture consistency; not a full narrative accuracy assessment"})
        seen = set()
        for evidence in dossier.get("evidence_map", []):
            key = (evidence.get("document"), evidence.get("page"), evidence.get("quote"))
            if key in seen:
                continue
            seen.add(key)
            name, page_number, quote = key
            try:
                text = pages.get((name, int(page_number)))
            except (ValueError, TypeError):
                text = None
            if text is None:
                outcome = "source_or_page_missing"
            elif not text.strip():
                outcome = "image_only_requires_visual_review"
            elif normalized(quote) and normalized(quote) in normalized(text):
                outcome = "normalized_quote_found"
            else:
                outcome = "no_exact_normalized_match_requires_review"
            citations.append({"stage": row["stage"], "app_id": row["app_id"], "section": evidence.get("section"),
                              "document": name, "page": page_number, "quote": quote,
                              "agent_verification": evidence.get("verification_status"), "independent_text_check": outcome})
        narrative = {k: v for k, v in dossier.items() if k not in {"applicant_demographics", "app_id", "generated_at", "updated_at"}}
        for column in ("Hooks", "Gender", "Ethnicity", "Date_Of_Birth", "Mailing_Address", "Primary_Phone_Number", "Email_Address"):
            value = source.get(column, "").strip()
            if not value or normalized(value) in {"not provided", "none", "n/a", "nan"}:
                continue
            matches = [p for p, text in strings(narrative) if contains_exact_value(text, value)]
            privacy.append({"stage": row["stage"], "app_id": row["app_id"], "restricted_field": column,
                            "exact_value_matches_in_output": len(matches), "matching_paths": "; ".join(matches),
                            "scope": "Exact fixture-value scan only; absence does not prove privacy"})
        # Human input remains blank. Assistant/source checks are separately labeled.
    data = {"facts": facts, "citations": citations, "privacy": privacy, "source_documents": documents,
            "human_review": review, "course_coverage": courses,
            "limitations": ["Four numeric academic fields checked against CSV fixtures; CSV and PDFs can disagree.",
                            "Citation matching checks quotation text/location, not claim entailment.",
                            "Scanned-page citations need visual inspection.",
                            "Human reviewer time is not measured. Automated and assistant review do not substitute for it."]}
    save(out / "quality_checks.json", data)
    for name, rows in data.items():
        if name != "limitations":
            flat_csv(out / (name + ".csv"), rows)
    return data


def resource_summaries(samples):
    groups = {}
    for row in samples:
        groups.setdefault(row["stage"], []).append(row)
    result = []
    metrics = ["host_cpu_percent", "host_ram_used_bytes", "gpu_util_percent", "gpu_vram_used_mib", "gpu_power_watts"]
    for stage, rows in groups.items():
        row = {"stage": stage, "samples": len(rows)}
        for metric in metrics:
            values = [r[metric] for r in rows if isinstance(r.get(metric), (int, float))]
            row[metric + "_mean"] = statistics.mean(values) if values else None
            row[metric + "_max"] = max(values) if values else None
        energy, coverage = 0, 0
        for a, b in zip(rows, rows[1:]):
            dt = b["elapsed_seconds"] - a["elapsed_seconds"]
            if 0 < dt <= 6 and a.get("gpu_power_watts") is not None and b.get("gpu_power_watts") is not None:
                energy += (a["gpu_power_watts"] + b["gpu_power_watts"]) / 2 * dt / 3600000
                coverage += dt
        row.update(sampled_gpu_kwh=energy if coverage else None, gpu_energy_sampled_seconds=coverage,
                   energy_scope="GPU board only; includes idle GPU power; sampled intervals only")
        result.append(row)
    return result


def junit_summary(path):
    if not path.exists():
        return None
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    result = {"file": path.name}
    for key in ("tests", "failures", "errors", "skipped"):
        result[key] = sum(int(s.get(key, 0)) for s in suites)
    result["passed"] = result["tests"] - result["failures"] - result["errors"] - result["skipped"]
    result["seconds"] = sum(float(s.get("time", 0)) for s in suites)
    return result


def container_summaries(rows):
    grouped = {}
    for row in rows:
        for item in row.get("containers", []):
            key = (row["stage"], item["Name"])
            grouped.setdefault(key, []).append(item)
    result = []
    for (stage, name), items in grouped.items():
        cpus, memory = [], []
        for item in items:
            try:
                cpus.append(float(item["CPUPerc"].rstrip("%")))
                match = re.match(r"([\d.]+)([KMG]?i?B)", item["MemUsage"])
                scales = {"B": 1, "kB": 1000, "KB": 1000, "KiB": 1024, "MB": 1000000,
                          "MiB": 1024**2, "GB": 1000000000, "GiB": 1024**3}
                memory.append(float(match[1]) * scales[match[2]])
            except (ValueError, TypeError, KeyError):
                continue
        result.append({"stage": stage, "container": name, "samples": len(items),
                       "cpu_percent_mean": statistics.mean(cpus) if cpus else None,
                       "cpu_percent_max": max(cpus) if cpus else None,
                       "memory_bytes_mean": statistics.mean(memory) if memory else None,
                       "memory_bytes_max": max(memory) if memory else None})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    data = load(out / "results.json")
    calls, resources, operations = [lines(out / (name + ".jsonl")) for name in ("calls", "resources", "operations")]
    quality = quality_checks(out, data["agent"])
    input_checks = input_score_checks()
    save(out / "input_score_checks.json", input_checks)
    flat_csv(out / "input_score_checks.csv", input_checks)
    summaries = resource_summaries(resources)
    repeats = []
    grouped = {}
    for row in data["agent"]:
        if row.get("snapshot"):
            content = load(out / row["snapshot"]).get("applicant_dossier")
            if content:
                content = {k: v for k, v in content.items() if k not in {"generated_at", "updated_at"}}
                digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
                grouped.setdefault(row["app_id"], []).append((row, digest))
    for app_id, rows in grouped.items():
        if len(rows) > 1:
            repeats.append({"app_id": app_id, "runs": len(rows), "content_identical_excluding_timestamps": len({r[1] for r in rows}) == 1,
                            "minimum_wall_seconds": min(r[0]["wall_seconds"] for r in rows),
                            "maximum_wall_seconds": max(r[0]["wall_seconds"] for r in rows)})
    save(out / "repeatability_checks.json", repeats)
    containers = container_summaries(lines(out / "containers_and_models.jsonl"))
    flat_csv(out / "container_summary.csv", containers)
    flat_csv(out / "agent_runs.csv", data["agent"])
    flat_csv(out / "ingestion_runs.csv", data["ingestion"])
    flat_csv(out / "chat_requests.csv", data["chat"])
    flat_csv(out / "model_calls.csv", calls)
    flat_csv(out / "resource_summary.csv", summaries)
    flat_csv(out / "operation_timings.csv", operations)
    checked = [f for f in quality["facts"] if f["matches_fixture"] is not None]
    outcomes = {}
    for c in quality["citations"]:
        key = c["independent_text_check"]
        outcomes[key] = outcomes.get(key, 0) + 1
    success = [r for r in data["agent"] if r["status"] == "DOSSIER_READY"]
    routine = [r for r in data["agent"] if r["app_id"] != "APP_013"]
    chats = data["chat"]
    summary = {
        "status": data.get("status"), "ingestion_applicants": sum(r.get("applicants_processed", 0) for r in data["ingestion"]),
        "upload_attempts": sum(r["upload_attempts"] for r in data["ingestion"]),
        "uploaded_bytes": sum(r["successful_upload_bytes"] for r in data["ingestion"]),
        "agent_runs": len(data["agent"]), "agent_successful_runs": len(success),
        "agent_failed_runs": len(data["agent"]) - len(success),
        "routine_runs": len(routine), "routine_successful_runs": sum(r["status"] == "DOSSIER_READY" for r in routine),
        "routine_successful_unique_applicants": len({r["app_id"] for r in routine if r["status"] == "DOSSIER_READY"}),
        "historical_probe_outcomes": [{"stage": r["stage"], "status": r["status"]} for r in data["agent"] if r["app_id"] == "APP_013"],
        "successful_unique_applicants": len({r["app_id"] for r in success}),
        "agent_total_wall_seconds_including_failures": sum(r["wall_seconds"] for r in data["agent"]),
        "agent_successful_mean_seconds": statistics.mean(r["wall_seconds"] for r in success) if success else None,
        "agent_successful_median_seconds": statistics.median(r["wall_seconds"] for r in success) if success else None,
        "agent_successful_max_seconds": max((r["wall_seconds"] for r in success), default=None),
        "agent_wall_seconds_per_success_including_failures": sum(r["wall_seconds"] for r in data["agent"]) / len(success) if success else None,
        "agent_section_retry_attempts": sum(r.get("section_retry_attempts") or 0 for r in data["agent"]),
        "agent_first_attempt_successful_runs": sum(r["status"] == "DOSSIER_READY" and r.get("section_retry_attempts") == 0 for r in data["agent"]),
        "chat_requests": len(chats), "chat_http_failures": sum(r.get("http_status") != 200 for r in chats),
        "chat_mean_seconds": statistics.mean(r["wall_seconds"] for r in chats) if chats else None,
        "chat_median_seconds": statistics.median(r["wall_seconds"] for r in chats) if chats else None,
        "chat_max_seconds": max((r["wall_seconds"] for r in chats), default=None),
        "academic_fixture_fields_checked": len(checked), "academic_fixture_fields_matching": sum(f["matches_fixture"] for f in checked),
        "input_score_fields_checked": len(input_checks),
        "input_scores_provided": sum(r["status"] != "missing_optional_score" for r in input_checks),
        "input_scores_invalid": [r for r in input_checks if r["status"] == "invalid_range_or_type"],
        "ap_course_fixture_names_checked": sum(r["fixture_ap_courses"] for r in quality["course_coverage"]),
        "ap_course_fixture_names_matched": sum(r["fixture_courses_matched"] for r in quality["course_coverage"]),
        "citation_text_outcomes": outcomes,
        "privacy_scans_with_exact_value_matches": sum(p["exact_value_matches_in_output"] > 0 for p in quality["privacy"]),
        "resource_samples": len(resources), "resource_sampling_error_samples": sum(bool(r.get("sampling_error")) for r in resources),
        "automated_suites": [s for p in (out / "python_suite.xml", out / "contracts.xml", out / "measurement_tests.xml") if (s := junit_summary(p))],
        "human_reviewer_minutes": None, "manual_review_baseline_minutes": None,
        "whole_system_energy_kwh": None, "electricity_usd_per_kwh": None, "hardware_cost_allocation_usd_per_hour": None,
        "resources_by_stage": summaries,
        "containers_by_stage": containers,
        "repeatability": repeats,
    }
    manifest = load(out / "manifest.json")
    from datetime import datetime
    if data.get("completed_at_utc"):
        summary["benchmark_wall_seconds_including_build_idle_and_measurement"] = (datetime.fromisoformat(data["completed_at_utc"]) - datetime.fromisoformat(manifest["started_at_utc"])).total_seconds()
    summary["active_workload_wall_seconds"] = (sum(r["wall_seconds"] for r in data["ingestion"] + data["agent"] + data["chat"])
        + sum(r["wall_seconds"] for r in data["checks"] if r["name"] == "policy_index"))
    summary["workload_scope"] = "20 ingestion applicants; selected dossier attempts and fixed chat set. Not a complete 20-applicant end-to-end generation batch."
    for name in ("storage_initial", "storage_final"):
        path = out / (name + ".json")
        if path.exists():
            summary[name] = {k: v for k, v in load(path).items() if k not in {"tables", "buckets"}}
    path = out / "storage_and_ui_checks.json"
    if path.exists():
        result = load(path)
        summary["source_objects_checked"] = result["objects_checked"]
        summary["source_objects_matching"] = result["objects_matching"]
        summary["fixture_routing_checks"] = len(result["routing"])
        summary["fixture_routing_matches"] = result["routing_matches"]
        summary["ui_http_smoke_checks"] = len(result["ui_checks"])
        summary["ui_http_smoke_passed"] = sum(r["passed"] for r in result["ui_checks"])
    from run_baseline import aggregate_calls
    device_rows = lines(out / "processor_split.jsonl")
    device_states = {}
    for row in device_rows:
        for line in row.get("ollama_ps", "").splitlines():
            if line.startswith("qwen3-vl"):
                match = re.search(r"(?:\d+%/\d+% CPU/GPU|100% GPU|100% CPU)", line)
                if match:
                    device_states.setdefault(row["stage"], set()).add(match[0])
    summary["observed_vlm_processor_split_by_stage"] = {k: sorted(v) for k, v in device_states.items()}
    summary["processor_split_note"] = "Ollama's model processor allocation, not CPU/GPU utilization. Initial helper timestamps identify stage starts; host/GPU resource logs have actual sampling timestamps."
    summary["all_model_usage"] = aggregate_calls(calls)
    for category, select in [("agent_model_usage", lambda c: c["stage"].startswith("agent_")),
                             ("chat_model_usage", lambda c: c["stage"].startswith("chat_")),
                             ("index_model_usage", lambda c: c["stage"] == "policy_index")]:
        summary[category] = aggregate_calls([c for c in calls if select(c)])
    routine_chats = [r for r in chats if r["question_type"] in {"gpa_evidence", "activities", "policy_evidence"}]
    guardrail_chats = [r for r in chats if r not in routine_chats]
    summary["routine_chat_requests"] = len(routine_chats)
    summary["guardrail_chat_requests"] = len(guardrail_chats)
    summary["routine_chat_mean_seconds"] = statistics.mean(r["wall_seconds"] for r in routine_chats) if routine_chats else None
    summary["guardrail_chat_mean_seconds"] = statistics.mean(r["wall_seconds"] for r in guardrail_chats) if guardrail_chats else None
    save(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"resources_by_stage", "containers_by_stage"}}, indent=2))


if __name__ == "__main__":
    main()
