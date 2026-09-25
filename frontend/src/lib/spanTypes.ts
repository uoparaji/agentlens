/** Visual identity for span types.
 *
 *  Colours are taken from the AgentLens mark: cyan for agents, violet for
 *  model calls, green for tools, amber for retrieval. Each type keeps the same
 *  colour in the tree, the waterfall and the inspector so a trace can be read
 *  at a glance.
 */

export interface SpanTypeStyle {
  label: string
  /** Waterfall bar (solid). */
  bar: string
  /** Text + badge colour. */
  text: string
  /** Badge background. */
  chip: string
  /** Tree dot. */
  dot: string
}

const STYLES: Record<string, SpanTypeStyle> = {
  agent: {
    label: 'agent',
    bar: 'bg-sky-400',
    text: 'text-sky-500 dark:text-sky-300',
    chip: 'bg-sky-500/10 text-sky-600 dark:text-sky-300 ring-sky-500/20',
    dot: 'bg-sky-400',
  },
  llm: {
    label: 'llm',
    bar: 'bg-violet-400',
    text: 'text-violet-500 dark:text-violet-300',
    chip: 'bg-violet-500/10 text-violet-600 dark:text-violet-300 ring-violet-500/20',
    dot: 'bg-violet-400',
  },
  tool: {
    label: 'tool',
    bar: 'bg-emerald-400',
    text: 'text-emerald-600 dark:text-emerald-300',
    chip: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300 ring-emerald-500/20',
    dot: 'bg-emerald-400',
  },
  retrieval: {
    label: 'retrieval',
    bar: 'bg-amber-400',
    text: 'text-amber-600 dark:text-amber-300',
    chip: 'bg-amber-500/10 text-amber-600 dark:text-amber-300 ring-amber-500/20',
    dot: 'bg-amber-400',
  },
  workflow: {
    label: 'workflow',
    bar: 'bg-indigo-400',
    text: 'text-indigo-500 dark:text-indigo-300',
    chip: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-300 ring-indigo-500/20',
    dot: 'bg-indigo-400',
  },
  custom: {
    label: 'custom',
    bar: 'bg-slate-400',
    text: 'text-slate-500 dark:text-slate-300',
    chip: 'bg-slate-500/10 text-slate-600 dark:text-slate-300 ring-slate-500/20',
    dot: 'bg-slate-400',
  },
}

export function spanTypeStyle(spanType: string): SpanTypeStyle {
  return STYLES[spanType] ?? { ...STYLES.custom, label: spanType }
}

export const STATUS_STYLE: Record<string, { dot: string; text: string; label: string }> = {
  ok: { dot: 'bg-emerald-400', text: 'text-emerald-600 dark:text-emerald-400', label: 'ok' },
  error: { dot: 'bg-rose-500', text: 'text-rose-600 dark:text-rose-400', label: 'error' },
  running: { dot: 'bg-sky-400', text: 'text-sky-600 dark:text-sky-400', label: 'running' },
}
