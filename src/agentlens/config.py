"""Configuration and privacy controls.

AgentLens is local-first: traces are written to a SQLite file on the machine
that runs the agent and are never sent anywhere. Because agent inputs and
outputs routinely contain prompts, documents and user data, capture is fully
controllable -- globally, per instance, and per value via a redaction hook.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from agentlens.models import Span

__all__ = [
    "REDACTED",
    "AgentLensConfig",
    "Redactor",
    "default_db_path",
    "redact_keys",
]

REDACTED = "<redacted>"

Redactor = Callable[[str, Any, "Span"], Any]
"""``redactor(field, value, span) -> value``.

``field`` is one of ``"input"``, ``"output"`` or ``"metadata"``. Return the
value to store; return :data:`REDACTED` (or anything else) to replace it.
The hook runs *before* the value is serialized and persisted, so a value the
redactor drops never reaches disk.
"""


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_db_path() -> Path:
    """Where traces are stored unless told otherwise.

    ``$AGENTLENS_DB`` wins; otherwise ``~/.agentlens/traces.db`` so that
    ``agentlens ui`` finds your traces no matter which directory you ran the
    agent from.
    """
    env = os.environ.get("AGENTLENS_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".agentlens" / "traces.db"


@dataclass
class AgentLensConfig:
    """Runtime settings for a tracer.

    Attributes:
        enabled: Master switch. When false, tracing becomes a no-op but your
            code still runs untouched. Set ``AGENTLENS_DISABLED=1`` to force.
        db_path: SQLite file. Created (with parent directories) on first write.
        capture_io: Record span inputs and outputs. Set ``AGENTLENS_CAPTURE_IO=0``
            to keep names, timings and token counts while dropping payloads.
        capture_traceback: Record full tracebacks for recorded exceptions.
        max_value_chars: Long strings are truncated to this many characters
            before storage, so one huge document cannot bloat the database.
        max_items: Lists and dicts are truncated to this many entries.
        redactor: Optional :data:`Redactor` hook, applied to every captured
            input, output and metadata value.
    """

    enabled: bool = True
    db_path: Path = field(default_factory=default_db_path)
    capture_io: bool = True
    capture_traceback: bool = True
    max_value_chars: int = 8_000
    max_items: int = 200
    redactor: Optional[Redactor] = None

    @classmethod
    def from_env(cls) -> AgentLensConfig:
        return cls(
            enabled=not _env_flag("AGENTLENS_DISABLED", False),
            db_path=default_db_path(),
            capture_io=_env_flag("AGENTLENS_CAPTURE_IO", True),
            capture_traceback=_env_flag("AGENTLENS_CAPTURE_TRACEBACK", True),
            max_value_chars=_env_int("AGENTLENS_MAX_VALUE_CHARS", 8_000),
            max_items=_env_int("AGENTLENS_MAX_ITEMS", 200),
        )

    def merged(self, **overrides: Any) -> AgentLensConfig:
        """Return a copy with ``overrides`` applied, ignoring ``None`` values."""
        clean = {k: v for k, v in overrides.items() if v is not None}
        if "db_path" in clean:
            clean["db_path"] = Path(clean["db_path"]).expanduser()
        return replace(self, **clean)


def redact_keys(keys: Iterable[str], placeholder: str = REDACTED) -> Redactor:
    """Build a redactor that masks matching dict keys anywhere in a value.

    >>> configure(redactor=redact_keys(["api_key", "password"]))

    Matching is case-insensitive and substring-based, so ``"key"`` also masks
    ``"OPENAI_API_KEY"``.
    """
    needles = tuple(k.lower() for k in keys)

    def _walk(value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return value
        if isinstance(value, dict):
            return {
                k: (
                    placeholder
                    if isinstance(k, str) and any(n in k.lower() for n in needles)
                    else _walk(v, depth + 1)
                )
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [_walk(v, depth + 1) for v in value]
        return value

    def redactor(field_name: str, value: Any, span: Span) -> Any:
        return _walk(value)

    return redactor
