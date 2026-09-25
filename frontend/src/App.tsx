import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import type { Span } from './api'
import { usePolling } from './hooks/usePolling'
import { EmptyState } from './components/EmptyState'
import { RunList } from './components/RunList'
import { SpanInspector } from './components/SpanInspector'
import { TopBar } from './components/TopBar'
import { TraceView } from './components/TraceView'

const LIST_INTERVAL = 2000
const DETAIL_INTERVAL = 1500

export default function App() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null)
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null)
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const traces = usePolling(
    (signal) => api.traces({ search, status: status || undefined }, signal),
    [search, status],
    LIST_INTERVAL,
  )
  const stats = usePolling((signal) => api.stats(signal), [], LIST_INTERVAL)
  const health = usePolling((signal) => api.health(signal), [], null)
  const detail = usePolling(
    (signal) =>
      selectedTraceId ? api.trace(selectedTraceId, signal) : Promise.resolve(null),
    [selectedTraceId],
    DETAIL_INTERVAL,
  )

  const rows = useMemo(() => traces.data?.traces ?? [], [traces.data])

  // Keep a run selected so the dashboard is never an empty right-hand panel.
  useEffect(() => {
    if (rows.length === 0) {
      setSelectedTraceId(null)
      return
    }
    if (!selectedTraceId || !rows.some((trace) => trace.id === selectedTraceId)) {
      setSelectedTraceId(rows[0].id)
    }
  }, [rows, selectedTraceId])

  // Selecting a run opens its root span, which is the useful default.
  const spans = detail.data?.spans
  useEffect(() => {
    if (!spans || spans.length === 0) return
    if (!selectedSpanId || !spans.some((span) => span.id === selectedSpanId)) {
      setSelectedSpanId(spans[0].id)
    }
  }, [spans, selectedSpanId])

  const selectTrace = useCallback((id: string) => {
    setSelectedTraceId(id)
    setSelectedSpanId(null)
  }, [])

  // j / k move between runs, like less(1).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.metaKey || event.ctrlKey) return
      if (event.key !== 'j' && event.key !== 'k') return
      const index = rows.findIndex((trace) => trace.id === selectedTraceId)
      const next = event.key === 'j' ? index + 1 : index - 1
      if (next >= 0 && next < rows.length) {
        event.preventDefault()
        selectTrace(rows[next].id)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [rows, selectedTraceId, selectTrace])

  const toggleTheme = useCallback(() => {
    setDark((previous) => {
      const next = !previous
      document.documentElement.classList.toggle('dark', next)
      localStorage.setItem('agentlens-theme', next ? 'dark' : 'light')
      return next
    })
  }, [])

  const deleteTrace = useCallback(async () => {
    if (!selectedTraceId) return
    await api.deleteTrace(selectedTraceId)
    setSelectedTraceId(null)
    setSelectedSpanId(null)
    traces.refresh()
    stats.refresh()
  }, [selectedTraceId, traces, stats])

  const selectedSpan: Span | null =
    spans?.find((span) => span.id === selectedSpanId) ?? null

  const nothingRecorded = (stats.data?.trace_count ?? 0) === 0 && !traces.loading

  return (
    <div className="flex h-full flex-col">
      <TopBar
        stats={stats.data}
        dark={dark}
        onToggleTheme={toggleTheme}
        version={health.data?.version ?? ''}
        offline={Boolean(traces.error)}
      />

      {nothingRecorded ? (
        <EmptyState />
      ) : (
        <div className="flex min-h-0 flex-1">
          <RunList
            traces={rows}
            total={traces.data?.total ?? 0}
            selectedId={selectedTraceId}
            onSelect={selectTrace}
            search={search}
            onSearch={setSearch}
            status={status}
            onStatus={setStatus}
            loading={traces.loading}
          />

          {detail.data ? (
            <>
              <TraceView
                trace={detail.data}
                selectedSpanId={selectedSpanId}
                onSelectSpan={(span) => setSelectedSpanId(span.id)}
                onDelete={() => void deleteTrace()}
              />
              {selectedSpan && (
                <SpanInspector span={selectedSpan} onClose={() => setSelectedSpanId(null)} />
              )}
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-xs text-faint">
              {traces.error ? `Cannot reach the AgentLens server: ${traces.error}` : 'Select a run'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
