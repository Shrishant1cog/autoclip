import { useCallback, useEffect, useState } from 'react'

import {
  api,
  type InstagramAccount,
  type InstagramEligibility,
  type InstagramLoginType,
  type InstagramStatus,
  type Settings as SettingsData,
} from '../api'
import { ErrorNote } from './ErrorNote'

/**
 * The Instagram connection.
 *
 * Meta offers three ways to sign in, and they are not interchangeable:
 * two of them can take a local file and one cannot. The screen therefore
 * says which setup is in force, what it can and cannot do, and what is
 * still **unverified** — AutoClip does not claim a professional account or
 * an app-review status it cannot see.
 *
 * The publishing allowance is read from Meta rather than hardcoded: Meta's
 * own documents disagree about the number, so the page shows what the
 * endpoint currently reports.
 */

const LOGIN_TYPES: Record<InstagramLoginType, string> = {
  unified: 'Unified Login (recommended)',
  facebook: 'Facebook Login (needs a Page)',
  instagram: 'Instagram Login (no local files)',
}

const DEFAULTS = {
  app_id: '',
  redirect_uri: 'http://localhost:8000/api/instagram/callback',
  login_type: 'unified' as InstagramLoginType,
  api_version: 'v27.0',
  config_id: '',
  business_id: '',
  auto_upload: false,
  ig_user_id: '',
  username: '',
  connected_at: '',
  professional: false,
}

export function InstagramSettings({
  settings,
  onPatch,
  onReload,
  onError,
}: {
  settings: SettingsData
  onPatch: (update: Partial<SettingsData>) => void
  onReload: () => void
  onError: (error: Error) => void
}) {
  const config = { ...DEFAULTS, ...(settings.instagram ?? {}) }
  const [status, setStatus] = useState<InstagramStatus | null>(null)
  const [accounts, setAccounts] = useState<InstagramAccount[]>([])
  const [eligibility, setEligibility] = useState<InstagramEligibility | null>(null)
  const [busy, setBusy] = useState('')
  const [localError, setLocalError] = useState<Error | null>(null)
  const [waiting, setWaiting] = useState(false)

  const reload = useCallback(async () => {
    try {
      const [next, list] = await Promise.all([api.instagramStatus(), api.instagramAccounts()])
      setStatus(next)
      setAccounts(list)
      try {
        setEligibility(await api.instagramEligibility())
      } catch {
        setEligibility(null)
      }
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

  const patchConfig = (update: Partial<typeof config>) => {
    onPatch({ instagram: { ...config, ...update } })
  }

  /**
   * Meta sends the browser back to a small page that closes itself, so the
   * sign-in has to happen in a popup. The opener watches the status until
   * Meta says the account is connected.
   */
  const connect = (accountId = '') => {
    void run('connect', async () => {
      const { auth_url } = await api.instagramConnect(accountId)
      const popup = window.open(
        auth_url,
        'autoclip-instagram',
        'popup,width=620,height=760,noopener,noreferrer',
      )
      if (!popup) {
        throw new Error('The browser blocked the sign-in window. Allow popups and try again.')
      }
      setWaiting(true)
      for (let attempt = 0; attempt < 45; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000))
        const next = await api.instagramStatus()
        setStatus(next)
        if (next.connected) break
      }
      setWaiting(false)
      await reload()
    })
  }

  const limit = eligibility?.publishing_limit

  return (
    <div className="space-y-6">
      {localError && <ErrorNote error={localError} onDismiss={() => setLocalError(null)} />}

      {/* -- The connection -- */}
      <div className="flex flex-wrap items-center justify-between gap-3 border border-ink-800 p-4">
        <div>
          <p className="text-sm text-ink-100">
            {status?.connected
              ? `Connected to ${status.username || 'your Instagram account'}`
              : 'No account connected'}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            {status?.connected
              ? `Auto-post is ${status.auto_upload ? 'on' : 'off'}. ${
                  eligibility?.resumable_upload
                    ? 'Local files can be sent on this setup.'
                    : 'This setup cannot take a local file — only a public video URL can be published.'
                }`
              : 'Add the Meta app details below, then sign in. Tokens stay in your OS keyring.'}
          </p>
        </div>
        {status?.connected ? (
          <button
            className="btn btn-quiet"
            disabled={busy !== ''}
            onClick={() => void run('disconnect', async () => {
              const next = await api.instagramDisconnect()
              setStatus(next)
            })}
          >
            Disconnect
          </button>
        ) : (
          <button
            className="btn btn-primary"
            disabled={busy !== '' || !status?.configured}
            title={
              status?.configured
                ? undefined
                : 'Add the Meta app id and secret first — Meta refuses a sign-in without them.'
            }
            onClick={() => connect()}
          >
            {busy === 'connect' ? 'Waiting for Meta…' : 'Connect Instagram account'}
          </button>
        )}
      </div>

      {waiting && (
        <p className="text-xs text-ink-500">
          Finish the sign-in in the Meta window. This page updates on its own once Meta says the
          account is connected.
        </p>
      )}

      {/* -- The app details -- */}
      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          label="Meta app id"
          hint="developers.facebook.com — your app's App ID."
          value={config.app_id}
          placeholder="123456789012345"
          onCommit={(value) => patchConfig({ app_id: value })}
        />
        <Field
          label="Redirect URI"
          hint="Must match a redirect URI registered on the Meta app exactly."
          value={config.redirect_uri}
          onCommit={(value) => patchConfig({ redirect_uri: value })}
        />
        <label className="block">
          <span className="eyebrow">API setup</span>
          <select
            className="field mt-1 cursor-pointer text-sm"
            value={config.login_type}
            onChange={(e) => patchConfig({ login_type: e.target.value as InstagramLoginType })}
          >
            {(Object.keys(LOGIN_TYPES) as InstagramLoginType[]).map((type) => (
              <option key={type} value={type} className="bg-ink-850">
                {LOGIN_TYPES[type]}
              </option>
            ))}
          </select>
          <span className="mt-1.5 block text-xs leading-snug text-ink-500">
            {config.login_type === 'unified' &&
              'Facebook Login for Business. No Page needed, and local files can be uploaded.'}
            {config.login_type === 'facebook' &&
              'Page-linked. A Facebook Page is required, and local files can be uploaded.'}
            {config.login_type === 'instagram' &&
              'Instagram Login. No resumable upload — AutoClip refuses a local file on this setup rather than sending it somewhere else.'}
          </span>
        </label>
        <Field
          label="Configuration id"
          hint="Facebook Login for Business configuration. Required by the first two setups."
          value={config.config_id}
          placeholder="configuration id"
          onCommit={(value) => patchConfig({ config_id: value })}
        />
        <Field
          label="Business id"
          hint="The client business id Meta returns. Needed to refresh the Unified Login token."
          value={config.business_id}
          placeholder="client business id"
          onCommit={(value) => patchConfig({ business_id: value })}
        />
        <label className="block">
          <span className="eyebrow">Meta app secret</span>
          <SecretField
            present={settings.instagram_secret_present ?? false}
            onChanged={() => {
              void reload()
              onReload()
            }}
            onError={onError}
          />
        </label>
      </div>

      {/* -- Automation -- */}
      <label className="flex items-start gap-3 text-sm text-ink-200">
        <input
          type="checkbox"
          checked={config.auto_upload}
          disabled={!status?.connected}
          onChange={async (e) => {
            setBusy('auto')
            setLocalError(null)
            try {
              const next = await api.setInstagramAuto(e.target.checked)
              setStatus(next)
              patchConfig({ auto_upload: e.target.checked })
            } catch (err) {
              const error = err as Error
              setLocalError(error)
              onError(error)
            } finally {
              setBusy('')
            }
          }}
          className="mt-0.5 size-4 accent-sodium-500"
        />
        <span>
          Post every finished clip automatically
          <span className="mt-1 block text-xs leading-snug text-ink-500">
            Each export is queued as a Reel. The caption is yours to write before the file leaves
            the machine.
          </span>
        </span>
      </label>

      {/* -- The accounts -- */}
      {accounts.length > 0 && (
        <div className="border border-ink-800 p-4">
          <p className="text-sm text-ink-100">Accounts</p>
          <ul className="mt-3 space-y-3">
            {accounts.map((account) => (
              <li
                key={account.id}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-850 pb-3 last:border-0 last:pb-0"
              >
                <div>
                  <p className="text-sm text-ink-200">
                    {account.username || account.name || account.label || account.ig_user_id}
                  </p>
                  <p className="mt-0.5 text-xs text-ink-500">
                    {account.ig_user_id || 'no id yet'}
                    {account.has_token ? ' · credential held' : ' · no credential'}
                    {account.login_type ? ` · ${account.login_type} login` : ''}
                  </p>
                  {account.needs_reconnect && (
                    <p className="mt-1 text-xs text-signal-warn">
                      Meta refused this account's credential — sign in again.
                    </p>
                  )}
                  {account.last_error && (
                    <p className="mt-1 text-xs text-ink-500">{account.last_error}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {account.needs_reconnect && (
                    <button
                      className="btn btn-ghost text-xs"
                      disabled={busy !== ''}
                      onClick={() => connect(account.id)}
                    >
                      Connect again
                    </button>
                  )}
                  <button
                    className="btn btn-quiet text-xs"
                    disabled={busy !== ''}
                    onClick={() => void run(`disconnect-${account.id}`, async () => {
                      await api.instagramDisconnect(account.id)
                    })}
                  >
                    Disconnect
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* -- What is and is not known -- */}
      {eligibility && (
        <div className="border border-ink-800 p-4">
          <p className="text-sm text-ink-100">What Meta requires</p>
          <p className="mt-1 text-xs text-ink-500">
            {eligibility.setup_label} · {eligibility.host} · Graph {status?.api_version ?? 'v27.0'}
          </p>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <List
              title="Required"
              items={eligibility.requirements}
              className="text-ink-300"
            />
            <List
              title="Not verified"
              items={eligibility.unverified}
              className="text-ink-400"
              empty="Everything AutoClip can check has been checked."
            />
          </div>

          {eligibility.observations.length > 0 && (
            <div className="mt-4">
              <List title="Observed" items={eligibility.observations} className="text-ink-300" />
            </div>
          )}

          <div className="mt-4 border-t border-ink-850 pt-3">
            <p className="text-xs text-ink-500">
              Publishing allowance, read from Meta
            </p>
            {limit?.known ? (
              <p className="numeric mt-1 text-sm text-ink-200">
                {limit.remaining} of {limit.quota_total} left
                {limit.quota_usage > 0 ? ` · ${limit.quota_usage} used` : ''}
                {limit.quota_duration_s
                  ? ` · over ${Math.round(limit.quota_duration_s / 3600)} h`
                  : ''}
              </p>
            ) : (
              <p className="mt-1 text-sm text-ink-500">
                Meta has not reported a limit yet. AutoClip does not guess one.
              </p>
            )}
          </div>

          <p className="mt-4 text-xs leading-relaxed text-ink-500">
            AutoClip does not publish on its own authority. The account, the app review and the
            business verification are yours to complete.
          </p>
        </div>
      )}
    </div>
  )
}

function List({
  title,
  items,
  className,
  empty,
}: {
  title: string
  items: string[]
  className?: string
  empty?: string
}) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {items.length === 0 ? (
        <p className="mt-1.5 text-xs text-ink-500">{empty ?? 'Nothing to report.'}</p>
      ) : (
        <ul className={`mt-1.5 space-y-1.5 text-xs leading-relaxed ${className ?? ''}`}>
          {items.map((item) => (
            <li key={item} className="flex gap-2">
              <span className="text-ink-600">—</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
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

/** The Meta app secret. Write-only: the value is never read back. */
function SecretField({
  present,
  onChanged,
  onError,
}: {
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
      await api.putSecret('instagram_app_secret', value.trim())
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
      await api.deleteSecret('instagram_app_secret')
      onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-1">
      <div className="flex flex-wrap items-end gap-3">
        <input
          type="password"
          className="field min-w-56 flex-1 text-sm"
          value={value}
          placeholder={present ? '••••••••••••' : 'paste to add'}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && save()}
          autoComplete="off"
        />
        <button
          type="button"
          className="btn btn-quiet text-xs"
          disabled={busy || !value.trim()}
          onClick={save}
        >
          Save
        </button>
        {present && (
          <button
            type="button"
            className="btn btn-quiet text-xs"
            disabled={busy}
            onClick={remove}
          >
            Remove
          </button>
        )}
      </div>
      <span className="mt-1.5 block text-xs leading-snug text-ink-500">
        {present
          ? 'A secret is stored in your OS keyring. The value is never sent back.'
          : 'Stored in your OS keyring, never in config.json.'}
      </span>
    </div>
  )
}
