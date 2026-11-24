/**
 * MeowPower — the simple face of the processing pipeline.
 *
 * A job does six technical things: it extracts audio, transcribes it, finds
 * the highlights, reframes the video, times the captions and renders the
 * clips. That list is the pipeline's own vocabulary, and it is the wrong
 * thing to put in front of somebody who pasted a link and wants a clip.
 *
 * MeowPower is what the user sees instead: one line, in words, saying what
 * is happening right now; one number saying how far along it is; and
 * nothing else. The technical stages are still there — they are one
 * disclosure away — because somebody diagnosing a slow job needs them, but
 * nobody should have to read them to use the product.
 *
 * The mapping from stage to sentence lives in `PHRASES`, and it is the only
 * place the two vocabularies meet.
 */

/** The pipeline's stages, and what each one is called in plain words. */
const PHRASES: Record<string, string> = {
  prepare: 'Getting the video ready',
  transcribe: 'Listening to what is being said',
  highlights: 'Picking out the moments worth keeping',
  reframe: 'Finding the face and framing the shot',
  captions: 'Writing the subtitles',
  export: 'Rendering your clips',
}

const FALLBACK = 'Working on it'

export interface MeowPowerProps {
  /** The pipeline's current stage, or an empty string before it starts. */
  stage: string
  /** Overall completion, 0–1. */
  progress: number
  /** The job's status. */
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
}

export function MeowPower({ stage, progress, status }: MeowPowerProps) {
  const percent = Math.round(Math.min(1, Math.max(0, progress)) * 100)

  const headline = (() => {
    if (status === 'queued') return 'MeowPower is waking up'
    if (status === 'done') return 'MeowPower is done'
    if (status === 'failed') return 'MeowPower hit a snag'
    if (status === 'cancelled') return 'MeowPower stopped'
    return PHRASES[stage] ?? FALLBACK
  })()

  const subline = (() => {
    if (status === 'queued') return 'One moment — nothing to do yet.'
    if (status === 'done') return 'Your clips are ready to review.'
    if (status === 'failed') return 'The details are below.'
    if (status === 'cancelled') return 'The details are below.'
    return 'You can leave this page. It keeps working.'
  })()

  const tone =
    status === 'failed'
      ? 'text-signal-bad'
      : status === 'done'
        ? 'text-signal-good'
        : 'text-sodium-500'

  return (
    <section className="rise max-w-3xl" aria-live="polite">
      <p className="eyebrow">MeowPower</p>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-8 gap-y-4">
        <h2 className="font-display text-[clamp(1.75rem,4vw,2.75rem)] leading-tight text-ink-100">
          {headline}
        </h2>
        <span className={`numeric font-display text-[clamp(1.5rem,3vw,2rem)] leading-none ${tone}`}>
          {percent}
          <span className="text-ink-600">%</span>
        </span>
      </div>

      <p className="mt-3 text-sm text-ink-500">{subline}</p>

      {/* One rule, filling. The number above already says how far along it
          is; the rule is the shape of that number, not a second reading of
          it. */}
      <div className="mt-6 h-px w-full bg-ink-800" role="presentation">
        <div
          className="h-px origin-left bg-sodium-500 transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
          style={{ transform: `scaleX(${percent / 100})` }}
        />
      </div>
    </section>
  )
}
