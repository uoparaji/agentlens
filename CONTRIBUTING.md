# Contributing to AgentLens

Thanks for being here. AgentLens is small on purpose, and that makes it easy to
contribute to — most changes touch one file.

## Setup

```bash
git clone https://github.com/uoparaji/agentlens
cd agentlens
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

That's the whole Python setup. You do **not** need Node unless you are changing
the dashboard.

## The checks

```bash
pytest                  # tests
ruff check .            # lint
ruff format .           # format
mypy                    # types (strict, on src/agentlens)
```

CI runs all four on Python 3.9 – 3.13. Please run them before opening a PR.

## Working on the dashboard

The dashboard is a Vite + React + TypeScript + Tailwind app in `frontend/`. Its
build output is committed to `src/agentlens/static/` so that `pip install
agentlens` never requires Node.

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxies /api to a running `agentlens ui`
```

In another terminal, serve some traces for it to show:

```bash
agentlens demo
agentlens ui --no-open
```

When you are done, rebuild and commit the output:

```bash
npm run build    # writes ../src/agentlens/static
```

## Adding an integration

Integrations live in `src/agentlens/integrations/` and are the most valuable
thing you can contribute. The rules that keep them safe:

1. **Use only the public SDK.** `tracer.start_trace`, `tracer.start_span`,
   `SpanHandle.set_*`, `handle.end()`. Nothing in the integration should reach
   into storage or the data model directly.
2. **Never break the user's agent.** Every callback body goes in a
   `try/except Exception`, logs once, and returns. A tracing bug must never
   surface as an agent bug.
3. **Import the framework lazily** and raise a clear `ImportError` naming the
   extra to install. AgentLens itself must import fine without it.
4. **Respect an active trace.** If the user is already inside a `@trace`, nest
   under `current_span()` rather than starting a second run.
5. **Map onto the core span types** (`agent`, `llm`, `tool`, `retrieval`,
   `workflow`, `custom`) so the dashboard stays readable.
6. **Add the extra** to `[project.optional-dependencies]` in `pyproject.toml`,
   tests that run without network or API keys, and a README row that says what
   is actually captured.

`src/agentlens/integrations/llamaindex.py` is the reference implementation.

## Tests

Tests should describe behaviour a user would notice — nesting, timing, error
capture, privacy settings — rather than chase coverage. Useful fixtures live in
`tests/conftest.py`:

- `lens` — an isolated `AgentLens` on a temp database
- `global_lens` — points the module-level `trace`/`span` at a temp database
- `db_path` — a temp database path

Async tests are plain `async def`; `asyncio_mode = "auto"` is already set.

## Pull requests

- One change per PR, with a test.
- Update `CHANGELOG.md` under **Unreleased**.
- If you change the dashboard, include a screenshot.
- Never document a capability that does not work yet. An honest README is the
  project's most valuable asset.

## Reporting bugs

Please include the AgentLens version (`agentlens --version`), your Python
version, and a minimal snippet that reproduces the problem. If it is a
dashboard issue, a screenshot plus anything in the browser console helps.
