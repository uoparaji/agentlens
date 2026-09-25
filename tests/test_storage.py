"""SQLite persistence."""

from __future__ import annotations

from pathlib import Path

from agentlens import AgentLens, SpanType
from agentlens.storage import SQLiteStorage


def test_database_is_created_on_first_write(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "traces.db"
    assert not db.exists()

    lens = AgentLens(db)
    with lens.trace("agent"):
        pass
    lens.close()

    assert db.exists()


def test_traces_survive_a_new_connection(db_path: Path) -> None:
    writer = AgentLens(db_path)
    with writer.trace("agent") as root:
        root.set_metadata(topic="quantum")
        with writer.span("llm", span_type=SpanType.LLM) as s:
            s.set_model("demo-4o").set_tokens(prompt_tokens=10, completion_tokens=4)
            s.set_output({"answer": "42"})
    writer.close()

    reader = AgentLens(db_path)
    try:
        t = reader.get_traces()[0]
        assert t.name == "agent"
        assert t.metadata == {"topic": "quantum"}
        assert t.tokens.total_tokens == 14
        detail = reader.get_trace(t.id)
        llm = next(s for s in detail.spans if s.name == "llm")
        assert llm.output == {"answer": "42"}
        assert llm.model == "demo-4o"
        assert llm.start_time.tzinfo is not None
        assert llm.end_time >= llm.start_time
    finally:
        reader.close()


def test_running_traces_are_visible_before_they_finish(lens: AgentLens) -> None:
    with lens.trace("slow-agent"):
        live = lens.get_traces()[0]
        assert live.status == "running"
        assert live.end_time is None
        assert lens.get_trace(live.id).spans[0].status == "running"

    assert lens.get_traces()[0].status == "ok"


def test_list_pagination_search_and_status_filter(lens: AgentLens) -> None:
    for i in range(5):
        with lens.trace(f"agent-{i}"):
            pass
    try:
        with lens.trace("broken-agent"):
            raise RuntimeError("x")
    except RuntimeError:
        pass

    page = lens.storage.list_traces(limit=2)
    assert page.total == 6
    assert len(page.traces) == 2
    assert page.traces[0].name == "broken-agent", "newest first"

    assert lens.storage.list_traces(offset=2, limit=2).traces[0].name == "agent-3"
    assert [t.name for t in lens.storage.list_traces(status="error").traces] == ["broken-agent"]
    assert [t.name for t in lens.storage.list_traces(search="agent-1").traces] == ["agent-1"]


def test_get_span_delete_and_clear(lens: AgentLens) -> None:
    with lens.trace("agent"):
        with lens.span("child"):
            pass
    trace_id = lens.get_traces()[0].id
    child = next(s for s in lens.get_trace(trace_id).spans if s.name == "child")

    assert lens.get_span(child.id).name == "child"
    assert lens.get_span("missing") is None
    assert lens.get_trace("missing") is None

    assert lens.delete_trace(trace_id) is True
    assert lens.delete_trace(trace_id) is False
    assert lens.get_trace(trace_id) is None
    assert lens.get_span(child.id) is None, "spans are removed with their trace"

    with lens.trace("another"):
        pass
    assert lens.clear() == 1
    assert lens.get_traces() == []


def test_stats(lens: AgentLens) -> None:
    with lens.trace("agent"):
        with lens.span("llm", span_type=SpanType.LLM) as s:
            s.set_tokens(total_tokens=25)
    try:
        with lens.trace("broken"):
            raise ValueError("x")
    except ValueError:
        pass

    stats = lens.stats()
    assert stats.trace_count == 2
    assert stats.span_count == 3
    assert stats.error_count == 1
    assert stats.total_tokens == 25
    assert stats.db_path.endswith("traces.db")
    assert stats.db_size_bytes > 0


def test_storage_failures_never_break_the_agent(lens: AgentLens, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(lens.storage, "save_span", explode)
    monkeypatch.setattr(lens.storage, "save_trace", explode)
    monkeypatch.setattr(lens.storage, "finalize_trace", explode)

    with lens.trace("agent"):
        with lens.span("still-runs") as s:
            s.set_output("result")

    assert lens.get_traces() == []


def test_storage_backend_can_be_swapped(db_path: Path) -> None:
    storage = SQLiteStorage(db_path)
    lens = AgentLens(storage=storage)
    try:
        with lens.trace("agent"):
            pass
        assert storage.list_traces().total == 1
    finally:
        lens.close()


def test_many_threads_can_open_the_database_at_once(db_path: Path) -> None:
    """Regression: the first connections used to race on `PRAGMA journal_mode`."""
    import concurrent.futures

    lens = AgentLens(db_path)

    def work(i: int) -> None:
        with lens.trace(f"run-{i}"):
            with lens.span("step", span_type=SpanType.TOOL) as s:
                s.set_output(i)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(work, range(24)))

        page = lens.storage.list_traces(limit=100)
        assert page.total == 24
        assert all(t.status == "ok" and t.span_count == 2 for t in page.traces)
    finally:
        lens.close()


def test_two_storage_instances_share_one_file(db_path: Path) -> None:
    """The dashboard reads the same database an agent is writing to."""
    writer = AgentLens(db_path)
    reader = SQLiteStorage(db_path)
    try:
        with writer.trace("live-run"):
            assert reader.list_traces().traces[0].status == "running"
        assert reader.list_traces().traces[0].status == "ok"
    finally:
        writer.close()
        reader.close()
