import { useEffect, useState } from 'react'

import {
  api,
  type MusicTrack,
  type PrivacyOperation,
  type ProviderStatus,
  type Settings as SettingsData,
  type SystemStatus,
  type TransferRecord,
  type YouTubeStatus,
} from '../api'
import { ErrorNote } from '../components/ErrorNote'
import { MusicLibrary } from '../components/MusicLibrary'
import { MusicPreference } from '../components/MusicPreference'
import { LayoutSettings } from '../components/LayoutSettings'

const SECRET_LABELS: Record<string, string> = {
  anthropic: 'Anthropic API key',
  openai: 'OpenAI-compatible API key',
  gemini: 'Google Gemini API key',
  elevenlabs: 'ElevenLabs API key',
  huggingface_token: 'HuggingFace token',
}

/** Mirrors backend TranscriptionSettings defaults; used when an older server
 * response predates the field. */
const DEFAULT_TRANSCRIPTION = {
  engine: 'auto' as 'auto' | 'elevenlabs' | 'local',
  elevenlabs_model: 'scribe_v2',
  diarize: true,
  voiceover: 'off' as 'off' | 'muxed',
  voice_id: '',
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [youtube, setYoutube] = useState<YouTubeStatus | null>(null)
  const [tracks, setTracks] = useState<MusicTrack[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [saved, setSaved] = useState(false)

  const reload = () => {
    void api.getSettings().then(setSettings).catch((e) => setError(e as Error))
    void api.providerStatus().then(setProviders).catch(() => undefined)
    void api.system().then(setSystem).catch(() => undefined)
    void api.youtubeStatus().then(setYoutube).catch(() => undefined)
    void api.listMusicTracks().then(setTracks).catch(() => undefined)
  }

  useEffect(reload, [])

  const patch = async (update: Partial<SettingsData>) => {
    setError(null)
    try {
      setSettings(await api.putSettings(update))
      setSaved(true)
      setTimeout(() => setSaved(false), 1600)
    } catch (err) {
      setError(err as Error)
    }
  }

  if (!settings) return <p className="pt-24 text-sm text-ink-500">Loading…</p>

  return (
    <div className="max-w-4xl pt-14">
      <div className="rise flex items-baseline justify-between border-b border-ink-800 pb-5">
        <h1 className="font-display text-[clamp(2rem,4vw,3rem)] leading-none text-ink-100">
          Settings
        </h1>
        <span
          className="text-xs text-signal-good transition-opacity duration-300"
          style={{ opacity: saved ? 1 : 0 }}
        >
          saved
        </span>
      </div>

      {error && (
        <div className="mt-6">
          <ErrorNote error={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {settings.insecure_secret_storage && (
        <p className="mt-6 border-l-2 border-sodium-600 pl-4 text-sm leading-relaxed text-ink-300">
          No OS keyring is available on this machine, so API keys are stored in plain text
          in <code className="text-ink-200">config.json</code>. On headless Linux, installing
          a Secret Service provider or <code className="text-ink-200">keyrings.alt</code>{' '}
          fixes this.
        </p>
      )}

      <Section title="AI provider" note="Which model picks the clips.">
        <div className="space-y-1">
          {providers.map((provider) => (
            <button
              key={provider.name}
              onClick={() => patch({ active_provider: provider.name })}
              className={[
                'block w-full border-l-2 py-3 pl-3 text-left transition-colors duration-200',
                provider.name === settings.active_provider
                  ? 'border-sodium-500 bg-ink-850/60'
                  : 'border-transparent hover:border-ink-700 hover:bg-ink-850/30',
              ].join(' ')}
            >
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-ink-100">{provider.name}</span>
                <span
                  className={`text-xs ${provider.available ? 'text-signal-good' : 'text-ink-500'}`}
                >
                  {provider.available ? 'reachable' : provider.detail || 'unavailable'}
                </span>
              </div>
              {provider.models.length > 0 && (
                <span className="numeric mt-1 block truncate text-xs text-ink-600">
                  {provider.models.slice(0, 6).join(' · ')}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          <Field
            label="Model"
            value={settings.providers[settings.active_provider]?.model ?? ''}
            placeholder="model name"
            onCommit={(value) =>
              patch({
                providers: {
                  [settings.active_provider]: {
                    ...settings.providers[settings.active_provider],
                    model: value,
                  },
                },
              })
            }
          />
          <Field
            label="Base URL"
            hint="Point at OpenRouter, Groq, DeepSeek, or a local server."
            value={settings.providers[settings.active_provider]?.base_url ?? ''}
            placeholder="https://…"
            onCommit={(value) =>
              patch({
                providers: {
                  [settings.active_provider]: {
                    ...settings.providers[settings.active_provider],
                    base_url: value || null,
                  },
                },
              })
            }
          />
        </div>
      </Section>

      <Section title="Keys" note="Stored in your OS keyring. Never sent anywhere but the provider.">
        <div className="space-y-4">
          {Object.entries(SECRET_LABELS).map(([key, label]) => (
            <SecretField
              key={key}
              secretKey={key}
              label={label}
              present={settings.keys_present[key] ?? false}
              onChanged={reload}
              onError={setError}
            />
          ))}
        </div>
      </Section>

      <Section title="Transcription">
        <div className="grid gap-5 sm:grid-cols-2">
          <Select
            label="Engine"
            hint="Auto prefers ElevenLabs and falls back to local Whisper if it fails."
            value={settings.transcription?.engine ?? 'auto'}
            onChange={(value) =>
              patch({
                transcription: {
                  ...DEFAULT_TRANSCRIPTION,
                  ...settings.transcription,
                  engine: value as 'auto' | 'elevenlabs' | 'local',
                },
              })
            }
            options={['auto', 'elevenlabs', 'local']}
            labels={{
              auto: 'Auto (external first)',
              elevenlabs: 'ElevenLabs Scribe only',
              local: 'Local Whisper only',
            }}
          />
          {settings.transcription?.engine !== 'local' && (
            <>
              <Select
                label="Scribe model"
                value={settings.transcription?.elevenlabs_model ?? 'scribe_v2'}
                onChange={(value) =>
                  patch({
                    transcription: {
                      ...DEFAULT_TRANSCRIPTION,
                      ...settings.transcription,
                      elevenlabs_model: value,
                    },
                  })
                }
                options={['scribe_v2', 'scribe_v3']}
              />
              <label className="flex items-start gap-3 text-sm text-ink-200 sm:col-span-2">
                <input
                  type="checkbox"
                  checked={settings.transcription?.diarize ?? true}
                  onChange={(e) =>
                    patch({
                      transcription: {
                        ...DEFAULT_TRANSCRIPTION,
                        ...settings.transcription,
                        diarize: e.target.checked,
                      },
                    })
                  }
                  className="mt-0.5 size-4 accent-sodium-500"
                />
                <span>
                  Identify speakers with Scribe
                  <span className="mt-1 block text-xs text-ink-500">
                    Included in the transcription call — no HuggingFace token needed.
                  </span>
                </span>
              </label>
            </>
          )}
        </div>

        <div className="mt-8 grid gap-5 sm:grid-cols-2">
          <Select
            label="Whisper model"
            value={settings.whisper.model}
            onChange={(value) => patch({ whisper: { ...settings.whisper, model: value } })}
            options={['tiny', 'base', 'small', 'medium', 'large-v3']}
          />
          <Field
            label="Language"
            hint="Leave empty to detect automatically."
            value={settings.whisper.language}
            placeholder="auto"
            onCommit={(value) => patch({ whisper: { ...settings.whisper, language: value } })}
          />
        </div>

        <label className="mt-5 flex items-start gap-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={settings.whisper.diarization}
            disabled={!system?.diarization_available}
            onChange={(e) =>
              patch({ whisper: { ...settings.whisper, diarization: e.target.checked } })
            }
            className="mt-0.5 size-4 accent-sodium-500"
          />
          <span>
            Identify speakers
            {!system?.diarization_available && (
              <span className="mt-1 block text-xs text-ink-500">
                Needs the diarization extra:{' '}
                <code className="text-ink-300">uv pip install &apos;autoclip[diarization]&apos;</code>
              </span>
            )}
          </span>
        </label>
      </Section>

      <Section title="Clips">
        <div className="grid gap-5 sm:grid-cols-3">
          <NumberField
            label="Min length (s)"
            value={settings.clips.min_duration_s}
            onCommit={(value) => patch({ clips: { ...settings.clips, min_duration_s: value } })}
          />
          <NumberField
            label="Max length (s)"
            value={settings.clips.max_duration_s}
            onCommit={(value) => patch({ clips: { ...settings.clips, max_duration_s: value } })}
          />
          <NumberField
            label="Max clips"
            value={settings.clips.max_clips}
            onCommit={(value) => patch({ clips: { ...settings.clips, max_clips: value } })}
          />
        </div>

        <div className="mt-8 border-t border-ink-800 pt-6">
          <h3 className="text-sm text-ink-100">Story and gameplay</h3>
          <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-500">
            A bias in the ranking, not a quota. Nothing requires half the clips to be story and
            half to be action: a video with no action in it produces no action clips. At the
            middle setting nothing changes at all.
          </p>

          <div className="mt-4 grid gap-5 sm:grid-cols-2">
            <Select
              label="Highlight style"
              hint="A deliberate choice about which kind of moment to look for."
              value={settings.clips.highlight_style ?? 'auto'}
              onChange={(value) =>
                patch({
                  clips: {
                    ...settings.clips,
                    highlight_style: value as 'auto' | 'story' | 'action',
                  },
                })
              }
              options={['auto', 'story', 'action']}
              labels={{
                auto: 'Automatic (use the balance below)',
                story: 'Story — the moment that explains something',
                action: 'Action — the moment something happens',
              }}
            />
            <NumberField
              label="Story balance (0 action – 1 story)"
              value={settings.clips.story_density ?? 0.5}
              onCommit={(value) =>
                patch({
                  clips: {
                    ...settings.clips,
                    story_density: Math.max(0, Math.min(1, value)),
                  },
                })
              }
            />
          </div>
        </div>
      </Section>

      <Section
        title="Voiceover"
        note="ElevenLabs narration, off by default. Billed per character by ElevenLabs."
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <Select
            label="Narration"
            value={settings.transcription?.voiceover ?? 'off'}
            onChange={(value) =>
              patch({
                transcription: {
                  ...DEFAULT_TRANSCRIPTION,
                  ...settings.transcription,
                  voiceover: value as 'off' | 'muxed',
                },
              })
            }
            options={['off', 'muxed']}
            labels={{ off: 'Off (default)', muxed: 'Narrate over the original audio' }}
          />
          <Field
            label="Voice ID"
            hint="Empty = Rachel (ElevenLabs default). Find IDs under voices in your ElevenLabs dashboard."
            value={settings.transcription?.voice_id ?? ''}
            placeholder="JBFqnCBsd6RMkjVDRZzb"
            onCommit={(value) =>
              patch({
                transcription: {
                  ...DEFAULT_TRANSCRIPTION,
                  ...settings.transcription,
                  voice_id: value,
                },
              })
            }
          />
        </div>
        {settings.transcription?.voiceover === 'muxed' && !settings.keys_present.elevenlabs && (
          <p className="mt-4 border-l-2 border-sodium-600 pl-4 text-sm text-ink-300">
            Voiceover needs an ElevenLabs API key — add it under Keys above.
          </p>
        )}
      </Section>

      <ExternalProcessingSection onError={setError} />

      <Section title="Ingest">
        <div className="grid gap-5 sm:grid-cols-2">
          <Select
            label="YouTube cookies from"
            hint="YouTube blocks most anonymous downloads. Sign in in that browser and close it before downloading."
            value={settings.ingest.cookies_from_browser}
            onChange={(value) =>
              patch({ ingest: { ...settings.ingest, cookies_from_browser: value } })
            }
            options={['', 'chrome', 'firefox', 'edge', 'brave', 'chromium', 'safari']}
            labels={{ '': 'None' }}
          />
        </div>
      </Section>

      <Section title="Export">
        <div className="grid gap-5 sm:grid-cols-2">
          <Select
            label="Default ratio"
            value={settings.export.ratio}
            onChange={(value) => patch({ export: { ...settings.export, ratio: value } })}
            options={['9:16', '1:1', '16:9']}
          />
          <NumberField
            label="Loudness target (LUFS)"
            value={settings.export.loudness_lufs}
            onCommit={(value) => patch({ export: { ...settings.export, loudness_lufs: value } })}
          />
        </div>

        <label className="mt-5 flex items-start gap-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={settings.export.prefer_hardware_encoder}
            onChange={(e) =>
              patch({
                export: { ...settings.export, prefer_hardware_encoder: e.target.checked },
              })
            }
            className="mt-0.5 size-4 accent-sodium-500"
          />
          <span>
            Use GPU encoding when available
            {system && !system.nvenc_works && (
              <span className="mt-1 block text-xs text-ink-500">
                Not usable on this machine — exports will use the CPU encoder. Same quality,
                slower.
              </span>
            )}
          </span>
        </label>

        <label className="mt-4 flex items-center gap-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={settings.export.write_srt}
            onChange={(e) => patch({ export: { ...settings.export, write_srt: e.target.checked } })}
            className="size-4 accent-sodium-500"
          />
          Also write an .srt sidecar
        </label>

        <div className="mt-8 border-t border-ink-800 pt-6">
          <h3 className="text-sm text-ink-100">Webcam</h3>
          <p className="mt-1 text-xs leading-snug text-ink-500">
            Automatic decides from what it detects. A webcam that is too small to show without
            turning into a blur gets a corner instead of a strip.
          </p>

          <div className="mt-4 grid gap-5 sm:grid-cols-2">
            <Select
              label="Layout"
              value={settings.export.layout ?? 'auto'}
              onChange={(value) =>
                patch({
                  export: {
                    ...settings.export,
                    layout: value as 'auto' | 'above' | 'corner' | 'gameplay_only',
                  },
                })
              }
              options={['auto', 'above', 'corner', 'gameplay_only']}
              labels={{ auto: 'Automatic' }}
            />
            <Select
              label="Corner"
              value={settings.export.webcam_position ?? 'top-right'}
              onChange={(value) =>
                patch({
                  export: {
                    ...settings.export,
                    webcam_position: value as 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right',
                  },
                })
              }
              options={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
            />
          </div>

          {(settings.export.layout ?? 'auto') === 'above' && (
            <div className="mt-4 grid gap-5 sm:grid-cols-2">
              <NumberField
                label="Webcam height (fraction of the frame)"
                value={settings.export.webcam_height_frac ?? 0.4}
                onCommit={(value) =>
                  patch({ export: { ...settings.export, webcam_height_frac: value } })
                }
              />
            </div>
          )}
        </div>

        <div className="mt-8 border-t border-ink-800 pt-6">
          <h3 className="text-sm text-ink-100">Background music</h3>
          <p className="mt-1 text-xs leading-snug text-ink-500">
            Tracks live in <code className="text-ink-400">~/.autoclip/music</code>. Music is looped
            under the clip; ducking drops it while someone is speaking.
          </p>

          <div className="mt-4 grid gap-5 sm:grid-cols-2">
            <Select
              label="Track"
              value={settings.export.music_track}
              onChange={(value) => patch({ export: { ...settings.export, music_track: value } })}
              options={['', ...tracks.map((t) => t.name)]}
              labels={{ '': 'None' }}
            />
            <NumberField
              label="Music volume (0–1)"
              value={settings.export.music_volume}
              onCommit={(value) => patch({ export: { ...settings.export, music_volume: value } })}
            />
          </div>

          <label className="mt-4 flex items-center gap-3 text-sm text-ink-200">
            <input
              type="checkbox"
              checked={settings.export.music_ducking}
              onChange={(e) =>
                patch({ export: { ...settings.export, music_ducking: e.target.checked } })
              }
              className="size-4 accent-sodium-500"
            />
            Duck the music while speech is present
          </label>

          {settings.export.music_ducking && (
            <div className="mt-4 grid gap-5 sm:grid-cols-2">
              <NumberField
                label="Ducking depth (dB, negative)"
                value={settings.export.ducking_amount_db}
                onCommit={(value) =>
                  patch({ export: { ...settings.export, ducking_amount_db: value } })
                }
              />
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <label className="cursor-pointer border border-ink-700 px-3 py-2 text-xs text-ink-200 transition-colors hover:border-ink-600">
              Add track…
              <input
                type="file"
                accept="audio/*,.mp3,.m4a,.aac,.wav,.ogg,.flac,.opus"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (!file) return
                  try {
                    await api.uploadMusicTrack(file)
                    setTracks(await api.listMusicTracks())
                  } catch (err) {
                    setError(err as Error)
                  }
                }}
              />
            </label>
            <span className="text-xs text-ink-500">
              {tracks.length === 0 ? 'Library is empty.' : `${tracks.length} track${tracks.length === 1 ? '' : 's'} in library`}
            </span>
          </div>

          {tracks.length > 0 && (
            <ul className="mt-4 space-y-1">
              {tracks.map((track) => (
                <li
                  key={track.name}
                  className="flex items-center justify-between gap-3 border-b border-ink-850 py-2 text-sm"
                >
                  <span className="truncate text-ink-200">{track.name}</span>
                  <button
                    onClick={async () => {
                      try {
                        await api.deleteMusicTrack(track.name)
                        setTracks(await api.listMusicTracks())
                        if (settings.export.music_track === track.name) {
                          await patch({ export: { ...settings.export, music_track: '' } })
                        }
                      } catch (err) {
                        setError(err as Error)
                      }
                    }}
                    className="text-xs text-ink-500 transition-colors hover:text-signal-bad"
                  >
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      <Section
        title="Music library"
        note="Your music, indexed where it already is — never copied, moved or deleted."
      >
        <div className="mb-8 max-w-prose border-l-2 border-ink-700 pl-4">
          <MusicPreference scope="global" onError={setError} />
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            The default for every clip. A clip can override it, and a single video can override
            the default for all of its clips, without disturbing either.
          </p>
        </div>
        <MusicLibrary onError={setError} />
      </Section>

      <Section
        title="Webcam layout"
        note="Where the webcam sits in the vertical clip. Your choice wins over the automatic one."
      >
        <LayoutSettings onError={setError} />
      </Section>

      <Section
        title="YouTube"
        note="Uploads use your own Google Cloud OAuth client. Tokens stay in your OS keyring."
      >
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border border-ink-800 p-4">
            <div>
              <p className="text-sm text-ink-100">
                {youtube?.connected
                  ? `Connected to ${youtube.channel_title || 'your channel'}`
                  : 'No channel connected'}
              </p>
              <p className="mt-1 text-xs text-ink-500">
                {youtube?.connected
                  ? `Auto-upload is ${youtube.auto_upload ? 'on' : 'off'} — visible by default as ${youtube.privacy}.`
                  : 'Press Connect YouTube channel in the header after adding the client below.'}
              </p>
            </div>
            {youtube?.connected ? (
              <div className="flex items-center gap-2">
                {youtube.channel_url && (
                  <a
                    href={youtube.channel_url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-ghost"
                  >
                    Open channel
                  </a>
                )}
                <button
                  className="btn btn-quiet"
                  onClick={async () => {
                    setError(null)
                    try {
                      const next = await api.youtubeDisconnect()
                      setYoutube(next)
                      reload()
                    } catch (err) {
                      setError(err as Error)
                    }
                  }}
                >
                  Disconnect
                </button>
              </div>
            ) : (
              <button
                className="btn btn-primary"
                disabled={!youtube?.configured}
                onClick={async () => {
                  setError(null)
                  try {
                    const { auth_url } = await api.youtubeConnect()
                    window.location.href = auth_url
                  } catch (err) {
                    setError(err as Error)
                  }
                }}
              >
                Connect YouTube channel
              </button>
            )}
          </div>

          <Field
            label="OAuth client ID"
            hint="Google Cloud Console — APIs & Services — Credentials — OAuth client."
            value={settings.youtube.client_id}
            placeholder="...apps.googleusercontent.com"
            onCommit={(value) => patch({ youtube: { ...settings.youtube, client_id: value } })}
          />

          <SecretField
            secretKey="youtube_client_secret"
            label="OAuth client secret"
            present={settings.youtube_secret_present}
            onChanged={reload}
            onError={setError}
          />

          <div className="grid gap-5 sm:grid-cols-2">
            <Field
              label="Redirect URI"
              hint="Must match the URI registered on the OAuth client exactly."
              value={settings.youtube.redirect_uri}
              onCommit={(value) =>
                patch({ youtube: { ...settings.youtube, redirect_uri: value } })
              }
            />
            <Select
              label="Default visibility"
              hint="New Google Cloud projects can only upload Private until YouTube audits the project."
              value={settings.youtube.privacy}
              onChange={async (value) => {
                setError(null)
                try {
                  await api.setYouTubePrivacy(value as 'private' | 'unlisted' | 'public')
                  reload()
                } catch (err) {
                  setError(err as Error)
                }
              }}
              options={['public', 'unlisted', 'private']}
              labels={{ public: 'Public', unlisted: 'Unlisted', private: 'Private' }}
            />
          </div>

          <label className="flex items-start gap-3 text-sm text-ink-200">
            <input
              type="checkbox"
              checked={settings.youtube.auto_upload}
              disabled={!youtube?.connected}
              onChange={async (e) => {
                setError(null)
                try {
                  const next = await api.setYouTubeAuto(e.target.checked)
                  setYoutube(next)
                  reload()
                } catch (err) {
                  setError(err as Error)
                }
              }}
              className="mt-0.5 size-4 accent-sodium-500"
            />
            <span>
              Upload every finished clip automatically
              <span className="mt-1 block text-xs leading-snug text-ink-500">
                Each successful export is queued, titled, described, and tagged by the active
                AI model from its own subtitles. Uploads cost 1,600 of the 10,000 daily YouTube
                API quota units, so roughly six clips a day.
              </span>
            </span>
          </label>

          <details className="border border-ink-800 p-4 text-sm text-ink-300">
            <summary className="cursor-pointer text-ink-200">Google Cloud setup</summary>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-xs leading-relaxed text-ink-400">
              <li>
                Create a project at console.cloud.google.com and enable{' '}
                <span className="text-ink-200">YouTube Data API v3</span>.
              </li>
              <li>
                Configure the OAuth consent screen. Add the scopes{' '}
                <code className="text-ink-200">youtube.upload</code> and{' '}
                <code className="text-ink-200">youtube.readonly</code>, and add your Google
                account as a test user.
              </li>
              <li>
                Create an OAuth client. A <span className="text-ink-200">Web application</span>{' '}
                client needs this exact redirect URI:{' '}
                <code className="text-ink-200">{settings.youtube.redirect_uri}</code>. A{' '}
                <span className="text-ink-200">Desktop app</span> client needs none.
              </li>
              <li>Paste the client ID and secret above, then connect from the header.</li>
            </ol>
          </details>
        </div>
      </Section>

      {system && (
        <Section title="This machine">
          <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
            <Row label="Platform" value={system.platform} />
            <Row label="Python" value={system.python_version} />
            <Row label="ffmpeg" value={system.ffmpeg_version ?? 'not found'} />
            <Row label="Acceleration" value={system.accel.toUpperCase()} />
            <Row label="Device" value={system.gpu_name ?? '—'} />
            <Row label="Whisper compute" value={system.compute_type} />
            <Row label="GPU encode" value={system.nvenc_works ? 'available' : 'unavailable'} />
            <Row label="Captions" value={system.has_libass ? 'libass present' : 'libass missing'} />
          </dl>
        </Section>
      )}

      <ResourcesSection settings={settings} onPatch={patch} onError={setError} />

      <LearningSection onError={setError} />
    </div>
  )
}

/** Mirrors the backend defaults; used when the server predates Phase 16. */
const DEFAULT_RESOURCES = {
  ffmpeg_threads: 0,
  max_parallel_ffmpeg: 2,
  work_retention_days: 7,
  export_retention_days: 0,
  raw_retention_days: 0,
  cleanup_on_start: true,
  max_output_tokens: 4096,
  max_llm_calls_per_job: 0,
}

/** Phase 16: what AutoClip is using, what it may use, and what can go. */
function ResourcesSection({
  settings,
  onPatch,
  onError,
}: {
  settings: SettingsData
  onPatch: (update: Partial<SettingsData>) => void
  onError: (err: Error) => void
}) {
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof api.resources>> | null>(null)
  const [cleaning, setCleaning] = useState(false)
  const [report, setReport] = useState<Awaited<ReturnType<typeof api.cleanupResources>> | null>(
    null,
  )

  const limits = settings.resources ?? DEFAULT_RESOURCES

  const load = () => {
    void api
      .resources()
      .then(setOverview)
      .catch(() => undefined)
  }

  useEffect(load, [])

  const patchResources = (update: Partial<typeof limits>) => {
    onPatch({ resources: { ...limits, ...update } })
    load()
  }

  const clean = async () => {
    setCleaning(true)
    try {
      setReport(await api.cleanupResources())
      load()
    } catch (err) {
      onError(err as Error)
    } finally {
      setCleaning(false)
    }
  }

  return (
    <Section
      title="Resources"
      note="What AutoClip is using, what it is allowed to use, and what can be reclaimed."
    >
      {overview && (
        <>
          <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
            {overview.disk.directories.map((directory) => (
              <Row
                key={directory.name}
                label={`${directory.name} (${directory.file_count} files)`}
                value={directory.size_human}
              />
            ))}
            <Row label="database" value={overview.disk.database_human} />
            <Row label="total on disk" value={overview.disk.total_human} />
          </dl>

          <div className="mt-6 border-t border-ink-850 pt-5">
            <h3 className="text-sm text-ink-100">Measured use</h3>
            <p className="mt-1 text-xs text-ink-500">
              Token counts are what the provider reported; ffmpeg time is the wall clock around
              the real process. Nothing here is estimated.
            </p>
            <dl className="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
              <Row label="Model calls" value={overview.usage.totals.llm_calls.toLocaleString()} />
              <Row
                label="Tokens in / out"
                value={`${overview.usage.totals.llm_input_tokens.toLocaleString()} / ${overview.usage.totals.llm_output_tokens.toLocaleString()}`}
              />
              <Row label="ffmpeg runs" value={overview.usage.totals.ffmpeg_runs.toLocaleString()} />
              <Row
                label="ffmpeg time"
                value={`${Math.round(overview.usage.totals.ffmpeg_seconds / 60)} min`}
              />
              <Row label="Exported" value={overview.usage.totals.export_human} />
              {overview.usage.totals.windows_skipped > 0 && (
                <Row
                  label="Windows not analysed"
                  value={String(overview.usage.totals.windows_skipped)}
                />
              )}
            </dl>
          </div>
        </>
      )}

      <div className="mt-8 border-t border-ink-800 pt-6">
        <h3 className="text-sm text-ink-100">Limits</h3>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <NumberField
            label="Parallel ffmpeg processes"
            value={limits.max_parallel_ffmpeg}
            onCommit={(value) => patchResources({ max_parallel_ffmpeg: value })}
          />
          <NumberField
            label="ffmpeg threads (0 = automatic)"
            value={limits.ffmpeg_threads}
            onCommit={(value) => patchResources({ ffmpeg_threads: value })}
          />
          <NumberField
            label="Max output tokens per call"
            value={limits.max_output_tokens}
            onCommit={(value) => patchResources({ max_output_tokens: value })}
          />
          <NumberField
            label="Detection calls per job (0 = no limit)"
            value={limits.max_llm_calls_per_job}
            onCommit={(value) => patchResources({ max_llm_calls_per_job: value })}
          />
        </div>

        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <NumberField
            label="Keep scratch files for (days, 0 = forever)"
            value={limits.work_retention_days}
            onCommit={(value) => patchResources({ work_retention_days: value })}
          />
          <NumberField
            label="Keep published clips for (days, 0 = forever)"
            value={limits.export_retention_days}
            onCommit={(value) => patchResources({ export_retention_days: value })}
          />
          <NumberField
            label="Keep downloaded videos for (days, 0 = forever)"
            value={limits.raw_retention_days}
            onCommit={(value) => patchResources({ raw_retention_days: value })}
          />
        </div>

        <label className="mt-4 flex items-center gap-3 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={limits.cleanup_on_start}
            onChange={(e) => patchResources({ cleanup_on_start: e.target.checked })}
            className="size-4 accent-sodium-500"
          />
          Clean up when the app starts
        </label>

        <p className="mt-4 text-xs leading-relaxed text-ink-500">
          Cleanup never removes an unpublished clip, an uploaded source file, or the scratch
          directory of a failed job — that is what lets a failed job resume instead of starting
          over.
        </p>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            onClick={clean}
            disabled={cleaning}
            className="btn btn-primary disabled:opacity-50"
          >
            {cleaning ? 'Cleaning…' : 'Clean up now'}
          </button>
          {report && (
            <span className="text-xs text-ink-400">
              {report.changed
                ? `Removed ${report.removed_files} file(s) and ${report.removed_directories} directory(ies), freeing ${report.freed_human}.`
                : 'Nothing to reclaim.'}
            </span>
          )}
        </div>
      </div>
    </Section>
  )
}

/** Phase 11: outcome stats plus the improve.txt steering file. */
function LearningSection({ onError }: { onError: (err: Error) => void }) {
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.learningSummary>> | null>(
    null,
  )
  const [bands, setBands] = useState<Awaited<ReturnType<typeof api.learningScoreBands>>>([])
  const [channelRows, setChannelRows] = useState<Awaited<ReturnType<typeof api.learningChannels>>>(
    [],
  )
  const [feedback, setFeedback] = useState('')
  const [feedbackPath, setFeedbackPath] = useState('')
  const [maxChars, setMaxChars] = useState(4000)
  const [draft, setDraft] = useState('')
  const [savedAt, setSavedAt] = useState<string | null>(null)

  useEffect(() => {
    void api
      .learningSummary()
      .then(setSummary)
      .catch(() => undefined)
    void api
      .learningScoreBands()
      .then(setBands)
      .catch(() => undefined)
    void api
      .learningChannels()
      .then(setChannelRows)
      .catch(() => undefined)
    void api
      .learningFeedback()
      .then((data) => {
        setFeedbackPath(data.path)
        setFeedback(data.content)
        setDraft(data.content)
        setMaxChars(data.max_chars)
      })
      .catch(() => undefined)
  }, [])

  const dirty = draft !== feedback

  const save = async () => {
    try {
      const result = await api.saveLearningFeedback(draft)
      setFeedback(draft)
      setSavedAt(`${result.active_chars} chars active`)
    } catch (err) {
      onError(err as Error)
    }
  }

  return (
    <Section title="Learning" note="What the pipeline has done, and standing instructions for the clip finder.">
      {summary && (
        <div className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          <Row label="Clips produced" value={String(summary.clips)} />
          <Row label="Exported" value={String(summary.exported)} />
          <Row label="Failed validation" value={String(summary.invalid)} />
          <Row label="Discarded" value={String(summary.discarded)} />
          <Row label="Uploads published" value={String(summary.uploads_done)} />
          <Row label="Uploads failed" value={String(summary.uploads_failed)} />
        </div>
      )}

      {summary && Object.keys(summary.validation_failures).length > 0 && (
        <p className="mt-3 text-xs text-ink-500">
          Most common failed checks:{' '}
          {Object.entries(summary.validation_failures)
            .slice(0, 4)
            .map(([name, count]) => `${name} (${count})`)
            .join(', ')}
        </p>
      )}

      {bands.some((band) => band.total > 0) && (
        <div className="mt-8">
          <h3 className="text-sm text-ink-100">Do high scores survive?</h3>
          <p className="mt-1 text-xs leading-snug text-ink-500">
            If clips scored 85+ are discarded more often than 70s, the model's scoring is
            miscalibrated for your taste — write the correction in the feedback box below.
          </p>
          <table className="mt-4 w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-xs text-ink-500">
                <th className="py-2 font-normal">Score band</th>
                <th className="py-2 font-normal">Clips</th>
                <th className="py-2 font-normal">Kept</th>
                <th className="py-2 font-normal">Exported</th>
                <th className="py-2 font-normal">Published</th>
                <th className="py-2 font-normal">Trimmed</th>
              </tr>
            </thead>
            <tbody>
              {bands
                .filter((band) => band.total > 0)
                .map((band) => (
                  <tr key={band.band} className="border-b border-ink-850">
                    <td className="numeric py-2 text-ink-200">{band.band}</td>
                    <td className="numeric py-2 text-ink-300">{band.total}</td>
                    <td className="numeric py-2 text-ink-300">{band.kept}</td>
                    <td className="numeric py-2 text-ink-300">{band.exported}</td>
                    <td className="numeric py-2 text-ink-300">{band.uploaded}</td>
                    <td className="numeric py-2 text-ink-300">{band.trimmed}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {channelRows.length > 0 && (
        <div className="mt-8">
          <h3 className="text-sm text-ink-100">Per-channel uploads</h3>
          <table className="mt-4 w-full text-sm">
            <thead>
              <tr className="border-b border-ink-800 text-left text-xs text-ink-500">
                <th className="py-2 font-normal">Channel</th>
                <th className="py-2 font-normal">Published</th>
                <th className="py-2 font-normal">Failed</th>
                <th className="py-2 font-normal">Skipped</th>
                <th className="py-2 font-normal">Queued</th>
              </tr>
            </thead>
            <tbody>
              {channelRows.map((row) => (
                <tr key={row.channel_row_id || 'legacy'} className="border-b border-ink-850">
                  <td className="py-2 text-ink-200">{row.channel_title}</td>
                  <td className="numeric py-2 text-ink-300">{row.done}</td>
                  <td className="numeric py-2 text-ink-300">{row.failed}</td>
                  <td className="numeric py-2 text-ink-300">{row.skipped}</td>
                  <td className="numeric py-2 text-ink-300">{row.pending}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-8">
        <h3 className="text-sm text-ink-100">Standing instructions</h3>
        <p className="mt-1 text-xs leading-snug text-ink-500">
          Injected into every highlight-detection call. Lines starting with <code>#</code> are
          ignored. File: <code className="text-ink-400">{feedbackPath}</code>
        </p>
        <textarea
          className="field mt-3 min-h-40 w-full font-mono text-xs leading-relaxed"
          value={draft}
          maxLength={100_000}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex items-center gap-4">
          <button
            onClick={save}
            disabled={!dirty}
            className="border border-ink-700 px-3 py-2 text-xs text-ink-100 transition-colors enabled:hover:border-sodium-600 disabled:opacity-40"
          >
            {dirty ? 'Save instructions' : 'Saved'}
          </button>
          {savedAt && <span className="text-xs text-ink-500">{savedAt}</span>}
          {draft.length > maxChars && (
            <span className="text-xs text-signal-bad">
              Only the first {maxChars.toLocaleString()} characters reach the model.
            </span>
          )}
        </div>
      </div>
    </Section>
  )
}

/**
 * M0.5 — external processing.
 *
 * One switch per operation and per kind of destination. A blocked operation
 * stops the job at that step with an explanation; AutoClip never quietly
 * picks a different service to work around a refusal.
 *
 * Below the switches is the transfer log: what actually left this machine,
 * where it went, and whether it worked. It never contains the content — only
 * a description of it.
 */
function ExternalProcessingSection({ onError }: { onError: (err: Error) => void }) {
  const [operations, setOperations] = useState<PrivacyOperation[]>([])
  const [transfers, setTransfers] = useState<TransferRecord[]>([])
  const [pending, setPending] = useState('')

  const reload = async () => {
    try {
      setOperations(await api.listConsents())
      setTransfers(await api.listTransfers(50))
    } catch (err) {
      onError(err as Error)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const decide = async (operation: string, destinationClass: string, granted: boolean) => {
    const key = `${operation}:${destinationClass}`
    setPending(key)
    try {
      setOperations(await api.putConsent(operation, destinationClass, granted))
      setTransfers(await api.listTransfers(50))
    } catch (err) {
      onError(err as Error)
      // Put the switch back where the server says it is, so the screen never
      // shows a decision that was not recorded.
      await reload()
    } finally {
      setPending('')
    }
  }

  const classLabel = (destinationClass: string) =>
    destinationClass === 'private' ? 'Private network' : 'Public services'

  const classHint = (destinationClass: string) =>
    destinationClass === 'private'
      ? 'Devices on your own network, such as a model server running at home.'
      : 'Services on the internet operated by someone else.'

  return (
    <Section
      title="External processing"
      note="What AutoClip may send off this machine, and what it has sent."
    >
      <p className="max-w-2xl text-sm leading-relaxed text-ink-400">
        Local work — transcription with Whisper, a local model, rendering, and the music
        library — never leaves this machine. The switches below cover the steps that can.
        Anything running on this machine itself is always allowed, but a tunnel or reverse
        proxy on localhost can forward it somewhere else, so treat localhost services with
        the same care as a public one.
      </p>

      <div className="mt-6 space-y-4">
        {operations.length === 0 && (
          <p className="text-sm text-ink-500">Loading external-processing settings…</p>
        )}

        {operations.map((operation) => (
          <div key={operation.operation} className="border border-ink-800 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm text-ink-100">{operation.title}</p>
              <p className="text-xs text-ink-500">
                {operation.decisions.every((decision) => decision.granted)
                  ? 'allowed'
                  : operation.decisions.some((decision) => decision.granted)
                    ? 'partly allowed'
                    : 'blocked'}
              </p>
            </div>

            <p className="mt-2 text-xs leading-relaxed text-ink-400">{operation.data}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">{operation.why}</p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {operation.decisions.map((decision) => {
                const key = `${operation.operation}:${decision.destination_class}`
                const note =
                  decision.source === 'configured'
                    ? ' — allowed because you configured this destination'
                    : decision.source === 'user' && decision.note
                      ? ` — ${decision.note}`
                      : ''
                return (
                  <label
                    key={decision.destination_class}
                    className="flex items-start gap-3 text-sm text-ink-200"
                  >
                    <input
                      type="checkbox"
                      checked={decision.granted}
                      disabled={pending !== ''}
                      aria-busy={pending === key}
                      onChange={(e) =>
                        decide(
                          operation.operation,
                          decision.destination_class,
                          e.target.checked,
                        )
                      }
                      className="mt-0.5 size-4 accent-sodium-500"
                    />
                    <span>
                      {classLabel(decision.destination_class)}
                      <span className="mt-0.5 block text-xs leading-snug text-ink-500">
                        {decision.granted ? 'Allowed' : 'Blocked'}
                        {note}
                      </span>
                      <span className="mt-0.5 block text-xs leading-snug text-ink-600">
                        {classHint(decision.destination_class)}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <details className="mt-6 border border-ink-800 p-4 text-sm text-ink-300">
        <summary className="cursor-pointer text-ink-200">
          Recent transfers{transfers.length > 0 ? ` (${transfers.length})` : ''}
        </summary>
        {transfers.length === 0 ? (
          <p className="mt-3 text-xs text-ink-500">
            Nothing has left this machine yet.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {transfers.map((transfer, index) => (
              <li
                key={`${transfer.occurred_at}-${index}`}
                className="border-b border-ink-850 pb-2 last:border-b-0"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-xs text-ink-200">{transfer.data_summary}</span>
                  <span
                    className={`text-xs ${
                      transfer.outcome === 'ok' ? 'text-signal-good' : 'text-signal-bad'
                    }`}
                  >
                    {transfer.outcome === 'ok' ? 'sent' : transfer.outcome}
                  </span>
                </div>
                <span className="numeric mt-0.5 block truncate text-xs text-ink-600">
                  {transfer.occurred_at} · {transfer.provider || transfer.operation} ·{' '}
                  {transfer.destination}
                  {transfer.duration_ms > 0 ? ` · ${transfer.duration_ms} ms` : ''}
                </span>
                {transfer.detail && (
                  <span className="mt-0.5 block text-xs text-ink-600">{transfer.detail}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </details>
    </Section>
  )
}

function Section({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <section className="rise mt-14">
      <div className="border-b border-ink-800 pb-2">
        <h2 className="eyebrow">{title}</h2>
        {note && <p className="mt-1 text-xs text-ink-500">{note}</p>}
      </div>
      <div className="mt-5">{children}</div>
    </section>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink-850 pb-2">
      <dt className="text-ink-500">{label}</dt>
      <dd className="numeric truncate text-right text-ink-200">{value}</dd>
    </div>
  )
}

/** Commits on blur rather than per keystroke, so a PUT isn't fired per letter. */
function Field({
  label,
  hint,
  value,
  placeholder,
  onCommit,
}: {
  label: string
  hint?: string
  value: string
  placeholder?: string
  onCommit: (value: string) => void
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])

  return (
    <label className="block">
      <span className="eyebrow">{label}</span>
      <input
        className="field mt-1 text-sm"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft !== value && onCommit(draft)}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        spellCheck={false}
      />
      {hint && <span className="mt-1.5 block text-xs leading-snug text-ink-500">{hint}</span>}
    </label>
  )
}

function NumberField({
  label,
  value,
  onCommit,
}: {
  label: string
  value: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])

  return (
    <label className="block">
      <span className="eyebrow">{label}</span>
      <input
        type="number"
        className="field numeric mt-1 text-sm"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const parsed = Number(draft)
          if (!Number.isNaN(parsed) && parsed !== value) onCommit(parsed)
        }}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
    </label>
  )
}

function Select({
  label,
  hint,
  value,
  onChange,
  options,
  labels = {},
}: {
  label: string
  hint?: string
  value: string
  onChange: (value: string) => void
  options: string[]
  labels?: Record<string, string>
}) {
  return (
    <label className="block">
      <span className="eyebrow">{label}</span>
      <select
        className="field mt-1 cursor-pointer text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option} className="bg-ink-850">
            {labels[option] ?? option}
          </option>
        ))}
      </select>
      {hint && <span className="mt-1.5 block text-xs leading-snug text-ink-500">{hint}</span>}
    </label>
  )
}

function SecretField({
  secretKey,
  label,
  present,
  onChanged,
  onError,
}: {
  secretKey: string
  label: string
  present: boolean
  onChanged: () => void
  onError: (error: Error) => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (!value.trim()) return
    setBusy(true)
    try {
      await api.putSecret(secretKey, value.trim())
      setValue('')
      onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteSecret(secretKey)
      onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-56 flex-1">
        <span className="eyebrow">
          {label}
          {present && <span className="ml-2 text-signal-good">set</span>}
        </span>
        <input
          type="password"
          className="field mt-1 text-sm"
          value={value}
          placeholder={present ? '••••••••••••' : 'paste to add'}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && save()}
          autoComplete="off"
        />
      </label>
      <button onClick={save} disabled={!value.trim() || busy} className="btn btn-ghost">
        Save
      </button>
      {present && (
        <button onClick={remove} disabled={busy} className="btn btn-quiet">
          Remove
        </button>
      )}
    </div>
  )
}
