"""Capturing arbitrary Python values must never raise and never explode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from agentlens.serialization import to_jsonable


@dataclass
class Doc:
    title: str
    score: float


class Role(str, Enum):
    USER = "user"


class Message(BaseModel):
    role: str
    content: str


class Opaque:
    def __init__(self) -> None:
        self.public = 1
        self._private = 2


class Exploding:
    def __repr__(self) -> str:
        raise RuntimeError("no repr for you")


def test_common_python_values() -> None:
    assert to_jsonable({"a": 1, "b": [1, 2.5, True, None]}) == {"a": 1, "b": [1, 2.5, True, None]}
    assert to_jsonable(Doc("t", 0.5)) == {"title": "t", "score": 0.5}
    assert to_jsonable(Message(role="user", content="hi")) == {"role": "user", "content": "hi"}
    assert to_jsonable(Role.USER) == "user"
    assert to_jsonable(Path("/tmp/x")) == "/tmp/x"
    assert to_jsonable({1, 2}) == [1, 2]
    assert to_jsonable(datetime(2026, 1, 1, tzinfo=timezone.utc)).startswith("2026-01-01")
    assert to_jsonable(b"abc") == "<bytes len=3>"
    assert to_jsonable(float("nan")) == "nan"


def test_unknown_objects_degrade_to_fields_or_repr() -> None:
    assert to_jsonable(Opaque()) == {"__type__": "Opaque", "public": 1}
    assert to_jsonable(len) == repr(len)
    assert to_jsonable(Exploding()) == "<Exploding>"


def test_cycles_are_detected() -> None:
    a: dict = {"name": "a"}
    a["self"] = a
    assert to_jsonable(a) == {"name": "a", "self": "<circular reference>"}


def test_collections_and_strings_are_truncated() -> None:
    long_list = to_jsonable(list(range(500)), max_items=10)
    assert len(long_list) == 11
    assert long_list[-1] == "... [490 more items]"

    big_dict = to_jsonable({str(i): i for i in range(50)}, max_items=5)
    assert len(big_dict) == 6

    text = to_jsonable("y" * 100, max_chars=10)
    assert text.startswith("y" * 10) and "truncated 90 chars" in text


def test_deeply_nested_values_stop_recursing() -> None:
    value: dict = {}
    node = value
    for _i in range(20):
        node["next"] = {}
        node = node["next"]
    assert "next" in to_jsonable(value)
