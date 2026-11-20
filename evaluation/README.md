# AutoDev evaluation: how to run it, and what it measured

This folder holds everything used to measure AutoDev for the IEEE paper
(`paper/AutoDev_IEEE_Final.tex`, Section VI): the offline component experiments
(RQ1–RQ3), the live end-to-end benchmark (RQ4), the single-prompt baseline, the
held-out acceptance tests and the counterfactual ablation (RQ5). Every number in
the paper's tables can be regenerated from the files listed here.

Results recorded below were measured on 2026-11-20 on a Windows 11 laptop with
DeepSeek V4.1 Flash (`deepseek-flash`).

---

## 1. Layout

| Path | Purpose |
|---|---|
| `component/` | Offline experiments for RQ1–RQ3 (no API key). See `component/README.md`. |
| `benchmark_requirements.json` | The 10 benchmark requirements: 3 easy, 4 medium, 3 hard. |
| `run_e2e_benchmark.py` | Runs every requirement N times through the full pipeline (RQ4). |
| `summarise_e2e.py` | Turns a benchmark JSONL into the per-tier table (paper Table VIII). |
| `run_single_prompt_baseline.py` | Same requirements, same model, one structured call per project. |
| `acceptance/` | Held-out acceptance tests, one suite per easy/medium requirement. |
| `run_acceptance.py` | Runs the acceptance suites against AutoDev and baseline projects (Table IX). |
| `analyse_attempts.py` | Per-attempt log analysis and counterfactual ablations (Table X). |
| `results/` | All raw results (JSONL / JSON). |

Generated projects are kept under `runs/benchmark/<label>/runs/<run_id>/`
(AutoDev) and `runs/benchmark/baseline/<label>/` (baseline), so failures can be
inspected after the fact.

---

## 2. Configuration used

The live runs use the OpenAI-compatible provider pointed at DeepSeek. In `.env`
(never commit the key):

```ini
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=...                # your own key
MODEL_HEAVY=deepseek-flash        # and MODEL_STRUCTURED / MODEL_TEXT / MODEL_CHEAP
OPENAI_THINKING=enabled
OPENAI_REASONING_EFFORT=low
MAX_OUTPUT_HEAVY=16384
MAX_OUTPUT_STRUCTURED=8192
LLM_TOKENS_PER_MINUTE=200000
LLM_MAX_OUTPUT_TOKENS=8192
```

Why these values:

- **Thinking on, low effort.** With thinking disabled, DeepSeek caps output at
  8,192 tokens, which truncated the Developer's JSON on medium and hard
  projects. With thinking at the default effort, an easy run cost about
  US$0.11 and was slow. Low effort allows long outputs and spends few tokens on
  reasoning.
- **Ceilings.** The Groq-sized defaults (4,096 / 3,500 tokens) are too small for
  a whole service. 16k / 8k fit every service in the suite.
- **Structured output.** DeepSeek rejects the `native` and `json_schema`
  response formats with HTTP 400. The structured-output ladder falls back to
  `json_mode` and remembers the rejected rungs, so no other change is needed.

Pipeline settings are the defaults: τ = 7 (minimum QA score), A = 3 (Developer
attempts), temperature 0.2, routing off, Developer parallelism 4. The benchmark
auto-approves both human review gates.

**Pricing.** Cost comes from `llm/pricing.py`, using DeepSeek's published peak
rates per million tokens: $0.30 input, $1.20 output, $0.006 cached input.
Off-peak calls are billed at half, so these are upper bounds. Token counts are
the provider's own `usage_metadata`. A callback in `llm/registry.py` captures
them even when the structured-output parser discards the raw message.

---

## 3. How to run

All commands run from the repository root. On Windows the interpreter is
`.venv/Scripts/python.exe`; on Linux/macOS it is `.venv/bin/python`.

### 3.1 Component experiments (RQ1–RQ3, offline, about 5 minutes)

```bash
cd evaluation/component
PYTHONPATH=../.. ../../.venv/Scripts/python.exe run_component_eval.py
PYTHONPATH=../.. ../../.venv/Scripts/python.exe run_robustness_eval.py
uv run --no-project --with matplotlib python make_figs.py     # Figs 4-5
uv run --no-project --with matplotlib python make_fig6.py     # Fig 6
```

### 3.2 End-to-end benchmark (RQ4, about 2 hours, about US$4.30)

```bash
.venv/Scripts/python.exe evaluation/run_e2e_benchmark.py --label deepseek-flash-v2 --repeats 3 --concurrency 3
.venv/Scripts/python.exe evaluation/summarise_e2e.py evaluation/results/e2e_deepseek-flash-v2.jsonl
```

- **Resuming.** The harness is resumable: re-running with the same label skips
  finished runs.
- **Infrastructure errors.** The harness stops on a provider error: a 401, 402
  or 403, an exhausted quota, or insufficient balance. Such rows are marked
  `infra_error` and excluded from the tables. Only the provider's own message
  is searched, never model output quoted inside a parser error.
- **Concurrency.** `--concurrency 3` runs three pipelines at once. They share
  the token budget, as they would in production.

### 3.3 Single-prompt baseline (about 20 minutes, about US$0.65)

```bash
.venv/Scripts/python.exe evaluation/run_single_prompt_baseline.py --label deepseek-flash --repeats 3
```

The baseline makes one structured call, which returns every file of the
project plus its tests. Its output then goes through AutoDev's own static gate
and test runner, so "self-verified" means the same thing for both systems.

### 3.4 Held-out acceptance tests (about 15 minutes, no API calls)

```bash
.venv/Scripts/python.exe evaluation/run_acceptance.py --e2e deepseek-flash-v2 --baseline deepseek-flash --workers 3
```

- **How they were written.** The suites in `acceptance/` were written from each
  requirement's text alone, before any project was generated. They check only
  what the requirement states: paths, status codes, rules and named fields.
- **Shape tolerance.** `_helpers.py` accepts bare or wrapped lists, any id key,
  and any spelling of a count field.
- **Coverage.** Hard requirements have no suites: their services call each
  other over HTTP.
- **Scoring.** A multi-service project is scored by its best service.
- **Isolation.** Each run starts from a fresh SQLite file.

### 3.5 Per-attempt analysis and counterfactual ablation

```bash
.venv/Scripts/python.exe evaluation/analyse_attempts.py deepseek-flash-v2
```

This replays each run's event log (static verdicts, QA calls and scores, test
results, regenerated services) to estimate:

- QA calls and tokens without the static gate;
- runs accepted, and falsely accepted, without test execution;
- service generations without failure attribution.

### 3.6 Unit tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

1,267 tests in 35 modules. Run them only while no benchmark is active: they
share the machine, and timings are reported.

---

## 4. Results

### 4.1 Component level (RQ1–RQ3)

| Metric | Result |
|---|---|
| Faults detected (all / build / logic), 141 mutants | 88.7% / 100% / 75.8% |
| Static gate vs. test run, median per service | 128 ms vs. 2.02 s (about 16×) |
| Detected faults stopped before QA | 60% (75 of 125) |
| False positives on clean services | 0 |
| Attribution precision / recall (40 trials) | 100% / 100% |
| Developer calls, surgical vs. full regeneration | 57 vs. 160 (−64.4%) |
| Malformed replies recovered by the parse rung | 8/8 (`json.loads`: 1/8) |
| Error-disposition accuracy | 100% (16 cases) |
| HTTP 429s: no budget / static wrong budget / AutoDev / oracle | 48 / 16 / 1 / 0 |

Timings differ by machine. An earlier Linux-container run gave 28 ms vs. 0.68 s.
The gate now includes an application-import check in a subprocess, which costs
more on Windows.

### 4.2 End-to-end benchmark (RQ4): 10 requirements × 3 runs

**v1 prompts** (`results/e2e_deepseek-flash.jsonl`):

| Tier | RSR % | 1st-attempt % | Dev. attempts | Static pass % | Test pass % | QA score | Calls | Tokens (k) | Cost ($) | Latency (min) |
|---|---|---|---|---|---|---|---|---|---|---|
| Easy | 33.3 | 22.2 | 2.56 | 77.8 | 80.7 | 9.0 | 9.1 | 122.6 | 0.102 | 6.6 |
| Medium | 33.3 | 8.3 | 2.58 | 75.0 | 43.8 | 7.8 | 7.8 | 143.3 | 0.120 | 7.0 |
| Hard | 0.0 | 0.0 | 3.00 | 48.1 | 54.5 | – | 12.2 | 283.4 | 0.234 | 9.5 |
| **All** | **23.3** | 10.0 | 2.70 | 67.8 | 58.5 | 8.3 | 9.5 | 179.1 | 0.149 | 7.6 |

**v2 prompts** (`results/e2e_deepseek-flash-v2.jsonl`, commit `053556c`):

| Tier | RSR % | 1st-attempt % | Dev. attempts | Static pass % | Test pass % | QA score | Calls | Tokens (k) | Cost ($) | Latency (min) |
|---|---|---|---|---|---|---|---|---|---|---|
| Easy | 55.6 | 44.4 | 1.67 | 87.5 | 98.5 | 8.8 | 7.3 | 99.9 | 0.093* | 5.3 |
| Medium | 41.7 | 41.7 | 2.17 | 91.7 | 89.1 | 8.0 | 8.1 | 131.1 | 0.115 | 7.3 |
| Hard | 22.2 | 11.1 | 2.78 | 81.5 | 75.0 | 7.0 | 13.3 | 283.4 | 0.238 | 10.2 |
| **All** | **40.0** | 33.3 | 2.20 | 87.4 | 89.2 | 8.2 | 9.4 | 167.4 | 0.147 | 7.6 |

\* One easy run ended in the PM stage on a truncated reply and has no usage
record, so this figure is the mean of the other eight.

The two hard-tier token means agree to one decimal place (283.4k) by
coincidence: the per-run values differ.

What changed in v2 (`prompts/architect_json_prompt.py`,
`prompts/developer_json_prompt.py`, `prompts/qa_json_prompt.py`):

- **Architect.** A fixed compact layout (`main.py`, `database.py`, `models.py`,
  `schemas.py`, `routes.py`), SQLite, and no extra infrastructure unless asked.
- **Developer.** Keep names consistent across files. Follow Pydantic 2 idioms
  and create tables at startup. Add auth and CORS only when required. When
  renaming a name, re-emit every file that imports it.
- **QA.** Test through the client only, and only behaviour the requirement
  states.

HTTP 429s: 0 in v1, 1 in v2, across 60 runs. No service was escalated a tier.
Rejected ladder rungs were logged in 3 v1 runs and 6 v2 runs.

### 4.3 Baseline comparison (RQ5)

Acceptance figures cover the 21 easy and medium projects per system, with 38
tests per set of 7 requirements (114 per system).

| Metric | Single prompt | AutoDev v1 | AutoDev v2 |
|---|---|---|---|
| Self-verified, easy+medium | 16/21 | 7/21 | 10/21 |
| Self-verified, all 30 runs | 73.3% | 23.3% | 40.0% |
| Acceptance: projects passing all tests | **20/21** | 7/21 | 15/21 |
| Acceptance: tests passed | **107/114** | 42/114 | 88/114 |
| Accepted and all-pass | 16 of 16 | 6 of 7 | 9 of 10 |
| All-pass but rejected by own tests | 4 | 1 | 6 |
| Tokens per run (k), all tiers | 18.6 | 179.1 | 167.4 |
| Cost per run ($), all tiers | 0.022 | 0.149 | 0.147 |
| Latency per run (min), all tiers | 2.0 | 7.6 | 7.6 |

Hard tier, self-verified: baseline 6/9, AutoDev v1 0/9, AutoDev v2 2/9.

Notable cases:

- **v1 M3 r3** passed its own tests, but its app never creates its tables; the
  QA-written tests created them. The test runner's app-import check does not
  catch this: the app imports fine.
- **v2 M4 r1** passed its own tests, then failed all 6 acceptance tests with
  401. The PM agent had added an `X-API-Key` requirement the user never asked
  for. This is drift the PM review gate exists to catch; the benchmark
  auto-approves it.
- **Baseline M1 r1** crashed on import (`None | None` in a schema annotation).
- Of the 72 acceptance tests v1 projects failed, 45 were import-time crashes
  (names a sibling file never defined), 6 were wrong paths, 1 was auth and 20
  were other failures.

### 4.4 Counterfactual ablation (RQ5, from v2 logs)

| Variant | RSR % | Service gens/run | QA calls/run | Tokens (k) |
|---|---|---|---|---|
| Full AutoDev | 40.0 | 3.73 | 3.17 | 167.4 |
| − static gate (QA first) | 40.0 | 3.73 | 4.50 | 198.8 |
| − test execution (QA score only) | 56.7 claimed (5 of 17 false accepts) | – | – | – |
| − attribution (regenerate all) | 40.0 | 3.87 | 3.17 | – |
| − token budget | no change on DeepSeek (1 × 429); simulated: 48 vs. 1 | | | |
| − structured-output ladder | 0 (DeepSeek rejects native / json_schema) | | | |
| − routing | no change (disabled) | | | |

v1 equivalents:

- **Without the static gate:** +64 QA calls and +1.61 M tokens.
- **Without test execution:** 14 runs accepted, 7 of them false; claimed RSR
  46.7% vs. a true 23.3%.
- **Without attribution:** 132 service generations instead of 119.

### 4.5 Spend

All at peak rates; actual billing is lower for calls made off-peak.

| Item | Runs | Cost ($) |
|---|---|---|
| AutoDev v1 benchmark | 30 | 4.46 |
| AutoDev v2 benchmark | 30 | 4.27 |
| Single-prompt baseline | 30 | 0.65 |
| Pilots (thinking settings) | 7 | 0.72 |
| **Total** | | **≈ 10.10** |

---

## 5. Interpretation and caveats

- **A single prompt wins on small projects.** With a strong model, one reply
  holds a whole small API, and one reply has no inter-file inconsistency.
  AutoDev's decomposition into planned files is what introduces most of its
  defects. v2 prompts halved that gap but did not close it.
- **AutoDev's verdict is conservative.** 9 of the 10 v2 projects it accepted
  pass the held-out tests. Six projects that pass them were rejected by its own
  stricter QA tests. The next fix is to derive QA tests only from the PRD's
  acceptance criteria.
- **Execution is what makes the success rate trustworthy.** Scoring by review
  alone would have overstated success by 17 points (v2) and 23 points (v1).
- **The token budget and routing were idle on DeepSeek.** Their evidence is the
  RQ3 simulation and the earlier Groq free-tier runs, not this benchmark.
- **Small samples.** There are 9–12 runs per tier, so differences of one or two
  runs are noise.
- **Prompt overfitting.** v2 prompts were tuned after reading v1 failures on
  the same requirements, so they may be overfitted to this suite. The
  acceptance suites were written first and not changed, except to accept PATCH
  as well as PUT in M1.
- **Counterfactual ablations.** The ablations are estimated from logs, not
  rerun.

## 6. Repeating with another model

1. **Configure.** Set the provider and model in `.env`, and check
   `llm/pricing.py` has the model's rates; otherwise cost is reported as `–`.
2. **Pilot.** Run a 3-run pilot first:
   ```bash
   .venv/Scripts/python.exe evaluation/run_e2e_benchmark.py --label <model>-pilot --only E1-todo M2-library H1-shop --repeats 1
   ```
3. **Full run.** Then run the full benchmark, the baseline, acceptance and the
   analyser with a new label. Results never overwrite another label's.
