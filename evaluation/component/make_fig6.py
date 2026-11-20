"""Fig. 6: the automated test suite by subsystem, from a live `pytest --collect-only`.

    uv run --no-project --with matplotlib python evaluation/component/make_fig6.py

Needs the project's own environment for collection (it runs .venv's pytest) and
matplotlib for drawing, which the project does not depend on.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIGS = ROOT / "paper" / "figs"

SUBSYSTEMS = {
    "LLM layer": [
        "escalation", "routing", "accounting", "errors", "account_pool", "config_and_registry",
        "adaptive_ceilings", "budget", "structured", "output_ceilings", "rung_memory", "pricing",
    ],
    "Verification & repair": [
        "attribution", "surgical_regeneration", "verification", "service_evidence", "import_check",
        "content_repair",
    ],
    "Agents & orchestration": [
        "graph", "contracts", "agents", "prompts", "projections", "developer_chunking", "schema_enums",
        "developer_instructions", "developer_parallel",
    ],
    "Service & storage": ["service", "api", "db", "paths"],
    "Documents & tooling": ["pdf_export", "pdf_documents", "benchmark_harness", "fakes"],
}


def collect() -> Counter[str]:
    python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    out = subprocess.run(
        [str(python), "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    counts: Counter[str] = Counter()
    for line in out.splitlines():
        if "::" in line:
            module = Path(line.split("::", 1)[0]).stem.removeprefix("test_")
            counts[module] += 1
    return counts


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts = collect()
    lookup = {module: group for group, modules in SUBSYSTEMS.items() for module in modules}
    unmapped = sorted(set(counts) - set(lookup))
    if unmapped:
        raise SystemExit(f"Map these test modules to a subsystem first: {', '.join(unmapped)}")
    groups: Counter[str] = Counter()
    for module, n in counts.items():
        groups[lookup[module]] += n
    total = sum(groups.values())

    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
        "font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
    })
    names = sorted(groups, key=groups.get)
    fig, ax = plt.subplots(figsize=(3.4, 1.9))
    bars = ax.barh(names, [groups[n] for n in names], color="#00487F")
    for bar, name in zip(bars, names, strict=True):
        ax.text(bar.get_width() + 6, bar.get_y() + bar.get_height() / 2, str(groups[name]), va="center")
    ax.set_xlabel(f"Tests ({total:,} in {len(counts)} modules)")
    ax.set_xlim(0, max(groups.values()) * 1.15)
    fig.tight_layout()
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / "fig6_test_distribution.png", dpi=300)
    print(json.dumps({"total": total, "modules": len(counts), "by_subsystem": dict(groups)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
