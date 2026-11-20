"""M3 — the AI call budget.

The budget is the promise that AutoClip does not spend more money than it
said it would. These tests check the three things that make it a promise
rather than a counter:

* the **three allowances are separate** — spending the music calls cannot
  stop the planning call;
* a **refusal is recorded**, because a silently capped budget reads
  exactly like a budget that was never needed;
* the counters **survive a retry**, because spending twice because
  something went wrong is how a cost control stops being one.
"""

from __future__ import annotations

import pytest
from autoclip.budget import CallBudget, JobBudget, budget_for
from autoclip.db import budget_store

# --------------------------------------------------------------------------
# The arithmetic
# --------------------------------------------------------------------------


def test_the_default_budget_is_twelve_calls_at_ten_clips() -> None:
    """One plan, one repair, and one music call per clip."""
    budget = JobBudget.for_job("job1", max_clips=10)

    assert budget.plan.max_calls == 1
    assert budget.repair.max_calls == 1
    assert budget.music.max_calls == 10
    assert budget.total_limit == 12


def test_the_budget_follows_the_clip_count() -> None:
    assert JobBudget.for_job("job1", max_clips=3).total_limit == 5
    assert JobBudget.for_job("job1", max_clips=0).total_limit == 2
    assert JobBudget.for_job("job1", max_clips=-5).music.max_calls == 0


def test_spending_the_music_allowance_cannot_stop_the_plan() -> None:
    """The three allowances are spent for different reasons.

    A job with ten clips spends ten music calls. That must not eat the
    planning call, which happens once for the whole job.
    """
    budget = JobBudget.for_job("job1", max_clips=10)

    for _ in range(10):
        assert budget.take_music() is True
    assert budget.take_music() is False

    assert budget.plan.used == 0
    assert budget.take_plan() is True
    assert budget.take_repair() is True


def test_the_plan_allowance_is_one_call() -> None:
    budget = JobBudget.for_job("job1", max_clips=10)

    assert budget.take_plan() is True
    assert budget.take_plan() is False
    assert budget.plan.used == 1


def test_a_refusal_is_recorded_with_its_reason() -> None:
    """A silently capped budget reads like a budget that was never needed."""
    budget = JobBudget.for_job("job1", max_clips=1)

    assert budget.take_music("the first clip") is True
    assert budget.take_music("the second clip needed a call too") is False

    assert budget.music.overruns == ["the second clip needed a call too"]
    assert budget.total_used == 1


def test_the_overruns_carry_the_category_they_belong_to() -> None:
    budget = JobBudget.for_job("job1", max_clips=0)

    budget.take_plan()
    budget.take_plan("the planning call was already used")
    budget.take_music("the music allowance was spent")

    records = budget.overrun_records()
    assert {record["category"] for record in records} == {"plan", "music"}
    assert all(record["reason"] for record in records)


def test_a_refusal_without_a_reason_is_still_a_refusal() -> None:
    budget = CallBudget(max_calls=0)

    assert budget.take() is False
    assert budget.overruns == []


def test_remaining_never_goes_negative() -> None:
    budget = CallBudget(max_calls=2)

    budget.take()
    budget.take()
    budget.take()

    assert budget.remaining == 0
    assert budget.spent is True


# --------------------------------------------------------------------------
# The persistence
# --------------------------------------------------------------------------


def test_a_budget_is_saved_and_loaded(initialised_db: int) -> None:
    budget = JobBudget.for_job("job1", max_clips=4)
    budget.take_plan()
    budget.take_music()
    budget.save()

    loaded = budget_store.load("job1")

    assert loaded is not None
    assert loaded.plan.used == 1
    assert loaded.music.used == 1
    assert loaded.music.max_calls == 4


def test_a_retry_does_not_get_a_fresh_allowance(initialised_db: int) -> None:
    """The counters live in the database, so a retry keeps them.

    Spending twice because something went wrong is how a cost control
    stops being a cost control.
    """
    first = budget_for("job1", max_clips=10)
    first.take_plan()
    first.take_music()
    first.save()

    # The job is retried: the same job id, the same budget.
    second = budget_for("job1", max_clips=10)

    assert second.plan.used == 1
    assert second.music.used == 1
    assert second.take_plan() is False


def test_a_job_that_has_never_run_gets_the_approved_budget(initialised_db: int) -> None:
    budget = budget_for("fresh", max_clips=10)

    assert budget.total_limit == 12
    assert budget.total_used == 0


def test_the_overrun_reasons_survive_the_round_trip(initialised_db: int) -> None:
    budget = JobBudget.for_job("job1", max_clips=0)
    budget.take_plan()
    budget.take_plan("the planning call was already used")
    budget.save()

    loaded = budget_store.load("job1")

    assert loaded is not None
    assert loaded.plan.overruns == ["the planning call was already used"]
    assert loaded.overrun_records() == [
        {"category": "plan", "reason": "the planning call was already used"}
    ]


def test_the_row_round_trip_keeps_the_counters(initialised_db: int) -> None:
    budget = JobBudget.for_job("job1", max_clips=6)
    budget.take_repair()

    restored = JobBudget.from_row(budget.to_row())

    assert restored.job_id == "job1"
    assert restored.repair.used == 1
    assert restored.music.max_calls == 6


def test_a_broken_overrun_column_does_not_break_the_load(initialised_db: int) -> None:
    budget = JobBudget.for_job("job1", max_clips=2)
    budget.save()

    from autoclip.db import connection

    with connection() as conn:
        conn.execute(
            "UPDATE job_ai_budget SET overruns = ? WHERE job_id = ?",
            ("not json at all", "job1"),
        )

    loaded = budget_store.load("job1")

    assert loaded is not None
    assert loaded.overruns == []
    assert loaded.plan.used == 0


def test_a_budget_for_a_job_that_does_not_exist_is_none(initialised_db: int) -> None:
    assert budget_store.load("never-seen") is None


def test_the_budgets_can_be_listed(initialised_db: int) -> None:
    JobBudget.for_job("job1", max_clips=2).save()
    JobBudget.for_job("job2", max_clips=3).save()

    budgets = budget_store.list_budgets()

    assert {budget.job_id for budget in budgets} == {"job1", "job2"}


@pytest.mark.parametrize("field", ["plan", "repair", "music"])
def test_every_allowance_is_refused_when_it_is_spent(field: str) -> None:
    budget = JobBudget.for_job("job1", max_clips=1)

    taken = getattr(budget, f"take_{field}")
    assert taken() is True
    assert taken() is False
