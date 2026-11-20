"""Per-attempt analysis of benchmark runs, and the ablation estimates it supports.

Each benchmark label keeps its runs' event logs in
``runs/benchmark/<label>/agentforge.db``. This reads them back attempt by
attempt -- what the Developer regenerated, whether the static gate passed, what
QA said, what the tests did -- and answers "what would have happened without X"
for the mechanisms whose effect can be read off the same runs:

* without the static gate, every attempt that failed it would have gone to QA;
* without test execution, a run would stop at the first attempt QA approved,
  whether or not its tests passed;
* without attribution, every service would be regenerated on every attempt.

These are counterfactual *estimates* from logged runs, not separate runs, and
are reported as such. ::

    python evaluation/analyse_attempts.py deepseek-flash
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(__file__).resolve().parent / "results"

WROTE = re.compile(r"Wrote \d+ file\(s\) across (\d+) service\(s\); (\d+) regenerated, (\d+) preserved")
STATIC_PASS = re.compile(r"^Static gate passed")
STATIC_FAIL = re.compile(r"^Static gate failed with (\d+) problem")
REVIEW = re.compile(r"Review complete: (\d+) bug\(s\), (\d+) critical")
SCORED = re.compile(r"^\s*(\S+) scored ([\d.]+)/10")
TESTS = re.compile(r"^Tests: (.*)$")
REJECTED_RUNG = re.compile(r"Structured strategy '(native|json_schema)' failed .*Error code: 400")
TAU = 7.0


@dataclass
class Attempt:
    regenerated: int = 0
    preserved: int = 0
    static_passed: bool | None = None
    qa_reached: bool = False
    qa_bugs: int = 0
    qa_critical: int = 0
    qa_scores: list[float] = field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    tests_blocked: int = 0
    tests_ran: bool = False

    @property
    def qa_approves(self) -> bool:
        return self.qa_reached and self.qa_critical == 0 and bool(self.qa_scores) and min(self.qa_scores) >= TAU

    @property
    def tests_clean(self) -> bool:
        return self.tests_ran and self.tests_failed == 0 and self.tests_blocked == 0


def parse_tests(summary: str) -> tuple[int, int, int, bool]:
    passed = re.search(r"(\d+) passed", summary)
    failed = re.search(r"(\d+) failed", summary)
    blocked = re.search(r"(\d+) service\(s\) could not run tests", summary)
    ran = "no tests were executed" not in summary and bool(passed or failed)
    return (
        int(passed.group(1)) if passed else 0,
        int(failed.group(1)) if failed else 0,
        int(blocked.group(1)) if blocked else 0,
        ran,
    )


def attempts_of(db: sqlite3.Connection, run_id: str) -> tuple[list[Attempt], int]:
    attempts: list[Attempt] = []
    rejected = 0
    for (message,) in db.execute("select message from run_events where run_id = ? order by id", (run_id,)):
        if REJECTED_RUNG.search(message):
            rejected += 1
        if m := WROTE.search(message):
            attempts.append(Attempt(regenerated=int(m.group(2)), preserved=int(m.group(3))))
            continue
        if not attempts:
            continue
        current = attempts[-1]
        if STATIC_PASS.search(message):
            current.static_passed = True
        elif STATIC_FAIL.search(message):
            current.static_passed = False
        elif m := REVIEW.search(message):
            current.qa_reached, current.qa_bugs, current.qa_critical = True, int(m.group(1)), int(m.group(2))
        elif m := SCORED.search(message):
            current.qa_scores.append(float(m.group(2)))
        elif m := TESTS.search(message):
            p, f, b, ran = parse_tests(m.group(1))
            current.tests_passed, current.tests_failed, current.tests_blocked, current.tests_ran = p, f, b, ran
    return attempts, rejected


def analyse(label: str) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in (RESULTS / f"e2e_{label}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if not r.get("infra_error")]
    db = sqlite3.connect(f"file:{ROOT / 'runs' / 'benchmark' / label / 'agentforge.db'}?mode=ro", uri=True)

    per_run = []
    for row in rows:
        attempts, rejected = attempts_of(db, row["run_id"])
        stages = row.get("by_stage") or {}
        qa = stages.get("qa_agent") or {}
        qa_passes = sum(1 for a in attempts if a.qa_reached)
        qa_calls_per_pass = (qa.get("calls") or 0) / qa_passes if qa_passes else 2.0
        qa_tokens_per_pass = (qa.get("actual_tokens") or 0) / qa_passes if qa_passes else 0.0
        static_failed = sum(1 for a in attempts if a.static_passed is False)

        # Without test execution: the first attempt QA approved ends the run.
        approved_at = next((i for i, a in enumerate(attempts) if a.qa_approves), None)
        accepted_untested = approved_at is not None
        false_accept = accepted_untested and not attempts[approved_at].tests_clean

        per_run.append({
            "requirement_id": row["requirement_id"],
            "tier": row["tier"],
            "passed": bool(row["passed"]),
            "attempts": len(attempts),
            "service_generations": sum(a.regenerated for a in attempts),
            "service_generations_without_attribution": sum(a.regenerated + a.preserved for a in attempts),
            "static_failed_attempts": static_failed,
            "extra_qa_calls_without_static_gate": round(static_failed * qa_calls_per_pass, 1),
            "extra_qa_tokens_without_static_gate": round(static_failed * qa_tokens_per_pass),
            "accepted_without_tests": accepted_untested,
            "false_accept_without_tests": false_accept,
            "rejected_rungs": rejected,
            "tokens": row.get("actual_tokens") or row.get("reserved_tokens") or 0,
            "attempt_log": [asdict(a) for a in attempts],
        })

    def total(key: str) -> float:
        return sum(r[key] for r in per_run)

    n = len(per_run)
    multi = [r for r in per_run if r["service_generations_without_attribution"] > r["attempts"]]
    summary = {
        "label": label,
        "runs": n,
        "rsr": 100 * sum(r["passed"] for r in per_run) / n if n else None,
        "static_failed_attempts": total("static_failed_attempts"),
        "runs_with_a_static_failure": sum(1 for r in per_run if r["static_failed_attempts"]),
        "extra_qa_calls_without_static_gate": total("extra_qa_calls_without_static_gate"),
        "extra_qa_tokens_without_static_gate": total("extra_qa_tokens_without_static_gate"),
        "service_generations": total("service_generations"),
        "service_generations_without_attribution": total("service_generations_without_attribution"),
        "multi_service_runs": len(multi),
        "multi_service_generations": sum(r["service_generations"] for r in multi),
        "multi_service_generations_without_attribution": sum(
            r["service_generations_without_attribution"] for r in multi
        ),
        "accepted_without_tests": sum(r["accepted_without_tests"] for r in per_run),
        "false_accepts_without_tests": sum(r["false_accept_without_tests"] for r in per_run),
        "rsr_claimed_without_tests": 100 * sum(r["accepted_without_tests"] for r in per_run) / n if n else None,
        "rsr_true_without_tests": (
            100 * sum(r["accepted_without_tests"] and not r["false_accept_without_tests"] for r in per_run) / n
            if n else None
        ),
        "runs_with_rejected_rungs": sum(1 for r in per_run if r["rejected_rungs"]),
        "mean_tokens": mean(r["tokens"] for r in per_run) if per_run else None,
    }
    return {"summary": summary, "runs": per_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", nargs="+")
    args = parser.parse_args(argv)
    for label in args.labels:
        result = analyse(label)
        out = RESULTS / f"attempts_{label}.json"
        out.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result["summary"], indent=1))
        print(f"-> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
