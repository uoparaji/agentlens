/** Turning a flat list of spans into the execution tree the UI renders. */

import type { Span } from '../api'

export interface SpanNode {
  span: Span
  children: SpanNode[]
  depth: number
  /** Index in the flattened, depth-first order. */
  order: number
}

export interface TraceWindow {
  start: number
  end: number
  duration: number
}

/** Build the span tree. Spans whose parent is missing are treated as roots so
 *  a partially written trace still renders. */
export function buildTree(spans: Span[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>()
  for (const span of spans) {
    nodes.set(span.id, { span, children: [], depth: 0, order: 0 })
  }

  const roots: SpanNode[] = []
  for (const span of spans) {
    const node = nodes.get(span.id)!
    const parent = span.parent_span_id ? nodes.get(span.parent_span_id) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }

  const byStart = (a: SpanNode, b: SpanNode) =>
    new Date(a.span.start_time).getTime() - new Date(b.span.start_time).getTime()

  let order = 0
  const assign = (node: SpanNode, depth: number) => {
    node.depth = depth
    node.order = order++
    node.children.sort(byStart)
    for (const child of node.children) assign(child, depth + 1)
  }
  roots.sort(byStart)
  for (const root of roots) assign(root, 0)
  return roots
}

export interface FlatRow {
  node: SpanNode
  hasChildren: boolean
  collapsed: boolean
  /** Whether each ancestor level still has siblings below it, for tree guides. */
  guides: boolean[]
  isLast: boolean
}

export function flattenTree(roots: SpanNode[], collapsed: ReadonlySet<string>): FlatRow[] {
  const rows: FlatRow[] = []

  const walk = (node: SpanNode, guides: boolean[], isLast: boolean) => {
    const isCollapsed = collapsed.has(node.span.id)
    rows.push({
      node,
      hasChildren: node.children.length > 0,
      collapsed: isCollapsed,
      guides,
      isLast,
    })
    if (isCollapsed) return
    node.children.forEach((child, index) => {
      const last = index === node.children.length - 1
      walk(child, [...guides, !isLast], last)
    })
  }

  roots.forEach((root, index) => walk(root, [], index === roots.length - 1))
  return rows
}

/** Every descendant id of a node, used by expand/collapse-all. */
export function collectIds(nodes: SpanNode[], out: string[] = []): string[] {
  for (const node of nodes) {
    out.push(node.span.id)
    collectIds(node.children, out)
  }
  return out
}

/** The time window the waterfall is drawn against. */
export function traceWindow(spans: Span[]): TraceWindow {
  if (spans.length === 0) return { start: 0, end: 1, duration: 1 }
  let start = Infinity
  let end = -Infinity
  for (const span of spans) {
    const spanStart = new Date(span.start_time).getTime()
    const spanEnd = span.end_time
      ? new Date(span.end_time).getTime()
      : spanStart + (span.duration_ms ?? 0)
    start = Math.min(start, spanStart)
    end = Math.max(end, spanEnd)
  }
  // Running traces have no end yet; keep the window growing with the clock.
  if (spans.some((s) => s.status === 'running')) end = Math.max(end, Date.now())
  const duration = Math.max(end - start, 1)
  return { start, end, duration }
}

/** Fractional offset and width of a span's bar, clamped to the window. */
export function barGeometry(span: Span, window: TraceWindow) {
  const start = new Date(span.start_time).getTime()
  const end = span.end_time
    ? new Date(span.end_time).getTime()
    : Math.max(start + (span.duration_ms ?? 0), span.status === 'running' ? Date.now() : start)
  const offset = ((start - window.start) / window.duration) * 100
  const width = ((end - start) / window.duration) * 100
  return {
    offset: Math.max(0, Math.min(100, offset)),
    width: Math.max(0.35, Math.min(100 - Math.max(0, offset), width)),
  }
}

/** Nicely rounded tick marks for the timeline ruler. */
export function ticks(durationMs: number, count = 5): number[] {
  const rough = durationMs / count
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? magnitude * 10
  const result: number[] = []
  for (let value = 0; value <= durationMs + step * 0.001; value += step) result.push(value)
  return result
}
