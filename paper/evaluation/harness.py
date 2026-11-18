"""Shared helpers: build a workspace from the reference services, run the real gate + test runner."""
import json, os, shutil, sys, tempfile, time
from pathlib import Path

REPO = Path("/home/claude/src/AutoDev")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("LLM_PROVIDER", "google")
os.environ.setdefault("GOOGLE_API_KEY", "offline")

from core.paths import RunWorkspace  # noqa: E402
from verification.runner import LocalSubprocessRunner  # noqa: E402
from verification.static_gate import run_static_gate  # noqa: E402
from verification.test_runner import run_tests  # noqa: E402
from ref_services import SERVICES  # noqa: E402

RUNS = Path(tempfile.mkdtemp(prefix="autodev_eval_"))
RUNNER = LocalSubprocessRunner(install_deps=False, timeout_seconds=120)
_counter = [0]


def build_workspace(overrides=None, only=None):
    """overrides: {(slug, relpath): new_content}"""
    overrides = overrides or {}
    _counter[0] += 1
    ws = RunWorkspace.create(f"r{_counter[0]}", runs_dir=RUNS)
    for slug, svc in SERVICES.items():
        if only and slug not in only:
            continue
        for rel, content in svc["files"].items():
            ws.write_source_file(slug, rel, overrides.get((slug, rel), content))
        for rel, content in svc["tests"].items():
            ws.write_test_file(slug, rel, overrides.get((slug, rel), content))
    return ws


def verify(ws):
    """Verify the way the graph does: static gate first, tests only if it passes.
    Returns dict(stage, detected, static_s, tests_s, static_report, test_report)."""
    t0 = time.perf_counter()
    static = run_static_gate(ws, runner=RUNNER)
    static_s = time.perf_counter() - t0
    out = {"static_s": static_s, "tests_s": None, "static": static.model_dump(), "tests": None}
    if not static.passed:
        out.update(stage="static", detected=True)
        return out
    t1 = time.perf_counter()
    tests = run_tests(ws, runner=RUNNER)
    out["tests_s"] = time.perf_counter() - t1
    out["tests"] = tests.model_dump()
    out.update(stage="tests" if not tests.passed else "none", detected=not tests.passed)
    return out
