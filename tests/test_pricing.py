"""Cost comes from listed prices and reported usage, or it is unknown."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from llm.accounting import Ledger, merge_reports, recording
from llm.pricing import cost_of, price_for


class TestCostOf:
    def test_a_listed_model_is_priced_from_its_split(self):
        # 1M uncached input at $0.30 + 1M output at $1.20
        assert cost_of("deepseek-flash", 1_000_000, 1_000_000) == pytest.approx(1.50)

    def test_cached_input_is_charged_at_the_cache_rate(self):
        full = cost_of("deepseek-flash", 1_000_000, 0)
        cached = cost_of("deepseek-flash", 1_000_000, 0, cached_input_tokens=1_000_000)
        assert full == pytest.approx(0.30)
        assert cached == pytest.approx(0.006)

    def test_an_unlisted_model_is_unknown_not_free(self):
        assert price_for("openai/gpt-oss-120b") is None
        assert cost_of("openai/gpt-oss-120b", 1000, 1000) is None

    def test_missing_usage_is_unknown(self):
        assert cost_of("deepseek-flash", None, 100) is None


class TestTheLedgerAddsItUp:
    def _record(self, ledger: Ledger, model: str, inp: int | None, out: int | None) -> None:
        ledger.record(
            purpose="heavy", provider="openai", model=model, estimated_tokens=10,
            reserved_tokens=100, actual_tokens=None if inp is None else inp + out,
            duration_seconds=1.0, outcome="success", input_tokens=inp, output_tokens=out,
        )

    def test_split_and_cost_are_summed(self):
        ledger = Ledger()
        self._record(ledger, "deepseek-flash", 1000, 500)
        self._record(ledger, "deepseek-flash", 2000, 0)
        totals = ledger.totals()
        assert totals["input_tokens"] == 3000
        assert totals["output_tokens"] == 500
        assert totals["estimated_cost"] == pytest.approx((3000 * 0.30 + 500 * 1.20) / 1e6)

    def test_an_unpriced_model_leaves_cost_unknown(self):
        ledger = Ledger()
        self._record(ledger, "some-unlisted-model", 1000, 500)
        assert ledger.totals()["input_tokens"] == 1000
        assert ledger.totals()["estimated_cost"] is None

    def test_merging_stages_sums_the_split_and_the_cost(self):
        a, b = Ledger(), Ledger()
        self._record(a, "deepseek-flash", 1000, 100)
        self._record(b, "deepseek-flash", 500, 50)
        merged = merge_reports(a.report(), b.report())
        assert merged["input_tokens"] == 1500
        assert merged["output_tokens"] == 150
        assert merged["estimated_cost"] == pytest.approx((1500 * 0.30 + 150 * 1.20) / 1e6, abs=1e-6)

    def test_reports_without_a_split_still_merge(self):
        old = {"calls": 1, "actual_tokens": 10}
        merged = merge_reports(old, None)
        assert merged["input_tokens"] is None
        assert merged["estimated_cost"] is None


def test_the_metered_wrapper_records_usage_the_callback_saw():
    """A response stripped of its usage (as a structured parser does) is still counted."""
    from langchain_core.runnables import RunnableLambda

    from core.config import LLMProvider, Purpose, Settings
    from llm.budget import TokenBudget
    from llm.registry import _metered

    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="{}", usage_metadata={
            "input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
        })]
    )
    stripped = model | RunnableLambda(lambda message: {"parsed": True})
    metered = _metered(
        stripped, TokenBudget(100_000), Settings(), label="t", ceiling=100,
        provider=LLMProvider.OPENAI, model_name="deepseek-flash", purpose=Purpose.STRUCTURED,
    )

    with recording("run", "stage") as ledger:
        assert asyncio.run(metered.ainvoke("hi")) == {"parsed": True}

    record = ledger.records[0]
    assert (record.actual_tokens, record.input_tokens, record.output_tokens) == (150, 120, 30)
    assert record.cost == pytest.approx((120 * 0.30 + 30 * 1.20) / 1e6)
