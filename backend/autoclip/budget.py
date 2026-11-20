"""How many AI calls a job is allowed to make.

AutoClip's creative layer runs on a fixed, small budget, and the budget is
written down here rather than being discovered at runtime:

* **one** creative-planning call,
* **one** repair retry for that call,
* **up to one** music-selection call per eligible clip, capped by the clip
  count.

With the default of ten clips that is twelve calls in total, and no more,
whatever the model asks for.

Two things make the budget more than a counter.

**A refusal is recorded.** A job that wanted a thirteenth call and did not
get one writes down the reason. A silently capped budget reads exactly
like a budget that was never needed, and the user is left unable to tell
the difference.

**The budget survives a retry.** The counters live in the database and are
loaded when a job resumes, so retrying a failed job does not hand it a
fresh allowance. Spending twice because something went wrong is how a
cost control stops being a cost control.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

__all__ = [
    "CallBudget",
    "JobBudget",
    "budget_for",
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class CallBudget:
    """One category of AI calls.

    ``take()`` is the only way to spend: it returns ``False`` when the
    budget is gone, so a caller cannot accidentally go over by forgetting
    to check first.
    """

    max_calls: int
    used: int = 0
    #: Why a call was refused, in plain words.
    overruns: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.used)

    @property
    def spent(self) -> bool:
        return self.used >= self.max_calls

    def take(self, reason: str = "") -> bool:
        """Reserve one call. Returns ``False`` when the budget is spent."""
        if self.used >= self.max_calls:
            if reason:
                self.overruns.append(reason)
            return False
        self.used += 1
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "max_calls": self.max_calls,
            "used": self.used,
            "remaining": self.remaining,
        }


@dataclass
class JobBudget:
    """Every AI call one job is allowed to make.

    The three categories are separate because they are spent for different
    reasons: a plan call and its repair happen once, while music calls
    happen once per clip. Spending the music allowance must not stop the
    plan, and a failed plan must not eat the clips' music calls.
    """

    job_id: str = ""
    plan: CallBudget = field(default_factory=lambda: CallBudget(1))
    repair: CallBudget = field(default_factory=lambda: CallBudget(1))
    music: CallBudget = field(default_factory=lambda: CallBudget(0))
    #: Set when the user explicitly raised the budget for this job.
    user_approved_overrides: int = 0
    updated_at: str = ""

    # -- construction ----------------------------------------------------

    @classmethod
    def for_job(cls, job_id: str, *, max_clips: int) -> JobBudget:
        """The approved budget for a job that may produce ``max_clips`` clips."""
        return cls(
            job_id=job_id,
            plan=CallBudget(1),
            repair=CallBudget(1),
            music=CallBudget(max(0, int(max_clips))),
        )

    # -- spending --------------------------------------------------------

    def take_plan(self, reason: str = "") -> bool:
        """Reserve the one creative-planning call."""
        return self.plan.take(reason or "the creative-planning call was already used")

    def take_repair(self, reason: str = "") -> bool:
        """Reserve the one repair retry."""
        return self.repair.take(reason or "the repair retry was already used")

    def take_music(self, reason: str = "") -> bool:
        """Reserve one music-selection call."""
        return self.music.take(reason or "the music-selection budget was spent")

    @property
    def total_limit(self) -> int:
        return self.plan.max_calls + self.repair.max_calls + self.music.max_calls

    @property
    def total_used(self) -> int:
        return self.plan.used + self.repair.used + self.music.used

    @property
    def remaining(self) -> int:
        return max(0, self.total_limit - self.total_used)

    @property
    def overruns(self) -> list[str]:
        """Every refusal, in the order they happened."""
        return [*self.plan.overruns, *self.repair.overruns, *self.music.overruns]

    def overrun_records(self) -> list[dict[str, str]]:
        """Every refusal, with the category it belongs to."""
        records: list[dict[str, str]] = []
        for category, budget in (
            ("plan", self.plan),
            ("repair", self.repair),
            ("music", self.music),
        ):
            for reason in budget.overruns:
                records.append({"category": category, "reason": reason})
        return records

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "plan": self.plan.to_dict(),
            "repair": self.repair.to_dict(),
            "music": self.music.to_dict(),
            "total_limit": self.total_limit,
            "total_used": self.total_used,
            "remaining": self.remaining,
            # The records carry the category, so the user can see *which*
            # allowance ran out and not just that something did.
            "overruns": self.overrun_records(),
            "user_approved_overrides": self.user_approved_overrides,
            "updated_at": self.updated_at,
        }

    def to_row(self) -> dict[str, object]:
        """The flat shape the database table stores."""
        return {
            "job_id": self.job_id,
            "plan_limit": self.plan.max_calls,
            "plan_used": self.plan.used,
            "repair_limit": self.repair.max_calls,
            "repair_used": self.repair.used,
            "music_limit": self.music.max_calls,
            "music_used": self.music.used,
            "overruns": self.overrun_records(),
            "user_approved_overrides": self.user_approved_overrides,
            "updated_at": _now(),
        }

    @classmethod
    def from_row(cls, row: object) -> JobBudget:
        """Rebuild a budget from a database row.

        The overrun column holds JSON, but the method also accepts the
        already-decoded list, so ``from_row(to_row())`` is a round trip
        rather than a special case.
        """
        import json

        raw_overruns = row["overruns"]  # type: ignore[index]
        if isinstance(raw_overruns, list):
            overruns = list(raw_overruns)
        else:
            try:
                overruns = json.loads(raw_overruns) if raw_overruns else []
            except (TypeError, ValueError):
                overruns = []
        if not isinstance(overruns, list):
            overruns = []

        budget = cls(
            job_id=str(row["job_id"]),  # type: ignore[index]
            plan=CallBudget(
                max_calls=int(row["plan_limit"]),  # type: ignore[index]
                used=int(row["plan_used"]),  # type: ignore[index]
            ),
            repair=CallBudget(
                max_calls=int(row["repair_limit"]),  # type: ignore[index]
                used=int(row["repair_used"]),  # type: ignore[index]
            ),
            music=CallBudget(
                max_calls=int(row["music_limit"]),  # type: ignore[index]
                used=int(row["music_used"]),  # type: ignore[index]
            ),
            user_approved_overrides=int(row["user_approved_overrides"]),  # type: ignore[index]
            updated_at=str(row["updated_at"]),  # type: ignore[index]
        )

        categories = {
            "plan": budget.plan,
            "repair": budget.repair,
            "music": budget.music,
        }
        for record in overruns:
            if not isinstance(record, dict):
                continue
            reason = str(record.get("reason") or "")
            if not reason:
                continue
            category = str(record.get("category") or "")
            target = categories.get(category)
            if target is None:
                # An unknown category is still a refusal the user should see.
                target = budget.plan
            target.overruns.append(reason)
        return budget

    def save(self) -> None:
        """Write the counters down, so a retry does not get a fresh budget."""
        from .db import budget_store

        budget_store.save(self)


def budget_for(job_id: str, *, max_clips: int) -> JobBudget:
    """The budget for a job, loaded from the database if it already has one.

    A job that has never run gets the approved budget. A job that is
    being retried keeps the counters it had, because spending twice
    because something went wrong is how a cost control stops being one.
    """
    from .db import budget_store

    existing = budget_store.load(job_id)
    if existing is not None:
        return existing
    return JobBudget.for_job(job_id, max_clips=max_clips)
