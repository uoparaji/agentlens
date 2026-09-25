"""``agentlens`` command line interface."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from agentlens import __version__
from agentlens.config import default_db_path

DEFAULT_HOST = os.environ.get("AGENTLENS_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("AGENTLENS_PORT", "4180"))

_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _color(text: str, code: str) -> str:
    return text if not sys.stdout.isatty() else f"{code}{text}{_RESET}"


def _resolve_db(raw: Optional[str]) -> Path:
    return Path(raw).expanduser() if raw else default_db_path()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_ui(args: argparse.Namespace) -> int:
    import uvicorn

    from agentlens.server import create_app, dashboard_is_built

    db = _resolve_db(args.db)
    if not db.exists():
        print(f"No trace database at {db}")
        print("Nothing has been traced yet. Try:  agentlens demo")
        print("Starting the dashboard anyway -- it will pick up new runs as they arrive.\n")

    url = f"http://{args.host}:{args.port}"
    print(_color("  AgentLens", _BOLD))
    print(f"  dashboard  {url}")
    print(f"  database   {db}")
    if not dashboard_is_built():
        print(
            _color(
                "  note       dashboard assets are not built in this checkout;\n"
                "             run `cd frontend && npm install && npm run build`",
                _DIM,
            )
        )
    print(_color("  press ctrl-c to stop\n", _DIM))
    sys.stdout.flush()

    app = create_app(db_path=db)

    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    except OSError as exc:
        if getattr(exc, "errno", None) in (48, 98):  # address already in use
            print(f"\nPort {args.port} is already in use.", file=sys.stderr)
            print(f"Try:  agentlens ui --port {args.port + 1}", file=sys.stderr)
            return 1
        raise
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from agentlens.demo import main as run_demo_main

    db = _resolve_db(args.db)
    code = run_demo_main(db, show_next_step=not args.ui)
    if code == 0 and args.ui:
        return cmd_ui(
            argparse.Namespace(
                db=str(db),
                host=args.host,
                port=args.port,
                open=args.open,
                log_level="warning",
            )
        )
    return code


def cmd_list(args: argparse.Namespace) -> int:
    from agentlens.storage import SQLiteStorage

    db = _resolve_db(args.db)
    if not db.exists():
        print(f"No trace database at {db}. Try:  agentlens demo", file=sys.stderr)
        return 1

    storage = SQLiteStorage(db)
    try:
        page = storage.list_traces(limit=args.limit)
        if not page.traces:
            print("No runs recorded yet. Try:  agentlens demo")
            return 0
        print(
            f"  {'STATUS':<7} {'RUN':<22} {'STARTED':<20} {'DURATION':>10} "
            f"{'SPANS':>6} {'TOKENS':>7}  ID"
        )
        for trace in page.traces:
            duration = f"{trace.duration_ms:.0f} ms" if trace.duration_ms else "-"
            tokens = trace.tokens.total_tokens if trace.tokens else None
            print(
                f"  {trace.status:<7} {trace.name[:22]:<22} "
                f"{trace.start_time.astimezone().strftime('%Y-%m-%d %H:%M:%S'):<20} "
                f"{duration:>10} {trace.span_count:>6} {tokens or '-':>7}  {trace.id[:12]}"
            )
        print(f"\n  {page.total} run(s) in {db}")
    finally:
        storage.close()
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    from agentlens.storage import SQLiteStorage

    db = _resolve_db(args.db)
    if not db.exists():
        print(f"No trace database at {db}; nothing to clear.")
        return 0
    if not args.yes:
        answer = input(f"Delete every run in {db}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 1
    storage = SQLiteStorage(db)
    try:
        print(f"Deleted {storage.clear()} run(s).")
    finally:
        storage.close()
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentlens",
        description="See what your AI agents are actually doing.",
        epilog="Traces are stored locally and never leave your machine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agentlens {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add_db(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            metavar="PATH",
            help=f"trace database to use (default: {default_db_path()})",
        )

    def add_server(p: argparse.ArgumentParser) -> None:
        p.add_argument("--host", default=DEFAULT_HOST, help=f"default: {DEFAULT_HOST}")
        p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default: {DEFAULT_PORT}")
        p.add_argument(
            "--no-open",
            dest="open",
            action="store_false",
            help="do not open a browser window",
        )

    ui = sub.add_parser("ui", help="launch the local dashboard")
    add_db(ui)
    add_server(ui)
    ui.add_argument(
        "--log-level",
        default="warning",
        choices=["critical", "error", "warning", "info", "debug"],
        help="uvicorn log level (default: warning)",
    )
    ui.set_defaults(func=cmd_ui)

    demo = sub.add_parser("demo", help="generate example traces to look at")
    add_db(demo)
    add_server(demo)
    demo.add_argument("--ui", action="store_true", help="launch the dashboard afterwards")
    demo.set_defaults(func=cmd_demo)

    ls = sub.add_parser("list", help="list recent runs in the terminal")
    add_db(ls)
    ls.add_argument("-n", "--limit", type=int, default=20, help="default: 20")
    ls.set_defaults(func=cmd_list)

    clear = sub.add_parser("clear", help="delete every stored run")
    add_db(clear)
    clear.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    clear.set_defaults(func=cmd_clear)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
