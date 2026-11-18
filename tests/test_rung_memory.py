"""Remembering structured-output rungs a provider refuses.

The ladder is rebuilt for every call, so without memory a rung the provider
cannot serve is paid for on every call. These tests drive the real registry
ladder with a fake model and pin the three rules: only a provider rejection
(HTTP 400) counts, two in a row are needed, and the last rung is never skipped.
"""

from __future__ import annotations

import contextlib

import pytest
from langchain_core.runnables import RunnableLambda

from core.config import LLMProvider, Purpose
from llm import registry
from llm.structured import (
    REJECTIONS_BEFORE_SKIP,
    remembering,
    reset_rung_memory,
    skipped_rungs,
    usable_strategies,
)
from tests.test_accounting import UNSATISFIABLE, StructuredModel, _patch_model
from tests.test_structured import Widget


def _call() -> Widget:
    return registry.get_structured_llm(Widget, Purpose.STRUCTURED).invoke("make a widget")


class TestTheLadderStopsAskingForARefusedRung:
    def test_a_rung_rejected_twice_is_skipped_on_the_next_call(self, monkeypatch: pytest.MonkeyPatch):
        model = _patch_model(
            monkeypatch, StructuredModel(failing=("default",), error=RuntimeError(UNSATISFIABLE))
        )

        for _ in range(REJECTIONS_BEFORE_SKIP + 2):
            assert isinstance(_call(), Widget)

        # Asked twice, refused twice, then never again.
        assert model.calls.count("default") == REJECTIONS_BEFORE_SKIP
        assert model.calls.count("json_schema") == REJECTIONS_BEFORE_SKIP + 2

    def test_a_single_rejection_is_not_enough(self, monkeypatch: pytest.MonkeyPatch):
        model = _patch_model(
            monkeypatch, StructuredModel(failing=("default",), error=RuntimeError(UNSATISFIABLE))
        )

        _call()

        model_name = registry.model_name_for(LLMProvider.GOOGLE, Purpose.STRUCTURED)
        assert skipped_rungs(LLMProvider.GOOGLE.value, model_name) == set()
        assert model.calls.count("default") == 1

    def test_an_output_that_fails_validation_never_counts(self, monkeypatch: pytest.MonkeyPatch):
        """A bad answer says something about that output, not about the rung."""
        model = _patch_model(
            monkeypatch,
            StructuredModel(
                failing=("default",), error=ValueError("Failed to parse Widget from completion {")
            ),
        )

        for _ in range(4):
            _call()

        assert model.calls.count("default") == 4


class TestTheRules:
    def setup_method(self):
        reset_rung_memory()

    def test_a_success_clears_the_count(self):
        outcomes = [RuntimeError(UNSATISFIABLE), "ok", RuntimeError(UNSATISFIABLE)]

        def flaky(_prompt):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        rung = remembering("groq", "llama", "native", RunnableLambda(flaky))
        for _ in range(3):
            with contextlib.suppress(RuntimeError):
                rung.invoke("x")

        # Rejected, then served, then rejected: never two in a row.
        assert skipped_rungs("groq", "llama") == set()

    def test_the_last_rung_is_never_skipped(self):
        strategies = [("native", RunnableLambda(lambda p: p)), ("parse", RunnableLambda(lambda p: p))]
        failing = RunnableLambda(lambda p: (_ for _ in ()).throw(RuntimeError(UNSATISFIABLE)))
        for name in ("native", "parse"):
            for _ in range(REJECTIONS_BEFORE_SKIP):
                with pytest.raises(RuntimeError):
                    remembering("groq", "llama", name, failing).invoke("x")

        kept = usable_strategies(strategies, "groq", "llama")

        assert [name for name, _ in kept] == ["parse"]

    def test_memory_is_per_provider_and_model(self):
        failing = RunnableLambda(lambda p: (_ for _ in ()).throw(RuntimeError(UNSATISFIABLE)))
        for _ in range(REJECTIONS_BEFORE_SKIP):
            with pytest.raises(RuntimeError):
                remembering("openai", "deepseek-flash", "json_schema", failing).invoke("x")

        assert skipped_rungs("openai", "deepseek-flash") == {"json_schema"}
        assert skipped_rungs("openai", "gpt-6-luna") == set()
        assert skipped_rungs("groq", "deepseek-flash") == set()
