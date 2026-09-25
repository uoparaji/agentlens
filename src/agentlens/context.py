"""Ambient trace/span context built on :mod:`contextvars`.

Using context variables (rather than a global or thread-local) is what makes
nesting correct under ``asyncio``: every task gets its own copy of the context,
so two agents running concurrently with ``asyncio.gather`` never adopt each
other's spans as parents.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from agentlens.tracer import SpanHandle, TraceHandle

__all__ = [
    "current_span",
    "current_trace",
    "pop_span",
    "pop_trace",
    "push_span",
    "push_trace",
]

_current_trace: ContextVar[Optional[TraceHandle]] = ContextVar("agentlens_trace", default=None)
_current_span: ContextVar[Optional[SpanHandle]] = ContextVar("agentlens_span", default=None)


def current_trace() -> Optional[TraceHandle]:
    """The trace enclosing the caller, if any."""
    return _current_trace.get()


def current_span() -> Optional[SpanHandle]:
    """The innermost span enclosing the caller, if any.

    Useful for attaching data from deep inside your code::

        span = agentlens.current_span()
        if span:
            span.set_tokens(prompt_tokens=120, completion_tokens=48)
    """
    return _current_span.get()


def push_trace(handle: TraceHandle) -> Token[Optional[TraceHandle]]:
    return _current_trace.set(handle)


def pop_trace(token: Token[Optional[TraceHandle]]) -> None:
    try:
        _current_trace.reset(token)
    except ValueError:  # pragma: no cover - context left in a different task
        _current_trace.set(None)


def push_span(handle: SpanHandle) -> Token[Optional[SpanHandle]]:
    return _current_span.set(handle)


def pop_span(token: Token[Optional[SpanHandle]]) -> None:
    try:
        _current_span.reset(token)
    except ValueError:  # pragma: no cover - context left in a different task
        _current_span.set(None)
