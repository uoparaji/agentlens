/** Types and fetchers for the local AgentLens API. */

export type SpanStatus = 'running' | 'ok' | 'error'

export interface TokenUsage {
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
}

export interface SpanError {
  type: string
  message: string
  traceback: string | null
}

export interface Span {
  id: string
  trace_id: string
  parent_span_id: string | null
  name: string
  span_type: string
  status: SpanStatus
  start_time: string
  end_time: string | null
  duration_ms: number | null
  input: unknown
  output: unknown
  metadata: Record<string, unknown>
  error: SpanError | null
  model: string | null
  tokens: TokenUsage | null
}

export interface Trace {
  id: string
  name: string
  status: SpanStatus
  start_time: string
  end_time: string | null
  duration_ms: number | null
  metadata: Record<string, unknown>
  error: SpanError | null
  span_count: number
  model: string | null
  tokens: TokenUsage | null
}

export interface TraceDetail extends Trace {
  spans: Span[]
}

export interface TracePage {
  traces: Trace[]
  total: number
}

export interface Health {
  status: string
  version: string
  db_path: string
}

export interface Stats {
  trace_count: number
  span_count: number
  error_count: number
  total_tokens: number | null
  db_path: string | null
  db_size_bytes: number | null
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { accept: 'application/json' } })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) => get<Health>('/api/health', signal),
  traces: (params: { search?: string; status?: string; limit?: number }, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    if (params.search) query.set('search', params.search)
    if (params.status) query.set('status', params.status)
    query.set('limit', String(params.limit ?? 200))
    return get<TracePage>(`/api/traces?${query}`, signal)
  },
  trace: (id: string, signal?: AbortSignal) => get<TraceDetail>(`/api/traces/${id}`, signal),
  stats: (signal?: AbortSignal) => get<Stats>('/api/stats', signal),
  deleteTrace: async (id: string) => {
    const response = await fetch(`/api/traces/${id}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`Could not delete run (${response.status})`)
  },
}
