import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, type MusicLibraryTrack, type MusicPreferences } from '../api'

/** The sentinel the backend stores for "no music at all". */
const NO_MUSIC = '__none__'

/** The three scopes a music choice can live at. */
export type MusicScope = 'global' | 'source' | 'clip'

/**
 * The music choice, at one scope.
 *
 * Three things the screen has to keep apart, because they are three
 * different answers:
 *
 * * **No preference here** — this scope says nothing, and the next
 *   scope down decides. It is the same as "not set".
 * * **No music at all** — an explicit choice, and it is honoured.
 * * **A track** — this scope's own pick.
 *
 * The most specific scope wins: a clip's choice survives the source's
 * choice being changed, and clearing one scope never clears another.
 */
export function MusicPreference({
  scope,
  scopeId = '',
  onError,
}: {
  scope: MusicScope
  scopeId?: string
  onError: (error: Error) => void
}) {
  const [tracks, setTracks] = useState<MusicLibraryTrack[]>([])
  const [preferences, setPreferences] = useState<MusicPreferences | null>(null)
  const [saving, setSaving] = useState(false)
  const [localError, setLocalError] = useState<Error | null>(null)

  const reload = useCallback(async () => {
    try {
      const [library, stored] = await Promise.all([
        api.listMusicLibrary({}),
        api.musicPreferences(scope === 'clip' ? scopeId : '', scope === 'source' ? scopeId : ''),
      ])
      setTracks(library)
      setPreferences(stored)
    } catch (err) {
      setLocalError(err as Error)
    }
  }, [scope, scopeId])

  useEffect(() => {
    void reload()
  }, [reload])

  const mine = useMemo(() => {
    if (!preferences) return null
    return preferences[scope]
  }, [preferences, scope])

  const effective = useMemo(() => {
    if (!preferences) return null
    if (preferences.none) return { label: 'No music', source: 'your choice' }
    if (!preferences.track_id) return null
    const track = tracks.find((entry) => entry.id === preferences.track_id)
    return {
      label: track?.name ?? preferences.track_id,
      source: preferences.scope === 'global' ? 'your global choice' : `your ${preferences.scope} choice`,
    }
  }, [preferences, tracks])

  const save = async (value: string) => {
    setSaving(true)
    setLocalError(null)
    try {
      if (value === '') {
        await api.clearMusicPreference(scope, scopeId)
      } else {
        await api.putMusicPreference(scope, scopeId, value)
      }
      await reload()
    } catch (err) {
      const error = err as Error
      setLocalError(error)
      onError(error)
    } finally {
      setSaving(false)
    }
  }

  const current = mine?.none ? NO_MUSIC : (mine?.track_id ?? '')

  return (
    <div className="space-y-2">
      <label className="block">
        <span className="eyebrow">Music</span>
        <select
          className="field mt-1 cursor-pointer text-sm"
          value={current}
          disabled={saving}
          onChange={(e) => void save(e.target.value)}
        >
          <option value="" className="bg-ink-850">
            No preference here
          </option>
          <option value={NO_MUSIC} className="bg-ink-850">
            No music at all
          </option>
          {tracks.map((track) => (
            <option key={track.id} value={track.id} className="bg-ink-850">
              {track.name}
              {track.license.state === 'unknown' ? ' — licence unknown' : ''}
            </option>
          ))}
        </select>
      </label>

      {effective && (
        <p className="text-xs leading-snug text-ink-500">
          In force: {effective.label} — {effective.source}.
        </p>
      )}
      {!effective && !localError && (
        <p className="text-xs leading-snug text-ink-500">
          Nothing is set here, so AutoClip picks from the measurements.
        </p>
      )}

      {localError && (
        <p className="text-xs text-signal-bad">{localError.message}</p>
      )}
    </div>
  )
}
