"""Tracing LlamaIndex automatically.

    pip install 'agentlens[llamaindex]'
    python examples/llamaindex_agent.py
    agentlens ui

Uses LlamaIndex's own mock LLM and embedding model, so it needs no API key.
Swap in a real ``Settings.llm`` and the traces gain real models and token counts.
"""

from __future__ import annotations

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM

import agentlens
from agentlens.integrations.llamaindex import instrument

DOCUMENTS = [
    "AgentLens is a local-first tracing toolkit for AI agents.",
    "A trace is one agent run; spans are the steps inside it.",
    "Spans record timing, token usage, inputs, outputs and errors.",
]


def main() -> None:
    # One call: every LlamaIndex span now lands in AgentLens.
    instrument()

    Settings.llm = MockLLM(max_tokens=64)
    Settings.embed_model = MockEmbedding(embed_dim=16)

    # Wrapping the work in a trace of your own keeps indexing and querying in a
    # single run instead of one run per top-level LlamaIndex call.
    with agentlens.trace("llamaindex-rag") as run:
        index = VectorStoreIndex.from_documents([Document(text=t) for t in DOCUMENTS])
        engine = index.as_query_engine()
        answer = engine.query("What does AgentLens record?")
        run.set_output(str(answer))

    print(answer)
    print("\nNow run:  agentlens ui")


if __name__ == "__main__":
    main()
