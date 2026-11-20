"""Component evaluation: RQ1 (fault detection) and RQ2 (attribution + surgical regeneration).

Runs the repo's real static gate and test runner on mutated copies of four reference services.
Seed 42. Writes results.json next to this file.
"""
import ast, json, logging, random, statistics, sys, time
from collections import defaultdict
from pathlib import Path

import harness as h
from ref_services import SERVICES

logging.disable(logging.CRITICAL)
SEED = 42
MAX_PER_OP_PER_SERVICE = 8

BUILD_OPS = ["syntax_error", "undefined_name", "missing_import", "invalid_json"]
LOGIC_OPS = ["arith_swap", "compare_swap", "return_none"]

ARITH = {ast.Add: "-", ast.Sub: "+", ast.Mult: "/", ast.Div: "*"}
ARITH_SRC = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
COMPARE = {ast.Lt: ("<", "<="), ast.LtE: ("<=", "<"), ast.Gt: (">", ">="), ast.GtE: (">=", ">"),
           ast.Eq: ("==", "!="), ast.NotEq: ("!=", "==")}


def _offsets(src):
    lines = src.splitlines(keepends=True)
    acc, total = [], 0
    for ln in lines:
        acc.append(total)
        total += len(ln.encode("utf-8"))
    return acc


def _pos(src_bytes, offs, lineno, col):
    return offs[lineno - 1] + col


def sites(op, service, rel, src):
    """Return list of callables producing mutated source for each mutation site."""
    out = []
    if rel.endswith(".json"):
        if op == "invalid_json":
            out.append(lambda s=src: s.rstrip().rstrip("}") + "\n")
        return out
    if not rel.endswith(".py") or not src.strip():
        return out
    tree = ast.parse(src)
    b = src.encode("utf-8")
    offs = _offsets(src)
    lines = src.splitlines(keepends=True)

    def splice(start, end, new):
        return (b[:start] + new.encode() + b[end:]).decode("utf-8")

    if op == "syntax_error":  # drop the colon ending a def line
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef,)):
                ln = node.lineno - 1
                if lines[ln].rstrip().endswith(":"):
                    out.append(lambda ln=ln: "".join(lines[:ln] + [lines[ln].rstrip()[:-1] + "\n"] + lines[ln + 1:]))
    elif op == "undefined_name":  # a parameter use renamed to a name that does not exist
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            params = {a.arg for a in fn.args.args}
            for node in ast.walk(fn):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in params:
                    s0 = _pos(b, offs, node.lineno, node.col_offset)
                    s1 = _pos(b, offs, node.end_lineno, node.end_col_offset)
                    out.append(lambda s0=s0, s1=s1: splice(s0, s1, "undefined_value"))
    elif op == "missing_import":  # delete an import that is used
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                ln = node.lineno - 1
                n_lines = node.end_lineno - node.lineno + 1
                out.append(lambda ln=ln, n=n_lines: "".join(lines[:ln] + lines[ln + n:]))
    elif op == "arith_swap":
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and type(node.op) in ARITH:
                s0 = _pos(b, offs, node.left.end_lineno, node.left.end_col_offset)
                s1 = _pos(b, offs, node.right.lineno, node.right.col_offset)
                mid = b[s0:s1].decode()
                sym = ARITH_SRC[type(node.op)]
                if sym in mid:
                    out.append(lambda s0=s0, s1=s1, mid=mid, sym=sym, new=ARITH[type(node.op)]:
                               splice(s0, s1, mid.replace(sym, new, 1)))
    elif op == "compare_swap":
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                left = node.left
                for cmp_op, comp in zip(node.ops, node.comparators):
                    if type(cmp_op) in COMPARE:
                        s0 = _pos(b, offs, left.end_lineno, left.end_col_offset)
                        s1 = _pos(b, offs, comp.lineno, comp.col_offset)
                        mid = b[s0:s1].decode()
                        sym, new = COMPARE[type(cmp_op)]
                        if sym in mid:
                            out.append(lambda s0=s0, s1=s1, mid=mid, sym=sym, new=new:
                                       splice(s0, s1, mid.replace(sym, new, 1)))
                    left = comp
    elif op == "return_none":
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value is not None:
                s0 = _pos(b, offs, node.value.lineno, node.value.col_offset)
                s1 = _pos(b, offs, node.value.end_lineno, node.value.end_col_offset)
                out.append(lambda s0=s0, s1=s1: splice(s0, s1, "None"))
    return out


def sample_mutants(rng):
    mutants = []
    for slug, svc in SERVICES.items():
        for op in BUILD_OPS + LOGIC_OPS:
            cand = []
            for rel, src in svc["files"].items():
                for fn in sites(op, slug, rel, src):
                    cand.append((rel, fn))
            rng.shuffle(cand)
            for rel, fn in cand[:MAX_PER_OP_PER_SERVICE]:
                mutants.append({"service": slug, "op": op, "rel": rel,
                                "kind": "build" if op in BUILD_OPS else "logic", "make": fn})
    return mutants


def main():
    rng = random.Random(SEED)
    mutants = sample_mutants(rng)
    print(f"{len(mutants)} mutants ({sum(m['kind']=='build' for m in mutants)} build, "
          f"{sum(m['kind']=='logic' for m in mutants)} logic)", flush=True)

    # clean baseline: zero false positives, per-service timings
    clean = {}
    for slug in SERVICES:
        ws = h.build_workspace(only={slug})
        r = h.verify(ws)
        clean[slug] = {"flagged": r["detected"], "static_s": r["static_s"], "tests_s": r["tests_s"]}

    # RQ1
    rows = []
    for i, m in enumerate(mutants):
        new_src = m["make"]()
        ws = h.build_workspace(overrides={(m["service"], m["rel"]): new_src}, only={m["service"]})
        r = h.verify(ws)
        rows.append({k: m[k] for k in ("service", "op", "rel", "kind")} |
                    {"detected": r["detected"], "stage": r["stage"],
                     "static_s": r["static_s"], "tests_s": r["tests_s"]})
        if i % 20 == 0:
            print(f"  RQ1 {i}/{len(mutants)}", flush=True)

    by_kind = defaultdict(lambda: [0, 0])
    by_op = defaultdict(lambda: {"n": 0, "static": 0, "tests": 0, "either": 0})
    for r in rows:
        by_kind[r["kind"]][0] += 1
        by_kind[r["kind"]][1] += r["detected"]
        o = by_op[r["op"]]
        o["n"] += 1
        # static-only and test-only detection need both stages run on every mutant;
        # the gate-first order means a static catch hides the test result, so measure test-only separately below.
        o["either"] += r["detected"]
        o["static"] += r["stage"] == "static"
    # test-only detection for ALL mutants (run tests regardless of the gate) for the per-operator figure
    for i, (m, r) in enumerate(zip(mutants, rows)):
        if r["stage"] == "static":
            ws = h.build_workspace(overrides={(m["service"], m["rel"]): m["make"]()}, only={m["service"]})
            tests = h.run_tests(ws, runner=h.RUNNER)
            by_op[m["op"]]["tests"] += (not tests.passed)
        else:
            by_op[m["op"]]["tests"] += r["stage"] == "tests"

    detected = sum(r["detected"] for r in rows)
    static_caught = sum(r["stage"] == "static" for r in rows)
    static_times = [r["static_s"] for r in rows if r["static_s"]] + [c["static_s"] for c in clean.values()]
    test_times = [r["tests_s"] for r in rows if r["tests_s"]] + [c["tests_s"] for c in clean.values() if c["tests_s"]]

    rq1 = {
        "n_mutants": len(rows),
        "n_build": by_kind["build"][0], "n_logic": by_kind["logic"][0],
        "detected_all": detected / len(rows),
        "detected_build": by_kind["build"][1] / by_kind["build"][0],
        "detected_logic": by_kind["logic"][1] / by_kind["logic"][0],
        "n_detected": detected,
        "caught_by_static": static_caught,
        "share_of_detected_stopped_before_qa": static_caught / detected,
        "static_median_ms": statistics.median(static_times) * 1000,
        "tests_median_s": statistics.median(test_times),
        "speed_ratio": statistics.median(test_times) / statistics.median(static_times),
        "false_positives": sum(c["flagged"] for c in clean.values()),
        "by_operator": dict(by_op),
        "missed": [{k: r[k] for k in ("service", "op", "rel")} for r in rows if not r["detected"]],
    }
    print(json.dumps({k: v for k, v in rq1.items() if k not in ("by_operator", "missed")}, indent=1), flush=True)

    # RQ2: 40 trials, 1-3 of 4 services mutated simultaneously, gate-first verification
    from agents.attribution import implicated_services
    pool = [(m, r) for m, r in zip(mutants, rows) if r["detected"]]
    by_service = defaultdict(list)
    for m, r in pool:
        by_service[m["service"]].append((m, r))
    slugs = list(SERVICES)
    rng2 = random.Random(SEED)
    tp = fp = fn = exact = 0
    surgical_calls = 0
    n_trials = 40
    for t in range(n_trials):
        k = rng2.choice([1, 2, 3])
        chosen = rng2.sample(slugs, k)
        overrides, picked = {}, {}
        for s in chosen:
            m, r = rng2.choice(by_service[s])
            overrides[(s, m["rel"])] = m["make"]()
            picked[s] = r["stage"]
        ws = h.build_workspace(overrides=overrides)
        res = h.verify(ws)
        # ground truth from the solo (RQ1) result: what the gate-first pass can observe
        truth = {s for s, st in picked.items() if st == "static"} or {s for s, st in picked.items() if st == "tests"}
        got = set(implicated_services(static_report=res["static"], verification_report=res["tests"]))
        tp += len(truth & got); fp += len(got - truth); fn += len(truth - got)
        exact += truth == got
        surgical_calls += len(got)
        if t % 10 == 0:
            print(f"  RQ2 {t}/{n_trials}", flush=True)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    rq2 = {"trials": n_trials, "precision": precision, "recall": recall,
           "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
           "exact_match_trials": exact,
           "developer_calls_surgical": surgical_calls,
           "developer_calls_full": n_trials * len(slugs),
           "reduction": 1 - surgical_calls / (n_trials * len(slugs))}
    print(json.dumps(rq2, indent=1), flush=True)

    Path(__file__).with_name("results_rq1_rq2.json").write_text(json.dumps({"rq1": rq1, "rq2": rq2}, indent=1, default=str))


if __name__ == "__main__":
    main()
