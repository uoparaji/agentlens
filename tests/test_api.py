"""The local JSON API the dashboard runs on."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentlens import AgentLens, SpanType
from agentlens.server import create_app


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    lens = AgentLens(db_path)
    with lens.trace("research-agent") as root:
        root.set_metadata(topic="quantum")
        with lens.span("search", span_type=SpanType.TOOL) as s:
            s.set_input({"query": "quantum"}).set_output(["r1", "r2"])
        with lens.span("summarize", span_type=SpanType.LLM) as s:
            s.set_model("demo-4o").set_tokens(prompt_tokens=120, completion_tokens=30)
    try:
        with lens.trace("broken-agent"):
            raise ValueError("kaboom")
    except ValueError:
        pass

    app = create_app(storage=lens.storage)
    with TestClient(app) as c:
        yield c
    lens.close()


def test_health_and_stats(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["version"]
    assert health["db_path"].endswith("traces.db")

    stats = client.get("/api/stats").json()
    assert stats["trace_count"] == 2
    assert stats["error_count"] == 1
    assert stats["total_tokens"] == 150


def test_list_traces(client: TestClient) -> None:
    body = client.get("/api/traces").json()
    assert body["total"] == 2
    assert [t["name"] for t in body["traces"]] == ["broken-agent", "research-agent"]

    run = body["traces"][1]
    assert run["status"] == "ok"
    assert run["model"] == "demo-4o"
    assert run["tokens"]["total_tokens"] == 150
    assert run["span_count"] == 3
    assert run["metadata"] == {"topic": "quantum"}
    assert run["start_time"].startswith("20")


def test_list_traces_filters(client: TestClient) -> None:
    assert client.get("/api/traces", params={"status": "error"}).json()["total"] == 1
    assert client.get("/api/traces", params={"search": "research"}).json()["total"] == 1
    assert len(client.get("/api/traces", params={"limit": 1}).json()["traces"]) == 1
    assert client.get("/api/traces", params={"status": "bogus"}).status_code == 422


def test_trace_detail_contains_the_span_tree(client: TestClient) -> None:
    trace_id = client.get("/api/traces", params={"search": "research"}).json()["traces"][0]["id"]
    detail = client.get(f"/api/traces/{trace_id}").json()

    names = [s["name"] for s in detail["spans"]]
    assert names == ["research-agent", "search", "summarize"]

    root, search, summarize = detail["spans"]
    assert root["parent_span_id"] is None
    assert search["parent_span_id"] == root["id"]
    assert search["span_type"] == "tool"
    assert search["input"] == {"query": "quantum"}
    assert search["output"] == ["r1", "r2"]
    assert summarize["tokens"]["prompt_tokens"] == 120
    assert all(s["duration_ms"] >= 0 for s in detail["spans"])


def test_error_details_are_exposed(client: TestClient) -> None:
    trace_id = client.get("/api/traces", params={"status": "error"}).json()["traces"][0]["id"]
    detail = client.get(f"/api/traces/{trace_id}").json()
    assert detail["error"]["type"] == "ValueError"
    assert detail["error"]["message"] == "kaboom"
    assert "ValueError" in detail["spans"][0]["error"]["traceback"]


def test_span_endpoint(client: TestClient) -> None:
    trace_id = client.get("/api/traces", params={"search": "research"}).json()["traces"][0]["id"]
    span_id = client.get(f"/api/traces/{trace_id}").json()["spans"][1]["id"]
    assert client.get(f"/api/spans/{span_id}").json()["name"] == "search"
    assert client.get("/api/spans/missing").status_code == 404


def test_missing_trace_returns_404_with_a_message(client: TestClient) -> None:
    response = client.get("/api/traces/does-not-exist")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_delete_and_clear(client: TestClient) -> None:
    trace_id = client.get("/api/traces").json()["traces"][0]["id"]
    assert client.delete(f"/api/traces/{trace_id}").json() == {"deleted": 1}
    assert client.delete(f"/api/traces/{trace_id}").status_code == 404
    assert client.delete("/api/traces").json() == {"deleted": 1}
    assert client.get("/api/traces").json()["total"] == 0


def test_root_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "AgentLens" in response.text


def test_unknown_paths_fall_back_to_the_dashboard(client: TestClient) -> None:
    """The dashboard is a single-page app, so deep links must still load it."""
    pytest.importorskip("agentlens.server")
    from agentlens.server import dashboard_is_built

    if not dashboard_is_built():
        pytest.skip("dashboard is not built in this checkout")

    assert "<!doctype html>" in client.get("/some/deep/route").text.lower()


@pytest.mark.parametrize(
    "path",
    [
        "/../../../etc/passwd",
        "/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "//etc/passwd",
        "/../pyproject.toml",
    ],
)
def test_static_route_never_escapes_the_bundle(client: TestClient, path: str) -> None:
    from agentlens.server import dashboard_is_built

    if not dashboard_is_built():
        pytest.skip("dashboard is not built in this checkout")

    response = client.get(path)
    assert response.status_code == 200
    assert "root:" not in response.text
    assert "[project]" not in response.text
    assert "<!doctype html>" in response.text.lower()


def test_api_routes_win_over_the_dashboard_catch_all(client: TestClient) -> None:
    assert client.get("/api/traces").headers["content-type"].startswith("application/json")
    assert client.get("/api/nope").status_code == 404
