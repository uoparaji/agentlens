/** Small formatting helpers. Durations and counts appear everywhere, so they
 *  are formatted in exactly one place. */

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms === 0) return '0 ms'
  if (ms < 1) return `${(ms * 1000).toFixed(0)} µs`
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  const minutes = Math.floor(ms / 60_000)
  return `${minutes}m ${((ms % 60_000) / 1000).toFixed(0)}s`
}

export function formatCompact(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`
  return `${(value / 1_000_000).toFixed(1)}M`
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

export function formatRelativeTime(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 45) return 'just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`
  if (seconds < 604_800) return `${Math.round(seconds / 86_400)}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatClock(iso: string, withMillis = false): string {
  const date = new Date(iso)
  const base = date.toLocaleTimeString(undefined, { hour12: false })
  return withMillis ? `${base}.${String(date.getMilliseconds()).padStart(3, '0')}` : base
}

export function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  return `${date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })} ${formatClock(iso, true)}`
}
