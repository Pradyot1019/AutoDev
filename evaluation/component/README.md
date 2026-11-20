# Component experiments (paper RQ1–RQ3)

Offline experiments that drive AutoDev's real verification and LLM-layer code with
controlled inputs. No API key and no network are needed; every run is seeded (42).

| Script | Paper | What it measures | Output |
|---|---|---|---|
| `run_component_eval.py` | RQ1, RQ2 | Fault detection on 141 injected mutants; attribution precision/recall and Developer calls saved over 40 multi-service trials | `results_rq1_rq2.json` |
| `run_robustness_eval.py` | RQ3 | Structured-output recovery (11 reply shapes), error disposition (16 cases), token budget under a simulated 8,000 TPM provider | `results_rq3.json` |
| `make_figs.py` | Figs 4–5 | Draws the two result figures into `paper/figs/` | PNG |
| `make_fig6.py` | Fig 6 | Collects the test suite and draws it by subsystem | PNG |

`ref_services.py` holds the four reference services (expense tracker, inventory,
authentication, notification worker; 24 tests) written in the layout the Developer
agent emits. `harness.py` builds run workspaces from them and verifies them the way
the graph does: static gate first, tests only if it passes.

## Running

From the repository root:

```bash
cd evaluation/component
PYTHONPATH=../.. ../../.venv/Scripts/python.exe run_component_eval.py    # ~5 min
PYTHONPATH=../.. ../../.venv/Scripts/python.exe run_robustness_eval.py   # seconds
uv run --no-project --with matplotlib python make_figs.py
uv run --no-project --with matplotlib python make_fig6.py
```

(On Linux/macOS use `../../.venv/bin/python`.)

Detection, attribution and robustness results are deterministic. Timings (static gate
vs. test run) depend on the machine and on what else it is running; re-time on an
idle machine before quoting them.

The live-model experiments (RQ4, RQ5) live one level up: see
[`../README.md`](../README.md).
