import { useMemo, useState } from 'react'

/** A small, dependency-free JSON viewer with collapsible nodes.
 *
 *  Span payloads are the reason anyone opens a tracing tool, so they get real
 *  syntax colouring rather than a grey blob of `JSON.stringify`.
 */

const PUNCT = 'text-faint'

function Primitive({ value }: { value: unknown }) {
  if (value === null) return <span className="text-rose-400/80">null</span>
  switch (typeof value) {
    case 'string':
      return <span className="text-emerald-600 dark:text-emerald-300">"{value}"</span>
    case 'number':
      return <span className="text-amber-600 dark:text-amber-300">{String(value)}</span>
    case 'boolean':
      return <span className="text-violet-600 dark:text-violet-300">{String(value)}</span>
    default:
      return <span className="text-muted">{String(value)}</span>
  }
}

function Node({
  name,
  value,
  depth,
  isLast,
}: {
  name?: string
  value: unknown
  depth: number
  isLast: boolean
}) {
  const isObject = value !== null && typeof value === 'object'
  const entries = useMemo(
    () => (isObject ? Object.entries(value as Record<string, unknown>) : []),
    [isObject, value],
  )
  // Deep structures start collapsed so a big payload stays scannable.
  const [open, setOpen] = useState(depth < 2 && entries.length <= 40)

  const key = name !== undefined && (
    <>
      <span className="text-sky-600 dark:text-sky-300">"{name}"</span>
      <span className={PUNCT}>: </span>
    </>
  )

  if (!isObject) {
    return (
      <div style={{ paddingLeft: depth * 14 }} className="whitespace-pre-wrap break-words">
        {key}
        <Primitive value={value} />
        {!isLast && <span className={PUNCT}>,</span>}
      </div>
    )
  }

  const isArray = Array.isArray(value)
  const openBrace = isArray ? '[' : '{'
  const closeBrace = isArray ? ']' : '}'

  if (entries.length === 0) {
    return (
      <div style={{ paddingLeft: depth * 14 }}>
        {key}
        <span className={PUNCT}>{openBrace + closeBrace}</span>
        {!isLast && <span className={PUNCT}>,</span>}
      </div>
    )
  }

  return (
    <div>
      <div style={{ paddingLeft: depth * 14 }} className="group flex items-baseline">
        <button
          onClick={() => setOpen((o) => !o)}
          className="-ml-3.5 mr-1 w-3 shrink-0 text-faint hover:text-ink"
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          {open ? '▾' : '▸'}
        </button>
        <span>
          {key}
          <span className={PUNCT}>{openBrace}</span>
          {!open && (
            <button onClick={() => setOpen(true)} className="mx-1 rounded bg-raised px-1 text-2xs text-muted hover:text-ink">
              {entries.length} {isArray ? 'items' : 'keys'}
            </button>
          )}
          {!open && (
            <>
              <span className={PUNCT}>{closeBrace}</span>
              {!isLast && <span className={PUNCT}>,</span>}
            </>
          )}
        </span>
      </div>
      {open && (
        <>
          {entries.map(([childKey, childValue], index) => (
            <Node
              key={childKey}
              name={isArray ? undefined : childKey}
              value={childValue}
              depth={depth + 1}
              isLast={index === entries.length - 1}
            />
          ))}
          <div style={{ paddingLeft: depth * 14 }}>
            <span className={PUNCT}>{closeBrace}</span>
            {!isLast && <span className={PUNCT}>,</span>}
          </div>
        </>
      )}
    </div>
  )
}

export function JsonView({ value }: { value: unknown }) {
  // A bare string (a prompt, a completion) reads better as text than as JSON.
  if (typeof value === 'string') {
    return (
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-ink">
        {value}
      </pre>
    )
  }
  return (
    <div className="pl-3.5 font-mono text-xs leading-relaxed text-ink">
      <Node value={value} depth={0} isLast />
    </div>
  )
}
