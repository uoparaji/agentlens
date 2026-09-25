import { useCallback, useEffect, useRef, useState } from 'react'

interface PollingState<T> {
  data: T | null
  error: string | null
  loading: boolean
  refresh: () => void
}

/** Fetch on mount and then on an interval, with in-flight requests aborted on
 *  change. Polling is what makes the dashboard feel live while an agent runs. */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  intervalMs: number | null,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    const run = async (isFirst: boolean) => {
      if (isFirst) setLoading(true)
      try {
        const result = await fetcherRef.current(controller.signal)
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      } catch (err) {
        if (!cancelled && (err as Error).name !== 'AbortError') {
          setError((err as Error).message)
        }
      } finally {
        if (!cancelled && isFirst) setLoading(false)
      }
    }

    void run(true)
    const timer = intervalMs ? window.setInterval(() => void run(false), intervalMs) : undefined

    return () => {
      cancelled = true
      controller.abort()
      if (timer) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, intervalMs, nonce])

  return { data, error, loading, refresh }
}
