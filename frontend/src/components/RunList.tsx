import { useEffect, useRef } from 'react'
import type { Trace } from '../api'
import { formatCompact, formatDuration, formatRelativeTime } from '../lib/format'
import { SearchIcon, StatusDot } from './primitives'

const FILTERS = [
  { key: '', label: 'All' },
  { key: 'ok', label: 'Passed' },
  { key: 'error', label: 'Failed' },
  { key: 'running', label: 'Live' },
] as const

interface Props {
  traces: Trace[]
  total: number
  selectedId: string | null
  onSelect: (id: string) => void
  search: string
  onSearch: (value: string) => void
  status: string
  onStatus: (value: string) => void
  loading: boolean
}

export function RunList({
  traces,
  total,
  selectedId,
  onSelect,
  search,
  onSearch,
  status,
  onStatus,
  loading,
}: Props) {
  const selectedRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

  return (
    <aside className="flex h-full w-[20.5rem] shrink-0 flex-col border-r border-line bg-panel">
      <div className="space-y-2.5 border-b border-line px-3 py-3">
        <div className="relative">
          <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint">
            <SearchIcon />
          </span>
          <input
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Filter runs"
            spellCheck={false}
            className="focus-ring w-full rounded-md border border-line bg-raised py-1.5 pl-8 pr-2
                       text-xs text-ink placeholder:text-faint"
          />
        </div>
        <div className="flex gap-1">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              onClick={() => onStatus(filter.key)}
              className={`focus-ring flex-1 rounded px-2 py-1 text-2xs font-medium transition-colors ${
                status === filter.key
                  ? 'bg-raised text-ink'
                  : 'text-muted hover:bg-raised/60 hover:text-ink'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {traces.length === 0 && !loading && (
          <p className="px-4 py-8 text-center text-xs text-faint">
            {search || status ? 'No runs match this filter.' : 'No runs recorded yet.'}
          </p>
        )}
        {traces.map((trace) => {
          const active = trace.id === selectedId
          return (
            <button
              key={trace.id}
              ref={active ? selectedRef : undefined}
              onClick={() => onSelect(trace.id)}
              className={`group relative block w-full border-b border-line/60 px-3 py-2.5 text-left
                          transition-colors ${active ? 'bg-raised' : 'hover:bg-raised/50'}`}
            >
              {active && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
              <div className="flex items-center gap-2">
                <StatusDot status={trace.status} />
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink">
                  {trace.name}
                </span>
                <span className="num shrink-0 text-2xs text-muted">
                  {formatDuration(trace.duration_ms)}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-1.5 overflow-hidden whitespace-nowrap
                              pl-4 text-2xs text-faint">
                <span className="shrink-0">{formatRelativeTime(trace.start_time)}</span>
                <span className="shrink-0 text-line">·</span>
                <span className="num shrink-0">{trace.span_count} spans</span>
                {trace.tokens?.total_tokens ? (
                  <>
                    <span className="shrink-0 text-line">·</span>
                    <span className="num shrink-0">
                      {formatCompact(trace.tokens.total_tokens)} tok
                    </span>
                  </>
                ) : null}
                {trace.model && (
                  <span
                    className="ml-auto min-w-0 truncate rounded bg-raised px-1 py-px text-2xs text-muted"
                    title={trace.model}
                  >
                    {trace.model}
                  </span>
                )}
              </div>
            </button>
          )
        })}
      </div>

      <div className="border-t border-line px-3 py-2 text-2xs text-faint">
        {total} run{total === 1 ? '' : 's'}
        <span className="float-right">j k to change run</span>
      </div>
    </aside>
  )
}
