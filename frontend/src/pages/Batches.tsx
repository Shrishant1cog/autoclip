/**
 * Batch queues.
 *
 * A batch is a list of videos to run through the pipeline one after another.
 * The runner advances it item by item, and the item's own status is the
 * truth about what happened — a failed item keeps its real error, and
 * "retry the failed ones" requeues exactly those.
 *
 * The page polls while a batch is running so the progress numbers are the
 * live ones rather than a snapshot from when the page opened.
 */
import { useCallback, useEffect, useState } from 'react'

import { api, type Batch, type BatchItem, type Source } from '../api'
import { ErrorNote } from '../components/ErrorNote'

/** How often the page re-reads a running batch. */
const POLL_MS = 3000

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  paused: 'Paused',
  done: 'Finished',
  failed: 'Failed',
  cancelled: 'Cancelled',
  pending: 'Waiting',
  processing: 'Working',
  skipped: 'Skipped',
}

export function Batches() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [items, setItems] = useState<Record<string, BatchItem[]>>({})
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      setBatches(await api.listBatches())
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadItems = useCallback(async (id: string) => {
    try {
      const batch = await api.getBatch(id)
      setItems((prev) => ({ ...prev, [id]: batch.items ?? [] }))
    } catch (err) {
      setError(err as Error)
    }
  }, [])

  useEffect(() => {
    void load()
    api.listSources().then(setSources).catch(() => undefined)
  }, [load])

  // Poll while a batch is actually running, so the numbers are live. A batch
  // that is merely queued does nothing until it is launched, and polling it
  // would be traffic for a page that will never change.
  const active = batches.some((b) => b.status === 'running')
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => {
      void load()
      if (openId) void loadItems(openId)
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [active, openId, load, loadItems])

  const open = async (batch: Batch) => {
    if (openId === batch.id) {
      setOpenId(null)
      return
    }
    setOpenId(batch.id)
    await loadItems(batch.id)
  }

  const create = async (name: string, settings: Record<string, unknown>) => {
    setBusy(true)
    setError(null)
    try {
      const batch = await api.createBatch(name, settings)
      await load()
      setOpenId(batch.id)
      await loadItems(batch.id)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const act = async (id: string, action: 'launch' | 'pause' | 'cancel' | 'retry') => {
    setBusy(true)
    setError(null)
    try {
      if (action === 'launch') await api.launchBatch(id)
      if (action === 'pause') await api.pauseBatch(id)
      if (action === 'cancel') await api.cancelBatch(id)
      if (action === 'retry') {
        const result = await api.retryBatchFailed(id)
        setStatus(`${result.requeued} failed item${result.requeued === 1 ? '' : 's'} requeued.`)
      }
      await load()
      await loadItems(id)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await api.deleteBatch(id)
      setOpenId(null)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const addSources = async (id: string, sourceIds: string[]) => {
    if (sourceIds.length === 0) return
    setBusy(true)
    try {
      const result = await api.addBatchSources(id, sourceIds)
      setStatus(`${result.added} video${result.added === 1 ? '' : 's'} added.`)
      await load()
      await loadItems(id)
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const totalItems = batches.reduce((n, b) => n + (b.progress?.total ?? 0), 0)

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Batches</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          Many videos, one queue
        </h1>
        <p className="numeric mt-3 text-xs text-ink-500">
          {batches.length} batch{batches.length === 1 ? '' : 'es'} · {totalItems} item
          {totalItems === 1 ? '' : 's'} queued
        </p>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-400">
          A batch runs its videos one after another, so the machine is never asked to
          transcribe and encode two at the same time. Each item carries its own status
          and its own error, and a restart picks the batch back up where it stopped.
        </p>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} onRetry={() => void load()} />
        </div>
      )}

      {status && <p className="mt-4 text-xs text-signal-good">{status}</p>}

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : (
        <>
          <section className="mt-10">
            <div className="flex items-baseline gap-4">
              <h2 className="eyebrow">Queues</h2>
              <span className="numeric text-xs text-ink-600">{batches.length}</span>
            </div>

            {batches.length === 0 ? (
              <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-500">
                No batches yet. Create one below and add the videos to it.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {batches.map((batch) => (
                  <BatchRow
                    key={batch.id}
                    batch={batch}
                    open={openId === batch.id}
                    items={items[batch.id]}
                    busy={busy}
                    onToggle={() => void open(batch)}
                    onAct={(action) => void act(batch.id, action)}
                    onRemove={() => void remove(batch.id)}
                    onAddSources={(ids) => void addSources(batch.id, ids)}
                    sources={sources}
                  />
                ))}
              </div>
            )}
          </section>

          <NewBatch onCreate={create} busy={busy} />
        </>
      )}
    </div>
  )
}

function BatchRow({
  batch,
  open,
  items,
  busy,
  onToggle,
  onAct,
  onRemove,
  onAddSources,
  sources,
}: {
  batch: Batch
  open: boolean
  items: BatchItem[] | undefined
  busy: boolean
  onToggle: () => void
  onAct: (action: 'launch' | 'pause' | 'cancel' | 'retry') => void
  onRemove: () => void
  onAddSources: (sourceIds: string[]) => void
  sources: Source[]
}) {
  const progress = batch.progress
  const failed = progress?.failed ?? 0
  const done = progress?.done ?? 0
  const total = progress?.total ?? 0
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <article className="border border-ink-800 bg-ink-850/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <h3 className="font-display text-lg leading-tight text-ink-100">
              {batch.name || 'Untitled batch'}
            </h3>
            <span className="text-[10px] uppercase tracking-wider text-ink-500">
              {STATUS_LABEL[batch.status] ?? batch.status}
            </span>
          </div>
          <p className="numeric mt-2 text-xs text-ink-500">
            {done} of {total} finished
            {failed > 0 ? ` · ${failed} failed` : ''}
            {progress && progress.pending > 0 ? ` · ${progress.pending} waiting` : ''}
          </p>
        </div>

        <div className="flex shrink-0 items-baseline gap-2">
          {(batch.status === 'queued' || batch.status === 'paused') && (
            <button
              onClick={() => onAct('launch')}
              disabled={busy}
              className="btn btn-primary text-xs disabled:opacity-50"
            >
              Run
            </button>
          )}
          {batch.status === 'running' && (
            <button
              onClick={() => onAct('pause')}
              disabled={busy}
              className="btn btn-ghost text-xs disabled:opacity-50"
            >
              Pause
            </button>
          )}
          {failed > 0 && (
            <button
              onClick={() => onAct('retry')}
              disabled={busy}
              className="btn btn-ghost text-xs disabled:opacity-50"
            >
              Retry failed
            </button>
          )}
          {batch.status !== 'done' && batch.status !== 'cancelled' && (
            <button
              onClick={() => onAct('cancel')}
              disabled={busy}
              className="btn btn-quiet text-xs disabled:opacity-50"
            >
              Cancel
            </button>
          )}
          <button
            onClick={onRemove}
            disabled={busy}
            className="btn btn-quiet text-xs text-signal-bad disabled:opacity-50"
          >
            Delete
            </button>
        </div>
      </div>

      {total > 0 && (
        <div className="mt-4 h-px w-full bg-ink-800">
          <div className="h-px bg-sodium-500" style={{ width: `${pct}%` }} />
        </div>
      )}

      <button onClick={onToggle} className="btn btn-quiet mt-3 text-xs" aria-expanded={open}>
        {open ? 'Hide items' : 'Items'}
      </button>

      {open && (
        <div className="mt-3 border-t border-ink-800 pt-4">
          {items === undefined ? (
            <p className="text-xs text-ink-500">Loading items…</p>
          ) : items.length === 0 ? (
            <p className="text-xs leading-relaxed text-ink-500">
              No videos in this batch yet. Add some below.
            </p>
          ) : (
            <ul className="space-y-2">
              {items.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-3 text-xs">
                  <div className="min-w-0">
                    <p className="truncate text-ink-200">
                      {item.source_title || item.source_id}
                    </p>
                    {item.error && (
                      <p className="mt-1 whitespace-pre-line text-signal-bad">{item.error}</p>
                    )}
                  </div>
                  <span className="shrink-0 text-[10px] uppercase tracking-wider text-ink-500">
                    {STATUS_LABEL[item.status] ?? item.status}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <SourcePicker sources={sources} onAdd={onAddSources} />
        </div>
      )}
    </article>
  )
}

function SourcePicker({
  sources,
  onAdd,
}: {
  sources: Source[]
  onAdd: (sourceIds: string[]) => void
}) {
  const [selected, setSelected] = useState<string[]>([])

  if (sources.length === 0) {
    return (
      <p className="mt-4 text-xs leading-relaxed text-ink-500">
        No videos have been added to the library yet.
      </p>
    )
  }

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div className="mt-4 border-t border-ink-800 pt-4">
      <span className="eyebrow">Add videos</span>
      <div className="mt-3 max-h-56 overflow-y-auto border border-ink-800">
        {sources.map((source) => (
          <label
            key={source.id}
            className="flex cursor-pointer items-center gap-3 border-b border-ink-800 px-3 py-2 text-xs last:border-b-0 hover:bg-ink-850/50"
          >
            <input
              type="checkbox"
              checked={selected.includes(source.id)}
              onChange={() => toggle(source.id)}
            />
            <span className="min-w-0 flex-1 truncate text-ink-200">
              {source.title || source.filename || source.url || source.id}
            </span>
            <span className="shrink-0 text-[10px] uppercase tracking-wider text-ink-600">
              {source.type}
            </span>
          </label>
        ))}
      </div>
      <button
        onClick={() => {
          onAdd(selected)
          setSelected([])
        }}
        disabled={selected.length === 0}
        className="btn btn-ghost mt-3 text-xs disabled:opacity-50"
      >
        Add {selected.length || ''} video{selected.length === 1 ? '' : 's'}
      </button>
    </div>
  )
}

function NewBatch({
  onCreate,
  busy,
}: {
  onCreate: (name: string, settings: Record<string, unknown>) => Promise<void>
  busy: boolean
}) {
  const [name, setName] = useState('')
  const [maxClips, setMaxClips] = useState(3)

  const submit = async () => {
    await onCreate(name.trim() || 'New batch', { max_clips: maxClips })
    setName('')
  }

  return (
    <section className="mt-10 border-t border-ink-800 pt-6">
      <h2 className="eyebrow">New batch</h2>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="block min-w-48 flex-1">
          <span className="eyebrow">Name</span>
          <input
            className="field mt-1 text-sm"
            value={name}
            placeholder="What is this run for?"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void submit()}
          />
        </label>

        <label className="block">
          <span className="eyebrow">Max clips per video</span>
          <input
            type="number"
            min={1}
            className="field numeric mt-1 w-24 text-sm"
            value={maxClips}
            onChange={(e) => setMaxClips(Number(e.target.value))}
          />
        </label>

        <button
          onClick={() => void submit()}
          disabled={busy}
          className="btn btn-primary text-xs disabled:opacity-50"
        >
          Create batch
        </button>
      </div>
    </section>
  )
}
