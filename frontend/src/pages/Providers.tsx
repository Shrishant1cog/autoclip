/**
 * AI providers — every preset, every key.
 *
 * The Settings page answers "which model finds the clips". This page answers
 * the questions a multi-provider setup actually raises: which providers are
 * configured, which of their keys are healthy enough to use right now, and
 * what happens when one of them fails.
 *
 * Nothing here is a simulation. `keys_healthy` is the number of keys that are
 * enabled and not cooling down; a key that hit an auth error is shown as
 * disabled with the real error text, not quietly hidden.
 */
import { useCallback, useEffect, useState } from 'react'

import { api, type ProviderKey, type ProviderPreset } from '../api'
import { ErrorNote } from '../components/ErrorNote'

/** The capabilities a provider advertises, in plain words. */
const CAPABILITY_LABEL: Record<string, string> = {
  text: 'Text',
  json: 'JSON',
  long_context: 'Long context',
  vision: 'Vision',
  embeddings: 'Embeddings',
  audio_understanding: 'Audio',
}

export function Providers() {
  const [providers, setProviders] = useState<ProviderPreset[]>([])
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [keys, setKeys] = useState<Record<string, ProviderKey[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setProviders(await api.listProviders())
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const loadKeys = useCallback(async (key: string) => {
    try {
      const list = await api.providerKeys(key)
      setKeys((prev) => ({ ...prev, [key]: list }))
    } catch (err) {
      setError(err as Error)
    }
  }, [])

  const toggle = async (provider: ProviderPreset) => {
    if (openKey === provider.key) {
      setOpenKey(null)
      return
    }
    setOpenKey(provider.key)
    await loadKeys(provider.key)
  }

  const hosted = providers.filter((p) => !p.is_local)
  const local = providers.filter((p) => p.is_local)
  const activeCount = providers.filter((p) => p.active).length

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Providers</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          Who does the thinking
        </h1>
        <p className="numeric mt-3 text-xs text-ink-500">
          {providers.length} providers · {activeCount} active · {hosted.length} need a key ·{' '}
          {local.length} run locally
        </p>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-400">
          AutoClip tries the providers in order and falls back to the next one when a
          provider fails. Several keys per provider are rotated automatically; a key
          that hits an authentication error is taken out of the rotation and the real
          reason is shown.
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
          <ProviderGroup
            title="Hosted"
            note="Need an API key. Add one below and the provider joins the fallback chain."
            providers={hosted}
            openKey={openKey}
            keys={keys}
            onToggle={toggle}
            onChanged={async (provider) => {
              await Promise.all([load(), loadKeys(provider.key)])
            }}
            onError={setError}
            onStatus={setStatus}
          />

          <ProviderGroup
            title="Local"
            note="Run on this machine. No key, no quota, no network — but they are the slowest to answer, so they sit last in the chain."
            providers={local}
            openKey={openKey}
            keys={keys}
            onToggle={toggle}
            onChanged={async (provider) => {
              await Promise.all([load(), loadKeys(provider.key)])
            }}
            onError={setError}
            onStatus={setStatus}
          />
        </>
      )}
    </div>
  )
}

function ProviderGroup({
  title,
  note,
  providers,
  openKey,
  keys,
  onToggle,
  onChanged,
  onError,
  onStatus,
}: {
  title: string
  note: string
  providers: ProviderPreset[]
  openKey: string | null
  keys: Record<string, ProviderKey[]>
  onToggle: (provider: ProviderPreset) => void
  onChanged: (provider: ProviderPreset) => Promise<void>
  onError: (error: Error) => void
  onStatus: (status: string) => void
}) {
  if (providers.length === 0) return null

  return (
    <section className="mt-10">
      <div className="flex items-baseline gap-4">
        <h2 className="eyebrow">{title}</h2>
        <span className="numeric text-xs text-ink-600">{providers.length}</span>
      </div>
      <p className="mt-2 max-w-prose text-xs leading-relaxed text-ink-500">{note}</p>

      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {providers.map((provider) => (
          <ProviderCard
            key={provider.key}
            provider={provider}
            open={openKey === provider.key}
            keys={keys[provider.key]}
            onToggle={() => onToggle(provider)}
            onChanged={() => onChanged(provider)}
            onError={onError}
            onStatus={onStatus}
          />
        ))}
      </div>
    </section>
  )
}

function ProviderCard({
  provider,
  open,
  keys,
  onToggle,
  onChanged,
  onError,
  onStatus,
}: {
  provider: ProviderPreset
  open: boolean
  keys: ProviderKey[] | undefined
  onToggle: () => void
  onChanged: () => Promise<void>
  onError: (error: Error) => void
  onStatus: (status: string) => void
}) {
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const [working, setWorking] = useState(false)

  const add = async () => {
    if (!value.trim()) {
      onError(new Error('Paste the key before adding it.'))
      return
    }
    setWorking(true)
    onStatus('')
    try {
      const result = await api.addProviderKey(provider.key, label.trim(), value.trim())
      setValue('')
      setLabel('')
      onStatus(
        result.stored === 'keyring'
          ? `${provider.label}: key stored in the system keyring.`
          : `${provider.label}: key stored in the local fallback file (no keyring on this machine).`,
      )
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setWorking(false)
    }
  }

  const remove = async (keyLabel: string) => {
    setWorking(true)
    try {
      await api.removeProviderKey(provider.key, keyLabel)
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setWorking(false)
    }
  }

  const setEnabled = async (keyLabel: string, enabled: boolean) => {
    setWorking(true)
    try {
      await api.setProviderKeyEnabled(provider.key, keyLabel, enabled)
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setWorking(false)
    }
  }

  const state = provider.active
    ? 'Active'
    : provider.is_local
      ? 'Local'
      : provider.keys_healthy > 0
        ? 'Ready'
        : provider.keys_total > 0
          ? 'No usable key'
          : 'No key'

  const stateClass = provider.active
    ? 'text-signal-good'
    : provider.keys_total > 0 && provider.keys_healthy === 0
      ? 'text-signal-warn'
      : 'text-ink-500'

  return (
    <article className="border border-ink-800 bg-ink-850/30 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="font-display text-lg leading-tight text-ink-100">{provider.label}</h3>
          <p className="mt-1 text-xs text-ink-500">
            <span className="numeric">{provider.adapter}</span>
            {provider.default_base_url ? ` · ${provider.default_base_url}` : ''}
          </p>
        </div>
        <span className={`shrink-0 text-[10px] uppercase tracking-wider ${stateClass}`}>
          {state}
        </span>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <dt className="eyebrow">Model</dt>
          <dd className="mt-1 truncate text-ink-300" title={provider.default_model}>
            {provider.default_model || '—'}
          </dd>
        </div>
        <div>
          <dt className="eyebrow">Keys</dt>
          <dd className="numeric mt-1 text-ink-300">
            {provider.keys_healthy} of {provider.keys_total} usable
          </dd>
        </div>
      </dl>

      {provider.suggested_models.length > 0 && (
        <p className="mt-3 truncate text-[11px] text-ink-600" title={provider.suggested_models.join(' · ')}>
          {provider.suggested_models.join(' · ')}
        </p>
      )}

      {provider.capabilities.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {provider.capabilities.map((cap) => (
            <span
              key={cap}
              className="border border-ink-700 px-2 py-0.5 text-[10px] uppercase tracking-wider text-ink-500"
            >
              {CAPABILITY_LABEL[cap] ?? cap}
            </span>
          ))}
        </div>
      )}

      {provider.requires_key && (
        <button
          onClick={onToggle}
          className="btn btn-ghost mt-4 text-xs"
          aria-expanded={open}
        >
          {open ? 'Hide keys' : `Keys${provider.keys_total ? ` (${provider.keys_total})` : ''}`}
        </button>
      )}

      {open && provider.requires_key && (
        <div className="mt-4 border-t border-ink-800 pt-4">
          {keys === undefined ? (
            <p className="text-xs text-ink-500">Loading keys…</p>
          ) : keys.length === 0 ? (
            <p className="text-xs leading-relaxed text-ink-500">
              No keys yet. A provider without a key cannot answer, so it stays out of the
              fallback chain.
            </p>
          ) : (
            <ul className="space-y-2">
              {keys.map((key) => (
                <li key={key.label} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-ink-200">
                      {key.label || 'default'}
                      {key.cooling_down && (
                        <span className="ml-2 text-[10px] uppercase tracking-wider text-signal-warn">
                          cooling down
                        </span>
                      )}
                      {!key.enabled && (
                        <span className="ml-2 text-[10px] uppercase tracking-wider text-ink-600">
                          disabled
                        </span>
                      )}
                    </p>
                    {key.last_error && (
                      <p className="mt-1 text-[11px] leading-relaxed text-signal-bad">
                        {key.last_error}
                      </p>
                    )}
                    {key.failures > 0 && !key.last_error && (
                      <p className="numeric mt-1 text-[11px] text-ink-600">
                        {key.failures} failed attempt{key.failures === 1 ? '' : 's'}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-baseline gap-2">
                    <button
                      onClick={() => void setEnabled(key.label, !key.enabled)}
                      disabled={working}
                      className="btn btn-quiet text-xs disabled:opacity-50"
                    >
                      {key.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      onClick={() => void remove(key.label)}
                      disabled={working}
                      className="btn btn-quiet text-xs text-signal-bad disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="min-w-32 flex-1">
              <span className="eyebrow">Label</span>
              <input
                className="field mt-1 text-sm"
                value={label}
                placeholder="optional"
                onChange={(e) => setLabel(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="min-w-56 flex-[2]">
              <span className="eyebrow">Key</span>
              <input
                type="password"
                className="field mt-1 text-sm"
                value={value}
                placeholder="paste to add"
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void add()}
                autoComplete="off"
              />
            </label>
            <button
              onClick={() => void add()}
              disabled={working}
              className="btn btn-primary text-xs disabled:opacity-50"
            >
              {working ? 'Adding…' : 'Add key'}
            </button>
          </div>
        </div>
      )}
    </article>
  )
}
