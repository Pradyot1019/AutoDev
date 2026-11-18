"""Turn end-to-end benchmark results into Table VIII.

    python evaluation/summarise_e2e.py                       # every results/e2e_*.jsonl
    python evaluation/summarise_e2e.py results/e2e_gemini-2.5-flash.jsonl --latex

Metrics follow Table VI of the paper:

* RSR             runs that pass (static gate passed, Eq. (1) false) / runs
* 1st-attempt     runs that pass with one developer attempt / runs
* Dev. attempts   mean developer attempts per run
* Static pass     mean over runs of (services passing the static gate / services checked)
* Test pass       generated tests passed / generated tests executed, pooled over runs
* QA score        mean of min_i s_i over *successful* runs
* LLM calls, Tokens (k), Latency (min), 429s: means per run

Tokens are the tokens *reserved* against the provider's per-minute window
(prompt + completion ceiling), the only figure available for every call; say so
in the caption. Runs flagged ``infra_error`` (daily quota, rejected key) are
excluded and counted separately.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

HERE = Path(__file__).resolve().parent
TIERS = ("easy", "medium", "hard")


def load(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _pct(numerator: float, denominator: float) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    passed = [r for r in rows if r.get("passed")]
    static_rates = [
        r["static_services_passed"] / r["static_services_checked"]
        for r in rows
        if r.get("static_services_checked")
    ]
    tests_passed = sum(int(r.get("tests_passed") or 0) for r in rows)
    tests_run = tests_passed + sum(int(r.get("tests_failed") or 0) for r in rows)
    qa = [r["qa_min_score"] for r in passed if r.get("qa_min_score") is not None]

    return {
        "runs": n,
        "rsr": _pct(len(passed), n),
        "first_attempt": _pct(sum(1 for r in passed if r.get("developer_attempts") == 1), n),
        "dev_attempts": mean(r.get("developer_attempts") or 0 for r in rows) if rows else None,
        "static_pass": 100.0 * mean(static_rates) if static_rates else None,
        "test_pass": _pct(tests_passed, tests_run),
        "qa_score": mean(qa) if qa else None,
        "llm_calls": mean(r.get("llm_calls") or 0 for r in rows) if rows else None,
        "tokens_k": mean((r.get("reserved_tokens") or 0) / 1000 for r in rows) if rows else None,
        "latency_min": mean((r.get("latency_seconds") or 0) / 60 for r in rows) if rows else None,
        "rate_limited": mean(r.get("rate_limited") or 0 for r in rows) if rows else None,
        "passed_without_tests": sum(
            1 for r in passed if not (r.get("tests_passed") or r.get("tests_failed"))
        ),
        "escalated_runs": sum(1 for r in rows if r.get("services_escalated")),
    }


COLUMNS = [
    ("rsr", "RSR (%)", "{:.1f}"),
    ("first_attempt", "1st-attempt (%)", "{:.1f}"),
    ("dev_attempts", "Dev. attempts", "{:.2f}"),
    ("static_pass", "Static pass (%)", "{:.1f}"),
    ("test_pass", "Test pass (%)", "{:.1f}"),
    ("qa_score", "QA score", "{:.1f}"),
    ("llm_calls", "LLM calls", "{:.1f}"),
    ("tokens_k", "Tokens (k)", "{:.1f}"),
    ("latency_min", "Latency (min)", "{:.1f}"),
]
EXTRA = [("rate_limited", "429s/run", "{:.2f}"), ("runs", "n", "{}")]


def fmt(value: Any, pattern: str) -> str:
    return "–" if value is None else pattern.format(value)


def table(rows: list[dict[str, Any]], latex: bool) -> str:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[row.get("label", "?")].append(row)

    lines: list[str] = []
    columns = COLUMNS if latex else COLUMNS + EXTRA
    if not latex:
        lines.append("| Model | Tier | " + " | ".join(h for _, h, _ in columns) + " |")
        lines.append("|---|---|" + "---|" * len(columns))

    for label, label_rows in by_label.items():
        groups = [(tier.capitalize(), [r for r in label_rows if r.get("tier") == tier]) for tier in TIERS]
        groups.append(("All", label_rows))
        for i, (tier, group) in enumerate(groups):
            stats = summarise(group)
            cells = [fmt(stats[key], pattern) for key, _, pattern in columns]
            model = label if i == 0 else ""
            if latex:
                lines.append(f"{model} & {tier} & " + " & ".join(cells) + r" \\")
            else:
                lines.append(f"| {model} | {tier} | " + " | ".join(cells) + " |")
        if latex:
            lines.append(r"\midrule")
    return "\n".join(lines)


def notes(rows: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> str:
    stats = summarise(rows)
    out = [
        f"Runs counted: {stats['runs']}; excluded for infrastructure errors: {len(excluded)}.",
        f"Passing runs with no generated tests executed: {stats['passed_without_tests']} "
        "(they satisfy Eq. (1) vacuously; report or exclude them).",
        f"Runs in which a service was escalated a tier: {stats['escalated_runs']}.",
    ]
    commits = sorted({(r.get("config") or {}).get("git_commit", "?") for r in rows})
    if len(commits) > 1:
        out.append(f"WARNING: results come from more than one commit: {', '.join(commits)}.")
    if any((r.get("config") or {}).get("fake_llm") for r in rows):
        out.append("WARNING: some rows were produced by the fake LLM and must not be reported.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Summarise end-to-end benchmark results.")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--latex", action="store_true", help="Print LaTeX table rows instead of Markdown.")
    args = parser.parse_args(argv)

    files = args.files or sorted((HERE / "results").glob("e2e_*.jsonl"))
    if not files:
        print("No results found in evaluation/results/.", file=sys.stderr)
        return 1

    rows = load(files)
    counted = [r for r in rows if not r.get("infra_error")]
    excluded = [r for r in rows if r.get("infra_error")]

    print(table(counted, args.latex))
    print()
    print(notes(counted, excluded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
