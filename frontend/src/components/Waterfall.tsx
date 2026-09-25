import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Span } from '../api'
import { formatDuration } from '../lib/format'
import { spanTypeStyle } from '../lib/spanTypes'
import type { SpanNode } from '../lib/tree'
import { barGeometry, buildTree, collectIds, flattenTree, ticks, traceWindow } from '../lib/tree'
import { AlertIcon, Chevron } from './primitives'

const ROW_HEIGHT = 28
const MIN_TREE_WIDTH = 200
const MAX_TREE_WIDTH = 640

interface Props {
  spans: Span[]
  selectedId: string | null
  onSelect: (span: Span) => void
}

/** The trace waterfall: an execution tree on the left, a time-proportional
 *  bar chart on the right. Slow spans are meant to be obvious without reading
 *  a single number. */
export function Waterfall({ spans, selectedId, onSelect }: Props) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [treeWidth, setTreeWidth] = useState(288)
  const [hovered, setHovered] = useState<string | null>(null)
  const dragging = useRef(false)

  const roots = useMemo(() => buildTree(spans), [spans])
  const timeWindow = useMemo(() => traceWindow(spans), [spans])
  const rows = useMemo(() => flattenTree(roots, collapsed), [roots, collapsed])
  const marks = useMemo(() => ticks(timeWindow.duration), [timeWindow.duration])
  const slowest = useMemo(
    () => spans.reduce((max, span) => Math.max(max, span.duration_ms ?? 0), 0),
    [spans],
  )

  const toggle = useCallback((id: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const allCollapsed = collapsed.size > 0

  const onDividerDown = (event: React.PointerEvent) => {
    event.preventDefault()
    dragging.current = true
    const startX = event.clientX
    const startWidth = treeWidth
    const move = (e: PointerEvent) => {
      if (!dragging.current) return
      const next = Math.min(MAX_TREE_WIDTH, Math.max(MIN_TREE_WIDTH, startWidth + e.clientX - startX))
      setTreeWidth(next)
    }
    const up = () => {
      dragging.current = false
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // Arrow-key navigation between spans, like a real debugger.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return
      const index = rows.findIndex((row) => row.node.span.id === selectedId)
      if (event.key === 'ArrowDown' && index < rows.length - 1) {
        event.preventDefault()
        onSelect(rows[index + 1].node.span)
      } else if (event.key === 'ArrowUp' && index > 0) {
        event.preventDefault()
        onSelect(rows[index - 1].node.span)
      } else if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && index >= 0) {
        const row = rows[index]
        if (row.hasChildren) {
          event.preventDefault()
          const shouldCollapse = event.key === 'ArrowLeft'
          if (shouldCollapse !== row.collapsed) toggle(row.node.span.id)
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [rows, selectedId, onSelect, toggle])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Ruler */}
      <div className="flex shrink-0 items-stretch border-b border-line bg-panel">
        <div
          style={{ width: treeWidth }}
          className="flex shrink-0 items-center justify-between gap-2 px-4 py-2"
        >
          <span className="text-2xs font-semibold uppercase tracking-wider text-faint">
            {rows.length} span{rows.length === 1 ? '' : 's'}
          </span>
          <button
            onClick={() => setCollapsed(allCollapsed ? new Set() : new Set(collectIds(roots)))}
            className="focus-ring rounded px-1.5 py-0.5 text-2xs text-muted hover:bg-raised hover:text-ink"
          >
            {allCollapsed ? 'Expand all' : 'Collapse all'}
          </button>
        </div>
        <div className="relative min-w-0 flex-1 px-4 py-2">
          {marks.map((mark, index) => (
            <span
              key={mark}
              style={{ left: `${(mark / timeWindow.duration) * 100}%` }}
              className={`num absolute top-2 whitespace-nowrap text-2xs text-faint ${
                index === 0
                  ? ''
                  : index === marks.length - 1
                    ? '-translate-x-full'
                    : '-translate-x-1/2'
              }`}
            >
              {mark === 0 ? '0' : formatDuration(mark)}
            </span>
          ))}
        </div>
      </div>

      {/* Rows */}
      <div className="relative min-h-0 flex-1 overflow-auto">
        <div className="relative min-w-full" style={{ minHeight: rows.length * ROW_HEIGHT }}>
          {/* Grid lines behind everything */}
          <div
            className="pointer-events-none absolute inset-y-0 right-0"
            style={{ left: treeWidth }}
            aria-hidden
          >
            <div className="relative mx-4 h-full">
              {marks.map((mark) => (
                <span
                  key={mark}
                  style={{ left: `${(mark / timeWindow.duration) * 100}%` }}
                  className="absolute inset-y-0 w-px bg-line/60"
                />
              ))}
            </div>
          </div>

          {rows.map((row) => {
            const span = row.node.span
            const style = spanTypeStyle(span.span_type)
            const geometry = barGeometry(span, timeWindow)
            const isSelected = span.id === selectedId
            const isError = span.status === 'error'
            const isSlowest = slowest > 0 && span.duration_ms === slowest && spans.length > 1
            // Long bars get their label inside, so it can never collide with the bar.
            const labelInside = geometry.offset + geometry.width > 82

            return (
              <div
                key={span.id}
                onClick={() => onSelect(span)}
                onMouseEnter={() => setHovered(span.id)}
                onMouseLeave={() => setHovered(null)}
                style={{ height: ROW_HEIGHT }}
                className={`group relative flex cursor-pointer items-stretch ${
                  isSelected ? 'bg-accent/10' : hovered === span.id ? 'bg-raised/60' : ''
                }`}
              >
                {isSelected && <span className="absolute inset-y-0 left-0 z-10 w-0.5 bg-accent" />}

                {/* Tree column */}
                <div
                  style={{ width: treeWidth }}
                  className="flex shrink-0 items-center gap-1 overflow-hidden pl-3 pr-2"
                >
                  {row.guides.map((visible, index) => (
                    <span
                      key={index}
                      className={`h-full w-3 shrink-0 ${visible ? 'border-l border-line' : ''}`}
                    />
                  ))}
                  <button
                    onClick={(event) => {
                      event.stopPropagation()
                      toggle(span.id)
                    }}
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-faint
                                hover:bg-raised hover:text-ink ${row.hasChildren ? '' : 'invisible'}`}
                    aria-label={row.collapsed ? 'Expand' : 'Collapse'}
                  >
                    <Chevron open={!row.collapsed} />
                  </button>
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isError ? 'bg-rose-500' : style.dot}`} />
                  <span
                    className={`min-w-0 flex-1 truncate text-xs ${
                      isSelected ? 'font-medium text-ink' : 'text-ink/90'
                    }`}
                    title={span.name}
                  >
                    {span.name}
                  </span>
                  {isError && <AlertIcon className="shrink-0 text-rose-500" />}
                  {row.collapsed && row.hasChildren && (
                    <span className="num shrink-0 rounded bg-raised px-1 text-2xs text-faint">
                      +{countDescendants(row.node)}
                    </span>
                  )}
                  <span className={`shrink-0 text-2xs uppercase tracking-wide ${style.text} opacity-70`}>
                    {style.label}
                  </span>
                </div>

                {/* Bar column */}
                <div className="relative min-w-0 flex-1 px-4">
                  <div className="relative h-full">
                    <div
                      style={{ left: `${geometry.offset}%`, width: `${geometry.width}%` }}
                      className={`absolute top-1/2 h-[11px] -translate-y-1/2 rounded-[3px]
                                  transition-[filter,opacity] ${
                                    isError ? 'bg-rose-500' : style.bar
                                  } ${isSelected ? '' : 'opacity-85 group-hover:opacity-100'} ${
                                    span.status === 'running' ? 'animate-pulse' : ''
                                  }`}
                    >
                      {isSlowest && !isError && (
                        <span className="absolute inset-0 rounded-[3px] ring-1 ring-inset ring-white/30" />
                      )}
                    </div>
                    <span
                      style={
                        labelInside
                          ? { right: `${Math.max(0, 100 - geometry.offset - geometry.width)}%` }
                          : { left: `${geometry.offset + geometry.width}%` }
                      }
                      className={`num pointer-events-none absolute top-1/2 z-10 -translate-y-1/2
                                  whitespace-nowrap text-2xs ${
                                    labelInside
                                      ? 'mr-1.5 text-white/95 mix-blend-normal'
                                      : `ml-2 ${isSelected ? 'text-ink' : 'text-muted'}`
                                  }`}
                    >
                      {formatDuration(span.duration_ms)}
                      {span.tokens?.total_tokens ? (
                        <span className={labelInside ? 'ml-2 text-white/70' : 'ml-2 text-faint'}>
                          {span.tokens.total_tokens} tok
                        </span>
                      ) : null}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}

          {/* Draggable divider */}
          <div
            onPointerDown={onDividerDown}
            style={{ left: treeWidth - 2 }}
            className="absolute inset-y-0 z-20 w-1 cursor-col-resize bg-line/0 hover:bg-accent/40"
            role="separator"
            aria-orientation="vertical"
          />
        </div>
      </div>
    </div>
  )
}

function countDescendants(node: SpanNode): number {
  return node.children.reduce((total, child) => total + 1 + countDescendants(child), 0)
}
