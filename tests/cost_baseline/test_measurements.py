"""Accounting checks; these do not claim to benchmark real model performance."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("baseline_runner", Path(__file__).with_name("run_baseline.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_incomplete_stream_usage_is_unknown():
    result = module.decode_usage(b'{"message":{"content":"partial"}}\n', True)
    assert result["prompt_eval_count"] is None
    assert result["total_duration"] is None
    assert result["stream_completed"] is None


def test_stream_uses_final_counts_and_preserves_zero():
    result = module.decode_usage(b'{"message":{"content":"hello"}}\n' + json.dumps({"done": True, "prompt_eval_count": 10, "eval_count": 0, "total_duration": 2000000000}).encode(), True)
    assert result["prompt_eval_count"] == 10
    assert result["eval_count"] == 0
    assert result["stream_completed"] is True


def test_failed_attempts_stay_in_the_cost_denominator_and_totals():
    calls = [{"endpoint": "/api/chat", "http_status": 200, "prompt_eval_count": 100, "eval_count": 20, "images": 4},
             {"endpoint": "/api/chat", "http_status": 200, "prompt_eval_count": 110, "eval_count": 25, "images": 4},
             {"endpoint": "/api/chat", "http_status": 500},
             {"endpoint": "/api/embed", "http_status": 200, "prompt_eval_count": 30}]
    result = module.aggregate_calls(calls)
    assert result["llm_vlm_calls"] == 3
    assert result["known_input_tokens"] == 210
    assert result["known_output_tokens"] == 45
    assert result["image_page_submissions"] == 8
    assert result["embedding_calls"] == 1
    assert result["chat_calls_missing_token_usage"] == 1
    assert result["transport_or_api_failed_calls"] == 1


def test_entirely_unknown_tokens_are_not_zero():
    result = module.aggregate_calls([{"endpoint": "/api/chat", "http_status": 503}])
    assert result["known_input_tokens"] is None
    assert result["known_output_tokens"] is None


def test_gpu_energy_excludes_long_gaps_and_stage_boundaries():
    spec = importlib.util.spec_from_file_location("baseline_summary", Path(__file__).with_name("summarize_baseline.py"))
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
    rows = [{"stage": "a", "elapsed_seconds": 0, "gpu_power_watts": 100},
            {"stage": "a", "elapsed_seconds": 2, "gpu_power_watts": 100},
            {"stage": "a", "elapsed_seconds": 20, "gpu_power_watts": 100},
            {"stage": "b", "elapsed_seconds": 22, "gpu_power_watts": 100}]
    result = {r["stage"]: r for r in summary.resource_summaries(rows)}
    assert result["a"]["sampled_gpu_kwh"] == pytest.approx(200 / 3600000)
    assert result["a"]["gpu_energy_sampled_seconds"] == 2
    assert result["b"]["sampled_gpu_kwh"] is None
    assert result["a"]["host_cpu_percent_mean"] is None


def test_restricted_value_scan_does_not_match_inside_another_word():
    spec = importlib.util.spec_from_file_location("baseline_summary_privacy", Path(__file__).with_name("summarize_baseline.py"))
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
    assert not summary.contains_exact_value("The female applicant", "male")
    assert not summary.contains_exact_value("The caucasian applicant", "asian")
    assert summary.contains_exact_value("Context: INTERNATIONAL student on visa.", "international student on visa")


def test_score_quality_distinguishes_wrong_scale_from_optional_missing():
    spec = importlib.util.spec_from_file_location("baseline_summary_scores", Path(__file__).with_name("summarize_baseline.py"))
    summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summary)
    assert summary.score_range_status("31", 400, 1600) == "invalid_range_or_type"
    assert summary.score_range_status("31", 1, 36) == "valid"
    assert summary.score_range_status("1500.0", 400, 1600) == "valid"
    assert summary.score_range_status("", 400, 1600) == "missing_optional_score"
    assert summary.score_range_status("NaN", 400, 1600) == "invalid_range_or_type"
