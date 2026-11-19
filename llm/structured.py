"""Provider-agnostic structured output.

``with_structured_output(schema)`` commits to one mechanism -- usually tool
calling -- and a model that cannot drive that mechanism has no way to succeed.
That is not a hypothetical: a small Llama emits the JSON as literal text in a
``<function=Schema> {...}`` wrapper, and the provider rejects the request with
``tool_use_failed`` even though the payload it produced was perfectly good.

So instead of one mechanism, each model gets a ladder of them, tried in order and
degrading only as far as it has to:

1. ``native``      -- whatever the provider does by default, normally tool calling.
2. ``json_schema`` -- constrained decoding, where the provider enforces the schema.
3. ``json_mode``   -- provider guarantees valid JSON; the schema goes in the prompt.
4. ``parse``       -- plain text, then find the JSON and validate it ourselves.

The last rung asks nothing of the provider beyond returning text, so it works on
any chat model at all, including a local one with no tool support. Rungs a
provider cannot build are skipped at construction time rather than failing later.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from core.logging import get_logger
from llm.content import flatten_content
from llm.errors import status_code
from utils.json_utils import extract_json_object

logger = get_logger(__name__)

INSTRUCTIONS = """Respond with a single JSON object and nothing else.

It must validate against this JSON Schema:

{schema}

Rules:
- Output raw JSON only. No markdown fences, no explanation, no text around it.
- Include every required property.
- Do not add properties the schema does not define.
"""


def as_messages(prompt: Any) -> list[BaseMessage]:
    """Coerce whatever an agent passed in into a message list."""
    if isinstance(prompt, str):
        return [HumanMessage(content=prompt)]
    if isinstance(prompt, BaseMessage):
        return [prompt]
    if hasattr(prompt, "to_messages"):
        return list(prompt.to_messages())
    if isinstance(prompt, Sequence):
        return list(prompt)
    return [HumanMessage(content=str(prompt))]


def schema_instructions(schema: type[BaseModel]) -> str:
    # Compact: indentation is whitespace the model does not need and every call
    # pays for. Indented, QASchema alone cost 1,269 tokens of an 8,000 window.
    return INSTRUCTIONS.format(schema=json.dumps(schema.model_json_schema(), separators=(",", ":")))


REMINDER = "Respond now with the single JSON object, valid against the JSON Schema given at the start. Raw JSON only."


def with_schema_prompt(schema: type[BaseModel]) -> Runnable:
    """Put the schema in the prompt.

    Needed by every rung below the provider-enforced ones, where the model is
    told what shape to produce rather than being constrained to it.

    The schema goes at the *start*, inside the system message, with a one-line
    reminder at the end. Providers discount a prompt prefix they have seen
    recently (DeepSeek, Qwen, OpenAI and Gemini all cache automatically), and the
    schema is both large and identical on every call for a given contract, while
    the requirement, the documents and the failure evidence vary. Appended at the
    end it sat after the variable part and could never be cached; the reminder
    keeps the format request as the last thing the model reads.
    """
    instructions = schema_instructions(schema)

    def place(prompt: Any) -> list[BaseMessage]:
        messages = as_messages(prompt)
        if messages and isinstance(messages[0], SystemMessage):
            head = SystemMessage(content=f"{instructions}\n\n{flatten_content(messages[0].content)}")
            rest = messages[1:]
        else:
            head = SystemMessage(content=instructions)
            rest = messages
        return [head, *rest, HumanMessage(content=REMINDER)]

    return RunnableLambda(place)


def parse_into(schema: type[BaseModel]) -> Runnable:
    def parse(response: Any) -> BaseModel:
        content = flatten_content(getattr(response, "content", response))
        return schema.model_validate(extract_json_object(content))

    return RunnableLambda(parse)


StrategyBuilder = Callable[[BaseChatModel, type[BaseModel]], Runnable]

STRATEGIES: tuple[tuple[str, StrategyBuilder], ...] = (
    ("native", lambda model, schema: model.with_structured_output(schema)),
    (
        "json_schema",
        lambda model, schema: model.with_structured_output(schema, method="json_schema"),
    ),
    (
        "json_mode",
        lambda model, schema: with_schema_prompt(schema)
        | model.with_structured_output(schema, method="json_mode"),
    ),
    ("parse", lambda model, schema: with_schema_prompt(schema) | model | parse_into(schema)),
)


def announce_failure(name: str, model: BaseChatModel, runnable: Runnable) -> Runnable:
    """Log why a rung failed on its way past.

    The ladder reports only the error it ended on, so without this the rungs it
    walked past -- and why each was rejected -- leave no trace in the run log.
    """

    def report(exc: Exception) -> None:
        logger.warning(
            "Structured strategy %r failed on %s: %s",
            name,
            type(model).__name__,
            str(exc).replace("\n", " ")[:300],
        )

    def invoke(prompt: Any, config: Any = None) -> Any:
        try:
            return runnable.invoke(prompt, config)
        except Exception as exc:
            report(exc)
            raise

    async def ainvoke(prompt: Any, config: Any = None) -> Any:
        try:
            return await runnable.ainvoke(prompt, config)
        except Exception as exc:
            report(exc)
            raise

    return RunnableLambda(invoke, afunc=ainvoke, name=f"structured:{name}")


def build_strategies(model: BaseChatModel, schema: type[BaseModel]) -> list[tuple[str, Runnable]]:
    """Every rung this model can actually construct, strongest first."""
    built: list[tuple[str, Runnable]] = []

    for name, builder in STRATEGIES:
        try:
            built.append((name, announce_failure(name, model, builder(model, schema))))
        except Exception as exc:
            # Providers signal an unsupported mode by raising here, which is a
            # normal outcome rather than a problem worth surfacing.
            logger.debug(
                "Structured strategy %r unavailable on %s: %s",
                name,
                type(model).__name__,
                exc,
            )

    if not built:  # pragma: no cover - a chat model that cannot even return text
        raise RuntimeError(f"No usable structured-output strategy for {type(model).__name__}")

    return built


# ── Remembering what a provider refuses ───────────────────────────
#
# The ladder is rebuilt for every call, so a rung the provider cannot serve used
# to be paid for again on every call: DeepSeek or Qwen through the openai provider
# refusing a response format, a small Groq Llama answering tool calls with
# ``tool_use_failed``. Each refusal is a 400 that costs a round trip and holds a
# reservation in the token window.
#
# Only a provider *rejection* (HTTP 400) counts. An answer that came back and
# failed validation says something about that one output, not about the rung:
# in a live Gemini run the native rung failed validation twice and served every
# other call. Two rejections in a row are needed before a rung is skipped, a
# success clears the count, and the last rung is never skipped, so a model always
# has something left to try. Kept per process and per provider and model, like
# the token budget.

REJECTIONS_BEFORE_SKIP = 2

_rejections: dict[tuple[str, str, str], int] = {}


# Groq reports a *generation* that failed its own JSON or tool-schema check as an
# HTTP 400 too ("Failed to generate JSON", json_validate_failed, "parameters for
# tool ... did not match schema"). Those are about one output -- in a live run the
# reasoning model had simply run out of tokens -- so they must not retire a rung.
_OUTPUT_FAILURE = re.compile(
    r"json_validate_failed|failed to (?:generate|validate) json|did not match schema|"
    r"failed to parse tool call arguments|parsing failed",
    re.IGNORECASE,
)


def _is_rejection(exc: BaseException) -> bool:
    return status_code(exc) == 400 and not _OUTPUT_FAILURE.search(str(exc))


def skipped_rungs(provider: str, model: str) -> set[str]:
    """Rungs this provider and model have refused often enough to stop asking."""
    return {
        name
        for (p, m, name), count in _rejections.items()
        if p == provider and m == model and count >= REJECTIONS_BEFORE_SKIP
    }


def usable_strategies(
    strategies: list[tuple[str, Runnable]], provider: str, model: str
) -> list[tuple[str, Runnable]]:
    """Drop remembered refusals, never leaving the model with nothing to try."""
    skip = skipped_rungs(provider, model)
    kept = [(name, runnable) for name, runnable in strategies if name not in skip]
    if len(kept) < len(strategies):
        logger.info(
            "Skipping structured strategy %s for %s:%s; the provider rejected it %d times in a row",
            ", ".join(sorted(skip)),
            provider,
            model,
            REJECTIONS_BEFORE_SKIP,
        )
    return kept or strategies[-1:]


def remembering(provider: str, model: str, name: str, runnable: Runnable) -> Runnable:
    """Count this rung's rejections by the provider; a success clears them."""
    key = (provider, model, name)

    def note(exc: Exception | None) -> None:
        if exc is None:
            _rejections.pop(key, None)
        elif _is_rejection(exc):
            _rejections[key] = _rejections.get(key, 0) + 1

    def invoke(prompt: Any, config: Any = None) -> Any:
        try:
            result = runnable.invoke(prompt, config)
        except Exception as exc:
            note(exc)
            raise
        note(None)
        return result

    async def ainvoke(prompt: Any, config: Any = None) -> Any:
        try:
            result = await runnable.ainvoke(prompt, config)
        except Exception as exc:
            note(exc)
            raise
        note(None)
        return result

    return RunnableLambda(invoke, afunc=ainvoke, name=f"remember:{name}")


def reset_rung_memory() -> None:
    """Forget every remembered refusal. For tests, like reset_budgets."""
    _rejections.clear()
