/**
 * Routing rules.
 *
 * A rule says: a clip whose content category contains this keyword goes to
 * this channel. The first enabled rule whose keyword matches wins; a clip
 * that matches nothing goes to the default channel.
 *
 * The categories are fixed by the classifier, so the page shows them as the
 * vocabulary a keyword can be drawn from. The targets are the channels
 * defined on the Channels page — a rule that points at a channel which no
 * longer exists is refused by the server rather than silently doing nothing.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, type RoutingRule, type YouTubeChannel } from '../api'
import { ErrorNote } from '../components/ErrorNote'

export function Routing() {
  const [rules, setRules] = useState<RoutingRule[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [channels, setChannels] = useState<YouTubeChannel[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [ruleList, categoryList, accounts] = await Promise.all([
        api.listRoutingRules(),
        api.routingCategories(),
        api.listYouTubeAccounts(),
      ])
      setRules(ruleList)
      setCategories(categoryList)
      setChannels(accounts.flatMap((a) => a.channels))
    } catch (err) {
      setError(err as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const channelById = useMemo(() => {
    const map = new Map<string, YouTubeChannel>()
    for (const channel of channels) map.set(channel.id, channel)
    return map
  }, [channels])

  const create = async (rule: {
    name: string
    match_keyword: string
    target_channel_id: string
    priority: number
    extra_channel_ids: string[]
  }) => {
    setBusy(true)
    setError(null)
    setStatus('')
    try {
      await api.createRoutingRule(rule)
      setStatus(`Rule “${rule.match_keyword}” added.`)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const update = async (ruleId: string, patch: Partial<RoutingRule>) => {
    setBusy(true)
    try {
      await api.updateRoutingRule(ruleId, patch)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (ruleId: string) => {
    setBusy(true)
    try {
      await api.deleteRoutingRule(ruleId)
      await load()
    } catch (err) {
      setError(err as Error)
    } finally {
      setBusy(false)
    }
  }

  const enabledCount = rules.filter((r) => r.enabled).length

  return (
    <div className="pt-10">
      <div className="border-b border-ink-800 pb-5">
        <p className="eyebrow">Routing</p>
        <h1 className="mt-2 font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-none text-ink-100">
          Which channel takes which clip
        </h1>
        <p className="numeric mt-3 text-xs text-ink-500">
          {rules.length} rule{rules.length === 1 ? '' : 's'} · {enabledCount} enabled ·{' '}
          {channels.length} channel{channels.length === 1 ? '' : 's'} to target
        </p>
        <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-400">
          Rules are checked in priority order, lowest first. The first enabled rule whose
          keyword appears in a clip's category sends it to that channel; a clip that
          matches nothing goes to the default channel.
        </p>
      </div>

      {error && (
        <div className="mt-6 max-w-3xl">
          <ErrorNote error={error} onDismiss={() => setError(null)} onRetry={() => void load()} />
        </div>
      )}

      {status && <p className="mt-4 text-xs text-signal-good">{status}</p>}

      {channels.length === 0 && !loading && (
        <div className="mt-8 border-l-2 border-signal-warn pl-4">
          <p className="text-sm font-medium text-ink-100">No channels to route to</p>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-400">
            A rule needs a target channel. Connect a Google account on the Channels page
            first — the server refuses a rule whose target does not exist rather than
            storing one that can never fire.
          </p>
        </div>
      )}

      {loading ? (
        <p className="pt-16 text-sm text-ink-500">Loading…</p>
      ) : (
        <>
          <section className="mt-10">
            <h2 className="eyebrow">Categories</h2>
            <p className="mt-2 max-w-prose text-xs leading-relaxed text-ink-500">
              These are the categories the classifier assigns. A rule's keyword is matched
              against the category, so a keyword of “gaming” catches every gaming clip.
            </p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {categories.map((category) => (
                <span
                  key={category}
                  className="border border-ink-700 px-2.5 py-1 text-[11px] lowercase tracking-wide text-ink-400"
                >
                  {category}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-10">
            <div className="flex items-baseline gap-4">
              <h2 className="eyebrow">Rules</h2>
              <span className="numeric text-xs text-ink-600">{rules.length}</span>
            </div>

            {rules.length === 0 ? (
              <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-500">
                No rules yet. Every clip goes to the default channel.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {rules.map((rule) => (
                  <RuleRow
                    key={rule.id}
                    rule={rule}
                    channels={channels}
                    channelById={channelById}
                    busy={busy}
                    onUpdate={update}
                    onRemove={remove}
                  />
                ))}
              </div>
            )}
          </section>

          {channels.length > 0 && (
            <NewRule
              categories={categories}
              channels={channels}
              busy={busy}
              onCreate={create}
            />
          )}
        </>
      )}
    </div>
  )
}

function RuleRow({
  rule,
  channels,
  channelById,
  busy,
  onUpdate,
  onRemove,
}: {
  rule: RoutingRule
  channels: YouTubeChannel[]
  channelById: Map<string, YouTubeChannel>
  busy: boolean
  onUpdate: (ruleId: string, patch: Partial<RoutingRule>) => Promise<void>
  onRemove: (ruleId: string) => Promise<void>
}) {
  const target = channelById.get(rule.target_channel_id)
  const extras = rule.extra_channel_ids
    .map((id) => channelById.get(id))
    .filter((c): c is YouTubeChannel => Boolean(c))

  return (
    <article className="border border-ink-800 bg-ink-850/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <h3 className="font-display text-lg leading-tight text-ink-100">
              {rule.name || rule.match_keyword}
            </h3>
            <span className="numeric text-[10px] uppercase tracking-wider text-ink-600">
              priority {rule.priority}
            </span>
            {!rule.enabled && (
              <span className="text-[10px] uppercase tracking-wider text-ink-600">
                disabled
              </span>
            )}
          </div>
          <p className="mt-2 text-xs text-ink-400">
            <span className="text-ink-500">when the category contains</span>{' '}
            <span className="lowercase text-ink-200">{rule.match_keyword}</span>
          </p>
          <p className="mt-1 text-xs text-ink-400">
            <span className="text-ink-500">send it to</span>{' '}
            <span className="text-ink-200">
              {target ? target.title || target.channel_id : 'a channel that no longer exists'}
            </span>
            {extras.length > 0 && (
              <span className="text-ink-500">
                {' '}
                and {extras.length} more (fan-out)
              </span>
            )}
          </p>
        </div>

        <div className="flex shrink-0 items-baseline gap-2">
          <button
            onClick={() => void onUpdate(rule.id, { enabled: !rule.enabled })}
            disabled={busy}
            className="btn btn-quiet text-xs disabled:opacity-50"
          >
            {rule.enabled ? 'Disable' : 'Enable'}
          </button>
          <button
            onClick={() => void onRemove(rule.id)}
            disabled={busy}
            className="btn btn-quiet text-xs text-signal-bad disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-4 border-t border-ink-800 pt-4">
        <label className="block">
          <span className="eyebrow">Target</span>
          <select
            className="field mt-1 text-sm"
            value={rule.target_channel_id}
            onChange={(e) => void onUpdate(rule.id, { target_channel_id: e.target.value })}
            disabled={busy}
          >
            {!target && <option value={rule.target_channel_id}>Missing channel</option>}
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id} className="bg-ink-900">
                {channel.title || channel.channel_id}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Priority</span>
          <input
            type="number"
            className="field numeric mt-1 w-24 text-sm"
            value={rule.priority}
            onChange={(e) => void onUpdate(rule.id, { priority: Number(e.target.value) })}
            disabled={busy}
          />
        </label>

        <label className="block min-w-40 flex-1">
          <span className="eyebrow">Name</span>
          <input
            className="field mt-1 text-sm"
            value={rule.name}
            placeholder="optional"
            onChange={(e) => void onUpdate(rule.id, { name: e.target.value })}
            disabled={busy}
          />
        </label>
      </div>
    </article>
  )
}

function NewRule({
  categories,
  channels,
  busy,
  onCreate,
}: {
  categories: string[]
  channels: YouTubeChannel[]
  busy: boolean
  onCreate: (rule: {
    name: string
    match_keyword: string
    target_channel_id: string
    priority: number
    extra_channel_ids: string[]
  }) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [keyword, setKeyword] = useState('')
  const [target, setTarget] = useState(channels[0]?.id ?? '')
  const [priority, setPriority] = useState(100)

  const submit = async () => {
    if (!keyword.trim()) return
    if (!target) return
    await onCreate({
      name: name.trim(),
      match_keyword: keyword.trim(),
      target_channel_id: target,
      priority: Number.isFinite(priority) ? priority : 100,
      extra_channel_ids: [],
    })
    setName('')
    setKeyword('')
  }

  return (
    <section className="mt-10 border-t border-ink-800 pt-6">
      <h2 className="eyebrow">New rule</h2>
      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="block min-w-40 flex-1">
          <span className="eyebrow">Keyword</span>
          <input
            className="field mt-1 text-sm"
            value={keyword}
            list="routing-categories"
            placeholder="gaming"
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void submit()}
          />
          <datalist id="routing-categories">
            {categories.map((category) => (
              <option key={category} value={category} />
            ))}
          </datalist>
        </label>

        <label className="block min-w-48 flex-1">
          <span className="eyebrow">Target channel</span>
          <select
            className="field mt-1 text-sm"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id} className="bg-ink-900">
                {channel.title || channel.channel_id}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="eyebrow">Priority</span>
          <input
            type="number"
            className="field numeric mt-1 w-24 text-sm"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          />
        </label>

        <label className="block min-w-40 flex-1">
          <span className="eyebrow">Name</span>
          <input
            className="field mt-1 text-sm"
            value={name}
            placeholder="optional"
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <button
          onClick={() => void submit()}
          disabled={busy || !keyword.trim() || !target}
          className="btn btn-primary text-xs disabled:opacity-50"
        >
          Add rule
        </button>
      </div>
    </section>
  )
}
