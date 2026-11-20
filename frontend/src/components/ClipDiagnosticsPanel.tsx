import { useEffect, useState } from 'react'

import { api, type ClipDiagnostics } from '../api'

/**
 * The objective quality measurements for one clip.
 *
 * There is no score here, and there is not going to be one. The
 * measurements are real — clipping, resolution, frame-rate consistency,
 * black frames, export validity, duplicate clips, missing audio,
 * duration, caption timing and crop safety — but there is no honest way
 * to fold ten different measurements into a single number, and a number
 * that looked like a verdict would be a lie.
 *
 * A measurement that could not be made says so. It is never shown as a
 * pass, because "we did not look" and "it is fine" are different
 * answers.
 */
export function ClipDiagnosticsPanel({ clipId }: { clipId: string }) {
  const [report, setReport] = useState<ClipDiagnostics | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    api
      .clipDiagnostics(clipId)
      .then((loaded) => {
        if (live) setReport(loaded)
      })
      .catch((err) => {
        if (live) setError(err as Error)
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [clipId])

  if (loading) return <p className="text-xs text-ink-500">Measuring…</p>
  if (error) return <p className="text-xs text-signal-bad">{error.message}</p>
  if (!report || report.diagnostics.length === 0) {
    return <p className="text-xs text-ink-500">Nothing measured yet.</p>
  }

  return (
    <ul className="space-y-1.5">
      {report.diagnostics.map((diagnostic) => {
        const tone = !diagnostic.available
          ? 'text-ink-600'
          : diagnostic.ok
            ? 'text-signal-good'
            : 'text-signal-bad'
        return (
          <li key={diagnostic.name} className="text-xs leading-snug">
            <span className="text-ink-300">{diagnostic.title}:</span>{' '}
            <span className={tone}>{diagnostic.measured}</span>
            {!diagnostic.available && (
              <span className="text-ink-600"> — could not be measured</span>
            )}
            {diagnostic.available && !diagnostic.ok && diagnostic.detail && (
              <span className="block pl-1 text-ink-400">{diagnostic.detail}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}
