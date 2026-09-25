import type { Stats } from '../api'
import { formatBytes, formatCompact } from '../lib/format'
import { MoonIcon, SunIcon } from './primitives'

interface Props {
  stats: Stats | null
  dark: boolean
  onToggleTheme: () => void
  version: string
  offline: boolean
}

export function TopBar({ stats, dark, onToggleTheme, version, offline }: Props) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel px-4">
      <img src="/logo.png" alt="" className="h-7 w-7 shrink-0 rounded" />
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-semibold tracking-tight text-ink">AgentLens</span>
        {version && <span className="num text-2xs text-faint">v{version}</span>}
      </div>

      <div className="ml-6 hidden items-center gap-5 md:flex">
        <Metric label="runs" value={stats ? String(stats.trace_count) : '—'} />
        <Metric label="spans" value={stats ? String(stats.span_count) : '—'} />
        <Metric
          label="errors"
          value={stats ? String(stats.error_count) : '—'}
          tone={stats && stats.error_count > 0 ? 'text-rose-500' : undefined}
        />
        <Metric label="tokens" value={stats ? formatCompact(stats.total_tokens) : '—'} />
      </div>

      <div className="ml-auto flex items-center gap-3">
        {offline && (
          <span className="chip border-amber-500/40 text-amber-600 dark:text-amber-400">
            server unreachable
          </span>
        )}
        {stats?.db_path && (
          <span
            className="num hidden max-w-[22rem] truncate text-2xs text-faint lg:block"
            title={`${stats.db_path} (${formatBytes(stats.db_size_bytes)}) — stored locally`}
          >
            {stats.db_path}
          </span>
        )}
        <button
          onClick={onToggleTheme}
          className="focus-ring rounded-md p-1.5 text-muted hover:bg-raised hover:text-ink"
          aria-label="Toggle theme"
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
    </header>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={`num text-xs font-medium ${tone ?? 'text-ink'}`}>{value}</span>
      <span className="text-2xs text-faint">{label}</span>
    </span>
  )
}
