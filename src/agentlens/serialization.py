"""Best-effort conversion of arbitrary Python values into JSON-safe data.

Agent inputs and outputs are whatever the user's code happens to pass around:
dataclasses, pydantic models, numpy arrays, framework objects, cyclic graphs.
Capturing them must never raise and must never blow up the database, so this
module degrades gracefully -- unknown objects become their ``repr``, long
strings and large collections are truncated with an explicit marker.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Optional
from uuid import UUID

__all__ = ["to_jsonable", "truncate_text"]

_MAX_DEPTH = 6
_PRIMITIVES = (str, int, float, bool)


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + f"... [truncated {len(text) - max_chars} chars]"
    return text


def to_jsonable(
    value: Any,
    *,
    max_chars: int = 8_000,
    max_items: int = 200,
    _depth: int = 0,
    _seen: Optional[set[int]] = None,
) -> Any:
    """Convert ``value`` into something :mod:`json` can encode.

    Never raises: any failure is reported inline as a string so a broken
    ``__repr__`` in user code cannot break the user's agent.
    """
    try:
        return _convert(value, max_chars, max_items, _depth, _seen or set())
    except Exception as exc:  # pragma: no cover - defensive
        return f"<unserializable: {type(exc).__name__}>"


def _convert(value: Any, max_chars: int, max_items: int, depth: int, seen: set[int]) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        # JSON has no NaN or Infinity; keep them as readable strings instead.
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return truncate_text(value, max_chars)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{type(value).__name__} len={len(bytes(value))}>"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, PurePath, Path)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return _convert(value.value, max_chars, max_items, depth, seen)

    if depth >= _MAX_DEPTH:
        return _fallback(value, max_chars)

    marker = id(value)
    if marker in seen:
        return "<circular reference>"
    seen = seen | {marker}
    nxt = depth + 1

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= max_items:
                out[f"... [{len(value) - max_items} more keys]"] = "<truncated>"
                break
            key = k if isinstance(k, str) else _stringify_key(k)
            out[key] = _convert(v, max_chars, max_items, nxt, seen)
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        converted = [_convert(v, max_chars, max_items, nxt, seen) for v in items[:max_items]]
        if len(items) > max_items:
            converted.append(f"... [{len(items) - max_items} more items]")
        return converted

    model = _model_dump(value)
    if model is not None:
        return _convert(model, max_chars, max_items, nxt, seen)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: getattr(value, f.name, None) for f in dataclasses.fields(value)}
        return _convert(fields, max_chars, max_items, nxt, seen)

    slots = getattr(value, "__dict__", None)
    if isinstance(slots, dict) and slots:
        public = {k: v for k, v in slots.items() if not k.startswith("_")}
        if public:
            body = _convert(public, max_chars, max_items, nxt, seen)
            if isinstance(body, dict):
                return {"__type__": type(value).__name__, **body}
            return body

    return _fallback(value, max_chars)


def _model_dump(value: Any) -> Optional[Any]:
    """Dump a pydantic model (v2 or v1) without touching deprecated members."""
    cls = type(value)
    try:
        if hasattr(cls, "model_fields") and callable(getattr(value, "model_dump", None)):
            return value.model_dump()
        if hasattr(cls, "__fields__") and callable(getattr(value, "dict", None)):
            return value.dict()
    except Exception:
        return None
    return None


def _stringify_key(key: Any) -> str:
    try:
        return str(key)
    except Exception:  # pragma: no cover - defensive
        return "<unprintable key>"


def _fallback(value: Any, max_chars: int) -> str:
    try:
        return truncate_text(repr(value), min(max_chars, 2_000))
    except Exception:  # pragma: no cover - defensive
        return f"<{type(value).__name__}>"
