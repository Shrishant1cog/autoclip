/**
 * A tiny Markdown renderer for assistant replies.
 *
 * The assistant answers in prose with emphasis, lists and code spans. Rather
 * than pull in a Markdown library for that subset, this handles exactly what
 * the model uses.
 *
 * It builds React elements and never HTML strings, so an answer cannot inject
 * markup — no `dangerouslySetInnerHTML` anywhere.
 */
import { Fragment, type ReactNode } from 'react'

/** Bold, italic and inline code — bold first so `**` wins over `*`. */
const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`)/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(INLINE).filter((part) => part !== '')
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={key} className="font-semibold text-ink-100">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={key} className="bg-ink-800 px-1 py-0.5 font-mono text-[0.85em] text-sodium-300">
          {part.slice(1, -1)}
        </code>
      )
    }
    return <Fragment key={key}>{part}</Fragment>
  })
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    // Fenced code block.
    if (line.trim().startsWith('```')) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre
          key={`b${key++}`}
          className="my-2 overflow-x-auto border border-ink-800 bg-ink-900 p-3 text-xs leading-relaxed text-ink-300"
        >
          <code>{body.join('\n')}</code>
        </pre>,
      )
      continue
    }

    // Heading.
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const sizes = ['text-base', 'text-sm', 'text-sm', 'text-xs']
      blocks.push(
        <p
          key={`b${key++}`}
          className={`mt-3 font-semibold text-ink-100 ${sizes[level - 1]} uppercase tracking-wide`}
        >
          {renderInline(heading[2], `h${key}`)}
        </p>,
      )
      index += 1
      continue
    }

    // Bullet list.
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={`b${key++}`} className="my-2 space-y-1">
          {items.map((item, itemIndex) => (
            <li key={itemIndex} className="flex gap-2">
              <span className="select-none text-sodium-500">·</span>
              <span>{renderInline(item, `l${key}-${itemIndex}`)}</span>
            </li>
          ))}
        </ul>,
      )
      continue
    }

    // Numbered list.
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ol key={`b${key++}`} className="my-2 list-inside list-decimal space-y-1">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item, `n${key}-${itemIndex}`)}</li>
          ))}
        </ol>,
      )
      continue
    }

    // Blank line.
    if (line.trim() === '') {
      index += 1
      continue
    }

    // Paragraph — consecutive lines join.
    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() !== '' &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !lines[index].trim().startsWith('```') &&
      !/^#{1,4}\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push(
      <p key={`b${key++}`} className="my-2 leading-relaxed">
        {renderInline(paragraph.join(' '), `p${key}`)}
      </p>,
    )
  }

  return <div className="text-ink-200">{blocks}</div>
}
