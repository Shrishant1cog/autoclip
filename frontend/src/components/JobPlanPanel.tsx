import { useEffect, useState } from 'react'

import { api, type JobBudget, type JobPlan } from '../api'

/**
 * What the job's AI allowance was, and what the plan decided.
 *
 * Two things are being shown, and both are there because the honest
 * version is the useful one:
 *
 * * **The budget**, with its refusals written down. A budget that was
 *   quietly capped reads exactly like a budget that was never needed.
 * * **The plan's source.** "The model's plan" and "the automatic
 *   choices" are different answers, and a plan that silently fell back
 *   would be indistinguishable from one the model agreed with.
 */
export function JobPlanPanel({ jobId }: { jobId: string }) {
  const [budget, setBudget] = useState<JobBudget | null>(null)
  const [plan, setPlan] = useState<JobPlan | null>(null)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let live = true
    void Promise.all([api.jobBudget(jobId), api.jobPlan(jobId)])
      .then(([loadedBudget, loadedPlan]) => {
        if (!live) return
        setBudget(loadedBudget)
        setPlan(loadedPlan)
      })
      .catch((err) => {
        if (live) setError(err as Error)
      })
    return () => {
      live = false
    }
  }, [jobId])

  if (error) {
    return <p className="text-xs text-signal-bad">{error.message}</p>
  }
  if (!budget || !plan) {
    return <p className="text-sm text-ink-500">Loading…</p>
  }

  const allowances = [
    { key: 'plan', label: 'Plan', allowance: budget.plan },
    { key: 'repair', label: 'Repair', allowance: budget.repair },
    { key: 'music', label: 'Music', allowance: budget.music },
  ]

  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow border-b border-ink-800 pb-2">AI calls</p>
        <p className="mt-2 text-xs leading-relaxed text-ink-500">
          {budget.total_used} of {budget.total_limit} used. The three allowances are separate:
          a clip choosing its music cannot use up the planning call.
        </p>

        <dl className="mt-3 space-y-1">
          {allowances.map(({ key, label, allowance }) => (
            <div key={key} className="flex items-baseline justify-between gap-3 text-sm">
              <dt className="text-ink-300">{label}</dt>
              <dd className="numeric text-ink-100">
                {allowance.used} / {allowance.max_calls}
              </dd>
            </div>
          ))}
        </dl>

        {budget.overruns.length > 0 && (
          <div className="mt-3 border-l-2 border-sodium-600 pl-4">
            <p className="text-xs text-ink-300">
              {budget.overruns.length} call{budget.overruns.length === 1 ? '' : 's'} asked for
              more than the allowance had:
            </p>
            <ul className="mt-1 space-y-1">
              {budget.overruns.map((overrun, index) => (
                <li key={`${overrun.category}-${index}`} className="text-xs leading-snug text-ink-500">
                  <span className="text-ink-300">{overrun.category}</span> — {overrun.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div>
        <p className="eyebrow border-b border-ink-800 pb-2">Plan</p>
        {plan.state === 'not planned yet' || plan.clips.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">
            No plan yet. The job has not reached the planning stage.
          </p>
        ) : (
          <>
            <p className="mt-2 text-xs leading-relaxed text-ink-500">
              {plan.source === 'ai'
                ? 'The model proposed this plan and every part of it checked out against what AutoClip can actually build.'
                : 'The automatic choices were used instead of a model plan. The reasons are below.'}
            </p>

            {plan.problems.length > 0 && (
              <ul className="mt-3 space-y-1 border-l-2 border-sodium-600 pl-4">
                {plan.problems.map((problem, index) => (
                  <li key={index} className="text-xs leading-snug text-ink-300">
                    {problem}
                  </li>
                ))}
              </ul>
            )}

            {plan.notes.length > 0 && (
              <ul className="mt-3 space-y-1">
                {plan.notes.map((note, index) => (
                  <li key={index} className="text-xs leading-snug text-ink-400">
                    {note}
                  </li>
                ))}
              </ul>
            )}

            <ul className="mt-4 space-y-2">
              {plan.clips.map((direction) => (
                <li key={direction.clip_id} className="border border-ink-800 p-3">
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-400">
                    <span className="text-ink-200">{direction.layout}</span>
                    <span>crop: {direction.crop}</span>
                    {direction.caption_strategy && (
                      <span>caption: {direction.caption_strategy}</span>
                    )}
                    {direction.ducking_db !== 0 && (
                      <span className="numeric">ducking {direction.ducking_db.toFixed(1)} dB</span>
                    )}
                    <span>transition: {direction.transition}</span>
                  </div>
                  {direction.reason && (
                    <p className="mt-1.5 text-xs leading-snug text-ink-500">{direction.reason}</p>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
