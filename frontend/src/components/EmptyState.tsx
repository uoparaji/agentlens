const SNIPPET = `from agentlens import trace, span

@trace
def research_agent(topic: str):
    with span("search", span_type="tool"):
        results = search(topic)
    with span("summarize", span_type="llm"):
        return summarize(results)`

export function EmptyState() {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-surface p-8">
      <div className="max-w-lg animate-fade-in">
        <img src="/logo.png" alt="" className="mb-5 h-14 w-14 rounded-lg" />
        <h2 className="text-lg font-semibold tracking-tight text-ink">No runs yet</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">
          Instrument a function and run it — this page updates on its own.
        </p>

        <pre className="mt-5 overflow-x-auto rounded-lg border border-line bg-panel p-4
                        font-mono text-xs leading-relaxed text-ink">
          {SNIPPET}
        </pre>

        <p className="mt-5 text-sm text-muted">
          Or generate a sample trace right now:
        </p>
        <p className="mt-2 rounded-lg border border-line bg-panel px-4 py-3 font-mono text-xs text-ink">
          <span className="select-none text-faint">$ </span>agentlens demo
        </p>
      </div>
    </div>
  )
}
