"""The tracing engine: traces, spans, decorators and context managers.

Everything a user touches goes through :class:`Tracer`. It is deliberately
small: start a span, end a span, write it somewhere. Framework integrations
build on exactly the same public surface.
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
import traceback as tb_module
import uuid
from contextvars import Token
from datetime import timedelta
from types import TracebackType
from typing import (
    Any,
    Callable,
    NamedTuple,
    Optional,
    TypeVar,
    cast,
)

from agentlens.config import AgentLensConfig
from agentlens.context import current_span as _current_span
from agentlens.context import current_trace as _current_trace
from agentlens.context import pop_span, pop_trace, push_span, push_trace
from agentlens.models import Span, SpanError, SpanType, TokenUsage, Trace, utc_now
from agentlens.serialization import to_jsonable
from agentlens.storage.base import Storage

__all__ = ["SpanHandle", "TraceHandle", "Tracer"]

logger = logging.getLogger("agentlens")

F = TypeVar("F", bound=Callable[..., Any])


def _new_id() -> str:
    return uuid.uuid4().hex


class _Recorder:
    """Shared mutation helpers for trace and span handles."""

    _tracer: Tracer
    recording: bool

    def _clean(self, field: str, value: Any, span: Span) -> Any:
        cfg = self._tracer.config
        if cfg.redactor is not None:
            try:
                value = cfg.redactor(field, value, span)
            except Exception:
                logger.warning("agentlens: redactor raised, dropping %s", field, exc_info=True)
                return "<redaction failed>"
        return to_jsonable(value, max_chars=cfg.max_value_chars, max_items=cfg.max_items)


class SpanHandle(_Recorder):
    """A live span. Yielded by ``with span(...)`` and returned by the SDK.

    All setters are safe to call on a non-recording handle (when tracing is
    disabled), in which case they do nothing.
    """

    __slots__ = ("_ended", "_start_perf", "_tracer", "recording", "span")

    def __init__(self, tracer: Tracer, span: Span, *, recording: bool = True) -> None:
        self._tracer = tracer
        self.span = span
        self.recording = recording
        self._start_perf = time.perf_counter()
        self._ended = False

    # -- identity ------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.span.id

    @property
    def trace_id(self) -> str:
        return self.span.trace_id

    @property
    def name(self) -> str:
        return self.span.name

    # -- mutation ------------------------------------------------------------

    def set_input(self, value: Any) -> SpanHandle:
        """Record the span's input. Ignored when ``capture_io`` is off."""
        if self.recording and self._tracer.config.capture_io:
            self.span.input = self._clean("input", value, self.span)
        return self

    def set_output(self, value: Any) -> SpanHandle:
        """Record the span's output. Ignored when ``capture_io`` is off."""
        if self.recording and self._tracer.config.capture_io:
            self.span.output = self._clean("output", value, self.span)
        return self

    def set_metadata(self, _values: Optional[dict[str, Any]] = None, **kwargs: Any) -> SpanHandle:
        """Merge key/value metadata into the span."""
        if not self.recording:
            return self
        merged = {**(_values or {}), **kwargs}
        if merged:
            cleaned = self._clean("metadata", merged, self.span)
            if isinstance(cleaned, dict):
                self.span.metadata.update(cleaned)
        return self

    def set_model(self, model: Optional[str]) -> SpanHandle:
        """Record which model this span used (shown on the run list)."""
        if self.recording and model:
            self.span.model = str(model)
        return self

    def set_tokens(
        self,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> SpanHandle:
        """Record token usage. Totals roll up to the trace automatically."""
        if not self.recording:
            return self
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ).resolved()
        self.span.tokens = usage if not usage.is_empty() else None
        return self

    def record_error(self, exc: BaseException) -> SpanHandle:
        """Mark the span as failed and attach the exception."""
        if not self.recording:
            return self
        self.span.status = "error"
        self.span.error = SpanError(
            type=type(exc).__name__,
            message=str(exc) or type(exc).__name__,
            traceback=(
                "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))[-8_000:]
                if self._tracer.config.capture_traceback
                else None
            ),
        )
        return self

    # -- children ------------------------------------------------------------

    def start_child(
        self,
        name: str,
        *,
        span_type: str = SpanType.CUSTOM,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> SpanHandle:
        """Start a child span explicitly parented to this one.

        Unlike ``with span(...)`` this does not touch the ambient context, so
        it is the right primitive for framework integrations that receive
        start/end callbacks out of band. You must call :meth:`end` yourself.
        """
        return self._tracer.start_span(
            name,
            span_type=span_type,
            metadata=metadata,
            input=input,
            parent=self,
        )

    # -- lifecycle -----------------------------------------------------------

    def end(self, output: Any = None, *, error: Optional[BaseException] = None) -> SpanHandle:
        """Finish the span and persist it. Calling twice is a no-op."""
        if self._ended:
            return self
        self._ended = True
        if not self.recording:
            return self
        if error is not None:
            self.record_error(error)
        if output is not None:
            self.set_output(output)
        duration_ms = (time.perf_counter() - self._start_perf) * 1_000
        self.span.duration_ms = duration_ms
        self.span.end_time = self.span.start_time + timedelta(milliseconds=duration_ms)
        if self.span.status == "running":
            self.span.status = "ok"
        self._tracer._write_span(self.span)
        return self


class TraceHandle(_Recorder):
    """A live trace: one complete agent execution plus its root span."""

    __slots__ = ("_ended", "_start_perf", "_tracer", "recording", "root", "trace")

    def __init__(
        self, tracer: Tracer, trace: Trace, root: SpanHandle, *, recording: bool = True
    ) -> None:
        self._tracer = tracer
        self.trace = trace
        self.root = root
        self.recording = recording
        self._start_perf = time.perf_counter()
        self._ended = False

    @property
    def id(self) -> str:
        return self.trace.id

    @property
    def name(self) -> str:
        return self.trace.name

    def set_metadata(self, _values: Optional[dict[str, Any]] = None, **kwargs: Any) -> TraceHandle:
        if not self.recording:
            return self
        merged = {**(_values or {}), **kwargs}
        if merged:
            cleaned = self._clean("metadata", merged, self.root.span)
            if isinstance(cleaned, dict):
                self.trace.metadata.update(cleaned)
        return self

    def end(self, output: Any = None, *, error: Optional[BaseException] = None) -> TraceHandle:
        if self._ended:
            return self
        self._ended = True
        self.root.end(output, error=error)
        if not self.recording:
            return self
        duration_ms = (time.perf_counter() - self._start_perf) * 1_000
        self.trace.duration_ms = duration_ms
        self.trace.end_time = self.trace.start_time + timedelta(milliseconds=duration_ms)
        self.trace.status = self.root.span.status
        self.trace.error = self.root.span.error
        self.trace.model = self.root.span.model
        # Metadata attached to the run's root span belongs to the run itself.
        self.trace.metadata = {**self.root.span.metadata, **self.trace.metadata}
        self._tracer._finalize_trace(self.trace)
        return self


class _Active(NamedTuple):
    """Bookkeeping for one entered scope."""

    span: SpanHandle
    span_token: Token[Optional[SpanHandle]]
    trace: Optional[TraceHandle]
    trace_token: Optional[Token[Optional[TraceHandle]]]


class _Scope:
    """Context manager + decorator returned by ``trace()`` and ``span()``.

    Works with ``with``, ``async with``, and as a decorator on sync functions,
    coroutine functions, generators and async generators. A scope object holds
    one pending span; the decorator builds a fresh scope per call, so
    concurrent invocations never share state.
    """

    __slots__ = ("_kind", "_kwargs", "_name", "_stack", "_tracer")

    def __init__(
        self,
        tracer: Optional[Tracer],
        name: Optional[str],
        kind: str,
        **kwargs: Any,
    ) -> None:
        self._tracer = tracer
        self._name = name
        self._kind = kind
        self._kwargs = kwargs
        self._stack: list[_Active] = []

    # -- resolution ----------------------------------------------------------

    def _resolve(self) -> Tracer:
        if self._tracer is not None:
            return self._tracer
        from agentlens.sdk import get_tracer

        return get_tracer()

    def _begin(self, name: Optional[str] = None, input: Any = None) -> SpanHandle:
        tracer = self._resolve()
        kwargs = dict(self._kwargs)
        if input is not None and kwargs.get("input") is None:
            kwargs["input"] = input
        final_name = name or self._name or "unnamed"

        if self._kind == "trace" and _current_trace() is None:
            trace_handle = tracer.start_trace(final_name, **kwargs)
            span_handle = trace_handle.root
            span_token = push_span(span_handle)
            trace_token = push_trace(trace_handle)
            self._stack.append(_Active(span_handle, span_token, trace_handle, trace_token))
            return span_handle

        # A trace opened inside another trace is a nested agent -- a handoff --
        # rather than a second root, so it becomes an ordinary child span.
        span_handle = tracer.start_span(final_name, **kwargs)
        span_token = push_span(span_handle)
        self._stack.append(_Active(span_handle, span_token, None, None))
        return span_handle

    def _finish(self, exc: Optional[BaseException]) -> None:
        if not self._stack:
            return
        active = self._stack.pop()
        if active.trace_token is not None:
            pop_trace(active.trace_token)
        pop_span(active.span_token)
        if active.trace is not None:
            active.trace.end(error=exc)
        else:
            active.span.end(error=exc)

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> SpanHandle:
        return self._begin()

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self._finish(exc)

    async def __aenter__(self) -> SpanHandle:
        return self._begin()

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self._finish(exc)

    # -- decorator -----------------------------------------------------------

    def _fork(self, name: Optional[str]) -> _Scope:
        return _Scope(self._tracer, name, self._kind, **self._kwargs)

    def __call__(self, func: F) -> F:
        name = self._name or _default_name(func)

        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def async_gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                scope = self._fork(name)
                scope._begin(input=_bind_arguments(func, args, kwargs))
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                except GeneratorExit:
                    scope._finish(None)
                    raise
                except BaseException as exc:
                    scope._finish(exc)
                    raise
                scope._finish(None)

            return cast(F, async_gen_wrapper)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                scope = self._fork(name)
                handle = scope._begin(input=_bind_arguments(func, args, kwargs))
                try:
                    result = await func(*args, **kwargs)
                except BaseException as exc:
                    scope._finish(exc)
                    raise
                handle.set_output(result)
                scope._finish(None)
                return result

            return cast(F, async_wrapper)

        if inspect.isgeneratorfunction(func):

            @functools.wraps(func)
            def gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                scope = self._fork(name)
                scope._begin(input=_bind_arguments(func, args, kwargs))
                try:
                    yield from func(*args, **kwargs)
                except GeneratorExit:
                    scope._finish(None)
                    raise
                except BaseException as exc:
                    scope._finish(exc)
                    raise
                scope._finish(None)

            return cast(F, gen_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            scope = self._fork(name)
            handle = scope._begin(input=_bind_arguments(func, args, kwargs))
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                scope._finish(exc)
                raise
            handle.set_output(result)
            scope._finish(None)
            return result

        return cast(F, wrapper)


def _build_scope(
    tracer: Optional[Tracer],
    name_or_func: Any,
    kind: str,
    span_type: str,
    metadata: Optional[dict[str, Any]],
    input: Any,
) -> Any:
    """Shared by ``trace``/``span`` at module level and on a tracer.

    Returns a wrapped function when used as a bare decorator, and a scope
    (context manager, or decorator factory) otherwise.
    """
    scope = _Scope(
        tracer,
        None if callable(name_or_func) else name_or_func,
        kind,
        span_type=span_type,
        metadata=metadata,
        input=input,
    )
    return scope(name_or_func) if callable(name_or_func) else scope


def _default_name(func: Callable[..., Any]) -> str:
    """A readable span name for a decorated function.

    ``__qualname__`` keeps the class for methods (``Crew.kickoff``) but adds
    noise for closures (``outer.<locals>.inner``), so locals are stripped.
    """
    qualname = getattr(func, "__qualname__", "") or getattr(func, "__name__", "") or "unnamed"
    if "<locals>." in qualname:
        qualname = qualname.rsplit("<locals>.", 1)[1]
    return qualname


def _bind_arguments(func: Callable[..., Any], args: Any, kwargs: Any) -> Optional[dict[str, Any]]:
    """Represent a call's arguments as a dict, skipping ``self``/``cls``."""
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        values = dict(bound.arguments)
    except (TypeError, ValueError):  # pragma: no cover - exotic signatures
        return {"args": list(args), "kwargs": kwargs} if (args or kwargs) else None
    values.pop("self", None)
    values.pop("cls", None)
    return values or None


class Tracer:
    """Creates spans and writes them to a :class:`~agentlens.storage.Storage`.

    Most users never instantiate this directly -- they use the module-level
    :func:`agentlens.trace` / :func:`agentlens.span` or the
    :class:`agentlens.AgentLens` facade.
    """

    def __init__(self, config: AgentLensConfig, storage: Storage) -> None:
        self.config = config
        self.storage = storage
        self._storage_failed = False

    # -- public API ----------------------------------------------------------

    def trace(
        self,
        name_or_func: Any = None,
        *,
        span_type: str = SpanType.AGENT,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> Any:
        """Start a top-level agent run (or a nested agent span if already in one).

        Usable as ``@tracer.trace``, ``@tracer.trace("name")`` or
        ``with tracer.trace("name"):`` -- exactly like :func:`agentlens.trace`.
        """
        return _build_scope(self, name_or_func, "trace", span_type, metadata, input)

    def span(
        self,
        name_or_func: Any = None,
        *,
        span_type: str = SpanType.CUSTOM,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> Any:
        """Start a child span of whatever is currently active."""
        return _build_scope(self, name_or_func, "span", span_type, metadata, input)

    def start_trace(
        self,
        name: str,
        *,
        span_type: str = SpanType.AGENT,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
    ) -> TraceHandle:
        """Low-level: begin a trace without binding it to the ambient context."""
        now = utc_now()
        trace_id = _new_id()
        recording = self.config.enabled
        trace = Trace(id=trace_id, name=name, start_time=now, metadata={})
        span = Span(
            id=_new_id(),
            trace_id=trace_id,
            parent_span_id=None,
            name=name,
            span_type=span_type,
            start_time=now,
        )
        root = SpanHandle(self, span, recording=recording)
        handle = TraceHandle(self, trace, root, recording=recording)
        if metadata:
            root.set_metadata(metadata)
            handle.set_metadata(metadata)
        if input is not None:
            root.set_input(input)
        if recording:
            self._write_trace(trace)
            self._write_span(span)
        return handle

    def start_span(
        self,
        name: str,
        *,
        span_type: str = SpanType.CUSTOM,
        metadata: Optional[dict[str, Any]] = None,
        input: Any = None,
        parent: Optional[SpanHandle] = None,
        trace_id: Optional[str] = None,
    ) -> SpanHandle:
        """Low-level: begin a span. The caller is responsible for ending it."""
        parent = parent or _current_span()
        resolved_trace_id = trace_id or (parent.trace_id if parent else None)
        recording = self.config.enabled and resolved_trace_id is not None
        span = Span(
            id=_new_id(),
            trace_id=resolved_trace_id or "orphan",
            parent_span_id=parent.id if parent else None,
            name=name,
            span_type=span_type,
            start_time=utc_now(),
        )
        handle = SpanHandle(self, span, recording=recording)
        if metadata:
            handle.set_metadata(metadata)
        if input is not None:
            handle.set_input(input)
        if recording:
            self._write_span(span)
        elif self.config.enabled and resolved_trace_id is None:
            logger.debug("agentlens: span %r created outside of a trace and was not recorded", name)
        return handle

    def close(self) -> None:
        self.storage.close()

    # -- storage (never raises into user code) -------------------------------

    def _write_span(self, span: Span) -> None:
        self._guard(lambda: self.storage.save_span(span))

    def _write_trace(self, trace: Trace) -> None:
        self._guard(lambda: self.storage.save_trace(trace))

    def _finalize_trace(self, trace: Trace) -> None:
        self._guard(lambda: self.storage.finalize_trace(trace))

    def _guard(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            if not self._storage_failed:
                self._storage_failed = True
                logger.warning(
                    "agentlens: failed to write to %s; tracing is degraded but your "
                    "program is unaffected",
                    getattr(self.storage, "db_path", self.storage),
                    exc_info=True,
                )
