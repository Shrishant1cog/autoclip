import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { api, type SystemStatus, type YouTubeStatus } from './api'

/**
 * Application shell.
 *
 * A masthead rather than a sidebar: this is a four-screen tool, and a
 * persistent nav rail would spend a fifth of the width restating that.
 */
export function App() {
  const [system, setSystem] = useState<SystemStatus | null>(null)

  useEffect(() => {
    api.system().then(setSystem).catch(() => setSystem(null))
  }, [])

  return (
    <div className="min-h-screen bg-ink-900">
      <header className="border-b border-ink-800">
        <div className="mx-auto flex max-w-[1600px] items-baseline gap-8 px-6 py-4 lg:px-10">
          <NavLink to="/" className="group flex items-baseline gap-2.5">
            <span className="font-display text-2xl leading-none text-ink-100">
              Auto<span className="italic text-sodium-500">Clip</span>
            </span>
          </NavLink>

          <nav className="flex items-baseline gap-6">
            <TopLink to="/" end>
              New
            </TopLink>
            <TopLink to="/clips">Clips</TopLink>
            <TopLink to="/workflows">Workflows</TopLink>
            <TopLink to="/settings">Settings</TopLink>
          </nav>

          <div className="ml-auto flex items-baseline gap-5">
            <YouTubeControls />
            {system && <SystemBadge system={system} />}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 pb-24 lg:px-10">
        <Outlet />
      </main>
    </div>
  )
}

/**
 * YouTube connection and the automation switch that sits beside it.
 *
 * The popup is opened synchronously on click (before the network call), because
 * browsers only allow window.open during the user gesture. The opener polls the
 * status endpoint while the popup is open; the callback page closes itself.
 */
function YouTubeControls() {
  const [status, setStatus] = useState<YouTubeStatus | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pollRef = useRef<number | null>(null)

  const refresh = useCallback(() => {
    api
      .youtubeStatus()
      .then(setStatus)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    // Keep the header honest when uploads happen while the app sits open.
    const id = window.setInterval(refresh, 20000)
    return () => {
      window.clearInterval(id)
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [refresh])

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const connect = async () => {
    setError('')
    setBusy(true)
    const popup = window.open('', 'autoclip-youtube', 'width=560,height=760')
    try {
      const { auth_url } = await api.youtubeConnect()
      if (popup) {
        popup.location.href = auth_url
      } else {
        // Popup blocked: fall back to the same tab so sign-in still works.
        window.location.href = auth_url
        return
      }

      stopPolling()
      pollRef.current = window.setInterval(async () => {
        try {
          const next = await api.youtubeStatus()
          if (next.connected) {
            stopPolling()
            setStatus(next)
            setBusy(false)
            popup.close()
          } else if (popup.closed) {
            stopPolling()
            setBusy(false)
            refresh()
          }
        } catch {
          /* transient; the next tick retries */
        }
      }, 1500)
    } catch (e) {
      popup?.close()
      setBusy(false)
      setError(e instanceof Error ? e.message : 'Could not start the YouTube sign-in.')
    }
  }

  const toggle = async () => {
    if (!status) return
    setError('')
    setBusy(true)
    try {
      setStatus(await api.setYouTubeAuto(!status.auto_upload))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change automation.')
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null

  const connected = status.connected
  const label = connected ? status.channel_title || 'YouTube connected' : 'Connect YouTube channel'

  return (
    <div className="flex items-center gap-3">
      {error && (
        <span className="hidden max-w-56 truncate text-xs text-signal-bad lg:inline" title={error}>
          {error}
        </span>
      )}

      {connected && status.channel_url ? (
        <a
          href={status.channel_url}
          target="_blank"
          rel="noreferrer"
          title={`Connected as ${status.channel_title || 'your channel'}`}
          className="flex items-center gap-2 rounded-md border border-ink-700 px-3 py-1.5 text-xs font-medium text-ink-200 transition-colors hover:border-ink-500 hover:text-ink-100"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-signal-good" />
          <span className="max-w-40 truncate">{label}</span>
        </a>
      ) : (
        <button
          type="button"
          onClick={() => {
            if (!status.configured) {
              window.location.href = '/settings'
              return
            }
            void connect()
          }}
          disabled={busy}
          title={
            status.configured
              ? 'Sign in with Google to connect a YouTube channel'
              : 'Add your Google OAuth client in Settings first'
          }
          className="rounded-md bg-sodium-500 px-3 py-1.5 text-xs font-semibold text-ink-900 transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {status.configured ? label : 'Set up YouTube'}
        </button>
      )}

      <button
        type="button"
        role="switch"
        aria-checked={status.auto_upload}
        aria-label="Auto-upload exports to YouTube"
        disabled={!connected || busy}
        onClick={() => void toggle()}
        title={
          connected
            ? status.auto_upload
              ? 'Auto-upload is on: every finished clip is published to YouTube'
              : 'Auto-upload is off: clips stay local until you publish them'
            : 'Connect a YouTube channel to enable auto-upload'
        }
        className={[
          'flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs transition-colors',
          status.auto_upload
            ? 'border-sodium-500/60 bg-sodium-500/10 text-sodium-400'
            : 'border-ink-700 text-ink-400 hover:text-ink-200',
          !connected ? 'cursor-not-allowed opacity-50' : '',
        ].join(' ')}
      >
        <span
          className={[
            'relative inline-flex h-3.5 w-6 items-center rounded-full transition-colors',
            status.auto_upload ? 'bg-sodium-500' : 'bg-ink-700',
          ].join(' ')}
        >
          <span
            className={[
              'absolute h-2.5 w-2.5 rounded-full bg-ink-900 transition-transform',
              status.auto_upload ? 'translate-x-3' : 'translate-x-0.5',
            ].join(' ')}
          />
        </span>
        Auto-upload
      </button>
    </div>
  )
}

function TopLink({
  to,
  end,
  children,
}: {
  to: string
  end?: boolean
  children: React.ReactNode
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        [
          'text-sm font-medium transition-colors duration-200',
          isActive ? 'text-sodium-500' : 'text-ink-400 hover:text-ink-200',
        ].join(' ')
      }
    >
      {children}
    </NavLink>
  )
}

/**
 * Compact machine status.
 *
 * Surfaced permanently rather than hidden in settings because the two things it
 * reports — whether ffmpeg can render, and whether the GPU is being used — are
 * the two that change how long everything takes.
 */
function SystemBadge({ system }: { system: SystemStatus }) {
  const accel = system.accel.toUpperCase()
  return (
    <div className="hidden items-baseline gap-4 text-xs md:flex">
      <span className="numeric text-ink-400">
        {accel}
        {system.gpu_name && accel === 'CUDA' && (
          <span className="text-ink-600"> · {system.gpu_name.replace('NVIDIA GeForce ', '')}</span>
        )}
      </span>
      <span
        className={system.ready ? 'text-ink-400' : 'text-signal-bad'}
        title={system.ready ? 'All required components present' : 'Run autoclip doctor'}
      >
        {system.ready ? 'ready' : 'not ready'}
      </span>
    </div>
  )
}
