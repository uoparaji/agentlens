"""Storage interface.

The tracing SDK only ever talks to this interface, so a different backend
(Postgres, a remote collector, an in-memory buffer for tests) can be added
later without touching the tracing API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel

from agentlens.models import Span, Trace, TraceDetail

__all__ = ["Storage", "StorageStats", "TracePage"]


class StorageStats(BaseModel):
    """Headline numbers for the dashboard."""

    trace_count: int = 0
    span_count: int = 0
    error_count: int = 0
    total_tokens: Optional[int] = None
    db_path: Optional[str] = None
    db_size_bytes: Optional[int] = None


class TracePage(BaseModel):
    """A page of traces plus the total number matching the query."""

    traces: list[Trace]
    total: int


class Storage(ABC):
    """Persistence for traces and spans."""

    @abstractmethod
    def save_trace(self, trace: Trace) -> None:
        """Insert or update a trace row."""

    @abstractmethod
    def save_span(self, span: Span) -> None:
        """Insert or update a span row."""

    @abstractmethod
    def finalize_trace(self, trace: Trace) -> None:
        """Persist a finished trace and refresh its derived aggregates.

        Aggregates (span count, token totals, primary model) are derived from
        the trace's spans so that spans written by integrations are included.
        """

    @abstractmethod
    def list_traces(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> TracePage:
        """Most recent traces first."""

    @abstractmethod
    def get_trace(self, trace_id: str) -> Optional[TraceDetail]:
        """A trace with all of its spans, ordered by start time."""

    @abstractmethod
    def get_span(self, span_id: str) -> Optional[Span]:
        """A single span by id."""

    @abstractmethod
    def delete_trace(self, trace_id: str) -> bool:
        """Delete a trace and its spans. Returns whether it existed."""

    @abstractmethod
    def clear(self) -> int:
        """Delete every trace. Returns the number of traces removed."""

    @abstractmethod
    def stats(self) -> StorageStats:
        """Aggregate counters across all stored traces."""

    def close(self) -> None:  # noqa: B027 - optional hook, not every backend needs it
        """Release resources. Safe to call more than once."""
