import { useCallback, useEffect, useState } from 'react'

import {
  api,
  type LayoutDetection,
  type LayoutOptions,
  type LayoutPosition,
  type LayoutVariant,
  type Source,
  type SourceLayout,
} from '../api'
import { ErrorNote } from './ErrorNote'

/**
 * The webcam layout.
 *
 * Three things the screen has to get right:
 *
 * * **It says what was found, and how sure it is.** The confidence is a
 *   measured number. When nothing was found the screen says so rather than
 *   showing an empty box that might be a webcam.
 * * **The user's choice wins.** Choosing a layout here overrides the
 *   automatic decision for this source, and the choice survives a
 *   re-render.
 * * **Nothing here identifies anybody.** A rectangle is a region of pixels.
 *   There is no name to show and no face to keep.
 */

const VARIANT_LABELS: Record<LayoutVariant, string> = {
  gameplay_only: 'Gameplay only',
  above: 'Webcam above',
  corner: 'Webcam in the corner',
}

const POSITION_LABELS: Record<LayoutPosition, string> = {
  'top-left': 'Top left',
  'top-right': 'Top right',
  'bottom-left': 'Bottom left',
  'bottom-right': 'Bottom right',
}

export function LayoutSettings({ onError }: { onError: (error: Error) => void }) {
  const [sources, setSources] = useState<Source[]>([])
  const [layouts, setLayouts] = useState<SourceLayout[]>([])
  const [options, setOptions] = useState<LayoutOptions | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [busy, setBusy] = useState('')
  const [detection, setDetection] = useState<LayoutDetection | null>(null)
  const [localError, setLocalError] = useState<Error | null>(null)

  const reload = useCallback(async () => {
    try {
      const [allSources, allLayouts, allOptions] = await Promise.all([
        api.listSources(),
        api.listLayouts(),
        api.layoutOptions(),
      ])
      setSources(allSources)
      setLayouts(allLayouts)
      setOptions(allOptions)
      setSelected((current) => current || allSources[0]?.id || '')
    } catch (err) {
      setLocalError(err as Error)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key)
    setLocalError(null)
    try {
      await action()
      await reload()
    } catch (err) {
      const error = err as Error
      setLocalError(error)
      onError(error)
    } finally {
      setBusy('')
    }
  }

  const current = layouts.find((layout) => layout.source_id === selected)
  const source = sources.find((item) => item.id === selected)
  const hasVideo = sources.filter((item) => item.has_video)

  const choose = (variant: LayoutVariant) => {
    if (!selected) return
    void run(`variant-${variant}`, async () => {
      await api.putLayout(selected, {
        variant,
        position: current?.position || 'top-right',
      })
    })
  }

  const move = (position: LayoutPosition) => {
    if (!selected) return
    void run(`position-${position}`, async () => {
      await api.putLayout(selected, {
        variant: current?.variant || 'corner',
        position,
      })
    })
  }

  const detect = () => {
    if (!selected) return
    void run('detect', async () => {
      setDetection(await api.detectLayout(selected))
    })
  }

  const clear = () => {
    if (!selected) return
    void run('clear', () => api.clearLayout(selected))
  }

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm leading-relaxed text-ink-400">
        AutoClip looks for a webcam that holds the same person in the same place while the
        gameplay cuts underneath. It never identifies anybody — only the region and how sure it
        is. If it gets it wrong, choose the layout yourself and it will use your choice instead.
      </p>

      {localError && (
        <ErrorNote error={localError} onDismiss={() => setLocalError(null)} />
      )}

      {hasVideo.length === 0 ? (
        <p className="text-sm text-ink-500">
          No videos yet. The layout is worked out when a video is processed.
        </p>
      ) : (
        <>
          {/* -- Which video -- */}
          <div className="border border-ink-800 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm text-ink-100">Video</p>
              <button
                onClick={detect}
                disabled={busy !== '' || !selected}
                className="btn btn-quiet text-xs disabled:opacity-50"
              >
                {busy === 'detect' ? 'Looking…' : 'Look again'}
              </button>
            </div>

            <label className="mt-3 block">
              <span className="eyebrow">Source</span>
              <select
                className="field mt-1 text-sm"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {hasVideo.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title || item.filename || item.id}
                  </option>
                ))}
              </select>
            </label>

            {source && (
              <p className="mt-2 text-xs text-ink-500">
                {source.width && source.height ? `${source.width}×${source.height}` : 'Unknown size'}
                {source.duration_s ? ` · ${Math.round(source.duration_s)}s` : ''}
              </p>
            )}
          </div>

          {/* -- What was found -- */}
          <div className="border border-ink-800 p-4">
            <p className="text-sm text-ink-100">What was found</p>

            {current?.detected ? (
              <div className="mt-3 space-y-2 text-sm text-ink-300">
                <p className="numeric">
                  Region at {Math.round(current.detected_x)}, {Math.round(current.detected_y)} ·{' '}
                  {Math.round(current.detected_width)} × {Math.round(current.detected_height)} px
                </p>
                <p className="numeric">
                  {Math.round(current.detected_confidence * 100)}% confident
                  {current.detected_face_width > 0 &&
                    ` · face about ${Math.round(current.detected_face_width)} px wide`}
                </p>
                {current.detected_reason && (
                  <p className="text-xs text-ink-500">{current.detected_reason}</p>
                )}
              </div>
            ) : (
              <p className="mt-2 text-sm text-ink-500">
                No webcam was found in this video. The clips are gameplay only, which is the
                safe result — AutoClip does not show a face it is not sure about.
              </p>
            )}

            {detection && !detection.found && detection.reason && (
              <p className="mt-2 text-xs text-ink-500">Last look: {detection.reason}</p>
            )}
          </div>

          {/* -- The choice -- */}
          <div className="border border-ink-800 p-4">
            <p className="text-sm text-ink-100">Layout</p>
            <p className="mt-1 text-xs text-ink-500">
              Your choice applies to this video and survives a re-render. Automatic lets
              AutoClip decide.
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => void run('variant-auto', async () => {
                  await api.clearLayout(selected)
                })}
                disabled={busy !== '' || !selected}
                className={`btn text-xs disabled:opacity-50 ${
                  !current?.variant ? 'btn-primary' : 'btn-ghost'
                }`}
              >
                Automatic
              </button>
              {(options?.variants ?? []).map((variant) => (
                <button
                  key={variant.value}
                  onClick={() => choose(variant.value)}
                  disabled={busy !== '' || !selected}
                  title={variant.description}
                  className={`btn text-xs disabled:opacity-50 ${
                    current?.variant === variant.value ? 'btn-primary' : 'btn-ghost'
                  }`}
                >
                  {VARIANT_LABELS[variant.value]}
                </button>
              ))}
            </div>

            {current?.variant === 'corner' && (
              <div className="mt-4">
                <span className="eyebrow">Corner</span>
                <div className="mt-1 flex flex-wrap gap-2">
                  {(options?.positions ?? []).map((position) => (
                    <button
                      key={position}
                      onClick={() => move(position)}
                      disabled={busy !== ''}
                      className={`btn text-xs disabled:opacity-50 ${
                        current.position === position ? 'btn-primary' : 'btn-ghost'
                      }`}
                    >
                      {POSITION_LABELS[position]}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {current?.variant && (
              <button
                onClick={clear}
                disabled={busy !== ''}
                className="mt-4 text-xs text-ink-500 transition-colors hover:text-signal-bad disabled:opacity-50"
              >
                Go back to automatic
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
