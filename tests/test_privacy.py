"""Privacy controls: capture toggles and redaction hooks."""

from __future__ import annotations

from pathlib import Path

import agentlens
from agentlens import (
    REDACTED,
    AgentLens,
    AgentLensConfig,
    SpanType,
    redact_keys,
    span,
    trace,
)


def test_capture_io_disabled_keeps_structure_but_drops_payloads(db_path: Path) -> None:
    lens = AgentLens(db_path, capture_io=False)
    try:
        with lens.trace("agent", input={"prompt": "my secret prompt"}) as root:
            root.set_output("sensitive answer")
            with lens.span("llm", span_type=SpanType.LLM) as s:
                s.set_input("another secret").set_output("more secrets")
                s.set_model("demo-4o").set_tokens(prompt_tokens=10, completion_tokens=2)
                s.set_metadata(temperature=0.2)

        detail = lens.get_trace(lens.get_traces()[0].id)
        llm = next(s for s in detail.spans if s.name == "llm")
        assert llm.input is None and llm.output is None
        assert detail.spans[0].input is None and detail.spans[0].output is None
        # Everything that is not a payload is still recorded.
        assert llm.model == "demo-4o"
        assert llm.tokens.total_tokens == 12
        assert llm.metadata == {"temperature": 0.2}
        assert llm.duration_ms is not None
    finally:
        lens.close()


def test_capture_io_disabled_via_environment(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTLENS_CAPTURE_IO", "0")
    lens = AgentLens(db_path)
    try:

        @lens.trace("agent")
        def run(secret: str) -> str:
            return secret

        run("hunter2")
        detail = lens.get_trace(lens.get_traces()[0].id)
        assert detail.spans[0].input is None
        assert detail.spans[0].output is None
    finally:
        lens.close()


def test_redactor_can_mask_values(db_path: Path) -> None:
    lens = AgentLens(db_path, redactor=redact_keys(["api_key", "password"]))
    try:
        with lens.trace("agent") as root:
            root.set_input({"api_key": "sk-live-123", "topic": "quantum"})
            root.set_metadata(nested={"user": {"password": "hunter2", "name": "ada"}})

        detail = lens.get_trace(lens.get_traces()[0].id)
        root_span = detail.spans[0]
        assert root_span.input == {"api_key": REDACTED, "topic": "quantum"}
        assert root_span.metadata["nested"]["user"] == {"password": REDACTED, "name": "ada"}
    finally:
        lens.close()


def test_custom_redactor_sees_field_and_span(db_path: Path) -> None:
    seen = []

    def redactor(field, value, span_model):
        seen.append((field, span_model.name, span_model.span_type))
        return "<dropped>" if field == "output" else value

    lens = AgentLens(db_path, redactor=redactor)
    try:
        with lens.trace("agent"):
            with lens.span("llm", span_type=SpanType.LLM) as s:
                s.set_input("prompt").set_output("completion")

        detail = lens.get_trace(lens.get_traces()[0].id)
        llm = next(s for s in detail.spans if s.name == "llm")
        assert llm.input == "prompt"
        assert llm.output == "<dropped>"
        assert ("output", "llm", SpanType.LLM) in seen
    finally:
        lens.close()


def test_a_broken_redactor_drops_the_value_instead_of_raising(db_path: Path) -> None:
    def redactor(field, value, span_model):
        raise RuntimeError("bad hook")

    lens = AgentLens(db_path, redactor=redactor)
    try:
        with lens.trace("agent") as root:
            root.set_input("secret")

        assert lens.get_trace(lens.get_traces()[0].id).spans[0].input == "<redaction failed>"
    finally:
        lens.close()


def test_disabled_tracing_is_a_no_op(db_path: Path) -> None:
    lens = AgentLens(db_path, enabled=False)
    try:

        @lens.trace("agent")
        def run(x: int) -> int:
            with lens.span("step", span_type=SpanType.TOOL) as s:
                s.set_output(x * 2)
            return x * 2

        assert run(21) == 42
        assert not db_path.exists(), "a disabled tracer must not write anything"
        assert lens.get_traces() == []
    finally:
        lens.close()


def test_disabled_via_environment(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTLENS_DISABLED", "1")
    assert AgentLensConfig.from_env().enabled is False

    lens = AgentLens(db_path)  # reads the environment at construction time
    try:

        @lens.trace("agent")
        def run() -> str:
            with lens.span("step"):
                return "ok"

        assert run() == "ok"
        assert lens.get_traces() == []
    finally:
        lens.close()


def test_configure_can_disable_the_global_tracer(db_path: Path) -> None:
    agentlens.configure(db_path=db_path, enabled=False)
    try:

        @trace("agent")
        def run() -> str:
            with span("step"):
                return "ok"

        assert run() == "ok"
        assert AgentLens(db_path).get_traces() == []
    finally:
        agentlens.configure(enabled=True)
        agentlens.shutdown()


def test_long_values_are_truncated(db_path: Path) -> None:
    lens = AgentLens(db_path, max_value_chars=50)
    try:
        with lens.trace("agent") as root:
            root.set_output("x" * 5_000)

        stored = lens.get_trace(lens.get_traces()[0].id).spans[0].output
        assert stored.startswith("x" * 50)
        assert "truncated" in stored
        assert len(stored) < 200
    finally:
        lens.close()
