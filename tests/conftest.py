from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import agentlens
from agentlens import AgentLens


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "traces.db"


@pytest.fixture
def lens(db_path: Path) -> Iterator[AgentLens]:
    instance = AgentLens(db_path)
    yield instance
    instance.close()


@pytest.fixture
def global_lens(db_path: Path) -> Iterator[AgentLens]:
    """Point the module-level ``trace``/``span`` at a throwaway database."""
    agentlens.configure(db_path=db_path, enabled=True, capture_io=True, redactor=None)
    reader = AgentLens(db_path)
    yield reader
    reader.close()
    agentlens.shutdown()
