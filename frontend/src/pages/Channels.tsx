/**
 * YouTube accounts and channels.
 *
 * AutoClip can publish to more than one channel, and each channel can have its
 * own policy: a different privacy default, a different category, a title
 * suffix, or no automatic publishing at all. That policy is what the routing
 * page points rules at, so this page is where the targets are defined.
 *
 * Accounts hold the Google credentials; channels belong to accounts. The
 * refresh token itself never reaches the browser — the page only ever shows
 * whether one is stored.
 */
import { useCallback, useEffect, useState } from 'react'

import { api, type YouTubeAccount, type YouTubeChannel } from '../api'
import { ErrorNote } from '../components/ErrorNote'

const PRIVACY_OPTIONS = [
  { value: 'public', label: 'Public' },
  { value: 'unlisted', label: 'Unlisted' },
  { value: 'private', label: 'Private' },
]

/**
 * The audience declaration. Three states, and "not decided" is not the
 * same as "no" — it means nobody has answered yet, and an upload is
 * refused until they do.
 */
const AUDIENCE_OPTIONS = [
  { value: '', label: 'Not decided' },
  { value: 'false', label: 'No — not made for kids' },
  { value: 'true', label: 'Yes — made for kids' },
]

export function Channels() {
  const [accounts, setAccounts] = useState<YouTubeAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setAccounts(await api.listYouTubeAccounts())
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const connect = async () => {
    setBusy(true)
    setError(null)
    setStatus('')
    try {
      const { auth_url } = await api.youtubeConnect()
      window.open(auth_url, '_blank', 'noopener')
      setStatus('Google sign-in opened in a new tab. Come back once it says you are connected.')
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const addAccount = async (label: string, email: string) => {
    setBusy(true)
    try {
      await api.createYouTubeAccount(label, email)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const removeAccount = async (id: string) => {
    setBusy(true)
    try {
      await api.deleteYouTubeAccount(id)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const totalChannels = accounts.reduce((n, a) => n + a.channels.length, 0)
  const autoChannels = accounts.reduce(
    (n, a) => n + a.channels.filter((c) => c.auto_upload).length,
    0,
  )

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Channels</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          Where the clips go
        </h1>
        <p className="numeric mt-3 text-xs text-ink-500">
          {accounts.length} account{accounts.length === 1 ? '' : 's'} · {totalChannels} channel
          {totalChannels === 1 ? '' : 's'} · {autoChannels} publish automatically
        </p>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-400">
          Each channel carries its own publishing policy. The routing page points rules at
          these channels, and a channel with automatic publishing switched off is never
          published to by a fan-out.
        </p>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} onRetry={() => void load()} />
        </div>
      )}

      {status && <p className="mt-4 text-xs text-signal-good">{status}</p>}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          onClick={() => void connect()}
          disabled={busy}
          className="btn btn-primary text-xs disabled:opacity-50"
        >
          {busy ? 'Opening…' : 'Connect a Google account'}
        </button>
      </div>

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : accounts.length === 0 ? (
        <div className="pt-16">
          <p className="max-w-xl text-sm leading-relaxed text-ink-300">
            No account is connected yet. Connect a Google account and its channels appear
            here — each one ready to be given its own publishing policy.
          </p>
        </div>
      ) : (
        <div className="mt-8 space-y-8">
          {accounts.map((account) => (
            <AccountBlock
              key={account.id}
              account={account}
              busy={busy}
              onChanged={load}
              onError={setError}
              onRemove={() => void removeAccount(account.id)}
            />
          ))}
          <NewAccount onAdd={addAccount} busy={busy} />
        </div>
      )}
    </div>
  )
}

function AccountBlock({
  account,
  busy,
  onChanged,
  onError,
  onRemove,
}: {
  account: YouTubeAccount
  busy: boolean
  onChanged: () => Promise<void>
  onError: (error: Error) => void
  onRemove: () => void
}) {
  const [adding, setAdding] = useState(false)

  const addChannel = async () => {
    setAdding(true)
    try {
      await api.addYouTubeChannel(account.id, {})
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setAdding(false)
    }
  }

  const connectAccount = async (accountId: string) => {
    try {
      const { auth_url } = await api.connectYouTubeAccount(accountId)
      window.open(auth_url, '_blank', 'noopener')
    } catch (err) {
      onError(err as Error)
    }
  }

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink-800 pb-3">
        <div className="min-w-0">
          <h2 className="font-display text-xl leading-tight text-ink-100">
            {account.label || 'Google account'}
          </h2>
          <p className="mt-1 truncate text-xs text-ink-500">
            {account.email || 'no email recorded'}
            {account.client_id ? ` · ${account.client_id.split('-')[0]}…` : ''}
          </p>
        </div>
        <div className="flex items-baseline gap-3">
          <span
            className={`text-[10px] uppercase tracking-wider ${
              account.has_refresh_token ? 'text-signal-good' : 'text-signal-warn'
            }`}
          >
            {account.has_refresh_token ? 'Token stored' : 'No token'}
          </span>
          <button
            onClick={onRemove}
            disabled={busy}
            className="btn btn-quiet text-xs text-signal-bad disabled:opacity-50"
          >
            Remove account
          </button>
        </div>
      </div>

      {!account.has_refresh_token && (
        <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-500">
          This account has no refresh token, so it cannot publish. Connect it through
          Google sign-in to give it one.
        </p>
      )}

      {account.needs_reconnect && (
        <p className="mt-3 max-w-prose text-xs leading-relaxed text-signal-warn">
          Google refused this account's credential, so it has to be connected again. The
          other accounts are not affected and keep publishing.
          {account.last_error ? ` (${account.last_error})` : ''}
        </p>
      )}

      {!account.has_refresh_token && (
        <button
          onClick={() => void connectAccount(account.id)}
          disabled={busy}
          className="btn btn-ghost mt-3 text-xs disabled:opacity-50"
        >
          Connect this account
        </button>
      )}

      {account.channels.length === 0 ? (
        <p className="mt-4 text-sm leading-relaxed text-ink-500">
          No channels registered under this account yet.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {account.channels.map((channel) => (
            <ChannelRow
              key={channel.id}
              channel={channel}
              busy={busy}
              onChanged={onChanged}
              onError={onError}
            />
          ))}
        </div>
      )}

      <button
        onClick={() => void addChannel()}
        disabled={busy || adding}
        className="btn btn-ghost mt-4 text-xs disabled:opacity-50"
      >
        {adding ? 'Adding…' : 'Register a channel'}
      </button>
    </section>
  )
}

function ChannelRow({
  channel,
  busy,
  onChanged,
  onError,
}: {
  channel: YouTubeChannel
  busy: boolean
  onChanged: () => Promise<void>
  onError: (error: Error) => void
}) {
  const [working, setWorking] = useState(false)

  const patch = async (fields: Partial<YouTubeChannel>) => {
    setWorking(true)
    try {
      await api.updateYouTubeChannel(channel.id, fields)
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setWorking(false)
    }
  }

  const remove = async () => {
    setWorking(true)
    try {
      await api.deleteYouTubeChannel(channel.id)
      await onChanged()
    } catch (err) {
      onError(err as Error)
    } finally {
      setWorking(false)
    }
  }

  return (
    <article className="border border-ink-800 bg-ink-850/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="font-display text-base leading-tight text-ink-100">
            {channel.title || 'Untitled channel'}
            {channel.is_default && (
              <span className="ml-2 text-[10px] uppercase tracking-wider text-signal-good">
                default
              </span>
            )}
          </h3>
          {channel.url && (
            <a
              href={channel.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block truncate text-xs text-ink-500 underline-offset-4 hover:text-ink-200 hover:underline"
            >
              {channel.url}
            </a>
          )}
        </div>
        <button
          onClick={() => void remove()}
          disabled={working || busy}
          className="btn btn-quiet text-xs text-signal-bad disabled:opacity-50"
        >
          Remove
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-5">
        <label className="block">
          <span className="eyebrow">Privacy</span>
          <select
            className="field mt-1 text-sm"
            value={channel.privacy}
            onChange={(e) => void patch({ privacy: e.target.value })}
            disabled={working}
          >
            {PRIVACY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value} className="bg-ink-900">
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Category id</span>
          <input
            className="field numeric mt-1 w-24 text-sm"
            value={channel.category_id}
            onChange={(e) => void patch({ category_id: e.target.value })}
            disabled={working}
          />
        </label>

        <label className="block">
          <span className="eyebrow">Audience</span>
          <select
            className="field mt-1 text-sm"
            value={channel.made_for_kids}
            onChange={(e) => void patch({ made_for_kids: e.target.value })}
            disabled={working}
          >
            {AUDIENCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value} className="bg-ink-900">
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Title suffix</span>
          <input
            className="field mt-1 w-40 text-sm"
            value={channel.title_suffix}
            placeholder="none"
            onChange={(e) => void patch({ title_suffix: e.target.value })}
            disabled={working}
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-ink-300">
          <input
            type="checkbox"
            checked={channel.auto_upload}
            onChange={(e) => void patch({ auto_upload: e.target.checked })}
            disabled={working}
          />
          Publish automatically
        </label>

        {!channel.is_default && (
          <button
            onClick={() => void patch({ is_default: true })}
            disabled={working || busy}
            className="btn btn-ghost text-xs disabled:opacity-50"
          >
            Make default
          </button>
        )}
      </div>

      {channel.made_for_kids === '' && (
        <p className="mt-3 max-w-prose text-xs leading-relaxed text-signal-warn">
          The audience declaration has not been answered. YouTube asks whether a video is
          made for kids, and that is a legal declaration rather than a setting AutoClip can
          choose for you — so nothing is published to this channel until you answer it.
        </p>
      )}
    </article>
  )
}

function NewAccount({
  onAdd,
  busy,
}: {
  onAdd: (label: string, email: string) => Promise<void>
  busy: boolean
}) {
  const [label, setLabel] = useState('')
  const [email, setEmail] = useState('')

  return (
    <section className="border-t border-ink-800 pt-6">
      <h2 className="eyebrow">Register an account slot</h2>
      <p className="mt-2 max-w-prose text-xs leading-relaxed text-ink-500">
        A slot is a named place for a Google account. The OAuth flow attaches the
        credentials when you sign in through it.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="min-w-40 flex-1">
          <span className="eyebrow">Label</span>
          <input
            className="field mt-1 text-sm"
            value={label}
            placeholder="Work channel"
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>
        <label className="min-w-56 flex-1">
          <span className="eyebrow">Email</span>
          <input
            type="email"
            className="field mt-1 text-sm"
            value={email}
            placeholder="you@example.com"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <button
          onClick={() => void onAdd(label.trim(), email.trim())}
          disabled={busy}
          className="btn btn-ghost text-xs disabled:opacity-50"
        >
          Add slot
        </button>
      </div>
    </section>
  )
}
