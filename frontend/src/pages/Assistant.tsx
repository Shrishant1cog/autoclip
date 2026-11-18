/**
 * The project-aware assistant.
 *
 * It answers questions about *this* AutoClip installation using a snapshot of
 * its real state. The snapshot is shown to the user on request, so it is
 * always clear what the assistant could and could not have known.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { Markdown } from '../components/Markdown'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  provider?: string
}

export function Assistant() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [starters, setStarters] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [showContext, setShowContext] = useState(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    api
      .chatStarters()
      .then((data) => setStarters(data.starters))
      .catch(() => undefined)
    api
      .chatContext()
      .then((data) => setPrompt(data.prompt))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  const send = useCallback(
    async (text: string) => {
      const message = text.trim()
      if (!message || sending) return

      setError(null)
      setSending(true)
      const history = turns.map((turn) => ({ role: turn.role, content: turn.content }))
      setTurns((current) => [...current, { role: 'user', content: message }])

      try {
        const result = await api.askAssistant(message, history)
        setTurns((current) => [
          ...current,
          { role: 'assistant', content: result.answer, provider: result.provider },
        ])
      } catch (err) {
        setError(err as Error)
        // Drop the unanswered question so the user can retry it cleanly.
        setTurns((current) => current.slice(0, -1))
      } finally {
        setSending(false)
        setDraft('')
      }
    },
    [turns, sending],
  )

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Assistant</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          Ask about this project
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-ink-400">
          The assistant sees this installation's real state — your clips, jobs, failures,
          channels and settings — and nothing else. It will tell you when the project
          data does not record something.
        </p>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {turns.length === 0 && (
            <div className="border border-ink-800 bg-ink-850/30 p-6">
              <h2 className="eyebrow">Try asking</h2>
              <div className="mt-4 flex flex-col gap-2">
                {starters.map((starter) => (
                  <button
                    key={starter}
                    onClick={() => void send(starter)}
                    className="border border-ink-800 px-4 py-3 text-left text-sm text-ink-200 transition-colors hover:border-sodium-600/60 hover:text-ink-100"
                  >
                    {starter}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-5">
            {turns.map((turn, index) => (
              <article
                key={index}
                className={
                  turn.role === 'user'
                    ? 'ml-auto max-w-3xl border border-ink-700 bg-ink-800/60 px-4 py-3'
                    : 'max-w-3xl border-l-2 border-sodium-600/70 pl-4'
                }
              >
                <div className="flex items-baseline gap-3">
                  <span className="eyebrow">
                    {turn.role === 'user' ? 'You' : 'Assistant'}
                  </span>
                  {turn.provider && (
                    <span className="text-[10px] uppercase tracking-wider text-ink-500">
                      {turn.provider}
                    </span>
                  )}
                </div>
                <div className="mt-2 text-sm text-ink-200">
                  {turn.role === 'assistant' ? <Markdown text={turn.content} /> : turn.content}
                </div>
              </article>
            ))}
            {sending && (
              <p className="text-sm text-ink-500">Thinking…</p>
            )}
            <div ref={bottomRef} />
          </div>

          <form
            className="mt-8 flex items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              void send(draft)
            }}
          >
            <textarea
              className="field min-h-20 flex-1 resize-y text-sm"
              placeholder="What do you want to know about this project?"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send(draft)
                }
              }}
              spellCheck={false}
            />
            <button type="submit" disabled={sending || !draft.trim()} className="btn btn-primary">
              Send
            </button>
          </form>
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <button
            onClick={() => setShowContext((value) => !value)}
            className="text-xs text-ink-400 underline-offset-4 hover:text-ink-200 hover:underline"
          >
            {showContext ? 'Hide' : 'Show'} what the assistant can see
          </button>
          {showContext && (
            <pre className="mt-3 max-h-[28rem] overflow-auto whitespace-pre-wrap border border-ink-800 bg-ink-850/40 p-3 text-[11px] leading-relaxed text-ink-400">
              {prompt || 'The project snapshot could not be loaded.'}
            </pre>
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-ink-600">
            This is the complete factual brief sent with your question. Anything not in
            it, the assistant has not been told.
          </p>
        </aside>
      </div>
    </div>
  )
}
