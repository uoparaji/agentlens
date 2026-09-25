"""Core tracing behaviour: trees, decorators, context managers, errors."""

from __future__ import annotations

import pytest

import agentlens
from agentlens import AgentLens, SpanType, span, trace


def _by_name(detail, name):
    return next(s for s in detail.spans if s.name == name)


def test_context_manager_creates_a_trace_with_a_root_span(lens: AgentLens) -> None:
    with lens.trace("research-agent"):
        pass

    traces = lens.get_traces()
    assert len(traces) == 1
    assert traces[0].name == "research-agent"
    assert traces[0].status == "ok"
    assert traces[0].duration_ms is not None and traces[0].duration_ms >= 0

    detail = lens.get_trace(traces[0].id)
    assert [s.name for s in detail.spans] == ["research-agent"]
    assert detail.spans[0].span_type == SpanType.AGENT
    assert detail.spans[0].parent_span_id is None


def test_spans_nest_into_a_tree(lens: AgentLens) -> None:
    with lens.trace("agent"):
        with lens.span("search", span_type=SpanType.TOOL):
            with lens.span("http", span_type=SpanType.CUSTOM):
                pass
        with lens.span("llm", span_type=SpanType.LLM):
            pass

    detail = lens.get_trace(lens.get_traces()[0].id)
    root, search, http, llm = (_by_name(detail, n) for n in ("agent", "search", "http", "llm"))
    assert root.parent_span_id is None
    assert search.parent_span_id == root.id
    assert http.parent_span_id == search.id
    assert llm.parent_span_id == root.id
    assert detail.span_count == 4


def test_decorator_captures_arguments_and_return_value(global_lens: AgentLens) -> None:
    @trace
    def research_agent(topic: str, depth: int = 2) -> str:
        return f"{topic}:{depth}"

    assert research_agent("quantum") == "quantum:2"

    detail = global_lens.get_trace(global_lens.get_traces()[0].id)
    root = detail.spans[0]
    assert root.name == "research_agent"
    assert root.input == {"topic": "quantum", "depth": 2}
    assert root.output == "quantum:2"


def test_decorator_accepts_a_name_and_metadata(global_lens: AgentLens) -> None:
    @trace("named-agent", metadata={"version": 2})
    def run() -> None:
        pass

    run()
    t = global_lens.get_traces()[0]
    assert t.name == "named-agent"
    assert t.metadata == {"version": 2}


def test_span_decorator_records_a_child(global_lens: AgentLens) -> None:
    @span("tool-call", span_type=SpanType.TOOL)
    def search(q: str) -> list:
        return [q]

    @trace("agent")
    def run() -> None:
        search("hello")

    run()
    detail = global_lens.get_trace(global_lens.get_traces()[0].id)
    child = _by_name(detail, "tool-call")
    assert child.span_type == SpanType.TOOL
    assert child.input == {"q": "hello"}
    assert child.output == ["hello"]


def test_exception_is_recorded_and_reraised(lens: AgentLens) -> None:
    with pytest.raises(ValueError, match="kaboom"):
        with lens.trace("agent"):
            with lens.span("boom", span_type=SpanType.TOOL):
                raise ValueError("kaboom")

    t = lens.get_traces()[0]
    assert t.status == "error"
    assert t.error is not None and t.error.type == "ValueError"

    detail = lens.get_trace(t.id)
    boom = _by_name(detail, "boom")
    assert boom.status == "error"
    assert boom.error.message == "kaboom"
    assert "ValueError" in boom.error.traceback


def test_error_in_child_does_not_mark_sibling_failed(lens: AgentLens) -> None:
    with lens.trace("agent"):
        with pytest.raises(RuntimeError):
            with lens.span("bad"):
                raise RuntimeError("nope")
        with lens.span("good"):
            pass

    detail = lens.get_trace(lens.get_traces()[0].id)
    assert _by_name(detail, "bad").status == "error"
    assert _by_name(detail, "good").status == "ok"
    # The exception was handled inside the trace, so the run itself succeeded.
    assert detail.status == "ok"


def test_nested_trace_becomes_an_agent_handoff_span(global_lens: AgentLens) -> None:
    @trace("writer-agent")
    def writer() -> str:
        return "draft"

    @trace("editor-agent")
    def editor() -> str:
        return writer() + "+edited"

    editor()

    traces = global_lens.get_traces()
    assert len(traces) == 1, "a nested @trace must not start a second run"
    detail = global_lens.get_trace(traces[0].id)
    writer_span = _by_name(detail, "writer-agent")
    assert writer_span.span_type == SpanType.AGENT
    assert writer_span.parent_span_id == _by_name(detail, "editor-agent").id


def test_tokens_and_model_roll_up_to_the_trace(lens: AgentLens) -> None:
    with lens.trace("agent"):
        with lens.span("llm-1", span_type=SpanType.LLM) as s:
            s.set_model("demo-4o").set_tokens(prompt_tokens=100, completion_tokens=20)
        with lens.span("llm-2", span_type=SpanType.LLM) as s:
            s.set_model("demo-4o").set_tokens(prompt_tokens=50, completion_tokens=10)

    t = lens.get_traces()[0]
    assert t.model == "demo-4o"
    assert t.tokens.prompt_tokens == 150
    assert t.tokens.completion_tokens == 30
    assert t.tokens.total_tokens == 180


def test_span_setters_and_manual_child(lens: AgentLens) -> None:
    with lens.trace("agent") as root:
        root.set_metadata(user="ada", retries=1)
        child = root.start_child("manual", span_type=SpanType.RETRIEVAL, input={"k": 3})
        child.set_output(["doc-1"]).end()

    detail = lens.get_trace(lens.get_traces()[0].id)
    manual = _by_name(detail, "manual")
    assert manual.span_type == SpanType.RETRIEVAL
    assert manual.input == {"k": 3}
    assert manual.output == ["doc-1"]
    assert manual.status == "ok"
    assert detail.spans[0].metadata == {"user": "ada", "retries": 1}


def test_current_span_is_reachable_from_nested_code(global_lens: AgentLens) -> None:
    def deep_helper() -> None:
        current = agentlens.current_span()
        assert current is not None
        current.set_tokens(prompt_tokens=7)

    @trace("agent")
    def run() -> None:
        with span("llm", span_type=SpanType.LLM):
            deep_helper()

    run()
    detail = global_lens.get_trace(global_lens.get_traces()[0].id)
    assert _by_name(detail, "llm").tokens.prompt_tokens == 7
    assert agentlens.current_span() is None


def test_span_outside_a_trace_is_dropped_but_code_still_runs(global_lens: AgentLens) -> None:
    with span("orphan", span_type=SpanType.TOOL) as s:
        assert s.recording is False
        s.set_output("still works")

    assert global_lens.get_traces() == []


def test_generator_span_covers_the_whole_iteration(global_lens: AgentLens) -> None:
    @trace("agent")
    def run() -> list:
        @span("stream", span_type=SpanType.LLM)
        def stream():
            yield from ("a", "b", "c")

        return list(stream())

    assert run() == ["a", "b", "c"]
    detail = global_lens.get_trace(global_lens.get_traces()[0].id)
    assert _by_name(detail, "stream").status == "ok"


def test_ending_a_span_twice_is_a_no_op(lens: AgentLens) -> None:
    with lens.trace("agent") as root:
        child = root.start_child("once")
        child.end("first")
        child.end("second")

    detail = lens.get_trace(lens.get_traces()[0].id)
    assert _by_name(detail, "once").output == "first"


def test_decorators_work_the_same_on_an_instance(lens: AgentLens) -> None:
    """`@lens.trace` must behave exactly like the module-level `@trace`."""

    @lens.trace
    def bare(x: int) -> int:
        @lens.span
        def helper(y: int) -> int:
            return y + 1

        return helper(x) * 2

    assert bare(20) == 42

    detail = lens.get_trace(lens.get_traces()[0].id)
    assert [s.name for s in detail.spans] == ["bare", "helper"]
    assert detail.spans[0].input == {"x": 20}
    assert detail.spans[0].output == 42
    assert detail.spans[1].output == 21
