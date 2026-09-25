"""Tracing a plain synchronous Python agent -- no framework involved.

    python examples/custom_agent.py
    agentlens ui

Everything here is mocked, so it runs without any API key.
"""

from __future__ import annotations

import random
import time

from agentlens import span, trace

RESULTS = {
    "vector databases": ["FAISS paper", "HNSW paper", "ANN benchmarks"],
    "agent evaluation": ["AgentBench", "SWE-bench", "tau-bench"],
}


def search(query: str) -> list[str]:
    """A pretend web search."""
    with span("search", span_type="tool", metadata={"query": query, "engine": "mock"}) as s:
        time.sleep(random.uniform(0.05, 0.15))
        results = RESULTS.get(query, ["nothing found"])
        s.set_output(results)
        return results


def summarize(documents: list[str]) -> str:
    """A pretend LLM call. Note the model and token counts on the span."""
    with span("summarize", span_type="llm") as s:
        s.set_input({"documents": documents})
        s.set_model("demo-sonnet-4")
        time.sleep(random.uniform(0.1, 0.3))
        answer = f"Key sources: {', '.join(documents)}."
        s.set_tokens(prompt_tokens=len(documents) * 40, completion_tokens=len(answer) // 4)
        s.set_output(answer)
        return answer


@trace
def research_agent(topic: str) -> str:
    """The run itself. Arguments and the return value are captured for you."""
    documents = search(topic)

    with span("filter", span_type="custom") as s:
        keep = [d for d in documents if "nothing" not in d]
        s.set_metadata(kept=len(keep), dropped=len(documents) - len(keep))
        s.set_output(keep)

    return summarize(keep)


if __name__ == "__main__":
    print(research_agent("vector databases"))
    print(research_agent("agent evaluation"))
    print("\nNow run:  agentlens ui")
