"""Generate the AgentLens demo traces.

    python examples/demo_agent.py
    agentlens ui

The agent itself lives in ``agentlens/demo.py`` so that the packaged
``agentlens demo`` command works from an installed wheel too. It is written to
be read -- open it to see how a multi-step agent is instrumented.

For hand-written examples of the API, see ``custom_agent.py`` (sync) and
``async_agent.py`` (async + concurrency) in this directory.
"""

from agentlens.demo import main

if __name__ == "__main__":
    raise SystemExit(main())
