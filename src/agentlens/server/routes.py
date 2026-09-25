"""Read-only JSON API consumed by the dashboard."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from agentlens import __version__
from agentlens.models import Span, TraceDetail
from agentlens.storage.base import Storage, StorageStats, TracePage

router = APIRouter(prefix="/api")


class Health(BaseModel):
    status: str = "ok"
    version: str
    db_path: str


class DeleteResult(BaseModel):
    deleted: int


def _storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


@router.get("/health", response_model=Health, summary="Server health and database location")
def health(request: Request) -> Health:
    return Health(version=__version__, db_path=str(_storage(request).stats().db_path or ""))


@router.get("/stats", response_model=StorageStats, summary="Totals across all runs")
def stats(request: Request) -> StorageStats:
    return _storage(request).stats()


@router.get("/traces", response_model=TracePage, summary="List agent runs, newest first")
def list_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, pattern="^(running|ok|error)$"),
    search: Optional[str] = Query(None, max_length=200),
) -> TracePage:
    return _storage(request).list_traces(
        limit=limit, offset=offset, status=status, search=search or None
    )


@router.get("/traces/{trace_id}", response_model=TraceDetail, summary="One run with its spans")
def get_trace(request: Request, trace_id: str) -> TraceDetail:
    trace = _storage(request).get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No trace with id {trace_id!r}")
    return trace


@router.delete("/traces/{trace_id}", response_model=DeleteResult, summary="Delete one run")
def delete_trace(request: Request, trace_id: str) -> DeleteResult:
    if not _storage(request).delete_trace(trace_id):
        raise HTTPException(status_code=404, detail=f"No trace with id {trace_id!r}")
    return DeleteResult(deleted=1)


@router.delete("/traces", response_model=DeleteResult, summary="Delete every run")
def clear_traces(request: Request) -> DeleteResult:
    return DeleteResult(deleted=_storage(request).clear())


@router.get("/spans/{span_id}", response_model=Span, summary="One span by id")
def get_span(request: Request, span_id: str) -> Span:
    span = _storage(request).get_span(span_id)
    if span is None:
        raise HTTPException(status_code=404, detail=f"No span with id {span_id!r}")
    return span
