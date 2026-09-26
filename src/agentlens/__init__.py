"""AgentLens -- see what your AI agents are actually doing.

Local-first tracing for AI agents::

    from agentlens import trace, span

    @trace
    def research_agent(topic: str) -> str:
        with span("search", span_type="tool", metadata={"query": topic}) as s:
            results = search(topic)
            s.set_output(results)
        return summarize(results)

Then run ``agentlens ui`` to inspect the run.
"""

from __future__ import annotations

from agentlens.config import REDACTED, AgentLensConfig, Redactor, default_db_path, redact_keys
from agentlens.context import current_span, current_trace
from agentlens.models import (
    Span,
    SpanError,
    SpanStatus,
    SpanType,
    TokenUsage,
    Trace,
    TraceDetail,
)
from agentlens.sdk import (
    AgentLens,
    configure,
    get_config,
    get_tracer,
    shutdown,
    span,
    trace,
)
from agentlens.storage import SQLiteStorage, Storage
from agentlens.tracer import SpanHandle, TraceHandle, Tracer

__version__ = "0.1.1"

__all__ = [
    "REDACTED",
    "AgentLens",
    "AgentLensConfig",
    "Redactor",
    "SQLiteStorage",
    "Span",
    "SpanError",
    "SpanHandle",
    "SpanStatus",
    "SpanType",
    "Storage",
    "TokenUsage",
    "Trace",
    "TraceDetail",
    "TraceHandle",
    "Tracer",
    "__version__",
    "configure",
    "current_span",
    "current_trace",
    "default_db_path",
    "get_config",
    "get_tracer",
    "redact_keys",
    "shutdown",
    "span",
    "trace",
]
