/**
 * Trending research.
 *
 * "What should I clip next?" needs a signal from outside the user's own back
 * catalogue. This page shows the real YouTube most-popular chart for the
 * channel's category and region, plus the analyst's read on it — and states
 * plainly when the data could not be fetched. Nothing here is invented.
 */
import { useCallback, useEffect, useState } from 'react'

import { api, type TrendResearch } from '../api'
import { ErrorNote } from '../components/ErrorNote'

/** The YouTube category IDs worth offering for a short-form clip pipeline. */
const CATEGORIES: { id: string; label: string }[] = [
  { id: '24', label: 'Entertainment' },
  { id: '20', label: 'Gaming' },
  { id: '27', label: 'People & Blogs' },
  { id: '26', label: 'Howto & Style' },
  { id: '10', label: 'Music' },
  { id: '17', label: 'Sports' },
  { id: '22', label: 'People & Vlogs' },
  { id: '28', label: 'Science & Tech' },
]

const REGIONS: { id: string; label: string }[] = [
  { id: 'US', label: 'United States' },
  { id: 'GB', label: 'United Kingdom' },
  { id: 'CA', label: 'Canada' },
  { id: 'AU', label: 'Australia' },
  { id: 'DE', label: 'Germany' },
  { id: 'IN', label: 'India' },
  { id: 'BR', label: 'Brazil' },
  { id: 'JP', label: 'Japan' },
]

function formatViews(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M views`
  if (count >= 1_000) return `${Math.round(count / 1_000)}K views`
  return `${count} views`
}

function fitStyle(fit: string): string {
  if (fit.toLowerCase() === 'high') return 'border-sodium-600/60 bg-sodium-600/15 text-sodium-300'
  if (fit.toLowerCase() === 'medium') return 'border-ink-600 bg-ink-700/60 text-ink-200'
  return 'border-ink-700 bg-ink-800/60 text-ink-400'
}

export function Trends() {
  const [data, setData] = useState<TrendResearch | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const [niche, setNiche] = useState('')
  const [category, setCategory] = useState('')
  const [region, setRegion] = useState('US')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.currentTrends(niche, category, region))
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [niche, category, region])

  useEffect(() => {
    void load()
  }, [load])

  const refresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      setData(await api.refreshTrends({ niche, category_id: category, region }))
    } catch (err) {
      setError(err as Error)
    } finally {
      setRefreshing(false)
    }
  }

  const fetchedAt = data?.fetched_at ? new Date(data.fetched_at * 1000) : null

  return (
    <div className="pt-10">
      <div className="flex flex-wrap items-end justify-between gap-6 border-b border-ink-800 pb-5">
        <div>
          <p className="eyebrow">Research</p>
          <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
            What is trending
          </h1>
          <p className="numeric mt-3 text-xs text-ink-500">
            {data
              ? `${data.videos.length} trending videos · category ${data.category_id} · ${data.region}`
              : 'Loading the most-popular chart…'}
            {fetchedAt && ` · fetched ${fetchedAt.toLocaleString()}`}
            {data?.from_cache && ' · cached'}
          </p>
        </div>

        <button
          onClick={() => void refresh()}
          disabled={refreshing}
          className="btn btn-primary"
          title="Re-fetch the trending chart and re-run the analysis"
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <label className="block">
          <span className="eyebrow">Your niche</span>
          <input
            className="field text-sm"
            placeholder="e.g. horror gaming stories"
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            spellCheck={false}
          />
          <span className="mt-1 block text-xs text-ink-500">
            Steers the analysis only — it never filters the chart.
          </span>
        </label>

        <label className="block">
          <span className="eyebrow">Category</span>
          <select
            className="field text-sm"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">Channel default</option>
            {CATEGORIES.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Region</span>
          <select
            className="field text-sm"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            {REGIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {data?.error && (
        <div className="mt-6 max-w-3xl border border-signal-bad/40 bg-signal-bad/10 px-4 py-3">
          <p className="text-sm text-ink-100">
            Could not complete the trend research: {data.error}
          </p>
          <p className="mt-1 text-xs text-ink-400">
            {data.videos.length > 0
              ? 'The raw chart below is real — only the analysis is missing.'
              : 'No trend data is available, so nothing was shown to the clip finder.'}
          </p>
        </div>
      )}

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : (
        <>
          {data && data.themes.length > 0 && (
            <section className="mt-10">
              <h2 className="eyebrow">What the analyst read</h2>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                {data.themes.map((theme) => (
                  <article
                    key={theme.theme}
                    className="border border-ink-800 bg-ink-850/40 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-display text-lg leading-tight text-ink-100">
                        {theme.theme}
                      </h3>
                      <span
                        className={[
                          'shrink-0 border px-2 py-0.5 text-[10px] uppercase tracking-wider',
                          fitStyle(theme.fit),
                        ].join(' ')}
                      >
                        {theme.fit || '—'} fit
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-ink-300">{theme.why}</p>
                  </article>
                ))}
              </div>

              {data.formats.length > 0 && (
                <div className="mt-6">
                  <h3 className="eyebrow">Formats working now</h3>
                  <ul className="mt-2 space-y-1 text-sm text-ink-300">
                    {data.formats.map((format) => (
                      <li key={format} className="flex gap-2">
                        <span className="text-sodium-500">·</span>
                        {format}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {data.avoid.length > 0 && (
                <div className="mt-6">
                  <h3 className="eyebrow">Saturated</h3>
                  <ul className="mt-2 space-y-1 text-sm text-ink-400">
                    {data.avoid.map((item) => (
                      <li key={item} className="flex gap-2">
                        <span className="text-signal-bad">·</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {data.provider && (
                <p className="mt-6 text-xs text-ink-500">
                  Analysed by {data.provider}. This context is injected into every
                  highlight-detection call.
                </p>
              )}
            </section>
          )}

          <section className="mt-12">
            <h2 className="eyebrow">The chart</h2>
            {data && data.videos.length > 0 ? (
              <table className="mt-4 w-full text-sm">
                <thead>
                  <tr className="border-b border-ink-800 text-left text-xs text-ink-500">
                    <th className="py-2 font-normal">Video</th>
                    <th className="py-2 font-normal">Channel</th>
                    <th className="py-2 text-right font-normal">Views</th>
                  </tr>
                </thead>
                <tbody>
                  {data.videos.map((video) => (
                    <tr key={video.video_id} className="border-b border-ink-850">
                      <td className="py-2 pr-6">
                        <a
                          href={video.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-ink-100 underline-offset-4 hover:underline"
                        >
                          {video.title}
                        </a>
                      </td>
                      <td className="py-2 pr-6 text-ink-400">{video.channel}</td>
                      <td className="numeric py-2 text-right text-ink-300">
                        {formatViews(video.view_count)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-400">
                No trend data yet. Connect a YouTube channel so AutoClip can read the
                most-popular chart, then press Refresh.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
