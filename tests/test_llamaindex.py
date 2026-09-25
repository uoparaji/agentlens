"""The LlamaIndex integration.

These tests run against LlamaIndex's own mock LLM and embedding model, so they
need no API keys and no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agentlens import AgentLens

pytest.importorskip("llama_index.core", reason="requires the 'llamaindex' extra")

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM

from agentlens.integrations.llamaindex import (
    _clean_model,
    _span_type_for,
    _split_span_id,
    _token_usage,
    instrument,
    uninstrument,
)


@pytest.fixture(autouse=True)
def mock_models() -> Iterator[None]:
    # Read the private slots: the public properties resolve a default LLM,
    # which would try to import the OpenAI integration.
    previous_llm = Settings._llm
    previous_embed = Settings._embed_model
    Settings.llm = MockLLM(max_tokens=16)
    Settings.embed_model = MockEmbedding(embed_dim=8)
    yield
    Settings._llm = previous_llm
    Settings._embed_model = previous_embed


@pytest.fixture
def instrumented(db_path: Path) -> Iterator[AgentLens]:
    lens = AgentLens(db_path)
    instrument(lens)
    yield lens
    uninstrument()
    lens.close()


def _index() -> VectorStoreIndex:
    return VectorStoreIndex.from_documents(
        [Document(text="AgentLens records agent runs."), Document(text="Spans form a tree.")]
    )


def test_span_names_and_types_are_mapped(instrumented: AgentLens) -> None:
    index = _index()
    answer = index.as_query_engine().query("What does AgentLens do?")
    assert str(answer)

    query_trace = next(t for t in instrumented.get_traces() if t.name.endswith(".query"))
    detail = instrumented.get_trace(query_trace.id)
    by_name = {span.name: span for span in detail.spans}

    # Names are readable: the uuid LlamaIndex appends is stripped.
    assert "RetrieverQueryEngine.query" in by_name
    assert all("-" not in name.split(".")[-1] for name in by_name)

    assert by_name["RetrieverQueryEngine.query"].span_type == "workflow"
    assert by_name["VectorIndexRetriever.retrieve"].span_type == "retrieval"
    assert any(span.span_type == "llm" for span in detail.spans)

    # LlamaIndex's own parent/child structure is preserved.
    root = detail.spans[0]
    assert root.parent_span_id is None
    assert by_name["VectorIndexRetriever._retrieve"].parent_span_id == (
        by_name["VectorIndexRetriever.retrieve"].id
    )
    assert all(span.duration_ms is not None for span in detail.spans)
    assert query_trace.status == "ok"


def test_llamaindex_spans_nest_inside_an_existing_trace(instrumented: AgentLens) -> None:
    index = _index()
    before = len(instrumented.get_traces())

    with instrumented.trace("my-agent"):
        with instrumented.span("answer_question", span_type="tool"):
            index.as_query_engine().query("anything")

    traces = instrumented.get_traces()
    assert len(traces) == before + 1, "the query must not start its own run"

    detail = instrumented.get_trace(traces[0].id)
    names = [span.name for span in detail.spans]
    assert names[0] == "my-agent"
    assert "answer_question" in names
    assert "RetrieverQueryEngine.query" in names

    by_id = {span.id: span for span in detail.spans}
    query_span = next(s for s in detail.spans if s.name == "RetrieverQueryEngine.query")
    parent = by_id[query_span.parent_span_id]
    assert parent.name == "answer_question"


def test_errors_inside_llamaindex_are_recorded(instrumented: AgentLens) -> None:
    index = _index()
    engine = index.as_query_engine()

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("retriever exploded")

    engine.retriever._retrieve = explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="retriever exploded"):
        engine.query("anything")

    trace = next(t for t in instrumented.get_traces() if t.name.endswith(".query"))
    assert trace.status == "error"
    detail = instrumented.get_trace(trace.id)
    assert any(span.error and span.error.type == "RuntimeError" for span in detail.spans)


def test_a_broken_tracer_never_breaks_the_query(instrumented: AgentLens, monkeypatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("tracer is broken")

    monkeypatch.setattr(instrumented.tracer, "start_span", explode)
    monkeypatch.setattr(instrumented.tracer, "start_trace", explode)

    # The user's query still returns normally.
    assert str(_index().as_query_engine().query("still works"))


def test_instrument_is_idempotent(instrumented: AgentLens) -> None:
    assert instrument(instrumented) is instrument(instrumented)


def test_span_id_and_type_mapping() -> None:
    assert _split_span_id("OpenAI.chat-6f3c9a2e-1111-2222-3333") == "OpenAI.chat"
    assert _split_span_id("plain") == "plain"
    assert _span_type_for("OpenAI.chat") == "llm"
    assert _span_type_for("VectorIndexRetriever.retrieve") == "retrieval"
    assert _span_type_for("FunctionTool.call") == "tool"
    assert _span_type_for("ReActAgent.run_step") == "agent"
    assert _span_type_for("RetrieverQueryEngine.query") == "workflow"
    assert _span_type_for("SomeThing.frobnicate") == "custom"


def test_token_usage_extraction() -> None:
    assert _token_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 4}}) == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": None,
    }
    # Anthropic-style naming.
    assert _token_usage({"usage": {"input_tokens": 7, "output_tokens": 2}})["prompt_tokens"] == 7
    assert _token_usage({}) == {}
    assert _token_usage(None) == {}
    assert _token_usage("nonsense") == {}


def test_placeholder_models_are_ignored() -> None:
    assert _clean_model("gpt-4o-mini") == "gpt-4o-mini"
    assert _clean_model("unknown") is None
    assert _clean_model(None) is None
