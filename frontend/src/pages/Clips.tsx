import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  api,
  formatBytes,
  formatDuration,
  type LibraryClip,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'

type Filter = 'all' | 'pending' | 'exported'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Ready to export' },
  { key: 'exported', label: 'Exported' },
]

/**
 * Every clip AutoClip has produced, across every job.
 *
 * The review screen is per-video; this is the shelf. Each row can be exported
 * on its own, and exporting is disabled while its job is still running because
 * the renderer needs that job's cached crop path.
 */
export function Clips() {
  const [clips, setClips] = useState<LibraryClip[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [showDropped, setShowDropped] = useState(false)
  const [exporting, setExporting] = useState<Set<string>>(new Set())
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    api
      .listAllClips()
      .then(setClips)
      .catch((err) => setError(err as Error))
      .finally(() => setLoading(false))
  }, [])

  const exportClip = useCallback(async (clip: LibraryClip) => {
    setExporting((current) => new Set(current).add(clip.id))
    setError(null)
    try {
      await api.exportClip(clip.id, clip.ratio, clip.caption_style)
      const updated = await api.getClip(clip.id)
      setClips((current) =>
        current.map((row) => (row.id === clip.id ? { ...row, ...updated } : row)),
      )
    } catch (err) {
      setError(err as Error)
    } finally {
      setExporting((current) => {
        const next = new Set(current)
        next.delete(clip.id)
        return next
      })
    }
  }, [])

  const retryUpload = useCallback(async (clip: LibraryClip, uploadId: string) => {
    setError(null)
    try {
      await api.retryUpload(uploadId)
      const updated = await api.getClip(clip.id)
      setClips((current) =>
        current.map((row) => (row.id === clip.id ? { ...row, ...updated } : row)),
      )    } catch (err) {
      setError(err as Error)
    }
  }, [])

  const revalidate = useCallback(async (clip: LibraryClip) => {
    setError(null)
    try {
      await api.validateClip(clip.id)
      const updated = await api.getClip(clip.id)
      setClips((current) =>
        current.map((row) => (row.id === clip.id ? { ...row, ...updated } : row)),
      )
    } catch (err) {
      setError(err as Error)
    }
  }, [])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return clips.filter((clip) => {
      if (!showDropped && clip.status === 'discarded') return false
      if (filter === 'pending' && clip.exports.length > 0) return false
      if (filter === 'exported' && clip.exports.length === 0) return false
      if (!needle) return true
      return `${clip.title} ${clip.source_title}`.toLowerCase().includes(needle)
    })
  }, [clips, filter, query, showDropped])

  const exportedCount = clips.filter((clip) => clip.exports.length > 0).length
  const sourceCount = new Set(clips.map((clip) => clip.source_title || clip.job_id)).size

  return (
    <div className="pt-10">
      <div className="flex flex-wrap items-end justify-between gap-6 border-b border-ink-800 pb-5">
        <div>
          <p className="eyebrow">Library</p>
          <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
            All clips
          </h1>
          <p className="numeric mt-3 text-xs text-ink-500">
            {clips.length} clips
            {sourceCount > 0 && ` · ${sourceCount} ${sourceCount === 1 ? 'video' : 'videos'}`}
            {` · ${exportedCount} exported`}
          </p>
        </div>

        <div className="flex flex-wrap items-baseline gap-2">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              onClick={() => setFilter(option.key)}
              className={[
                'btn',
                filter === option.key ? 'btn-primary' : 'btn-ghost',
              ].join(' ')}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-end gap-x-8 gap-y-4">
        <label className="min-w-52 flex-1">
          <span className="eyebrow">Search</span>
          <input
            className="field text-sm"
            placeholder="Clip title or source video…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            spellCheck={false}
          />
        </label>

        <label className="flex items-baseline gap-2 pb-2 text-xs text-ink-400">
          <input
            type="checkbox"
            checked={showDropped}
            onChange={(e) => setShowDropped(e.target.checked)}
            className="size-3.5 accent-sodium-500"
          />
          Show dropped clips
        </label>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : clips.length === 0 ? (
        <EmptyLibrary />
      ) : visible.length === 0 ? (
        <p className="max-w-xl pt-16 text-sm leading-relaxed text-ink-400">
          Nothing matches those filters.{' '}
          <button
            onClick={() => {
              setFilter('all')
              setQuery('')
              setShowDropped(true)
            }}
            className="text-sodium-500 underline underline-offset-4"
          >
            Reset them
          </button>
          .
        </p>
      ) : (
        <ul className="mt-4">
          {visible.map((clip, index) => (
            <ClipLibraryRow
              key={clip.id}
              clip={clip}
              index={index}
              exporting={exporting.has(clip.id)}
              onExport={() => exportClip(clip)}
              onRetryUpload={(uploadId) => retryUpload(clip, uploadId)}
              onRevalidate={() => revalidate(clip)}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function ClipLibraryRow({
  clip,
  index,
  exporting,
  onExport,
  onRetryUpload,
  onRevalidate,
}: {
  clip: LibraryClip
  index: number
  exporting: boolean
  onExport: () => void
  onRetryUpload: (uploadId: string) => void
  onRevalidate: () => void
}) {
  const latest = clip.exports[clip.exports.length - 1]
  const finished = clip.job_status === 'done'
  const sourceTitle = clip.source_title || 'Untitled source'

  return (
    <li
      className="rise grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-start gap-x-4 border-b border-ink-850 py-4 sm:grid-cols-[2.5rem_minmax(0,1fr)_minmax(0,12rem)_auto] sm:items-baseline"
      style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
    >
      <span
        title="The model's suggestion for how strong this moment is. A creative judgement, not a measured quality score."
        className={[
          'numeric self-start font-display text-2xl leading-none',
          clip.score >= 85 ? 'text-sodium-500' : 'text-ink-500',
        ].join(' ')}
      >
        {clip.score}
      </span>

      <div className="min-w-0">
        <p className="truncate text-[0.9375rem] leading-snug text-ink-100">
          {clip.title || 'Untitled clip'}
        </p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-ink-500">
          <span className="numeric">{formatDuration(clip.duration_s)}</span>
          <span className="numeric">{clip.ratio}</span>
          {clip.exports.length > 0 && (
            <span className="text-signal-good">
              exported{clip.exports.length > 1 ? ` ×${clip.exports.length}` : ''}
            </span>
          )}
          {!finished && (
            <span className="text-sodium-500">
              {clip.job_status === 'running' ? 'job still running' : clip.job_status}
            </span>
          )}
          <Link
            to={`/jobs/${clip.job_id}/clips`}
            className="text-ink-400 underline underline-offset-4 transition-colors hover:text-sodium-500 sm:hidden"
          >
            {sourceTitle}
          </Link>
        </div>
      </div>

      <Link
        to={`/jobs/${clip.job_id}/clips`}
        className="hidden truncate text-xs text-ink-400 underline-offset-4 transition-colors hover:text-sodium-500 hover:underline sm:block"
        title={sourceTitle}
      >
        {sourceTitle}
      </Link>

      <div className="flex flex-col items-end gap-1.5 justify-self-end">
        <button
          onClick={onExport}
          disabled={exporting || !finished}
          className="btn btn-ghost whitespace-nowrap"
          title={finished ? undefined : 'Wait for the job to finish before exporting'}
        >
          {exporting ? 'Rendering…' : clip.exports.length > 0 ? 'Export again' : 'Export'}
        </button>

        {latest && (
          <a
            href={latest.download_url}
            download
            className="numeric text-xs text-sodium-500 underline underline-offset-4"
          >
            download · {formatBytes(latest.size_bytes)}
          </a>
        )}

        {(() => {
          const rows =
            latest?.uploads && latest.uploads.length > 0
              ? latest.uploads
              : latest?.upload
                ? [latest.upload]
                : []
          return rows.map((upload) => (
            <UploadBadge
              key={upload.id}
              upload={upload}
              onRetry={() => onRetryUpload(upload.id)}
            />
          ))
        })()}

        {clip.validation && !clip.validation.ok && (
          <span
            className="flex items-center gap-2 text-xs text-signal-bad"
            title={clip.validation.checks
              .filter((check) => !check.ok)
              .map((check) => `${check.name}: ${check.detail}`)
              .join('\n')}
          >
            failed checks
            <button
              onClick={onRevalidate}
              className="text-ink-400 underline underline-offset-4 transition-colors hover:text-sodium-500"
            >
              re-check
            </button>
          </span>
        )}
        {clip.validation?.ok && clip.exports.length > 0 && (
          <span className="text-xs text-ink-600">validated</span>
        )}
      </div>
    </li>
  )
}

/** YouTube state for the newest export of a clip. */
function UploadBadge({
  upload,
  onRetry,
}: {
  upload: NonNullable<LibraryClip['exports'][number]['upload']>
  onRetry: () => void
}) {
  if (upload.status === 'done' && upload.watch_url) {
    return (
      <a
        href={upload.watch_url}
        target="_blank"
        rel="noreferrer"
        className="text-xs text-signal-good underline underline-offset-4"
        title={upload.title}
      >
        on YouTube
      </a>
    )
  }
  if (upload.status === 'failed') {
    return (
      <button
        onClick={onRetry}
        className="text-xs text-signal-bad underline underline-offset-4"
        title={upload.error || 'Upload failed'}
      >
        YouTube failed - retry
      </button>
    )
  }
  if (upload.status === 'skipped') {
    return (
      <span
        className="text-xs text-ink-400"
        title={upload.error || 'Duplicate of an upload already on YouTube'}
      >
        skipped (duplicate)
      </span>
    )
  }
  return (
    <span className="text-xs text-ink-500" title={upload.title}>
      {upload.status === 'uploading' ? 'uploading to YouTube...' : 'queued for YouTube'}
    </span>
  )
}

function EmptyLibrary() {
  return (
    <div className="max-w-xl pt-20">
      <h2 className="font-display text-3xl text-ink-200">No clips yet.</h2>
      <p className="mt-4 text-sm leading-relaxed text-ink-400">
        Paste a link or drop a file on the{' '}
        <Link to="/" className="text-sodium-500 underline underline-offset-4">
          New
        </Link>{' '}
        screen, and every clip it finds will show up here — ready to export.
      </p>
    </div>
  )
}
