"""SQLite storage backend -- zero infrastructure, created on first write."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from agentlens.models import Span, SpanError, TokenUsage, Trace, TraceDetail
from agentlens.storage.base import Storage, StorageStats, TracePage

__all__ = ["SQLiteStorage"]

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 15_000
WAL_ATTEMPTS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    status           TEXT NOT NULL,
    start_time       REAL NOT NULL,
    end_time         REAL,
    duration_ms      REAL,
    metadata         TEXT,
    error            TEXT,
    span_count       INTEGER NOT NULL DEFAULT 0,
    model            TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER
);

CREATE TABLE IF NOT EXISTS spans (
    id               TEXT PRIMARY KEY,
    trace_id         TEXT NOT NULL,
    parent_span_id   TEXT,
    name             TEXT NOT NULL,
    span_type        TEXT NOT NULL,
    status           TEXT NOT NULL,
    start_time       REAL NOT NULL,
    end_time         REAL,
    duration_ms      REAL,
    input            TEXT,
    output           TEXT,
    metadata         TEXT,
    error            TEXT,
    model            TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    FOREIGN KEY (trace_id) REFERENCES traces(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id, start_time);
CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_time DESC);
"""


def _dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - serialization already sanitizes
        return json.dumps(str(value))


def _loads(raw: Optional[str]) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - only hand-edited rows
        return raw


def _ts(value: Optional[datetime]) -> Optional[float]:
    return None if value is None else value.timestamp()


def _dt(value: Optional[float]) -> Optional[datetime]:
    return None if value is None else datetime.fromtimestamp(value, tz=timezone.utc)


def _dt_required(value: float) -> datetime:
    """For NOT NULL timestamp columns."""
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _tokens(row: Union[sqlite3.Row, dict[str, Any]]) -> Optional[TokenUsage]:
    usage = TokenUsage(
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        total_tokens=row["total_tokens"],
    )
    return None if usage.is_empty() else usage


def _error(raw: Optional[str]) -> Optional[SpanError]:
    data = _loads(raw)
    return SpanError(**data) if isinstance(data, dict) else None


class SQLiteStorage(Storage):
    """Stores traces in a single SQLite file.

    One connection is kept per thread (SQLite connections are not thread-safe)
    and WAL mode is enabled so the dashboard can read while an agent writes.
    """

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = Path(db_path).expanduser()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._initialized = False

    # -- connection handling -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        # busy_timeout must come first: it is what makes every statement below
        # wait for a competing writer instead of failing outright.
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            if not self._initialized:
                self._initialize(conn)
                self._initialized = True
        self._local.conn = conn
        return conn

    @staticmethod
    def _initialize(conn: sqlite3.Connection) -> None:
        """Enable WAL and create the schema, tolerating a concurrent creator.

        Switching journal mode needs a moment with no other connection mid-write,
        and SQLite does not always route that through the busy handler -- so a
        few threads or processes starting at once get a short retry instead of
        an error.
        """
        for attempt in range(WAL_ATTEMPTS):
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError:
                if attempt == WAL_ATTEMPTS - 1:
                    # Journalling stays at the default; everything still works.
                    break
                time.sleep(0.05 * (attempt + 1))
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- writes --------------------------------------------------------------

    def save_trace(self, trace: Trace) -> None:
        tokens = trace.tokens or TokenUsage()
        self._connect().execute(
            """
            INSERT INTO traces (id, name, status, start_time, end_time, duration_ms,
                                metadata, error, span_count, model,
                                prompt_tokens, completion_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, status=excluded.status, end_time=excluded.end_time,
                duration_ms=excluded.duration_ms, metadata=excluded.metadata,
                error=excluded.error, span_count=excluded.span_count, model=excluded.model,
                prompt_tokens=excluded.prompt_tokens,
                completion_tokens=excluded.completion_tokens,
                total_tokens=excluded.total_tokens
            """,
            (
                trace.id,
                trace.name,
                trace.status,
                _ts(trace.start_time),
                _ts(trace.end_time),
                trace.duration_ms,
                _dumps(trace.metadata or None),
                _dumps(trace.error.model_dump() if trace.error else None),
                trace.span_count,
                trace.model,
                tokens.prompt_tokens,
                tokens.completion_tokens,
                tokens.total_tokens,
            ),
        )

    def save_span(self, span: Span) -> None:
        tokens = (span.tokens or TokenUsage()).resolved()
        self._connect().execute(
            """
            INSERT INTO spans (id, trace_id, parent_span_id, name, span_type, status,
                               start_time, end_time, duration_ms, input, output,
                               metadata, error, model,
                               prompt_tokens, completion_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, span_type=excluded.span_type, status=excluded.status,
                end_time=excluded.end_time, duration_ms=excluded.duration_ms,
                input=excluded.input, output=excluded.output, metadata=excluded.metadata,
                error=excluded.error, model=excluded.model,
                prompt_tokens=excluded.prompt_tokens,
                completion_tokens=excluded.completion_tokens,
                total_tokens=excluded.total_tokens
            """,
            (
                span.id,
                span.trace_id,
                span.parent_span_id,
                span.name,
                span.span_type,
                span.status,
                _ts(span.start_time),
                _ts(span.end_time),
                span.duration_ms,
                _dumps(span.input),
                _dumps(span.output),
                _dumps(span.metadata or None),
                _dumps(span.error.model_dump() if span.error else None),
                span.model,
                tokens.prompt_tokens,
                tokens.completion_tokens,
                tokens.total_tokens,
            ),
        )

    def finalize_trace(self, trace: Trace) -> None:
        self.save_trace(trace)
        conn = self._connect()
        row = conn.execute(
            """
            SELECT COUNT(*) AS span_count,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(total_tokens) AS total_tokens
            FROM spans WHERE trace_id = ?
            """,
            (trace.id,),
        ).fetchone()
        model = trace.model
        if model is None:
            model_row = conn.execute(
                """
                SELECT model, COUNT(*) AS n FROM spans
                WHERE trace_id = ? AND model IS NOT NULL
                GROUP BY model ORDER BY n DESC, model LIMIT 1
                """,
                (trace.id,),
            ).fetchone()
            model = model_row["model"] if model_row else None
        conn.execute(
            """
            UPDATE traces SET span_count = ?, model = ?, prompt_tokens = ?,
                              completion_tokens = ?, total_tokens = ?
            WHERE id = ?
            """,
            (
                row["span_count"] or 0,
                model,
                row["prompt_tokens"],
                row["completion_tokens"],
                row["total_tokens"],
                trace.id,
            ),
        )

    # -- reads ---------------------------------------------------------------

    def list_traces(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> TracePage:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if search:
            where.append("name LIKE ?")
            params.append(f"%{search}%")
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        conn = self._connect()
        total = conn.execute(f"SELECT COUNT(*) FROM traces{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM traces{clause} ORDER BY start_time DESC LIMIT ? OFFSET ?",
            [*params, max(1, min(limit, 500)), max(0, offset)],
        ).fetchall()
        return TracePage(traces=[self._row_to_trace(r) for r in rows], total=total)

    def get_trace(self, trace_id: str) -> Optional[TraceDetail]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
        if row is None:
            return None
        spans = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,)
        ).fetchall()
        return TraceDetail(
            **self._row_to_trace(row).model_dump(),
            spans=[self._row_to_span(s) for s in spans],
        )

    def get_span(self, span_id: str) -> Optional[Span]:
        row = self._connect().execute("SELECT * FROM spans WHERE id = ?", (span_id,)).fetchone()
        return None if row is None else self._row_to_span(row)

    def delete_trace(self, trace_id: str) -> bool:
        conn = self._connect()
        conn.execute("DELETE FROM spans WHERE trace_id = ?", (trace_id,))
        return conn.execute("DELETE FROM traces WHERE id = ?", (trace_id,)).rowcount > 0

    def clear(self) -> int:
        conn = self._connect()
        count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        conn.execute("DELETE FROM spans")
        conn.execute("DELETE FROM traces")
        return int(count)

    def stats(self) -> StorageStats:
        conn = self._connect()
        traces = conn.execute(
            "SELECT COUNT(*) AS n, SUM(total_tokens) AS tokens,"
            " SUM(status = 'error') AS errors FROM traces"
        ).fetchone()
        spans = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        size = self.db_path.stat().st_size if self.db_path.exists() else None
        return StorageStats(
            trace_count=traces["n"] or 0,
            span_count=spans or 0,
            error_count=traces["errors"] or 0,
            total_tokens=traces["tokens"],
            db_path=str(self.db_path),
            db_size_bytes=size,
        )

    # -- row mapping ---------------------------------------------------------

    @staticmethod
    def _row_to_trace(row: sqlite3.Row) -> Trace:
        return Trace(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            start_time=_dt_required(row["start_time"]),
            end_time=_dt(row["end_time"]),
            duration_ms=row["duration_ms"],
            metadata=_loads(row["metadata"]) or {},
            error=_error(row["error"]),
            span_count=row["span_count"] or 0,
            model=row["model"],
            tokens=_tokens(row),
        )

    @staticmethod
    def _row_to_span(row: sqlite3.Row) -> Span:
        return Span(
            id=row["id"],
            trace_id=row["trace_id"],
            parent_span_id=row["parent_span_id"],
            name=row["name"],
            span_type=row["span_type"],
            status=row["status"],
            start_time=_dt_required(row["start_time"]),
            end_time=_dt(row["end_time"]),
            duration_ms=row["duration_ms"],
            input=_loads(row["input"]),
            output=_loads(row["output"]),
            metadata=_loads(row["metadata"]) or {},
            error=_error(row["error"]),
            model=row["model"],
            tokens=_tokens(row),
        )
