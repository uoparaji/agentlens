"""The public SDK: ``trace``, ``span``, ``configure`` and :class:`AgentLens`."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Union, overload

from agentlens.config import AgentLensConfig, Redactor
from agentlens.models import Span, SpanType, Trace, TraceDetail
from agentlens.storage.base import Storage, StorageStats
from agentlens.storage.sqlite import SQLiteStorage
from agentlens.tracer import SpanHandle, Tracer, _build_scope, _Scope

__all__ = [
    "AgentLens",
    "configure",
    "get_config",
    "get_tracer",
    "shutdown",
    "span",
    "trace",
]

F = TypeVar("F", bound=Callable[..., Any])

_UNSET: Any = object()
_lock = threading.Lock()
_config: AgentLensConfig = AgentLensConfig.from_env()
_tracer: Optional[Tracer] = None


# ---------------------------------------------------------------------------
# global tracer
# ---------------------------------------------------------------------------


def get_config() -> AgentLensConfig:
    """The configuration used by the module-level :func:`trace` / :func:`span`."""
    return _config


def get_tracer() -> Tracer:
    """The process-wide default tracer, created on first use."""
    global _tracer
    if _tracer is None:
        with _lock:
            if _tracer is None:
                _tracer = Tracer(_config, SQLiteStorage(_config.db_path))
    return _tracer


def configure(
    *,
    enabled: Optional[bool] = None,
    db_path: Optional[Union[str, Path]] = None,
    capture_io: Optional[bool] = None,
    capture_traceback: Optional[bool] = None,
    max_value_chars: Optional[int] = None,
    max_items: Optional[int] = None,
    redactor: Optional[Redactor] = _UNSET,
) -> AgentLensConfig:
    """Configure the default tracer. Call once, early, before tracing.

    Every argument is optional; omitted ones keep their current value.

    ::

        import agentlens

        agentlens.configure(
            db_path="./traces.db",
            capture_io=False,                       # names and timings only
            redactor=agentlens.redact_keys(["api_key", "email"]),
        )
    """
    global _config, _tracer
    with _lock:
        overrides: dict[str, Any] = {
            "enabled": enabled,
            "db_path": db_path,
            "capture_io": capture_io,
            "capture_traceback": capture_traceback,
            "max_value_chars": max_value_chars,
            "max_items": max_items,
        }
        new = _config.merged(**overrides)
        if redactor is not _UNSET:
            new.redactor = redactor
        rebuild = _tracer is None or new.db_path != _config.db_path
        _config = new
        if rebuild or _tracer is None:
            if _tracer is not None:
                _tracer.close()
            _tracer = Tracer(_config, SQLiteStorage(_config.db_path))
        else:
            _tracer.config = _config
    return _config


def shutdown() -> None:
    """Close the default tracer's storage. Mostly useful in tests."""
    global _tracer
    with _lock:
        if _tracer is not None:
            _tracer.close()
            _tracer = None


# ---------------------------------------------------------------------------
# decorators / context managers
# ---------------------------------------------------------------------------


@overload
def trace(name_or_func: F) -> F: ...


@overload
def trace(
    name_or_func: Optional[str] = ...,
    *,
    span_type: str = ...,
    metadata: Optional[dict[str, Any]] = ...,
    input: Any = ...,
) -> _Scope: ...


def trace(
    name_or_func: Any = None,
    *,
    span_type: str = SpanType.AGENT,
    metadata: Optional[dict[str, Any]] = None,
    input: Any = None,
) -> Any:
    """Record one agent run.

    Use it as a decorator, with or without arguments::

        @trace
        def research_agent(topic: str): ...

        @trace("research-agent", metadata={"version": 2})
        async def research_agent(topic: str): ...

    or as a context manager::

        with trace("research-agent") as run:
            run.set_metadata(topic=topic)

    Nesting a traced call inside another trace records a nested *agent* span
    (a handoff) rather than starting a second run.
    """
    return _build_scope(None, name_or_func, "trace", span_type, metadata, input)


@overload
def span(name_or_func: F) -> F: ...


@overload
def span(
    name_or_func: Optional[str] = ...,
    *,
    span_type: str = ...,
    metadata: Optional[dict[str, Any]] = ...,
    input: Any = ...,
) -> _Scope: ...


def span(
    name_or_func: Any = None,
    *,
    span_type: str = SpanType.CUSTOM,
    metadata: Optional[dict[str, Any]] = None,
    input: Any = None,
) -> Any:
    """Record one step inside a trace.

    ::

        with span("search", span_type="tool", metadata={"query": topic}) as s:
            results = search(topic)
            s.set_output(results)

    Spans nest automatically -- a span opened inside another becomes its child,
    including across ``await`` points and concurrent tasks.
    """
    return _build_scope(None, name_or_func, "span", span_type, metadata, input)


# ---------------------------------------------------------------------------
# instance facade
# ---------------------------------------------------------------------------


class AgentLens:
    """An isolated tracer with its own database.

    The module-level helpers are usually enough, but an instance is handy for
    tests, notebooks, or running two agents into separate databases::

        lens = AgentLens("./research.db")

        with lens.trace("research-agent"):
            ...

        print(lens.get_traces()[0].duration_ms)
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        *,
        enabled: Optional[bool] = None,
        capture_io: Optional[bool] = None,
        capture_traceback: Optional[bool] = None,
        max_value_chars: Optional[int] = None,
        max_items: Optional[int] = None,
        redactor: Optional[Redactor] = None,
        storage: Optional[Storage] = None,
    ) -> None:
        config = AgentLensConfig.from_env().merged(
            enabled=enabled,
            db_path=db_path,
            capture_io=capture_io,
            capture_traceback=capture_traceback,
            max_value_chars=max_value_chars,
            max_items=max_items,
        )
        config.redactor = redactor
        self.config = config
        self.storage: Storage = storage or SQLiteStorage(config.db_path)
        self.tracer = Tracer(config, self.storage)

    # -- tracing -------------------------------------------------------------

    def trace(
        self,
        name_or_func: Any = None,
        *,
        span_type: str = SpanType.AGENT,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> Any:
        """Same as :func:`agentlens.trace`, bound to this instance."""
        return self.tracer.trace(name_or_func, span_type=span_type, metadata=metadata, input=input)

    def span(
        self,
        name_or_func: Any = None,
        *,
        span_type: str = SpanType.CUSTOM,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> Any:
        """Same as :func:`agentlens.span`, bound to this instance."""
        return self.tracer.span(name_or_func, span_type=span_type, metadata=metadata, input=input)

    def start_span(self, name: str, **kwargs: Any) -> SpanHandle:
        """Low-level span creation; you must call ``.end()`` yourself."""
        return self.tracer.start_span(name, **kwargs)

    # -- reading -------------------------------------------------------------

    def get_traces(self, limit: int = 50, offset: int = 0) -> list[Trace]:
        """Most recent runs first."""
        return self.storage.list_traces(limit=limit, offset=offset).traces

    def get_trace(self, trace_id: str) -> Optional[TraceDetail]:
        """One run with all of its spans."""
        return self.storage.get_trace(trace_id)

    def get_span(self, span_id: str) -> Optional[Span]:
        return self.storage.get_span(span_id)

    def delete_trace(self, trace_id: str) -> bool:
        """Delete one run and its spans. Returns whether it existed."""
        return self.storage.delete_trace(trace_id)

    def stats(self) -> StorageStats:
        return self.storage.stats()

    def clear(self) -> int:
        """Delete every stored run. Returns how many were removed."""
        return self.storage.clear()

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self.tracer.close()

    def __enter__(self) -> AgentLens:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
