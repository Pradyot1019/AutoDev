"""End-to-end benchmark with live models (paper Section VI-F, Table VIII).

Runs every requirement in ``benchmark_requirements.json`` through the same
:class:`~server.service.RunService` the CLI and console use, with both review
gates auto-approved, and appends one JSON line per run to
``evaluation/results/e2e_<label>.jsonl``. ``summarise_e2e.py`` turns those lines
into the table.

    python evaluation/run_e2e_benchmark.py --label gemini-2.5-flash
    python evaluation/run_e2e_benchmark.py --label llama-groq --set LLM_PROVIDER=groq
    python evaluation/run_e2e_benchmark.py --label smoke --only E1-todo --repeats 1
    python evaluation/run_e2e_benchmark.py --label dry --fake      # offline, no API calls

It is resumable. A (requirement, repeat) pair that already has a result line is
skipped, so a run stopped by a daily quota, a crash or Ctrl+C carries on where it
left off. Runs that failed for an infrastructure reason (a daily quota, a rejected
key) are recorded with ``infra_error: true``, excluded from the table and retried
on the next invocation; the benchmark stops at the first one rather than burning
through the remaining requirements against a provider that will refuse them all.

Pass/fail is decided here, not taken from the run status. When the developer
retry budget runs out the graph ends "with the current result", so a run can be
``completed`` with tests still failing. A run passes only when the static gate
passed and Eq. (1) is false, which is exactly the graph's own rework test
(:func:`graph.build_graph._needs_rework`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
DEFAULT_REQUIREMENTS = HERE / "benchmark_requirements.json"
RESULTS_DIR = HERE / "results"

# A run that failed for one of these reasons says nothing about AutoDev: the
# provider would have refused any request. Per-minute 429s are deliberately not
# here -- surviving those is what the token budget is being measured on.
_INFRA_ERROR = re.compile(
    r"per.?day|perday|daily|quota exceeded for metric.*day|"
    r"api key not valid|invalid api key|invalid_api_key|permission denied|"
    r"error code: 40[123]\b|insufficient_quota|insufficient balance|billing",
    re.IGNORECASE,
)


# ── Arguments ────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--label",
        required=True,
        help="Names the configuration under test, e.g. gemini-2.5-flash. Results go to results/e2e_<label>.jsonl.",
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--repeats", type=int, default=3, help="Runs per requirement (default 3).")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Runs in flight at once (default 1). Latency is wall-clock per run, so say which was used.",
    )
    parser.add_argument("--only", nargs="*", default=None, help="Requirement ids to run.")
    parser.add_argument("--tier", choices=("easy", "medium", "hard"), help="Run one tier only.")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Environment override for this benchmark, e.g. LLM_PROVIDER=groq. Repeatable.",
    )
    parser.add_argument(
        "--run-timeout",
        type=float,
        default=3600.0,
        help="Seconds before a single run is cancelled and recorded as timed out (default 3600).",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Drive the pipeline with the test suite's fake LLM: no network, for checking the harness.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Do not stop at an infrastructure error (daily quota, rejected key).",
    )
    return parser


def apply_environment(label: str, overrides: list[str], fake: bool) -> None:
    """Point storage at a per-label location and apply ``--set`` overrides.

    Must run before anything reads settings, which are cached on first use.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)
    bench = ROOT / "runs" / "benchmark" / safe
    os.environ.setdefault("RUNS_DIR", str(bench / "runs"))
    os.environ.setdefault("DATABASE_PATH", str(bench / "agentforge.db"))
    os.environ.setdefault("CHECKPOINT_PATH", str(bench / "checkpoints.db"))

    if fake:
        # No real key may be used, and nothing should wait on a real rate limit.
        os.environ["AGENTFORGE_ENV_FILE"] = str(bench / "absent.env")
        os.environ["GOOGLE_API_KEY"] = "fake-key-not-real"
        os.environ["LLM_TOKENS_PER_MINUTE"] = "100000000"

    for item in overrides:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--set expects KEY=VALUE, got {item!r}")
        os.environ[key.strip()] = value

    from core.config import reset_settings_cache

    reset_settings_cache()


def is_infra_error(error: str) -> bool:
    """Whether the provider, not AutoDev, ended the run.

    Only the provider's own message is searched. A parser error quotes the
    model's output, and generated text about "daily" click counts once matched
    the daily-quota pattern and stopped a benchmark.
    """
    provider_part = error.split("Invalid json output", 1)[0]
    return bool(provider_part) and bool(_INFRA_ERROR.search(provider_part))

# ── Requirements and results ─────────────────────────────────────


def load_requirements(path: Path, only: list[str] | None, tier: str | None) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["requirements"]
    known = {item["id"] for item in items}
    for wanted in only or []:
        if wanted not in known:
            raise SystemExit(f"Unknown requirement id {wanted!r}. Known: {', '.join(sorted(known))}")
    return [item for item in items if (not only or item["id"] in only) and (not tier or item["tier"] == tier)]


def results_path(label: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", label)
    return RESULTS_DIR / f"e2e_{safe}.jsonl"


def completed_pairs(path: Path) -> set[tuple[str, int]]:
    """(requirement id, repeat) pairs that already have a usable result."""
    done: set[tuple[str, int]] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("infra_error"):
            done.add((row["requirement_id"], int(row["repeat"])))
    return done


def append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Configuration snapshot ───────────────────────────────────────


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return f"{out}-dirty" if dirty else out
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def config_snapshot(fake: bool) -> dict[str, Any]:
    """Every setting that changes what a run does, so a table can name its configuration."""
    from core.config import Purpose, get_settings
    from llm.registry import model_name_for

    settings = get_settings()
    provider = settings.llm_provider
    models = {}
    for purpose in Purpose:
        try:
            models[purpose.value] = model_name_for(provider, purpose, settings)
        except Exception as exc:  # a purpose with no model configured
            models[purpose.value] = f"unavailable: {exc}"

    return {
        "fake_llm": fake,
        "git_commit": git_commit(),
        "provider": provider.value,
        "fallback_providers": [p.value for p in settings.llm_fallback_providers],
        # Set when the openai provider points at DeepSeek, Qwen, Kimi or OpenRouter.
        "openai_base_url": settings.openai_base_url,
        "google_thinking_budget": settings.google_thinking_budget,
        "models": models,
        "temperature": settings.llm_temperature,
        "tokens_per_minute": settings.llm_tokens_per_minute,
        "max_developer_retries": settings.max_developer_retries,
        "min_quality_score": settings.min_quality_score,
        "routing_enabled": settings.routing_enabled,
        "adaptive_ceilings": settings.adaptive_ceilings,
        "max_model_escalations": settings.max_model_escalations,
        "verify_install_deps": settings.verify_install_deps,
    }


# ── Metrics from one finished run ────────────────────────────────


def static_service_pass(static_report: dict[str, Any]) -> tuple[int, int] | None:
    """(services passing, services checked) at the end of the run, or None if it never ran."""
    if not static_report.get("ran"):
        return None
    by_service: dict[str, bool] = {}
    for check in static_report.get("checks") or []:
        ok = bool(check.get("passed", True)) or bool(check.get("skipped"))
        service = check.get("service") or "?"
        by_service[service] = by_service.get(service, True) and ok
    return sum(by_service.values()), len(by_service)


def run_metrics(state: dict[str, Any]) -> dict[str, Any]:
    from graph.build_graph import _needs_rework

    static_report = state.get("static_report") or {}
    verification = state.get("verification_report") or {}
    qa_report = state.get("qa_report") or {}
    cost = state.get("cost_report") or {}

    services = verification.get("services") or []
    tests_passed = sum(int(s.get("passed") or 0) for s in services)
    tests_failed = sum(int(s.get("failed") or 0) + int(s.get("errors") or 0) for s in services)
    blocked = sum(1 for s in services if s.get("error"))

    scores = [
        float(r["code_quality_score"])
        for r in qa_report.get("service_reports") or []
        if r.get("code_quality_score") is not None
    ]

    static = static_service_pass(static_report)
    static_ok = bool(static_report.get("ran")) and bool(static_report.get("passed"))
    reached_tests = bool(verification.get("ran")) or bool(services)
    rework_reason = _needs_rework(state) if static_ok else "static gate failed"

    return {
        # Eq. (1) false, with the static gate passed and QA actually reached.
        "passed": static_ok and bool(qa_report) and not rework_reason,
        "rework_reason": rework_reason,
        "developer_attempts": int(state.get("retry_count") or 0),
        "static_ran": bool(static_report.get("ran")),
        "static_passed": static_ok,
        "static_services_passed": static[0] if static else None,
        "static_services_checked": static[1] if static else None,
        "tests_ran": reached_tests,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "services_blocked": blocked,
        "qa_min_score": min(scores) if scores else None,
        "qa_mean_score": round(sum(scores) / len(scores), 2) if scores else None,
        "qa_critical_issues": int(qa_report.get("critical_issues") or 0) if qa_report else None,
        "services_generated": len(state.get("generated_services") or []),
        "services_escalated": sum(1 for n in (state.get("service_escalations") or {}).values() if n),
        "llm_calls": int(cost.get("calls") or 0),
        "reserved_tokens": int(cost.get("reserved_tokens") or 0),
        "actual_tokens": cost.get("actual_tokens"),
        "input_tokens": cost.get("input_tokens"),
        "output_tokens": cost.get("output_tokens"),
        "calls_with_usage": int(cost.get("calls_with_usage") or 0),
        "estimated_cost_usd": cost.get("estimated_cost"),
        "rate_limited": int(cost.get("rate_limited") or 0),
        "llm_outcomes": cost.get("outcomes") or {},
        "model_seconds": float(cost.get("seconds") or 0.0),
        "by_model": {
            name: {"calls": totals.get("calls"), "reserved_tokens": totals.get("reserved_tokens")}
            for name, totals in (cost.get("by_model") or {}).items()
        },
        # Per stage, so ablation estimates (QA calls spent on code that does not
        # build, Developer calls without attribution) can be read off each run.
        "by_stage": {
            name: {
                "calls": totals.get("calls"),
                "actual_tokens": totals.get("actual_tokens"),
                "outcomes": totals.get("outcomes"),
            }
            for name, totals in (cost.get("by_stage") or {}).items()
        },
    }


# ── Driving one run ──────────────────────────────────────────────


async def drive(service: Any, run_id: str) -> Any:
    """Start one run and auto-approve both review gates until it reaches a terminal state."""
    await service.begin(run_id)
    while True:
        record = await service.wait(run_id)
        if record.status.is_terminal or not record.status.is_awaiting_review:
            return record
        await service.approve(run_id)


async def run_one(service: Any, item: dict[str, str], repeat: int, timeout: float) -> dict[str, Any]:
    from server.models import RunStatus

    # Created up front so its id is known even if the run has to be cancelled:
    # the service renames a run after its PRD, so the name cannot find it later.
    record = await service.create(item["requirement"], f"bench-{item['id']}-r{repeat}")
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    timed_out = False

    try:
        record = await asyncio.wait_for(drive(service, record.id), timeout=timeout)
    except TimeoutError:
        timed_out = True
        if service.is_running(record.id):
            await service.cancel(record.id)
        record = await service.get(record.id)

    latency = time.monotonic() - started
    state = await service.get_graph_state(record.id)
    error = record.error or str(state.get("error") or "")

    row: dict[str, Any] = {
        "requirement_id": item["id"],
        "tier": item["tier"],
        "repeat": repeat,
        "run_id": record.id,
        "status": "timeout" if timed_out else record.status.value,
        "error": error[:2000],
        "infra_error": is_infra_error(error),
        "started_at": started_at,
        "latency_seconds": round(latency, 1),
        "workspace": record.workspace,
    }
    row.update(run_metrics(state))
    if timed_out or record.status is not RunStatus.COMPLETED:
        row["passed"] = False
    return row


async def benchmark(args: argparse.Namespace) -> int:
    from core.logging import configure_logging
    from graph.checkpoint import open_checkpointer
    from server.db import open_database
    from server.service import RunService

    configure_logging()

    items = load_requirements(args.requirements, args.only, args.tier)
    out = results_path(args.label)
    done = completed_pairs(out)
    todo = [(item, r) for r in range(1, args.repeats + 1) for item in items if (item["id"], r) not in done]

    snapshot = config_snapshot(args.fake)
    print(f"Benchmark '{args.label}': {len(todo)} run(s) to do, {len(done)} already recorded -> {out}")
    print(json.dumps(snapshot, indent=2))

    if not todo:
        return 0

    async with open_database() as database, open_checkpointer() as checkpointer:
        service = await RunService(database, checkpointer).start()
        # Runs are independent (own workspace, own ledger, own graph thread), so
        # several can share the service. Rows are appended from this one event
        # loop, so the results file never sees two writers at once.
        gate = asyncio.Semaphore(max(1, args.concurrency))
        stop = asyncio.Event()

        async def one(index: int, item: dict[str, str], repeat: int) -> None:
            async with gate:
                if stop.is_set():
                    return
                print(f"\n[{index}/{len(todo)}] {item['id']} ({item['tier']}) repeat {repeat} started")
                row = await run_one(service, item, repeat, args.run_timeout)
            row["label"] = args.label
            row["config"] = snapshot
            row["concurrency"] = args.concurrency
            append_row(out, row)

            verdict = "PASS" if row["passed"] else "FAIL"
            cost = row.get("estimated_cost_usd")
            print(
                f"    [{index}] {item['id']} r{repeat}: {verdict}  status={row['status']}  "
                f"attempts={row['developer_attempts']}  "
                f"tests={row['tests_passed']}/{row['tests_passed'] + row['tests_failed']}  "
                f"calls={row['llm_calls']}  429s={row['rate_limited']}  "
                f"cost={'?' if cost is None else f'${cost:.4f}'}  "
                f"{row['latency_seconds'] / 60:.1f} min"
            )
            if row["infra_error"]:
                print(f"    Infrastructure error, not counted: {row['error'][:300]}")
                if not args.keep_going:
                    stop.set()

        try:
            await asyncio.gather(
                *(one(index, item, repeat) for index, (item, repeat) in enumerate(todo, start=1))
            )
        finally:
            await service.stop()
    if stop.is_set():
        print("Stopped on an infrastructure error. Fix the provider problem and re-run; finished runs are kept.")
        return 3
    return 0


def install_fake_llm() -> Any:
    """The test suite's canned agents, so the harness can be checked without a provider."""
    import pytest

    from schema.architect_schema import ArchitectSchema
    from schema.developer_schema import DeveloperSchema
    from schema.product_manager_schema import ManagerSchema
    from schema.qa_schema import QASchema
    from tests import fakes

    patcher = pytest.MonkeyPatch()
    stub = fakes.LLMStub()
    stub.set(ManagerSchema, fakes.build_prd())
    stub.set(ArchitectSchema, fakes.build_architecture())
    stub.set(DeveloperSchema, fakes.build_developer_output())
    stub.set(QASchema, fakes.build_qa_report())
    stub.install(patcher)
    return patcher


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    apply_environment(args.label, args.overrides, args.fake)
    if args.fake:
        install_fake_llm()
    try:
        return asyncio.run(benchmark(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Finished runs are saved; re-run the same command to continue.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
