"""Tracing an async agent, including concurrent work.

    python examples/async_agent.py
    agentlens ui

The three fetches below run concurrently. In the dashboard timeline their bars
overlap, and each one still lands under the correct parent -- AgentLens tracks
context with ``contextvars``, so concurrent tasks never steal each other's spans.
"""

from __future__ import annotations

import asyncio

from agentlens import span, trace

PAGES = {
    "docs.example.com": 0.30,
    "blog.example.com": 0.08,
    "wiki.example.com": 0.12,
}


async def fetch(host: str, delay: float) -> dict[str, object]:
    async with span(f"GET {host}", span_type="tool") as s:
        s.set_input({"method": "GET", "url": f"https://{host}/"})
        await asyncio.sleep(delay)
        s.set_metadata(status_code=200)
        page = {"host": host, "words": int(delay * 4000)}
        s.set_output(page)
        return page


async def answer(pages: list[dict[str, object]]) -> str:
    async with span("compose_answer", span_type="llm") as s:
        s.set_model("demo-haiku")
        await asyncio.sleep(0.2)
        text = f"Read {len(pages)} pages, {sum(int(p['words']) for p in pages)} words."
        s.set_tokens(prompt_tokens=sum(int(p["words"]) for p in pages) // 4, completion_tokens=32)
        s.set_output(text)
        return text


@trace("async-research-agent")
async def research(question: str) -> str:
    async with span("gather", span_type="workflow") as s:
        s.set_input({"question": question})
        pages = await asyncio.gather(*(fetch(host, delay) for host, delay in PAGES.items()))
        s.set_output({"pages": len(pages)})

    return await answer(list(pages))


async def main() -> None:
    # Two independent runs, in flight at the same time: each gets its own trace.
    results = await asyncio.gather(
        research("what is a vector index?"),
        research("how do agents use tools?"),
    )
    for result in results:
        print(result)
    print("\nNow run:  agentlens ui")


if __name__ == "__main__":
    asyncio.run(main())
