"""A self-contained demo agent that produces an interesting trace.

Nothing here talks to a real API: the "LLM" and the "web" are small mocks, so
anyone who clones the repository can generate a trace immediately::

    agentlens demo          # or: python examples/demo_agent.py

The agent below is deliberately shaped like a real one -- a planner, a
concurrent gather step, a handoff to a sub-agent, a tool that fails and is
retried, and a final answer -- because that is what makes the timeline worth
looking at.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any, Optional, Union

from agentlens import AgentLens, SpanType
from agentlens.tracer import Tracer

__all__ = ["main", "run_demo"]

_SOURCES = [
    ("Quantum error correction crosses threshold", "arxiv.org", 0.94),
    ("Surface codes in production hardware", "nature.com", 0.89),
    ("A skeptic's guide to quantum advantage", "acm.org", 0.71),
    ("Benchmarking logical qubits", "science.org", 0.66),
]

_ANSWER = (
    "Recent results suggest error-corrected logical qubits now outperform their "
    "physical counterparts, though useful quantum advantage remains workload-specific."
)


class MockLLM:
    """A fake chat model with plausible latency and token accounting."""

    def __init__(self, model: str, tracer: Tracer, rng: random.Random) -> None:
        self.model = model
        self._tracer = tracer
        self._rng = rng

    async def complete(self, name: str, prompt: str, reply: str, *, latency: float) -> str:
        async with self._tracer.span(name, span_type=SpanType.LLM) as span:
            span.set_input({"messages": [{"role": "user", "content": prompt}]})
            span.set_metadata(temperature=0.2, max_tokens=1024, streaming=False)
            span.set_model(self.model)
            await asyncio.sleep(latency * self._rng.uniform(0.85, 1.15))
            span.set_tokens(
                prompt_tokens=len(prompt.split()) * 3 + self._rng.randint(20, 60),
                completion_tokens=len(reply.split()) * 2 + self._rng.randint(5, 25),
            )
            span.set_output({"content": reply, "finish_reason": "stop"})
            return reply


class DemoAgent:
    """A small research agent instrumented with AgentLens."""

    def __init__(self, lens: AgentLens, seed: int = 7) -> None:
        self.lens = lens
        self.rng = random.Random(seed)
        self.llm = MockLLM("demo-sonnet-4", lens.tracer, self.rng)

    # -- tools ---------------------------------------------------------------

    async def _fetch(self, url: str, latency: float) -> dict[str, Any]:
        async with self.lens.span(f"GET {url}", span_type=SpanType.CUSTOM) as span:
            span.set_input({"method": "GET", "url": f"https://{url}/search"})
            await asyncio.sleep(latency)
            span.set_metadata(status_code=200, bytes=self.rng.randint(4_000, 40_000))
            span.set_output({"ok": True})
            return {"url": url}

    async def _web_search(self, query: str) -> list[dict[str, Any]]:
        async with self.lens.span("web_search", span_type=SpanType.TOOL) as span:
            span.set_input({"query": query, "engine": "demo-search"})
            # One of these hosts is slow -- the waterfall makes that obvious.
            await asyncio.gather(
                self._fetch("arxiv.org", 0.42),
                self._fetch("nature.com", 0.09),
                self._fetch("acm.org", 0.13),
            )
            hits = [{"title": t, "source": s, "score": sc} for t, s, sc in _SOURCES[:3]]
            span.set_output(hits)
            span.set_metadata(result_count=len(hits))
            return hits

    async def _vector_search(self, query: str) -> list[dict[str, Any]]:
        async with self.lens.span("vector_search", span_type=SpanType.RETRIEVAL) as span:
            span.set_input({"query": query, "top_k": 4, "collection": "papers"})
            await asyncio.sleep(0.11)
            hits = [{"title": t, "source": s, "score": sc} for t, s, sc in _SOURCES]
            span.set_output(hits)
            span.set_metadata(index="hnsw", dimensions=1536, top_k=4)
            return hits

    async def _fact_check(self, claim: str, *, fail: bool) -> dict[str, Any]:
        async with self.lens.span("fact_check", span_type=SpanType.TOOL) as span:
            span.set_input({"claim": claim})
            await asyncio.sleep(0.08)
            if fail:
                raise ConnectionError("fact-check API returned 503 (service unavailable)")
            span.set_output({"verdict": "supported", "confidence": 0.82})
            return {"verdict": "supported"}

    # -- sub-agent (a handoff) ----------------------------------------------

    async def _analyst(self, sources: list[dict[str, Any]]) -> str:
        async with self.lens.trace("analyst-agent") as span:
            span.set_input({"source_count": len(sources)})
            async with self.lens.span("rank_sources") as rank:
                rank.set_input(sources)
                await asyncio.sleep(0.04)
                ranked = sorted(sources, key=lambda s: -s["score"])[:3]
                rank.set_output(ranked)
            analysis = await self.llm.complete(
                "synthesize",
                prompt=f"Synthesize {len(ranked)} sources into three findings.",
                reply="1) Logical qubits beat physical ones. 2) Costs remain high. "
                "3) Advantage is workload-specific.",
                latency=0.33,
            )
            span.set_output(analysis)
            return analysis

    # -- the run -------------------------------------------------------------

    async def research(self, topic: str, *, fail_fact_check: bool = False) -> str:
        async with self.lens.trace("research-agent") as run:
            run.set_input({"topic": topic})
            run.set_metadata(agent_version="0.1.0", tools=["web_search", "vector_search"])

            plan = await self.llm.complete(
                "plan",
                prompt=f"Plan the research for: {topic}",
                reply="search the web, retrieve related papers, synthesize, verify",
                latency=0.21,
            )

            async with self.lens.span("gather_sources", span_type=SpanType.WORKFLOW) as gather:
                gather.set_input({"plan": plan})
                web, vectors = await asyncio.gather(
                    self._web_search(topic), self._vector_search(topic)
                )
                sources = web + vectors
                gather.set_output({"sources": len(sources)})

            analysis = await self._analyst(sources)

            try:
                await self._fact_check(analysis[:60], fail=fail_fact_check)
            except ConnectionError:
                # A recovered failure: the span is red, the run still succeeds.
                async with self.lens.span("fact_check_retry", span_type=SpanType.TOOL) as retry:
                    retry.set_metadata(attempt=2, backoff_ms=250)
                    await asyncio.sleep(0.12)
                    retry.set_output({"verdict": "unverified", "confidence": 0.4})

            answer = await self.llm.complete(
                "final_answer",
                prompt="Write the final answer for the user.",
                reply=_ANSWER,
                latency=0.38,
            )
            run.set_output(answer)
            return answer


async def _generate(lens: AgentLens) -> None:
    agent = DemoAgent(lens)

    # 1. A clean run.
    await agent.research("quantum error correction")

    # 2. A run where a tool fails and the agent recovers.
    await agent.research("quantum advantage benchmarks", fail_fact_check=True)

    # 3. A run that fails outright, so the dashboard has an error to show.
    try:
        async with lens.trace("ingest-agent") as run:
            run.set_input({"path": "./corpus/*.pdf"})
            async with lens.span("load_documents", span_type=SpanType.TOOL) as load:
                load.set_input({"glob": "./corpus/*.pdf"})
                await asyncio.sleep(0.06)
                load.set_output({"documents": 12})
            async with lens.span("embed", span_type=SpanType.RETRIEVAL) as embed:
                embed.set_metadata(model="demo-embed-3", batch_size=64)
                await asyncio.sleep(0.15)
                raise RuntimeError("embedding provider rate limit exceeded (429)")
    except RuntimeError:
        pass


def run_demo(db_path: Optional[Union[str, Path]] = None) -> AgentLens:
    """Generate the demo traces. Returns the lens they were written to."""
    lens = AgentLens(db_path) if db_path is not None else AgentLens()
    asyncio.run(_generate(lens))
    return lens


def main(db_path: Optional[Union[str, Path]] = None, *, show_next_step: bool = True) -> int:
    lens = run_demo(db_path)
    try:
        traces = lens.get_traces(limit=10)
        print("\n  AgentLens demo -- generated traces:\n")
        for trace in reversed(traces):
            mark = {"ok": "ok   ", "error": "error", "running": "run  "}.get(trace.status, "?")
            tokens = trace.tokens.total_tokens if trace.tokens else 0
            print(
                f"    {mark}  {trace.name:<16} {trace.duration_ms or 0:7.0f} ms"
                f"  {trace.span_count:>2} spans  {tokens or 0:>5} tokens"
            )
        print(f"\n  Stored in {lens.stats().db_path}")
        if show_next_step:
            print("  Next:  agentlens ui\n")
        else:
            print()
    finally:
        lens.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
