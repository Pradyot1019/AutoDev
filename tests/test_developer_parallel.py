"""The Developer's per-service calls run concurrently, bounded, and in order."""

from __future__ import annotations

import asyncio

from agents.developer_agent import _generate_all, _Job


class _SlowModel:
    """Answers after ``delay`` seconds, tracking how many calls overlap."""

    def __init__(self, tracker: dict[str, int], delay: float, fail: bool = False) -> None:
        self.tracker, self.delay, self.fail = tracker, delay, fail

    async def ainvoke(self, prompt: list) -> str:
        self.tracker["now"] += 1
        self.tracker["peak"] = max(self.tracker["peak"], self.tracker["now"])
        await asyncio.sleep(self.delay)
        self.tracker["now"] -= 1
        if self.fail:
            raise RuntimeError(f"boom {prompt[0]}")
        return f"answer {prompt[0]}"


def _jobs(tracker: dict[str, int], delays: list[float], failing: set[int] = frozenset()) -> list[_Job]:
    return [
        _Job({"name": f"s{i}"}, f"s{i}", _SlowModel(tracker, d, i in failing), [f"s{i}"], None, None, None)
        for i, d in enumerate(delays)
    ]


def test_answers_come_back_in_job_order_whatever_finishes_first():
    tracker = {"now": 0, "peak": 0}
    out = asyncio.run(_generate_all(_jobs(tracker, [0.05, 0.01, 0.03]), parallelism=3))
    assert out == ["answer s0", "answer s1", "answer s2"]
    assert tracker["peak"] == 3


def test_parallelism_caps_the_calls_in_flight():
    tracker = {"now": 0, "peak": 0}
    asyncio.run(_generate_all(_jobs(tracker, [0.02] * 5), parallelism=2))
    assert tracker["peak"] == 2


def test_parallelism_one_is_sequential():
    tracker = {"now": 0, "peak": 0}
    asyncio.run(_generate_all(_jobs(tracker, [0.01] * 3), parallelism=1))
    assert tracker["peak"] == 1


def test_one_failure_is_returned_and_does_not_cancel_the_others():
    tracker = {"now": 0, "peak": 0}
    out = asyncio.run(_generate_all(_jobs(tracker, [0.01, 0.02, 0.01], failing={1}), parallelism=3))
    assert out[0] == "answer s0" and out[2] == "answer s2"
    assert isinstance(out[1], RuntimeError)
