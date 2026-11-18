/**
 * The recovery centre.
 *
 * Everything that failed, in one list: failed jobs, failed uploads, and clips
 * whose render did not survive validation. Each row carries the real error and
 * the action that would fix it — the retry button calls the endpoint that
 * already owns that work.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import { ErrorNote } from '../components/ErrorNote'

interface RecoveryItem {
  kind: 'job' | 'upload' | 'clip'
  id: string
  title: string
  detail: string
  code: string
  retryable: boolean
  action: string
  action_label: string
  link: string
  entity_id: string
  created_at: string
}

const KIND_LABEL: Record<string, string> = {
  job: 'Job',
  upload: 'Upload',
  clip: 'Clip',
}

const CODE_LABEL: Record<string, string> = {
  auth: 'Credentials',
  quota: 'Quota used up',
  rate_limit: 'Rate limited',
  provider: 'AI provider',
  network: 'Network',
  timeout: 'Timed out',
  not_found: 'Missing',
  validation: 'Invalid input',
  config: 'Settings',
  media: 'Media',
  conflict: 'Conflict',
  internal: 'Unexpected',
}

export function Recovery() {
  const [items, setItems] = useState<RecoveryItem[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<Error | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const report = await api.recoveryReport()
      setItems(report.items)
      setCounts(report.counts)
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const retry = async (item: RecoveryItem) => {
    setBusy(item.id)
    setError(null)
    try {
      await api.retryAction(item.action)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Recovery</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          What needs attention
        </h1>
        <p className="numeric mt-3 text-xs text-ink-500">
          {counts.total ?? 0} items
          {counts.job ? ` · ${counts.job} jobs` : ''}
          {counts.upload ? ` · ${counts.upload} uploads` : ''}
          {counts.clip ? ` · ${counts.clip} clips` : ''}
        </p>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} onRetry={() => void load()} />
        </div>
      )}

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : items.length === 0 ? (
        <div className="pt-16">
          <p className="max-w-xl text-sm leading-relaxed text-ink-300">
            Nothing has failed. Every job, upload and render either succeeded or is still
            in progress.
          </p>
        </div>
      ) : (
        <div className="mt-8 space-y-3">
          {items.map((item) => (
            <article
              key={`${item.kind}-${item.id}`}
              className="border border-ink-800 bg-ink-850/30 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-3">
                    <span className="eyebrow">{KIND_LABEL[item.kind] ?? item.kind}</span>
                    <span className="text-[10px] uppercase tracking-wider text-ink-600">
                      {CODE_LABEL[item.code] ?? item.code}
                      {item.retryable ? ' · retryable' : ''}
                    </span>
                  </div>
                  <h2 className="mt-2 font-display text-lg leading-tight text-ink-100">
                    {item.title || 'Untitled'}
                  </h2>
                  <p className="mt-1 max-w-prose whitespace-pre-line text-sm leading-relaxed text-ink-400">
                    {item.detail}
                  </p>
                </div>

                <div className="flex shrink-0 items-baseline gap-3">
                  {item.retryable && (
                    <button
                      onClick={() => void retry(item)}
                      disabled={busy === item.id}
                      className="btn btn-primary text-xs disabled:opacity-50"
                    >
                      {busy === item.id ? 'Working…' : item.action_label}
                    </button>
                  )}
                  {item.link && (
                    <a href={item.link} className="text-xs text-ink-400 underline-offset-4 hover:text-ink-100 hover:underline">
                      Open
                    </a>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
