import { ApiError } from '../api'

/**
 * A failure and, where the server offered one, the fix.
 *
 * The hint carries most of the value: "YouTube blocked this download" is a
 * dead end, while "set a browser to pull cookies from" is something the user
 * can act on without leaving the app.
 *
 * When the server says the failure is retryable, a retry button appears — the
 * user asked for the action, so it is theirs to trigger.
 */
export function ErrorNote({
  error,
  onDismiss,
  onRetry,
  retrying,
}: {
  error: Error
  onDismiss?: () => void
  onRetry?: () => void
  retrying?: boolean
}) {
  const hint = error instanceof ApiError ? error.hint : ''
  const code = error instanceof ApiError ? error.code : ''
  const retryable = error instanceof ApiError ? error.retryable : false
  const showRetry = Boolean(onRetry) && (retryable || !code)

  return (
    <div className="border-l-2 border-signal-bad pl-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm font-medium text-ink-100">{error.message}</p>
        <div className="flex shrink-0 items-baseline gap-3">
          {showRetry && (
            <button
              onClick={onRetry}
              disabled={retrying}
              className="btn btn-quiet text-xs disabled:opacity-50"
            >
              {retrying ? 'Retrying…' : 'Try again'}
            </button>
          )}
          {onDismiss && (
            <button onClick={onDismiss} className="btn btn-quiet shrink-0" aria-label="Dismiss">
              ✕
            </button>
          )}
        </div>
      </div>
      {hint && (
        <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-ink-400">
          {hint}
        </p>
      )}
      {code && (
        <p className="mt-2 text-[10px] uppercase tracking-wider text-ink-600">
          {code}
          {retryable ? ' · retryable' : ''}
        </p>
      )}
    </div>
  )
}
