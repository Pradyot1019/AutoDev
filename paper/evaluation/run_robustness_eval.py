"""RQ3: structured-output parse rung, error disposition, and the rolling token budget under a simulated 8,000 TPM provider."""
import asyncio, json, logging, random, sys
from pathlib import Path

import harness as h  # sets up sys.path / env
from llm.budget import TokenBudget
from llm.errors import Disposition, classify, reported_usage, retry_after
from llm.structured import parse_into
from llm.budget import BudgetExceededError
from schema.qa_schema import QASchema
from tests import fakes

logging.disable(logging.CRITICAL)
OUT = {}

# ------------------------------------------------------------------ structured output
valid = fakes.build_qa_report().model_dump_json()
pretty = json.dumps(json.loads(valid), indent=2)
shapes = {
    "pretty_printed": pretty,
    "markdown_fence": f"```json\n{valid}\n```",
    "prose_before": f"Here is the QA report you asked for:\n{valid}",
    "prose_after": f"{valid}\nLet me know if you need anything changed.",
    "prose_both": f"Sure!\n{valid}\nHope that helps.",
    "fence_and_prose": f"Here you go:\n```json\n{pretty}\n```\nDone.",
    "function_call_tag": f"<function=QASchema>{valid}</function>",
    "content_blocks": [{"type": "text", "text": valid}],
}
invalid = {
    "truncated_json": valid[: len(valid) // 2],
    "missing_required_field": json.dumps({k: v for k, v in json.loads(valid).items() if k != "overall_assessment"}),
    "no_json": "I could not produce a report for this project.",
}


class Resp:  # minimal AIMessage-alike
    def __init__(self, content):
        self.content = content


parser = parse_into(QASchema)
rec, base = 0, 0
for name, content in shapes.items():
    try:
        parser.invoke(Resp(content)); rec += 1
    except Exception:
        pass
    if isinstance(content, str):
        try:
            QASchema.model_validate(json.loads(content)); base += 1
        except Exception:
            pass
rejected = 0
for name, content in invalid.items():
    try:
        parser.invoke(Resp(content))
    except Exception:
        rejected += 1
OUT["structured"] = {"recoverable_shapes": len(shapes), "parse_rung_recovered": rec,
                     "json_loads_recovered": base, "invalid_shapes": len(invalid), "invalid_rejected": rejected}

# ------------------------------------------------------------------ error disposition
class StatusError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


class ReadTimeout(Exception):
    pass


groq429 = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `llama-3.1-8b-instant` "
           "in organization `org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6200, "
           "Requested 3100. Please try again in 9.5s.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
cases = [
    ("429 Groq TPM", StatusError(groq429, 429), Disposition.RETRY),
    ("429 Gemini RESOURCE_EXHAUSTED", StatusError("Error code: 429 - RESOURCE_EXHAUSTED quota", 429), Disposition.RETRY),
    ("500", StatusError("Error code: 500 - internal error", 500), Disposition.RETRY),
    ("502", StatusError("Error code: 502 - bad gateway", 502), Disposition.RETRY),
    ("503", StatusError("Error code: 503 - overloaded", 503), Disposition.RETRY),
    ("timeout", ReadTimeout("read timed out"), Disposition.RETRY),
    ("dropped connection", ConnectionError("connection reset by peer"), Disposition.RETRY),
    ("400 tool_use_failed", StatusError("Error code: 400 - tool_use_failed: failed to call a function", 400), Disposition.DEGRADE),
    ("400 schema rejected", StatusError("Error code: 400 - invalid schema for response_format", 400), Disposition.DEGRADE),
    ("validation error", ValueError("1 validation error for QASchema"), Disposition.DEGRADE),
    ("unrecognised error", RuntimeError("something odd happened"), Disposition.DEGRADE),
    ("401 invalid key", StatusError("Error code: 401 - invalid api key", 401), Disposition.ABORT),
    ("403 forbidden", StatusError("Error code: 403 - permission denied", 403), Disposition.ABORT),
    ("404 model retired", StatusError("Error code: 404 - model decommissioned", 404), Disposition.ABORT),
    ("413 request too large", StatusError("Error code: 413 - request too large, TPM limit", 413), Disposition.ABORT),
    ("call larger than budget", BudgetExceededError("single call exceeds budget"), Disposition.ABORT),
]
agree = sum(classify(e) == want for _, e, want in cases)
non_retryable = sum(want != Disposition.RETRY for _, _, want in cases)
usage = reported_usage(StatusError(groq429, 429))
OUT["error_disposition"] = {
    "cases": len(cases), "agree": agree, "accuracy": agree / len(cases),
    "non_retryable_cases": non_retryable,
    "calls_spent_retry_everything_3_retries": non_retryable * 3,
    "parsed_usage_report": usage.__dict__ if usage else None,
    "parsed_retry_after_s": retry_after(StatusError(groq429, 429)),
    "misclassified": [n for n, e, want in cases if classify(e) != want],
}

# ------------------------------------------------------------------ token budget simulation
TRUE_TPM, WRONG_TPM, LATENCY = 8000, 12000, 6.0


def workload():
    rng = random.Random(42)
    return [rng.randint(2200, 7600) for _ in range(21)]


async def simulate(policy):
    vt = [0.0]
    charges = []  # provider-side rolling window: (time, tokens)
    rejections = 0

    def clock():
        return vt[0]

    async def vsleep(s):
        vt[0] += s

    def provider_try(tokens):
        nonlocal charges
        charges = [(t, k) for t, k in charges if t > vt[0] - 60]
        used = sum(k for _, k in charges)
        if used + tokens > TRUE_TPM:
            oldest = min(t for t, _ in charges)
            wait = oldest + 60 - vt[0]
            return StatusError(
                f"Error code: 429 - Rate limit reached ... tokens per minute (TPM): Limit {TRUE_TPM}, "
                f"Used {used}, Requested {tokens}. Please try again in {wait:.1f}s.", 429)
        charges.append((vt[0], tokens))
        return None

    budget = None
    if policy == "static":
        budget = TokenBudget(WRONG_TPM, clock=clock, sleep=vsleep)
    elif policy == "autodev":
        budget = TokenBudget(WRONG_TPM, clock=clock, sleep=vsleep)
    elif policy == "oracle":
        budget = TokenBudget(TRUE_TPM, clock=clock, sleep=vsleep)

    for tokens in workload():
        backoff = 10.0
        while True:
            if budget is not None:
                await budget.reserve(tokens)
            err = provider_try(tokens)
            if err is None:
                vt[0] += LATENCY
                break
            rejections += 1
            if policy == "autodev":
                u = reported_usage(err)
                if u:
                    budget.adopt_limit(u.limit)
                    budget.resync(u.used)
                # the budget now knows the real window; it decides how long to wait
                continue
            vt[0] += backoff
            backoff = min(backoff * 2, 40.0)
    return {"rejections": rejections, "makespan_min": vt[0] / 60}


async def run_all():
    return {p: await simulate(p) for p in ("none", "static", "autodev", "oracle")}


res = asyncio.run(run_all())
OUT["token_budget"] = {"workload_calls": 21, "reserved_tokens_range": [min(workload()), max(workload())],
                       "true_tpm": TRUE_TPM, "configured_tpm": WRONG_TPM, "latency_s": LATENCY, **res}

print(json.dumps(OUT, indent=1))
Path(__file__).with_name("results_rq3.json").write_text(json.dumps(OUT, indent=1))
