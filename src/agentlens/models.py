"""Core data model for AgentLens.

A :class:`Trace` is one complete agent execution. A :class:`Span` is one unit of
work inside it (an LLM call, a tool call, a retrieval step, ...). Spans form a
tree via ``parent_span_id``.

Nothing in this module knows about any particular AI framework -- integrations
are expected to map their own concepts onto these types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Span",
    "SpanError",
    "SpanStatus",
    "SpanType",
    "TokenUsage",
    "Trace",
    "TraceDetail",
    "utc_now",
]

SpanStatus = Literal["running", "ok", "error"]
"""Lifecycle of a span or trace: in flight, finished cleanly, or failed."""


class SpanType:
    """Well-known span types.

    These are plain strings, not an enum: the dashboard gives the known types
    dedicated colors and icons, but any string is accepted so that integrations
    and users are never blocked by our vocabulary.
    """

    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    WORKFLOW = "workflow"
    CUSTOM = "custom"


def utc_now() -> datetime:
    """Timezone-aware wall clock used for every timestamp AgentLens records."""
    return datetime.now(timezone.utc)


class TokenUsage(BaseModel):
    """LLM token accounting. Every field is optional -- providers differ."""

    model_config = ConfigDict(extra="allow")

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    def resolved(self) -> TokenUsage:
        """Fill in ``total_tokens`` when the provider only reported the parts."""
        if self.total_tokens is None and (
            self.prompt_tokens is not None or self.completion_tokens is not None
        ):
            return self.model_copy(
                update={"total_tokens": (self.prompt_tokens or 0) + (self.completion_tokens or 0)}
            )
        return self

    def is_empty(self) -> bool:
        return (
            self.prompt_tokens is None
            and self.completion_tokens is None
            and self.total_tokens is None
        )


class SpanError(BaseModel):
    """A recorded exception."""

    type: str
    message: str
    traceback: Optional[str] = None


class Span(BaseModel):
    """One unit of work inside a trace."""

    id: str
    trace_id: str
    parent_span_id: Optional[str] = None
    name: str
    span_type: str = SpanType.CUSTOM
    status: SpanStatus = "running"
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: Optional[SpanError] = None
    model: Optional[str] = None
    tokens: Optional[TokenUsage] = None


class Trace(BaseModel):
    """One complete agent execution, without its spans."""

    id: str
    name: str
    status: SpanStatus = "running"
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: Optional[SpanError] = None
    span_count: int = 0
    model: Optional[str] = None
    tokens: Optional[TokenUsage] = None


class TraceDetail(Trace):
    """A trace together with every span recorded under it."""

    spans: list[Span] = Field(default_factory=list)
