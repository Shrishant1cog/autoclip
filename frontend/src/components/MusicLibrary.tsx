import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  api,
  ApiError,
  type LicenseState,
  type MusicEnvelope,
  type MusicFolder,
  type MusicFormat,
  type MusicLibraryTrack,
  type MusicScanReport,
} from '../api'
import { ErrorNote } from './ErrorNote'

/**
 * The music library.
 *
 * Three things the screen has to get right:
 *
 * * **It is an index, not a manager.** AutoClip reads the user's music; it
 *   never copies, moves or deletes it. The buttons here say "remove from
 *   library", never "delete".
 * * **The licence is the user's, and the difference between asserting and
 *   verifying stays visible.** A tick in the licence form is the user's own
 *   word, not an independent check, and the screen says so where the tick
 *   is made.
 * * **The numbers are measured.** Tempo, energy and loudness come from
 *   listening to the file locally. Nothing here is a score out of ten.
 */

const LICENCE_STATES: { value: LicenseState; label: string; hint: string }[] = [
  {
    value: 'unknown',
    label: 'Unknown',
    hint: 'AutoClip will not put this in an export until you say where it came from.',
  },
  {
    value: 'user_confirmed',
    label: 'I have the rights',
    hint: 'Your own confirmation. Enough to export, and not an independent check.',
  },
  {
    value: 'incompatible',
    label: 'Not allowed',
    hint: 'The licence does not permit this use. Exports using it are blocked.',
  },
  {
    value: 'expired',
    label: 'Expired',
    hint: 'The licence has run out. Exports using it are blocked.',
  },
]

const MOODS = ['', 'calm', 'mellow', 'warm', 'driving', 'energetic', 'uplifting', 'dark', 'tense']

export function MusicLibrary({ onError }: { onError: (error: Error) => void }) {
  const [tracks, setTracks] = useState<MusicLibraryTrack[]>([])
  const [folders, setFolders] = useState<MusicFolder[]>([])
  const [formats, setFormats] = useState<MusicFormat[]>([])
  const [report, setReport] = useState<MusicScanReport | null>(null)
  const [query, setQuery] = useState('')
  const [mood, setMood] = useState('')
  const [licence, setLicence] = useState('')
  const [format, setFormat] = useState('')
  const [favouriteOnly, setFavouriteOnly] = useState(false)
  const [minBpm, setMinBpm] = useState('')
  const [maxBpm, setMaxBpm] = useState('')
  const [minEnergy, setMinEnergy] = useState('')
  const [maxEnergy, setMaxEnergy] = useState('')
  const [newFolder, setNewFolder] = useState('')
  const [busy, setBusy] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [localError, setLocalError] = useState<Error | null>(null)

  const reload = useCallback(async () => {
    try {
      setTracks(await api.listMusicLibrary({}))
      setFolders(await api.listMusicFolders())
    } catch (err) {
      setLocalError(err as Error)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    // The formats are the measured descriptions of the shapes a track
    // can have. A server older than M3 does not have them, and the
    // filter simply stays hidden.
    api
      .musicFormats()
      .then(setFormats)
      .catch(() => setFormats([]))
  }, [])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const min = minBpm ? Number(minBpm) : undefined
    const max = maxBpm ? Number(maxBpm) : undefined
    const lowEnergy = minEnergy ? Number(minEnergy) : undefined
    const highEnergy = maxEnergy ? Number(maxEnergy) : undefined

    return tracks.filter((track) => {
      if (needle) {
        const haystack = [
          track.name,
          track.title,
          track.artist,
          track.tags.join(' '),
          track.analysis.mood,
        ]
          .join(' ')
          .toLowerCase()
        if (!haystack.includes(needle)) return false
      }
      if (mood && track.analysis.mood !== mood) return false
      if (licence && track.license.state !== licence) return false
      if (favouriteOnly && !track.favourite) return false
      if (min !== undefined && track.analysis.bpm && track.analysis.bpm < min) return false
      if (max !== undefined && track.analysis.bpm && track.analysis.bpm > max) return false
      if (lowEnergy !== undefined && track.analysis.energy < lowEnergy) return false
      if (highEnergy !== undefined && track.analysis.energy > highEnergy) return false
      if (format && !(track.formats ?? []).includes(format)) return false
      return true
    })
  }, [
    tracks,
    query,
    mood,
    licence,
    favouriteOnly,
    minBpm,
    maxBpm,
    minEnergy,
    maxEnergy,
    format,
  ])

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

  const addFolder = () => {
    const path = newFolder.trim()
    if (!path) return
    void run('folder', async () => {
      const result = await api.addMusicFolder(path)
      setReport(result.scan)
      setNewFolder('')
    })
  }

  const unknownCount = tracks.filter((track) => track.license.state === 'unknown').length
  const blockedCount = tracks.filter(
    (track) => track.license.state === 'incompatible' || track.license.state === 'expired',
  ).length
  const chosenFormat = formats.find((entry) => entry.value === format) ?? null

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm leading-relaxed text-ink-400">
        Point AutoClip at a folder of music you own. It reads the files where they are and
        never copies, moves or deletes them. Tempo, energy and loudness are measured on this
        machine, so the same track always gets the same numbers.
      </p>

      {localError && (
        <ErrorNote error={localError} onDismiss={() => setLocalError(null)} />
      )}

      {/* -- Folders -- */}
      <div className="border border-ink-800 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-ink-100">Folders</p>
          <button
            onClick={() => void run('scan', async () => setReport(await api.scanMusicLibrary()))}
            disabled={busy !== ''}
            className="btn btn-quiet text-xs disabled:opacity-50"
          >
            {busy === 'scan' ? 'Scanning…' : 'Rescan'}
          </button>
        </div>

        {folders.length > 0 && (
          <ul className="mt-3 space-y-1">
            {folders.map((folder) => (
              <li
                key={folder.id}
                className="flex items-center justify-between gap-3 border-b border-ink-850 py-1.5 text-sm"
              >
                <span className="numeric truncate text-ink-300">{folder.path}</span>
                <button
                  onClick={() => void run(`folder-${folder.id}`, () => api.removeMusicFolder(folder.id))}
                  disabled={busy !== ''}
                  className="shrink-0 text-xs text-ink-500 transition-colors hover:text-signal-bad disabled:opacity-50"
                >
                  stop reading
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="min-w-0 flex-1">
            <span className="eyebrow">Add a folder</span>
            <input
              className="field mt-1 text-sm"
              value={newFolder}
              placeholder="C:\Music or /home/you/music"
              onChange={(e) => setNewFolder(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addFolder()}
              spellCheck={false}
            />
          </label>
          <button
            onClick={addFolder}
            disabled={busy !== '' || newFolder.trim() === ''}
            className="btn btn-ghost text-xs disabled:opacity-50"
          >
            Add folder
          </button>
        </div>

        {report && (
          <p className="mt-3 text-xs text-ink-500">
            Scanned {report.folders} folder{report.folders === 1 ? '' : 's'} · {report.found}{' '}
            file{report.found === 1 ? '' : 's'} found · {report.added} new
            {report.errors.length > 0 && ` · ${report.errors.length} could not be read`}
          </p>
        )}
      </div>

      {/* -- Filters -- */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className="eyebrow">Search</span>
          <input
            className="field mt-1 text-sm"
            value={query}
            placeholder="Name, tag, mood"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        <label className="block">
          <span className="eyebrow">Mood</span>
          <select
            className="field mt-1 cursor-pointer text-sm"
            value={mood}
            onChange={(e) => setMood(e.target.value)}
          >
            {MOODS.map((option) => (
              <option key={option || 'any'} value={option} className="bg-ink-850">
                {option === '' ? 'Any' : option}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Licence</span>
          <select
            className="field mt-1 cursor-pointer text-sm"
            value={licence}
            onChange={(e) => setLicence(e.target.value)}
          >
            <option value="" className="bg-ink-850">
              Any
            </option>
            {LICENCE_STATES.map((state) => (
              <option key={state.value} value={state.value} className="bg-ink-850">
                {state.label}
              </option>
            ))}
          </select>
        </label>

        {formats.length > 0 && (
          <label className="block">
            <span className="eyebrow">Shape</span>
            <select
              className="field mt-1 cursor-pointer text-sm"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="" className="bg-ink-850">
                Any
              </option>
              {formats.map((entry) => (
                <option key={entry.value} value={entry.value} className="bg-ink-850">
                  {entry.title}
                </option>
              ))}
            </select>
            {chosenFormat && (
              <span className="mt-1.5 block text-xs leading-snug text-ink-500">
                {chosenFormat.description} Measured as {chosenFormat.measured}.
              </span>
            )}
          </label>
        )}

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="eyebrow">BPM from</span>
            <input
              type="number"
              className="field numeric mt-1 text-sm"
              value={minBpm}
              placeholder="60"
              onChange={(e) => setMinBpm(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="eyebrow">BPM to</span>
            <input
              type="number"
              className="field numeric mt-1 text-sm"
              value={maxBpm}
              placeholder="180"
              onChange={(e) => setMaxBpm(e.target.value)}
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="eyebrow">Energy from</span>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              className="field numeric mt-1 text-sm"
              value={minEnergy}
              placeholder="0.00"
              onChange={(e) => setMinEnergy(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="eyebrow">Energy to</span>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              className="field numeric mt-1 text-sm"
              value={maxEnergy}
              placeholder="1.00"
              onChange={(e) => setMaxEnergy(e.target.value)}
            />
          </label>
        </div>
      </div>

      <label className="flex items-center gap-3 text-sm text-ink-200">
        <input
          type="checkbox"
          checked={favouriteOnly}
          onChange={(e) => setFavouriteOnly(e.target.checked)}
          className="size-4 accent-sodium-500"
        />
        Favourites only
      </label>

      {unknownCount > 0 && (
        <p className="border-l-2 border-sodium-600 pl-4 text-sm leading-relaxed text-ink-300">
          {unknownCount} track{unknownCount === 1 ? '' : 's'} still{' '}
          {unknownCount === 1 ? 'needs' : 'need'} a licence answer. An export that uses one of
          them is blocked until you say where it came from.
        </p>
      )}
      {blockedCount > 0 && (
        <p className="border-l-2 border-signal-bad pl-4 text-sm leading-relaxed text-ink-300">
          {blockedCount} track{blockedCount === 1 ? '' : 's'} cannot be used in an export.
        </p>
      )}

      {/* -- The tracks -- */}
      {tracks.length === 0 ? (
        <p className="text-sm text-ink-500">
          Nothing indexed yet. Add a folder above, or put files in your AutoClip music folder.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-ink-500">No track matches those filters.</p>
      ) : (
        <ul className="space-y-2">
          {filtered.map((track) => (
            <li key={track.id} className="border border-ink-800 p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink-100">{track.name}</p>
                  <p className="numeric mt-0.5 truncate text-xs text-ink-600">{track.path}</p>
                </div>
                <LicenceChip state={track.license.state} />
              </div>

              {track.analysis_at ? (
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
                  {track.analysis.bpm > 0 && (
                    <span className="numeric">
                      {track.analysis.bpm.toFixed(0)} BPM
                      {track.analysis.bpm_confidence < 0.2 && ' (uncertain)'}
                    </span>
                  )}
                  {track.analysis.mood && <span>{track.analysis.mood}</span>}
                  <span className="numeric">
                    energy {track.analysis.energy.toFixed(2)}
                  </span>
                  {track.analysis.loudness_lufs > -60 && (
                    <span className="numeric">{track.analysis.loudness_lufs.toFixed(1)} LUFS</span>
                  )}
                  {track.analysis.duration_s > 0 && (
                    <span className="numeric">
                      {Math.round(track.analysis.duration_s)}s
                    </span>
                  )}
                </div>
              ) : (
                <p className="mt-3 text-xs text-ink-600">Not measured yet.</p>
              )}

              {(track.formats ?? []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(track.formats ?? []).map((value) => (
                    <FormatChip key={value} value={value} formats={formats} />
                  ))}
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  onClick={() =>
                    void run(`fav-${track.id}`, () =>
                      api.setMusicFlags(track.id, { favourite: !track.favourite }),
                    )
                  }
                  disabled={busy !== ''}
                  className="btn btn-quiet text-xs disabled:opacity-50"
                >
                  {track.favourite ? 'Unfavourite' : 'Favourite'}
                </button>

                <button
                  onClick={() =>
                    void run(`analyse-${track.id}`, () => api.analyseMusicTrack(track.id, true))
                  }
                  disabled={busy !== ''}
                  className="btn btn-quiet text-xs disabled:opacity-50"
                >
                  {busy === `analyse-${track.id}` ? 'Measuring…' : 'Measure'}
                </button>

                <button
                  onClick={() => setExpanded(expanded === track.id ? null : track.id)}
                  className="btn btn-quiet text-xs"
                >
                  {expanded === track.id ? 'Close' : 'Licence'}
                </button>

                <button
                  onClick={() =>
                    void run(`remove-${track.id}`, () => api.removeMusicLibraryTrack(track.id))
                  }
                  disabled={busy !== ''}
                  className="btn btn-quiet text-xs disabled:opacity-50"
                >
                  Remove from library
                </button>
              </div>

              <audio
                controls
                preload="none"
                src={api.musicPreviewUrl(track.id)}
                className="mt-3 h-8 w-full max-w-sm"
              />

              {expanded === track.id && (
                <LicenceEditor
                  track={track}
                  onSaved={() => void reload()}
                  onError={onError}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <DuckingPreview onError={onError} />
    </div>
  )
}

function FormatChip({ value, formats }: { value: string; formats: MusicFormat[] }) {
  const entry = formats.find((format) => format.value === value)
  // The chip says what the shape is, and the tooltip says what was
  // measured — because a name on its own is a claim, and the number
  // behind it is the fact.
  return (
    <span
      title={entry ? `${entry.description} Measured as ${entry.measured}.` : value}
      className="border border-ink-700 px-1.5 py-0.5 text-[0.6875rem] text-ink-400"
    >
      {entry?.title ?? value}
    </span>
  )
}

function LicenceChip({ state }: { state: LicenseState }) {
  const label: Record<LicenseState, string> = {
    unknown: 'licence unknown',
    user_confirmed: 'your confirmation',
    incompatible: 'not allowed',
    expired: 'expired',
  }
  const tone: Record<LicenseState, string> = {
    unknown: 'text-ink-500',
    user_confirmed: 'text-signal-good',
    incompatible: 'text-signal-bad',
    expired: 'text-signal-bad',
  }
  return <span className={`text-xs ${tone[state]}`}>{label[state]}</span>
}

function LicenceEditor({
  track,
  onSaved,
  onError,
}: {
  track: MusicLibraryTrack
  onSaved: () => void
  onError: (error: Error) => void
}) {
  const [state, setState] = useState<LicenseState>(track.license.state)
  const [source, setSource] = useState(track.license.source)
  const [evidence, setEvidence] = useState(track.license.evidence)
  const [attribution, setAttribution] = useState(track.license.attribution)
  const [expires, setExpires] = useState(track.license.expires_at)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setState(track.license.state)
    setSource(track.license.source)
    setEvidence(track.license.evidence)
    setAttribution(track.license.attribution)
    setExpires(track.license.expires_at)
  }, [track])

  const chosen = LICENCE_STATES.find((entry) => entry.value === state)

  const save = async () => {
    setSaving(true)
    try {
      await api.putMusicLicence(track.id, {
        state,
        source,
        evidence,
        attribution,
        expires_at: expires,
      })
      onSaved()
    } catch (err) {
      onError(err as Error)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-4 border-t border-ink-850 pt-4">
      <label className="block">
        <span className="eyebrow">Licence</span>
        <select
          className="field mt-1 cursor-pointer text-sm"
          value={state}
          onChange={(e) => setState(e.target.value as LicenseState)}
        >
          {LICENCE_STATES.map((entry) => (
            <option key={entry.value} value={entry.value} className="bg-ink-850">
              {entry.label}
            </option>
          ))}
        </select>
        {chosen && <span className="mt-1.5 block text-xs leading-snug text-ink-500">{chosen.hint}</span>}
      </label>

      {state === 'user_confirmed' && (
        <p className="mt-3 border-l-2 border-sodium-600 pl-4 text-xs leading-relaxed text-ink-300">
          This is your own word, not an independent check. AutoClip has not verified it, and
          cannot.
        </p>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Where it came from</span>
          <input
            className="field mt-1 text-sm"
            value={source}
            placeholder="A store, a library, your own recording"
            onChange={(e) => setSource(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="eyebrow">Evidence</span>
          <input
            className="field mt-1 text-sm"
            value={evidence}
            placeholder="Receipt number, licence URL, a note"
            onChange={(e) => setEvidence(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="eyebrow">Credit to show</span>
          <input
            className="field mt-1 text-sm"
            value={attribution}
            placeholder="Artist — Track"
            onChange={(e) => setAttribution(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="eyebrow">Expires</span>
          <input
            type="date"
            className="field numeric mt-1 text-sm"
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          />
        </label>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="btn btn-ghost mt-4 text-xs disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save licence'}
      </button>
    </div>
  )
}

/**
 * The ducking envelope.
 *
 * The music drops while someone speaks, and comes back up when they stop.
 * The shape is drawn from the same speech timeline the export uses, so what
 * is drawn here is what the render does.
 */
function DuckingPreview({ onError }: { onError: (error: Error) => void }) {
  const [jobs, setJobs] = useState<{ id: string; label: string }[]>([])
  const [jobId, setJobId] = useState('')
  const [envelope, setEnvelope] = useState<MusicEnvelope | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    void api
      .listJobs(25)
      .then((list) => {
        const options = list.map((job) => ({
          id: job.id,
          label: job.source?.title || job.id,
        }))
        setJobs(options)
        if (options.length > 0) setJobId(options[0].id)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!jobId) return
    void api
      .musicEnvelope(jobId)
      .then(setEnvelope)
      .catch((err) => {
        setEnvelope(null)
        // A job that has not been transcribed yet is a normal state, not
        // a failure. It gets a sentence, not an error banner.
        if (err instanceof ApiError && err.status === 404) {
          setNote('This job has no speech timeline yet. Process the video first.')
          return
        }
        setNote((err as Error).message)
        onError(err as Error)
      })
  }, [jobId, onError])

  if (jobs.length === 0) {
    return (
      <div className="border border-ink-800 p-4">
        <p className="text-sm text-ink-100">Ducking preview</p>
        <p className="mt-2 text-xs text-ink-500">
          Process a video first. The preview is drawn from that video's speech timeline.
        </p>
      </div>
    )
  }

  const width = 640
  const height = 90
  // The server answers a job with no timeline with an empty envelope that
  // says so. That is a normal state — nothing to draw yet — and it gets
  // a sentence rather than a graph with no line on it.
  const measured = envelope !== null && envelope.state !== 'not measured yet'
  const points = measured ? (envelope?.points ?? []) : []
  const span = envelope ? Math.max(0.001, envelope.end_s - envelope.start_s) : 1

  const path = points
    .map((point, index) => {
      const x = ((point.t - (envelope?.start_s ?? 0)) / span) * width
      // The gain runs from 0 (silent) to 1 (full level). The floor is the
      // bottom of the box, so the line dips when the bed is ducked.
      const y = height - point.gain * (height - 6) - 3
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div className="border border-ink-800 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-sm text-ink-100">Ducking preview</p>
        <select
          className="field cursor-pointer text-sm"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
        >
          {jobs.map((job) => (
            <option key={job.id} value={job.id} className="bg-ink-850">
              {job.label}
            </option>
          ))}
        </select>
      </div>

      {measured && envelope ? (
        <>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="mt-4 w-full"
            role="img"
            aria-label="Music level over time"
          >
            <line x1="0" y1={height - 3} x2={width} y2={height - 3} stroke="var(--color-ink-800)" />
            {path && (
              <path
                d={path}
                fill="none"
                stroke="var(--color-sodium-500)"
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
              />
            )}
          </svg>
          <p className="mt-2 text-xs text-ink-500">
            The bed sits at {envelope.duck_db} dB under {envelope.intervals.length} stretch
            {envelope.intervals.length === 1 ? '' : 'es'} of speech
            {envelope.intervals.length > 0 && (
              <>
                , the first from {(envelope.intervals[0].start_ms / 1000).toFixed(1)}s
              </>
            )}
            . The line drops where someone is talking and comes back up when they stop.
          </p>
        </>
      ) : (
        <p className="mt-3 text-xs text-ink-500">
          {note ||
            (envelope?.state === 'not measured yet'
              ? 'This job has no speech timeline yet. Process the video first.'
              : 'No speech timeline for this video yet.')}
        </p>
      )}
    </div>
  )
}
