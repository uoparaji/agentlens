import { useState } from 'react'
import type { Span } from '../api'
import { formatDuration, formatTimestamp } from '../lib/format'
import { spanTypeStyle } from '../lib/spanTypes'
import { CopyIcon, Field, SectionTitle, StatusDot, TypeBadge } from './primitives'
import { JsonView } from './JsonView'

function CopyButton({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1200)
        })
      }}
      className="focus-ring flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-faint
                 hover:bg-raised hover:text-ink"
    >
      <CopyIcon />
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function Payload({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined) return null
  return (
    <section>
      <SectionTitle right={<CopyButton value={value} />}>{title}</SectionTitle>
      <div className="mx-4 overflow-x-auto rounded-md border border-line bg-raised/50 p-3">
        <JsonView value={value} />
      </div>
    </section>
  )
}

export function SpanInspector({ span, onClose }: { span: Span; onClose: () => void }) {
  const style = spanTypeStyle(span.span_type)
  const tokens = span.tokens
  const metadata = Object.keys(span.metadata ?? {}).length > 0 ? span.metadata : null

  return (
    <aside className="flex h-full w-[24rem] shrink-0 flex-col border-l border-line bg-panel">
      <header className="shrink-0 border-b border-line px-4 py-3">
        <div className="flex items-start gap-2">
          <StatusDot status={span.status} className="mt-1.5" />
          <h2 className="min-w-0 flex-1 break-words text-sm font-medium text-ink">{span.name}</h2>
          <button
            onClick={onClose}
            className="focus-ring -mr-1 rounded px-1.5 text-muted hover:bg-raised hover:text-ink"
            aria-label="Close inspector"
          >
            ✕
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-4">
          <TypeBadge spanType={span.span_type} />
          {span.model && (
            <span className="chip">
              <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
              {span.model}
            </span>
          )}
          <span className="chip num">{formatDuration(span.duration_ms)}</span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto pb-6">
        {span.error && (
          <section className="mx-4 mt-4 rounded-md border border-rose-500/30 bg-rose-500/5 p-3">
            <p className="font-mono text-xs font-semibold text-rose-500">{span.error.type}</p>
            <p className="mt-1 break-words font-mono text-xs text-rose-600 dark:text-rose-300">
              {span.error.message}
            </p>
            {span.error.traceback && (
              <details className="mt-2">
                <summary className="cursor-pointer text-2xs text-muted hover:text-ink">
                  Traceback
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words
                                font-mono text-2xs leading-relaxed text-muted">
                  {span.error.traceback}
                </pre>
              </details>
            )}
          </section>
        )}

        <section className="px-4 pt-4">
          <div className="divide-y divide-line/60">
            <Field label="Status">
              <span className="capitalize">{span.status}</span>
            </Field>
            <Field label="Started">{formatTimestamp(span.start_time)}</Field>
            <Field label="Ended">
              {span.end_time ? formatTimestamp(span.end_time) : '—'}
            </Field>
            <Field label="Duration">
              <span className="num">{formatDuration(span.duration_ms)}</span>
            </Field>
            {tokens && (
              <Field label="Tokens">
                <span className="num">
                  {tokens.prompt_tokens ?? 0} in · {tokens.completion_tokens ?? 0} out ·{' '}
                  <span className="text-ink">{tokens.total_tokens ?? 0} total</span>
                </span>
              </Field>
            )}
            <Field label="Span id">
              <span className="num text-faint">{span.id.slice(0, 16)}</span>
            </Field>
            {span.parent_span_id && (
              <Field label="Parent">
                <span className="num text-faint">{span.parent_span_id.slice(0, 16)}</span>
              </Field>
            )}
          </div>
        </section>

        <Payload title="Input" value={span.input} />
        <Payload title="Output" value={span.output} />
        <Payload title="Metadata" value={metadata} />

        {span.input === null && span.output === null && (
          <p className="px-4 pt-4 text-2xs leading-relaxed text-faint">
            No input or output was recorded for this span.
          </p>
        )}
      </div>
    </aside>
  )
}
