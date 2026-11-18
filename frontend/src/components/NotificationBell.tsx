/**
 * The notification bell.
 *
 * The pipeline runs unattended for minutes at a time, so something has to say
 * what happened while the user was away. The bell lives in the masthead with
 * an unread count; the panel below it lists the inbox, newest first, and each
 * row links to the thing it is about.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type Notification } from '../api'

const SEVERITY_DOT: Record<string, string> = {
  info: 'bg-ink-500',
  success: 'bg-signal-good',
  warning: 'bg-signal-warn',
  error: 'bg-signal-bad',
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()

  const refresh = useCallback(async () => {
    try {
      const [rows, count] = await Promise.all([
        api.listNotifications(50),
        api.unreadNotificationCount(),
      ])
      setItems(rows)
      setUnread(count.unread)
    } catch {
      /* transient; the next tick retries */
    }
  }, [])

  useEffect(() => {
    void refresh()
    // The pipeline writes notifications from background workers, so the badge
    // has to be polled — there is no push channel in a local-first app.
    const id = window.setInterval(refresh, 5000)
    return () => window.clearInterval(id)
  }, [refresh])

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const openItem = async (item: Notification) => {
    if (!item.read) {
      try {
        await api.markNotificationRead(item.id)
      } catch {
        /* the count refreshes on the next poll regardless */
      }
    }
    setOpen(false)
    void refresh()
    if (item.link) navigate(item.link)
  }

  const markAll = async () => {
    try {
      await api.markAllNotificationsRead()
      await refresh()
    } catch {
      /* transient */
    }
  }

  const clearRead = async () => {
    try {
      await api.clearReadNotifications()
      await refresh()
    } catch {
      /* transient */
    }
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label={unread > 0 ? `Notifications (${unread} unread)` : 'Notifications'}
        aria-expanded={open}
        title="Notifications"
        className="relative flex size-8 items-center justify-center rounded-md border border-ink-700 text-ink-300 transition-colors hover:border-ink-500 hover:text-ink-100"
      >
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.7">
          <path
            d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {unread > 0 && (
          <span className="numeric absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full bg-sodium-500 px-1 text-[10px] font-semibold leading-4 text-ink-900">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-96 border border-ink-700 bg-ink-850 shadow-2xl">
          <div className="flex items-baseline justify-between border-b border-ink-700 px-4 py-3">
            <h2 className="eyebrow">Notifications</h2>
            <div className="flex items-baseline gap-3">
              {unread > 0 && (
                <button
                  onClick={() => void markAll()}
                  className="text-xs text-ink-400 underline-offset-4 hover:text-ink-100 hover:underline"
                >
                  Mark all read
                </button>
              )}
              <button
                onClick={() => void clearRead()}
                className="text-xs text-ink-400 underline-offset-4 hover:text-ink-100 hover:underline"
              >
                Clear read
              </button>
            </div>
          </div>

          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-ink-500">
                Nothing yet. Events from your pipeline land here.
              </p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => void openItem(item)}
                  className={[
                    'block w-full border-b border-ink-800 px-4 py-3 text-left transition-colors hover:bg-ink-800/60',
                    item.read ? 'opacity-60' : '',
                  ].join(' ')}
                >
                  <div className="flex items-start gap-2.5">
                    <span
                      className={[
                        'mt-1.5 size-1.5 shrink-0 rounded-full',
                        SEVERITY_DOT[item.severity] ?? SEVERITY_DOT.info,
                      ].join(' ')}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-ink-100">{item.title}</span>
                      {item.body && (
                        <span className="mt-0.5 block text-xs leading-snug text-ink-400">
                          {item.body}
                        </span>
                      )}
                      <span className="mt-1 block text-[10px] uppercase tracking-wider text-ink-600">
                        {relativeTime(item.created_at)}
                      </span>
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
