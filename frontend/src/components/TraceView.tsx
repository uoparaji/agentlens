import type { TraceDetail } from '../api'
import { formatCompact, formatDuration, formatTimestamp } from '../lib/format'
import { STATUS_STYLE, spanTypeStyle } from '../lib/spanTypes'
import { StatusDot, TrashIcon } from './primitives'
import { Waterfall } from './Waterfall'
import type { Span } from '../api'

interface Props {
  trace: TraceDetail
  selectedSpanId: string | null
  onSelectSpan: (span: Span) => void
  onDelete: () => void
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-2xs uppercase tracking-wider text-faint">{label}</span>
      <span className="num text-xs text-ink">{value}</span>
    </div>
  )
}

export function TraceView({ trace, selectedSpanId, onSelectSpan, onDelete }: Props) {
  const status = STATUS_STYLE[trace.status] ?? STATUS_STYLE.ok
  const tokens = trace.tokens?.total_tokens ?? null
  const usedTypes = Array.from(new Set(trace.spans.map((span) => span.span_type)))

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface">
      <header className="shrink-0 border-b border-line bg-panel px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <StatusDot status={trace.status} />
          <h1 className="min-w-0 truncate text-sm font-semibold text-ink">{trace.name}</h1>
          <span className={`text-2xs font-medium uppercase tracking-wider ${status.text}`}>
            {status.label}
          </span>
          <button
            onClick={onDelete}
            title="Delete this run"
            className="focus-ring ml-auto rounded px-1.5 py-1 text-faint hover:bg-raised hover:text-rose-500"
          >
            <TrashIcon />
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3">
          <Stat label="Duration" value={formatDuration(trace.duration_ms)} />
          <Stat label="Spans" value={String(trace.span_count)} />
          <Stat label="Tokens" value={tokens != null ? formatCompact(tokens) : '—'} />
          <Stat label="Model" value={trace.model ?? '—'} />
          <Stat label="Started" value={formatTimestamp(trace.start_time)} />
          <Stat label="Trace id" value={trace.id.slice(0, 12)} />
        </div>

        {trace.error && (
          <p className="mt-3 truncate rounded-md border border-rose-500/30 bg-rose-500/5 px-3 py-2
                        font-mono text-xs text-rose-600 dark:text-rose-300">
            <span className="font-semibold">{trace.error.type}:</span> {trace.error.message}
          </p>
        )}
      </header>

      <Waterfall spans={trace.spans} selectedId={selectedSpanId} onSelect={onSelectSpan} />

      <footer className="flex shrink-0 flex-wrap items-center gap-4 border-t border-line
                         bg-panel px-5 py-2">
        {usedTypes.map((spanType) => {
          const style = spanTypeStyle(spanType)
          return (
            <span key={spanType} className="flex items-center gap-1.5 text-2xs text-muted">
              <span className={`h-2 w-2 rounded-sm ${style.bar}`} />
              {style.label}
            </span>
          )
        })}
        <span className="ml-auto text-2xs text-faint">
          click a span to inspect · ↑↓ to move · ←→ to fold
        </span>
      </footer>
    </section>
  )
}
