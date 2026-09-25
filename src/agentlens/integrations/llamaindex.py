"""LlamaIndex integration.

One call instruments everything LlamaIndex already reports through its
``instrumentation`` dispatcher::

    from agentlens.integrations.llamaindex import instrument

    instrument()

    index.as_query_engine().query("what changed?")

What is captured automatically:

* every LlamaIndex span (query engines, retrievers, LLMs, embeddings, agents,
  workflows) as a nested AgentLens span, with LlamaIndex's own parent/child
  relationships preserved;
* a span type inferred from the LlamaIndex class and method -- ``llm``,
  ``retrieval``, ``tool``, ``agent`` or ``workflow``;
* call arguments as the span input and the return value as the span output
  (subject to the usual ``capture_io`` and redaction settings);
* the model name and prompt/completion token counts reported by LLM events;
* exceptions, including the ones LlamaIndex swallows internally.

If a LlamaIndex call happens outside any AgentLens trace, a new run is started
for it. If one is already active -- for example inside your own ``@trace``
decorated agent -- the LlamaIndex spans are nested underneath it.

Every callback is defensive: an error inside this module is logged once and
never propagates into the instrumented application.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

from agentlens.context import current_span
from agentlens.models import SpanType
from agentlens.sdk import AgentLens, get_tracer
from agentlens.tracer import SpanHandle, TraceHandle, Tracer

logger = logging.getLogger("agentlens.llamaindex")

__all__ = ["AgentLensEventHandler", "AgentLensSpanHandler", "instrument", "uninstrument"]

try:
    from llama_index.core.instrumentation import get_dispatcher  # type: ignore[attr-defined]
    from llama_index.core.instrumentation.event_handlers import BaseEventHandler
    from llama_index.core.instrumentation.events import BaseEvent
    from llama_index.core.instrumentation.span_handlers import BaseSpanHandler
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "The LlamaIndex integration requires llama-index-core.\n"
        "Install it with:  pip install 'agentlens[llamaindex]'"
    ) from exc


# ---------------------------------------------------------------------------
# mapping LlamaIndex vocabulary onto AgentLens span types
# ---------------------------------------------------------------------------

_CLASS_HINTS = (
    ("retriev", SpanType.RETRIEVAL),
    ("embed", SpanType.RETRIEVAL),
    ("vectorstore", SpanType.RETRIEVAL),
    ("rerank", SpanType.RETRIEVAL),
    ("postprocessor", SpanType.RETRIEVAL),
    ("llm", SpanType.LLM),
    ("openai", SpanType.LLM),
    ("anthropic", SpanType.LLM),
    ("tool", SpanType.TOOL),
    ("agent", SpanType.AGENT),
    ("workflow", SpanType.WORKFLOW),
    ("queryengine", SpanType.WORKFLOW),
    ("chatengine", SpanType.WORKFLOW),
    ("pipeline", SpanType.WORKFLOW),
    ("synthes", SpanType.LLM),
)

_METHOD_HINTS = {
    "chat": SpanType.LLM,
    "achat": SpanType.LLM,
    "complete": SpanType.LLM,
    "acomplete": SpanType.LLM,
    "predict": SpanType.LLM,
    "apredict": SpanType.LLM,
    "stream_chat": SpanType.LLM,
    "astream_chat": SpanType.LLM,
    "retrieve": SpanType.RETRIEVAL,
    "aretrieve": SpanType.RETRIEVAL,
    "get_text_embedding": SpanType.RETRIEVAL,
    "call": SpanType.TOOL,
    "acall": SpanType.TOOL,
    "run_step": SpanType.AGENT,
    "arun_step": SpanType.AGENT,
    "query": SpanType.WORKFLOW,
    "aquery": SpanType.WORKFLOW,
    "synthesize": SpanType.WORKFLOW,
    "asynthesize": SpanType.WORKFLOW,
    "run": SpanType.WORKFLOW,
}

# Some components report a placeholder instead of a real model name.
_PLACEHOLDER_MODELS = {"", "unknown", "none", "custom", "mock"}


def _clean_model(value: Any) -> Optional[str]:
    if not isinstance(value, str) or value.strip().lower() in _PLACEHOLDER_MODELS:
        return None
    return value


# LlamaIndex span ids look like "OpenAI.chat-<uuid4>"; the uuid itself contains
# hyphens, so the split has to happen at the first one.
def _split_span_id(span_id: str) -> str:
    """``"OpenAI.chat-6f3c-..."`` -> ``"OpenAI.chat"``."""
    return span_id.partition("-")[0] or span_id


def _span_type_for(qualified_name: str) -> str:
    class_name, _, method = qualified_name.partition(".")
    if method in _METHOD_HINTS:
        return _METHOD_HINTS[method]
    lowered = class_name.lower()
    for needle, span_type in _CLASS_HINTS:
        if needle in lowered:
            return span_type
    return SpanType.CUSTOM


def _arguments(bound_args: Any) -> Optional[dict[str, Any]]:
    try:
        values = dict(bound_args.arguments)
    except Exception:
        return None
    values.pop("self", None)
    values.pop("cls", None)
    # These carry framework plumbing rather than anything a human wants to read.
    for noisy in ("callback_manager", "callback", "kwargs", "node_postprocessors"):
        values.pop(noisy, None)
    return values or None


def _token_usage(raw: Any) -> dict[str, Optional[int]]:
    """Pull prompt/completion counts out of whatever the provider returned."""
    usage: Any = None
    usage = raw.get("usage") if isinstance(raw, dict) else getattr(raw, "usage", None)
    if usage is None:
        return {}
    if not isinstance(usage, dict):
        usage = getattr(usage, "model_dump", getattr(usage, "dict", lambda: {}))()
    if not isinstance(usage, dict):
        return {}

    def _pick(*names: str) -> Optional[int]:
        for name in names:
            value = usage.get(name)
            if isinstance(value, int):
                return value
        return None

    return {
        "prompt_tokens": _pick("prompt_tokens", "input_tokens"),
        "completion_tokens": _pick("completion_tokens", "output_tokens"),
        "total_tokens": _pick("total_tokens"),
    }


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


class _Registry:
    """Thread-safe bookkeeping of the LlamaIndex spans currently open."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: dict[str, SpanHandle] = {}
        self._owned_traces: dict[str, TraceHandle] = {}

    def add(self, key: str, span: SpanHandle, trace: Optional[TraceHandle] = None) -> None:
        with self._lock:
            self._spans[key] = span
            if trace is not None:
                self._owned_traces[key] = trace

    def get(self, key: str) -> Optional[SpanHandle]:
        with self._lock:
            return self._spans.get(key)

    def pop(self, key: str) -> tuple[Optional[SpanHandle], Optional[TraceHandle]]:
        with self._lock:
            return self._spans.pop(key, None), self._owned_traces.pop(key, None)


class AgentLensSpanHandler(BaseSpanHandler[Any]):  # type: ignore[misc]
    """Turns LlamaIndex spans into AgentLens spans."""

    model_config = {"arbitrary_types_allowed": True}

    # LlamaIndex span handlers are pydantic models. Our state is attached as
    # ordinary attributes and only declared for the type checker, because
    # pydantic does not initialise declared private attributes on this base.
    if TYPE_CHECKING:
        _tracer: Optional[Tracer]
        _open: _Registry

    @classmethod
    def class_name(cls) -> str:
        return "AgentLensSpanHandler"

    def __init__(self, tracer: Optional[Tracer] = None, **data: Any) -> None:
        super().__init__(**data)
        self._tracer = tracer
        self._open = _Registry()

    @property
    def tracer(self) -> Tracer:
        return self._tracer if self._tracer is not None else get_tracer()

    # -- lookup used by the event handler ------------------------------------

    def span_for(self, span_id: Optional[str]) -> Optional[SpanHandle]:
        return None if span_id is None else self._open.get(span_id)

    # -- BaseSpanHandler -----------------------------------------------------

    def new_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Optional[Any] = None,
        parent_span_id: Optional[str] = None,
        tags: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            name = _split_span_id(id_)
            span_type = _span_type_for(name)
            metadata = {"llamaindex_span": name}
            if tags:
                metadata.update(tags)

            parent = self.span_for(parent_span_id)
            if parent is None:
                # A LlamaIndex root span. If the caller is already inside an
                # AgentLens trace, nest underneath it rather than starting a
                # second run for the same piece of work.
                parent = current_span()
            if parent is None:
                trace = self.tracer.start_trace(name, span_type=span_type, metadata=metadata)
                trace.root.set_input(_arguments(bound_args))
                self._open.add(id_, trace.root, trace)
                return

            handle = self.tracer.start_span(
                name,
                span_type=span_type,
                metadata=metadata,
                input=_arguments(bound_args),
                parent=parent,
            )
            self._open.add(id_, handle)
        except Exception:  # pragma: no cover - defensive
            _warn("failed to open span %s", id_)

    def prepare_to_exit_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Optional[Any] = None,
        result: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        self._close(id_, result=result, error=None)

    def prepare_to_drop_span(
        self,
        id_: str,
        bound_args: Any,
        instance: Optional[Any] = None,
        err: Optional[BaseException] = None,
        **kwargs: Any,
    ) -> None:
        self._close(id_, result=None, error=err)

    def _close(self, id_: str, *, result: Any, error: Optional[BaseException]) -> None:
        try:
            handle, trace = self._open.pop(id_)
            if handle is None:
                return
            if result is not None:
                handle.set_output(result)
            if trace is not None:
                trace.end(error=error)
            else:
                handle.end(error=error)
        except Exception:  # pragma: no cover - defensive
            _warn("failed to close span %s", id_)


class AgentLensEventHandler(BaseEventHandler):  # type: ignore[misc]
    """Enriches spans with the model and token counts LlamaIndex reports."""

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def class_name(cls) -> str:
        return "AgentLensEventHandler"

    if TYPE_CHECKING:
        _span_handler: AgentLensSpanHandler

    def __init__(self, span_handler: AgentLensSpanHandler, **data: Any) -> None:
        super().__init__(**data)
        self._span_handler = span_handler

    def handle(self, event: BaseEvent, **kwargs: Any) -> None:
        try:
            handle = self._span_handler.span_for(getattr(event, "span_id", None))
            if handle is None:
                return
            name = type(event).__name__

            model_dict = getattr(event, "model_dict", None)
            if isinstance(model_dict, dict):
                model = _clean_model(model_dict.get("model")) or _clean_model(
                    model_dict.get("model_name")
                )
                handle.set_model(model)
                temperature = model_dict.get("temperature")
                if temperature is not None:
                    handle.set_metadata(temperature=temperature)

            if name.endswith("EndEvent"):
                response = getattr(event, "response", None)
                if response is not None:
                    usage = _token_usage(getattr(response, "raw", None))
                    if any(value is not None for value in usage.values()):
                        handle.set_tokens(**usage)
                    if handle.span.model is None:
                        raw = getattr(response, "raw", None)
                        model = (
                            raw.get("model")
                            if isinstance(raw, dict)
                            else getattr(raw, "model", None)
                        )
                        handle.set_model(_clean_model(model))
                chunks = getattr(event, "chunks", None)
                if chunks is not None:
                    handle.set_metadata(chunk_count=len(chunks))
                nodes = getattr(event, "nodes", None)
                if nodes is not None:
                    handle.set_metadata(node_count=len(nodes))
        except Exception:  # pragma: no cover - defensive
            _warn("failed to handle event %s", type(event).__name__)


_warned = False


def _warn(message: str, *args: Any) -> None:
    global _warned
    if not _warned:
        _warned = True
        logger.warning(
            "agentlens: LlamaIndex instrumentation hit an error (" + message + "); "
            "tracing may be incomplete but your application is unaffected",
            *args,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def instrument(lens: Optional[AgentLens] = None) -> AgentLensSpanHandler:
    """Start recording LlamaIndex activity.

    Args:
        lens: Write to this :class:`~agentlens.AgentLens` instead of the
            default global tracer. Useful in tests and notebooks.

    Returns:
        The registered span handler, which can be passed to :func:`uninstrument`.
    """
    tracer = lens.tracer if lens is not None else None
    dispatcher = get_dispatcher()

    for existing in list(dispatcher.span_handlers):
        if isinstance(existing, AgentLensSpanHandler):
            return existing

    span_handler = AgentLensSpanHandler(tracer)
    dispatcher.add_span_handler(span_handler)
    dispatcher.add_event_handler(AgentLensEventHandler(span_handler))
    logger.debug("agentlens: LlamaIndex instrumentation enabled")
    return span_handler


def uninstrument() -> None:
    """Stop recording LlamaIndex activity."""
    dispatcher = get_dispatcher()
    dispatcher.span_handlers = [
        handler
        for handler in dispatcher.span_handlers
        if not isinstance(handler, AgentLensSpanHandler)
    ]
    dispatcher.event_handlers = [
        handler
        for handler in dispatcher.event_handlers
        if not isinstance(handler, AgentLensEventHandler)
    ]
