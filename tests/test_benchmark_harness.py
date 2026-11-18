"""The end-to-end benchmark's own judgement: what counts as a passing run.

The run status cannot be trusted for this. When the developer retry budget runs
out the graph ends "with the current result", so a run can be ``completed`` with
tests still failing. These tests pin the harness to Eq. (1) instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evaluation import run_e2e_benchmark as bench
from evaluation import summarise_e2e as summary


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "retry_count": 1,
        "static_report": {
            "ran": True,
            "passed": True,
            "checks": [
                {"name": "compile", "service": "api", "passed": True},
                {"name": "pyflakes", "service": "api", "passed": True},
            ],
        },
        "verification_report": {
            "ran": True,
            "passed": True,
            "services": [{"service": "api", "ran": True, "passed": 5, "failed": 0, "errors": 0}],
        },
        "qa_report": {
            "critical_issues": 0,
            "service_reports": [{"service_name": "api", "code_quality_score": 8}],
        },
        "cost_report": {"calls": 7, "reserved_tokens": 21000, "rate_limited": 2, "outcomes": {"success": 5}},
    }
    state.update(overrides)
    return state


class TestPassingIsEquationOne:
    def test_a_clean_run_passes(self):
        metrics = bench.run_metrics(_state())

        assert metrics["passed"] is True
        assert metrics["tests_passed"] == 5
        assert metrics["qa_min_score"] == 8
        assert metrics["rate_limited"] == 2

    def test_failing_tests_fail_the_run_even_if_it_completed(self):
        state = _state(
            verification_report={
                "ran": True,
                "passed": False,
                "services": [{"service": "api", "ran": True, "passed": 3, "failed": 2, "errors": 0}],
            },
            retry_count=3,
        )

        metrics = bench.run_metrics(state)

        assert metrics["passed"] is False
        assert "failing" in metrics["rework_reason"]

    def test_a_service_that_could_not_run_its_tests_fails(self):
        state = _state(
            verification_report={
                "ran": True,
                "passed": True,
                "services": [{"service": "api", "ran": False, "error": "pip install failed"}],
            }
        )

        assert bench.run_metrics(state)["passed"] is False

    def test_a_critical_bug_fails(self):
        state = _state(qa_report={"critical_issues": 1, "service_reports": [{"code_quality_score": 9}]})

        assert bench.run_metrics(state)["passed"] is False

    def test_a_score_below_the_threshold_fails(self):
        state = _state(qa_report={"critical_issues": 0, "service_reports": [{"code_quality_score": 6}]})

        assert bench.run_metrics(state)["passed"] is False

    def test_a_static_failure_fails_without_consulting_qa(self):
        state = _state(
            static_report={
                "ran": True,
                "passed": False,
                "checks": [{"name": "compile", "service": "api", "passed": False}],
            }
        )

        metrics = bench.run_metrics(state)

        assert metrics["passed"] is False
        assert metrics["static_services_passed"] == 0

    def test_a_run_that_never_reached_qa_fails(self):
        assert bench.run_metrics(_state(qa_report={}))["passed"] is False

    def test_static_pass_is_counted_per_service(self):
        state = _state(
            static_report={
                "ran": True,
                "passed": False,
                "checks": [
                    {"name": "compile", "service": "a", "passed": True},
                    {"name": "compile", "service": "b", "passed": False},
                    {"name": "json", "service": "c", "passed": False, "skipped": True},
                ],
            }
        )

        metrics = bench.run_metrics(state)

        assert (metrics["static_services_passed"], metrics["static_services_checked"]) == (2, 3)


class TestInfrastructureErrors:
    @pytest.mark.parametrize(
        "message",
        [
            "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generate_content_free_tier_requests, limit: 250, PerDay",
            "Error code: 401 - invalid api key",
            "API key not valid. Please pass a valid API key.",
        ],
    )
    def test_quota_and_key_failures_are_infrastructure(self, message: str):
        assert bench._INFRA_ERROR.search(message)

    def test_a_per_minute_rate_limit_is_not(self):
        message = "Error code: 429 - Rate limit reached on tokens per minute (TPM): Limit 8000, Used 5276"

        assert not bench._INFRA_ERROR.search(message)

    def test_infrastructure_rows_are_retried_on_the_next_invocation(self, tmp_path: Path):
        out = tmp_path / "e2e_x.jsonl"
        bench.append_row(out, {"requirement_id": "E1", "repeat": 1, "infra_error": False})
        bench.append_row(out, {"requirement_id": "E1", "repeat": 2, "infra_error": True})

        assert bench.completed_pairs(out) == {("E1", 1)}


class TestRequirements:
    def test_the_benchmark_has_ten_requirements_in_three_tiers(self):
        items = bench.load_requirements(bench.DEFAULT_REQUIREMENTS, None, None)

        assert len(items) == 10
        assert [sum(1 for i in items if i["tier"] == t) for t in ("easy", "medium", "hard")] == [3, 4, 3]
        assert len({i["id"] for i in items}) == 10

    def test_an_unknown_id_is_refused(self):
        with pytest.raises(SystemExit):
            bench.load_requirements(bench.DEFAULT_REQUIREMENTS, ["nope"], None)


class TestSummary:
    def test_rates_follow_table_six(self):
        rows = [
            {
                "tier": "easy",
                "passed": True,
                "developer_attempts": 1,
                "tests_passed": 4,
                "tests_failed": 0,
                "static_services_passed": 1,
                "static_services_checked": 1,
                "qa_min_score": 9,
                "llm_calls": 6,
                "reserved_tokens": 20000,
                "latency_seconds": 600,
                "rate_limited": 0,
            },
            {
                "tier": "easy",
                "passed": True,
                "developer_attempts": 2,
                "tests_passed": 3,
                "tests_failed": 1,
                "static_services_passed": 1,
                "static_services_checked": 1,
                "qa_min_score": 7,
                "llm_calls": 10,
                "reserved_tokens": 40000,
                "latency_seconds": 1200,
                "rate_limited": 2,
            },
            {
                "tier": "easy",
                "passed": False,
                "developer_attempts": 3,
                "tests_passed": 0,
                "tests_failed": 2,
                "static_services_passed": 0,
                "static_services_checked": 2,
                "qa_min_score": 3,
                "llm_calls": 14,
                "reserved_tokens": 60000,
                "latency_seconds": 1800,
                "rate_limited": 1,
            },
        ]

        stats = summary.summarise(rows)

        assert stats["rsr"] == pytest.approx(200 / 3)
        assert stats["first_attempt"] == pytest.approx(100 / 3)
        assert stats["dev_attempts"] == 2
        assert stats["static_pass"] == pytest.approx(100 * (1 + 1 + 0) / 3)
        assert stats["test_pass"] == pytest.approx(100 * 7 / 10)
        # QA score is over successful runs only.
        assert stats["qa_score"] == 8
        assert stats["tokens_k"] == 40
        assert stats["latency_min"] == 20
        assert stats["rate_limited"] == 1

    def test_an_empty_group_prints_dashes(self):
        assert summary.summarise([])["rsr"] is None
        assert summary.fmt(None, "{:.1f}") == "–"

    def test_results_from_the_fake_llm_are_flagged(self, tmp_path: Path):
        path = tmp_path / "e2e_x.jsonl"
        path.write_text(json.dumps({"label": "x", "tier": "easy", "config": {"fake_llm": True}}) + "\n")

        rows = summary.load([path])

        assert "fake LLM" in summary.notes(rows, [])
