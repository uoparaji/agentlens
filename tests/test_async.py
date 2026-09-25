"""Async tracing: awaits, concurrency and context isolation."""

from __future__ import annotations

import asyncio

import pytest

from agentlens import AgentLens, SpanType, span, trace


async def test_async_decorator_records_a_trace(global_lens: AgentLens) -> None:
    @trace
    async def research_agent(topic: str) -> str:
        await asyncio.sleep(0.01)
        return topic.upper()

    assert await research_agent("quantum") == "QUANTUM"

    t = global_lens.get_traces()[0]
    assert t.name == "research_agent"
    assert t.status == "ok"
    assert t.duration_ms >= 10
    detail = global_lens.get_trace(t.id)
    assert detail.spans[0].input == {"topic": "quantum"}
    assert detail.spans[0].output == "QUANTUM"


async def test_async_context_manager(lens: AgentLens) -> None:
    async with lens.trace("agent"):
        async with lens.span("llm", span_type=SpanType.LLM) as s:
            await asyncio.sleep(0)
            s.set_tokens(prompt_tokens=5, completion_tokens=5)

    detail = lens.get_trace(lens.get_traces()[0].id)
    assert [s.name for s in detail.spans] == ["agent", "llm"]
    assert detail.tokens.total_tokens == 10


async def test_async_exception_is_recorded(global_lens: AgentLens) -> None:
    @trace("failing-agent")
    async def run() -> None:
        async with span("step", span_type=SpanType.TOOL):
            await asyncio.sleep(0)
            raise TimeoutError("upstream timed out")

    with pytest.raises(TimeoutError):
        await run()

    t = global_lens.get_traces()[0]
    assert t.status == "error"
    assert t.error.type == "TimeoutError"
    detail = global_lens.get_trace(t.id)
    assert all(s.status == "error" for s in detail.spans)


async def test_concurrent_traces_do_not_leak_into_each_other(global_lens: AgentLens) -> None:
    @trace("worker")
    async def worker(i: int) -> int:
        async with span(f"step-{i}", span_type=SpanType.LLM):
            # Stagger so the tasks interleave rather than run back to back.
            await asyncio.sleep(0.01 * (i % 3))
        return i

    results = await asyncio.gather(*(worker(i) for i in range(6)))
    assert results == list(range(6))

    traces = global_lens.get_traces()
    assert len(traces) == 6
    for t in traces:
        detail = global_lens.get_trace(t.id)
        assert len(detail.spans) == 2, "each run owns exactly its own root and step"
        root, step = detail.spans
        assert step.parent_span_id == root.id
        assert step.trace_id == root.trace_id == t.id


async def test_concurrent_children_share_one_parent(global_lens: AgentLens) -> None:
    async def tool(i: int) -> int:
        async with span(f"tool-{i}", span_type=SpanType.TOOL):
            await asyncio.sleep(0.01 * (3 - i))
        return i

    @trace("fan-out-agent")
    async def run() -> None:
        await asyncio.gather(*(tool(i) for i in range(3)))

    await run()

    detail = global_lens.get_trace(global_lens.get_traces()[0].id)
    root = detail.spans[0]
    children = [s for s in detail.spans if s.id != root.id]
    assert len(children) == 3
    assert {c.parent_span_id for c in children} == {root.id}
    assert sorted(c.name for c in children) == ["tool-0", "tool-1", "tool-2"]


async def test_nesting_survives_await_boundaries(lens: AgentLens) -> None:
    async def depth_two() -> None:
        async with lens.span("inner"):
            await asyncio.sleep(0)

    async def depth_one() -> None:
        async with lens.span("outer"):
            await asyncio.sleep(0)
            await depth_two()

    async with lens.trace("agent"):
        await depth_one()

    detail = lens.get_trace(lens.get_traces()[0].id)
    spans = {s.name: s for s in detail.spans}
    assert spans["outer"].parent_span_id == spans["agent"].id
    assert spans["inner"].parent_span_id == spans["outer"].id


async def test_traces_from_threads_are_independent(lens: AgentLens) -> None:
    def work(i: int) -> None:
        with lens.trace(f"thread-{i}"):
            with lens.span("step"):
                pass

    await asyncio.gather(*(asyncio.to_thread(work, i) for i in range(4)))

    traces = lens.get_traces()
    assert sorted(t.name for t in traces) == [f"thread-{i}" for i in range(4)]
    for t in traces:
        assert len(lens.get_trace(t.id).spans) == 2
