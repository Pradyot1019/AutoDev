"""Single-prompt baseline for the end-to-end suite (paper Table IX).

The same model AutoDev uses is asked, in one call, for a whole project: every
service's source, its requirements.txt and its pytest tests. No PRD, no
architecture, no review, no retry. The answer is written into a run workspace
and judged by AutoDev's own verification -- the static gate and the test runner,
which also adds the mandatory "the application imports" test -- so both systems
are measured by the same instruments.

A baseline run is *verified* when the static gate passes, the tests ran, and
none failed or were blocked. That is AutoDev's Eq. (1) without the QA terms,
because the baseline has no reviewer; the summary reports both criteria.

    python evaluation/run_single_prompt_baseline.py --label deepseek-flash
    python evaluation/run_single_prompt_baseline.py --label smoke --only E1-todo --repeats 1

Resumable like run_e2e_benchmark.py: finished (requirement, repeat) pairs are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"

PROMPT = """You are a senior Python engineer. Build the complete project below in ONE answer.

Requirement:
{requirement}

Deliver, for every service the requirement needs (one service unless it asks for several):
- every source file, with the FastAPI application importable as `app` from app/main.py;
- a requirements.txt listing every third-party package the code imports;
- pytest tests that exercise every endpoint with fastapi.testclient.TestClient,
  including the error cases the requirement names. Tests must create the data they need.

Paths are relative to the service's own directory (for example "app/main.py",
"requirements.txt", "tests/test_api.py"). Use SQLite for any database, Pydantic v2
and SQLAlchemy 2.0. The code must run as written: no placeholders, no TODOs.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--requirements", type=Path, default=HERE / "benchmark_requirements.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--max-output", type=int, default=32_000,
        help="Output ceiling for the one call; a whole project is far larger than one service.",
    )
    return parser


def results_path(label: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR / f"baseline_single-prompt_{label}.jsonl"


def done_pairs(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    pairs = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not row.get("infra_error"):
                pairs.add((row["requirement_id"], int(row["repeat"])))
    return pairs


async def run_one(item: dict[str, str], repeat: int, label: str) -> dict[str, Any]:
    from pydantic import BaseModel, Field

    from core.config import Purpose, get_settings
    from core.paths import RunWorkspace, new_run_id, slugify
    from llm.accounting import recording
    from llm.registry import get_structured_llm
    from utils.content_repair import repair_escaped_newlines
    from verification.runner import LocalSubprocessRunner
    from verification.static_gate import run_static_gate
    from verification.test_runner import run_tests

    class ProjectFile(BaseModel):
        service: str = Field(description="Service this file belongs to, e.g. 'api'")
        path: str = Field(description="Path relative to the service directory, e.g. 'app/main.py'")
        content: str = Field(description="The complete file content")

    class Project(BaseModel):
        services: list[str] = Field(description="Service names")
        files: list[ProjectFile] = Field(description="Every source file and requirements.txt")
        tests: list[ProjectFile] = Field(description="pytest test files")

    settings = get_settings()
    workspace = RunWorkspace.create(new_run_id(), runs_dir=Path(settings.runs_dir) / "baseline" / label)
    started = time.monotonic()
    row: dict[str, Any] = {
        "requirement_id": item["id"], "tier": item["tier"], "repeat": repeat, "label": label,
        "workspace": str(workspace.root), "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    with recording(workspace.root.name, "baseline") as ledger:
        try:
            project = await get_structured_llm(Project, Purpose.HEAVY).ainvoke(
                PROMPT.format(requirement=item["requirement"])
            )
        except Exception as exc:  # recorded, not raised: one bad call is one failed run
            row.update(error=str(exc)[:2000], generated=False)
            project = None
        cost = ledger.totals()

    row.update(
        llm_calls=cost["calls"], actual_tokens=cost["actual_tokens"], input_tokens=cost["input_tokens"],
        output_tokens=cost["output_tokens"], estimated_cost_usd=cost["estimated_cost"],
        model_seconds=cost["seconds"],
    )
    message = str(row.get("error", ""))
    row["infra_error"] = any(s in message.lower() for s in ("insufficient balance", "error code: 402", "invalid api key"))

    if project is not None:
        row["generated"] = True
        for kind, entries in (("source", project.files), ("tests", project.tests)):
            for entry in entries:
                service = slugify(entry.service) or "app"
                rel = entry.path.lstrip("/\\")
                if kind == "tests" and rel.startswith(("tests/", "tests\\")):
                    rel = rel[len("tests/"):]  # the runner keeps tests in their own tree
                content = repair_escaped_newlines(rel, entry.content)
                try:
                    if kind == "source":
                        workspace.write_source_file(service, rel, content)
                    else:
                        workspace.write_test_file(service, rel, content)
                except Exception:  # an unsafe path is the model's failure, not the harness's
                    row.setdefault("rejected_paths", []).append(entry.path)
        row["services"] = sorted({slugify(f.service) or "app" for f in project.files})
        row["files"] = len(project.files)
        row["test_files"] = len(project.tests)

        static = await asyncio.to_thread(run_static_gate, workspace, None, LocalSubprocessRunner(install_deps=False))
        tests = await asyncio.to_thread(run_tests, workspace, None, LocalSubprocessRunner())
        services = tests.services
        passed = sum(s.passed for s in services)
        failed = sum(s.failed + s.errors for s in services)
        blocked = sum(1 for s in services if s.error)
        row.update(
            static_passed=bool(static.passed),
            static_failures=len(static.failures),
            tests_ran=bool(tests.ran),
            tests_passed=passed,
            tests_failed=failed,
            services_blocked=blocked,
        )
        row["verified"] = bool(static.passed) and bool(tests.ran) and failed == 0 and blocked == 0
    else:
        row.update(verified=False, static_passed=False, tests_ran=False, tests_passed=0, tests_failed=0)

    row["latency_seconds"] = round(time.monotonic() - started, 1)
    return row


async def main_async(args: argparse.Namespace) -> int:
    from core.logging import configure_logging

    configure_logging()
    data = json.loads(args.requirements.read_text(encoding="utf-8"))["requirements"]
    items = [i for i in data if not args.only or i["id"] in args.only]
    out = results_path(args.label)
    done = done_pairs(out)
    todo = [(i, r) for r in range(1, args.repeats + 1) for i in items if (i["id"], r) not in done]
    print(f"Baseline '{args.label}': {len(todo)} run(s) to do -> {out}")

    gate = asyncio.Semaphore(max(1, args.concurrency))

    async def one(item: dict[str, str], repeat: int) -> None:
        async with gate:
            row = await run_one(item, repeat, args.label)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        cost = row.get("estimated_cost_usd")
        print(
            f"  {item['id']} r{repeat}: {'VERIFIED' if row['verified'] else 'not verified'}  "
            f"static={row.get('static_passed')}  tests={row.get('tests_passed')}/"
            f"{(row.get('tests_passed') or 0) + (row.get('tests_failed') or 0)}  "
            f"cost={'?' if cost is None else f'${cost:.4f}'}  {row['latency_seconds'] / 60:.1f} min"
        )

    await asyncio.gather(*(one(i, r) for i, r in todo))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ["MAX_OUTPUT_HEAVY"] = str(args.max_output)
    os.environ.setdefault("RUNS_DIR", str(ROOT / "runs" / "benchmark"))
    from core.config import reset_settings_cache

    reset_settings_cache()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
