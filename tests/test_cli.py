"""The ``agentlens`` command line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentlens import __version__
from agentlens.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_bare_invocation_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "agentlens" in output
    for command in ("ui", "demo", "list", "clear"):
        assert command in output


def test_demo_generates_traces(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "demo.db"
    assert main(["demo", "--db", str(db)]) == 0

    output = capsys.readouterr().out
    assert "research-agent" in output
    assert "agentlens ui" in output, "the demo should tell you what to do next"
    assert db.exists()

    from agentlens import AgentLens

    lens = AgentLens(db)
    try:
        traces = lens.get_traces()
        assert len(traces) == 3
        assert any(t.status == "error" for t in traces), "one demo run should fail"
        biggest = max(traces, key=lambda t: t.span_count)
        assert biggest.span_count >= 10, "the demo trace should be worth looking at"
        assert biggest.tokens and biggest.tokens.total_tokens
    finally:
        lens.close()


def test_list_shows_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "demo.db"
    main(["demo", "--db", str(db)])
    capsys.readouterr()

    assert main(["list", "--db", str(db)]) == 0
    output = capsys.readouterr().out
    assert "research-agent" in output
    assert "STATUS" in output


def test_list_without_a_database_explains_what_to_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list", "--db", str(tmp_path / "nope.db")]) == 1
    assert "agentlens demo" in capsys.readouterr().err


def test_clear(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "demo.db"
    main(["demo", "--db", str(db)])
    capsys.readouterr()

    assert main(["clear", "--db", str(db), "--yes"]) == 0
    assert "Deleted 3 run(s)." in capsys.readouterr().out

    from agentlens import AgentLens

    lens = AgentLens(db)
    try:
        assert lens.get_traces() == []
    finally:
        lens.close()


def test_clear_on_a_missing_database_is_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["clear", "--db", str(tmp_path / "nope.db")]) == 0
    assert "nothing to clear" in capsys.readouterr().out


def test_ui_reports_a_busy_port(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "demo.db"
    main(["demo", "--db", str(db)])
    capsys.readouterr()

    import agentlens.cli as cli_module

    def busy(*args: object, **kwargs: object) -> None:
        raise OSError(48, "Address already in use")

    class FakeUvicorn:
        run = staticmethod(busy)

    import sys

    sys.modules["uvicorn"] = FakeUvicorn  # type: ignore[assignment]
    try:
        assert cli_module.main(["ui", "--db", str(db), "--port", "4180", "--no-open"]) == 1
    finally:
        del sys.modules["uvicorn"]
    assert "--port 4181" in capsys.readouterr().err


def test_version_is_declared_in_exactly_one_place() -> None:
    """`__version__` and pyproject.toml must not drift apart on a release."""
    import re

    import agentlens

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():  # running against an installed package
        pytest.skip("no source checkout")

    declared = re.search(r'^version = "([^"]+)"', pyproject.read_text(), re.M)
    assert declared is not None
    assert declared.group(1) == agentlens.__version__
