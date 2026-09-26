# Changelog

All notable changes to AgentLens are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-25

The first release. Trace an agent, look at the trace.

### Added

**Tracing SDK**
- `@trace` decorator for sync functions, coroutines, generators and async
  generators, usable bare or with arguments.
- `trace(...)` / `span(...)` as context managers, sync (`with`) and async
  (`async with`).
- Automatic capture of call arguments, return values, duration, status and
  exceptions.
- `SpanHandle` setters for input, output, metadata, model and token usage, plus
  `start_child()` for manually managed spans.
- Nested `@trace` calls record an agent handoff instead of starting a second run.
- `current_span()` / `current_trace()` for reaching the active span from
  anywhere.
- Correct nesting under `asyncio` concurrency and across threads, via
  `contextvars`.
- `AgentLens` instance facade for isolated tracers and reading traces back.

**Storage**
- Abstract `Storage` interface with a SQLite implementation; the database and
  its parent directories are created on first write.
- WAL mode so the dashboard can read while an agent writes.
- Token and model aggregates rolled up from spans to the run.
- Storage failures are caught and logged — they never reach the user's agent.

**Dashboard**
- Run list with status, duration, span count, model, token totals, plus search
  and status filters.
- Waterfall timeline with the execution tree, expand/collapse, a draggable
  divider, keyboard navigation and colour-coded span types.
- Span inspector with timings, token usage, errors with tracebacks, and a
  collapsible JSON viewer for inputs, outputs and metadata.
- Live updates while a run is in flight; light and dark themes.

**CLI**
- `agentlens ui`, `agentlens demo`, `agentlens list`, `agentlens clear`,
  `agentlens --version`.

**Privacy**
- `capture_io=False` keeps names, timings and token counts while dropping
  payloads.
- `redactor` hook applied before anything is written to disk, plus the
  `redact_keys()` helper.
- `AGENTLENS_DISABLED`, `AGENTLENS_CAPTURE_IO` and `AGENTLENS_DB` environment
  variables.

**Integrations**
- LlamaIndex, via its instrumentation dispatcher
  (`pip install 'agent-lense[llamaindex]'`).

**Examples**
- `agentlens demo` and `examples/demo_agent.py` (nested, concurrent, with a
  recovered failure), plus sync, async and LlamaIndex examples — all runnable
  without API keys.

[Unreleased]: https://github.com/uoparaji/agentlens/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/uoparaji/agentlens/releases/tag/v0.1.0
