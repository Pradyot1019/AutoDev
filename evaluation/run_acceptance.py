"""Run the held-out acceptance tests against every generated project.

``evaluation/acceptance/test_<id>.py`` holds tests written from each easy and
medium requirement's text alone, before any project was generated and without
looking at either system's output. They are the same for AutoDev and for the
single-prompt baseline, so -- unlike each system's own tests -- they can compare
the two. Hard requirements are left out: their services call each other over
HTTP, which an in-process acceptance test cannot drive.

Each project is tested in its own environment (the one verification built, or a
fresh one), with the same harness conftest the pipeline uses. A multi-service
project is scored by its best-scoring service, since a single-service
requirement's endpoints should all live in one of them. ::

    python evaluation/run_acceptance.py --e2e deepseek-flash --baseline deepseek-flash
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
SUITES = HERE / "acceptance"
RESULTS = HERE / "results"


def suite_for(requirement_id: str) -> Path | None:
    found = sorted(SUITES.glob(f"test_{requirement_id.split('-')[0]}_*.py"))
    return found[0] if found else None


def score_service(workspace: Any, source_dir: Path, suite: Path) -> dict[str, Any]:
    from schema.verification_schema import ServiceTestResult
    from verification.runner import LocalSubprocessRunner
    from verification.test_runner import (
        _fill_from_junit,
        _requirements_for,
        _scaffold_conftest,
        _write_pytest_ini,
    )

    runner = LocalSubprocessRunner()
    tests_dir = workspace.meta / "acceptance" / source_dir.name
    shutil.rmtree(tests_dir, ignore_errors=True)
    tests_dir.mkdir(parents=True)
    shutil.copy(SUITES / "_helpers.py", tests_dir / "_helpers.py")
    shutil.copy(suite, tests_dir / suite.name)
    _scaffold_conftest(tests_dir)
    config = _write_pytest_ini(workspace)

    prepared = runner.prepare_python(source_dir, _requirements_for(workspace, source_dir))
    if not prepared.ok:
        return {"service": source_dir.name, "passed": 0, "failed": 0, "error": f"install failed: {prepared.error}"}

    # A fresh database per acceptance run, so earlier runs' rows cannot interfere.
    for stale in source_dir.glob("*.db"):
        stale.unlink(missing_ok=True)

    junit = tests_dir / "junit.xml"
    command = runner.exec(
        [prepared.python, "-m", "pytest", str(tests_dir), "-c", str(config), "--rootdir", str(source_dir),
         f"--junitxml={junit}", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=source_dir,
        env={"PYTHONPATH": str(source_dir), "AGENTFORGE_SERVICE_ROOT": str(source_dir)},
    )
    result = ServiceTestResult(service=source_dir.name)
    if junit.exists():
        _fill_from_junit(result, junit)
    return {
        "service": source_dir.name,
        "passed": result.passed,
        "failed": result.failed + result.errors,
        "failures": [f.test for f in result.failures],
        "error": "" if junit.exists() else f"pytest did not run: {command.summary()}",
    }


def score_project(row: dict[str, Any], system: str) -> dict[str, Any] | None:
    from core.paths import RunWorkspace

    suite = suite_for(row["requirement_id"])
    if suite is None or not row.get("workspace"):
        return None
    root = Path(row["workspace"])
    workspace = RunWorkspace(run_id=root.name, root=root)
    services = [d for d in sorted(workspace.source.iterdir()) if d.is_dir()] if workspace.source.exists() else []
    scored = [score_service(workspace, d, suite) for d in services]
    best = max(scored, key=lambda s: (s["passed"], -s["failed"]), default=None)
    total = best["passed"] + best["failed"] if best else 0
    return {
        "system": system,
        "requirement_id": row["requirement_id"],
        "tier": row["tier"],
        "repeat": row["repeat"],
        "self_verified": bool(row.get("passed") if system == "autodev" else row.get("verified")),
        "services": len(services),
        "best_service": best["service"] if best else None,
        "acceptance_passed": best["passed"] if best else 0,
        "acceptance_total": total,
        "acceptance_rate": (best["passed"] / total) if total else 0.0,
        "acceptance_all": bool(total) and best["failed"] == 0,
        "failures": best.get("failures", []) if best else [],
        "error": best.get("error", "no source generated") if best else "no source generated",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--e2e", help="AutoDev benchmark label")
    parser.add_argument("--baseline", help="Single-prompt baseline label")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)

    jobs: list[tuple[dict[str, Any], str]] = []
    for label, system, name in ((args.e2e, "autodev", "e2e_{}.jsonl"), (args.baseline, "single-prompt",
                                "baseline_single-prompt_{}.jsonl")):
        if not label:
            continue
        for line in (RESULTS / name.format(label)).read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else None
            if row and not row.get("infra_error") and row.get("tier") in ("easy", "medium"):
                jobs.append((row, system))

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = [r for r in pool.map(lambda job: score_project(*job), jobs) if r]

    out = RESULTS / f"acceptance_{args.e2e or 'none'}_{args.baseline or 'none'}.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    for system in ("autodev", "single-prompt"):
        group = [r for r in results if r["system"] == system]
        if group:
            passed = sum(r["acceptance_passed"] for r in group)
            total = sum(r["acceptance_total"] for r in group)
            print(f"{system}: {len(group)} projects, all-pass {sum(r['acceptance_all'] for r in group)}, "
                  f"tests {passed}/{total}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
