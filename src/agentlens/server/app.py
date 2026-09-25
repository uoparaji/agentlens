"""The local FastAPI application: JSON API plus the prebuilt dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from agentlens import __version__
from agentlens.config import default_db_path
from agentlens.server.routes import router
from agentlens.storage.base import Storage
from agentlens.storage.sqlite import SQLiteStorage

__all__ = ["STATIC_DIR", "create_app", "dashboard_is_built"]

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_MISSING_UI = """<!doctype html>
<html><head><meta charset="utf-8"><title>AgentLens</title>
<style>
  body{background:#0b0d10;color:#e6e9ef;font:15px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  div{max-width:34rem;padding:2rem}
  h1{font-size:1.25rem;margin:0 0 1rem}
  code{background:#171b21;padding:.15rem .4rem;border-radius:4px}
  a{color:#5aa9ff}
</style></head>
<body><div>
  <h1>The AgentLens dashboard has not been built</h1>
  <p>The JSON API is running at <a href="/api/traces">/api/traces</a> and
     <a href="/docs">/docs</a>.</p>
  <p>You are probably running from a source checkout. Build the dashboard once:</p>
  <p><code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>
  <p>Released wheels ship the dashboard prebuilt, so <code>pip install agentlens</code>
     never needs Node.</p>
</div></body></html>
"""


def dashboard_is_built() -> bool:
    """Whether the compiled dashboard is present in this installation."""
    return (STATIC_DIR / "index.html").exists()


def create_app(
    storage: Optional[Storage] = None,
    *,
    db_path: Optional[Union[str, Path]] = None,
) -> FastAPI:
    """Build the local app.

    Pass ``storage`` to serve an existing backend, or ``db_path`` to open a
    SQLite file (defaults to the same database the SDK writes to).
    """
    app = FastAPI(
        title="AgentLens",
        description="Local-first tracing for AI agents.",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.storage = storage or SQLiteStorage(db_path or default_db_path())

    # The dashboard is served from the same origin in normal use; this only
    # exists so `npm run dev` on another port can talk to a running server.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    if dashboard_is_built():
        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            """Serve the dashboard, falling back to index.html for deep links."""
            # A typo under /api must be a JSON 404, not a page of HTML.
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404, detail=f"No API endpoint at /{full_path}")
            # `resolve()` plus the parent check keeps "../" out of the bundle.
            candidate = (STATIC_DIR / full_path).resolve()
            if full_path and STATIC_DIR in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        def missing_ui() -> HTMLResponse:
            return HTMLResponse(_MISSING_UI, status_code=200)

    return app
