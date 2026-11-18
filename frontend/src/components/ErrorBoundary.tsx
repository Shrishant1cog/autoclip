import { Component, type ErrorInfo, type ReactNode } from 'react'
import { isRouteErrorResponse, useRouteError } from 'react-router-dom'

/**
 * A crash boundary.
 *
 * A render error in one screen used to leave a blank page with no way back.
 * This catches it, shows what happened, and offers a way out — reload or
 * return to the library.
 *
 * There are two boundaries, because React Router catches route errors before
 * an outer React boundary ever sees them:
 *
 * * :func:`RouteError` is the router's ``errorElement`` — it handles a screen
 *   that crashed while rendering.
 * * :class:`ErrorBoundary` wraps the whole router — it handles a crash in
 *   the router itself, or anywhere outside the route tree.
 *
 * Both show the same screen, so a crash looks the same wherever it happens.
 */

interface CrashScreenProps {
  title: string
  detail: string
}

/** The shared crash presentation. */
export function CrashScreen({ title, detail }: CrashScreenProps) {
  return (
    <div className="mx-auto max-w-2xl px-6 pt-24">
      <p className="eyebrow">Something broke</p>
      <h1 className="mt-2 font-display text-3xl leading-none text-ink-100">{title}</h1>
      <p className="mt-4 text-sm leading-relaxed text-ink-300">
        The rest of AutoClip is still running — your jobs, clips and uploads are
        unaffected. Reload the page, or go back to the library.
      </p>
      {detail && (
        <pre className="mt-5 max-h-48 overflow-auto border border-ink-800 bg-ink-850/50 p-3 text-xs leading-relaxed text-ink-400">
          {detail}
        </pre>
      )}
      <div className="mt-6 flex gap-3">
        <button onClick={() => window.location.reload()} className="btn btn-primary">
          Reload
        </button>
        <a href="/" className="btn btn-ghost">
          Back to AutoClip
        </a>
      </div>
    </div>
  )
}

/**
 * The router's error element.
 *
 * React Router hands the thrown value to this component, so it knows both
 * what failed and whether the failure was a thrown error or a bad response.
 */
export function RouteError() {
  const error = useRouteError()

  if (isRouteErrorResponse(error)) {
    return (
      <CrashScreen
        title="This screen could not be shown"
        detail={`${error.status} ${error.statusText}${
          typeof error.data === 'string' ? ` — ${error.data}` : ''
        }`}
      />
    )
  }

  const detail = error instanceof Error ? error.message : String(error ?? 'Unknown error.')
  return <CrashScreen title="This screen could not be shown" detail={detail} />
}

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('AutoClip UI crashed:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <CrashScreen
        title="AutoClip could not start"
        detail={error.message}
      />
    )
  }
}
