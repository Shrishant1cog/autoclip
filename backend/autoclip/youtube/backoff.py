"""How long to wait before trying again.

A YouTube upload that fails because the connection dropped should be
tried again soon. One that fails because the API project is out of
quota should not be tried again until tomorrow, and one that fails
because the file is malformed should not be tried again at all.

So the delay grows with the number of attempts, and the cap is high
enough that a genuinely flaky connection gets several chances:

    30 s, 1 min, 2 min, 4 min, 8 min, 16 min, 32 min, 1 h, 1 h, 1 h…

The last one matters: without a cap, the tenth attempt would be sixteen
hours away, which is a punishment rather than a backoff.

A little jitter is added so that two uploads that failed at the same
moment do not come back at the same moment too.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

__all__ = [
    "BASE_DELAY_S",
    "MAX_DELAY_S",
    "MAX_ATTEMPTS",
    "next_delay_s",
    "next_attempt_at",
    "should_retry",
]

#: The first retry waits this long.
BASE_DELAY_S = 30.0

#: The longest a retry ever waits.
MAX_DELAY_S = 3600.0

#: How many attempts a row gets before it is left alone.
#:
#: The owner can always retry it by hand; this only stops the worker
#: from trying forever on its own.
MAX_ATTEMPTS = 10


def next_delay_s(attempt: int, *, jitter: bool = True) -> float:
    """The delay before attempt number ``attempt + 1``.

    ``attempt`` is how many attempts have already been made, so the
    first failure (attempt 1) waits ``BASE_DELAY_S``.
    """
    if attempt < 1:
        attempt = 1
    delay = min(BASE_DELAY_S * (2 ** (attempt - 1)), MAX_DELAY_S)
    if not jitter:
        return delay
    # Up to a fifth of the delay, so two uploads do not come back at the
    # same instant.
    return delay + random.uniform(0, delay * 0.2)


def next_attempt_at(attempt: int, *, now: datetime | None = None, jitter: bool = True) -> str:
    """When the next attempt should be made, as an ISO-8601 string."""
    now = now or datetime.now(UTC)
    return (now + timedelta(seconds=next_delay_s(attempt, jitter=jitter))).isoformat(
        timespec="seconds"
    )


def should_retry(attempt: int) -> bool:
    """True when another attempt is worth making on its own."""
    return attempt < MAX_ATTEMPTS


def is_due(next_at: str, *, now: datetime | None = None) -> bool:
    """True when the time to try again has arrived.

    An empty time means "now": a row that has never been scheduled is
    due straight away.
    """
    if not next_at:
        return True
    now = now or datetime.now(UTC)
    try:
        when = datetime.fromisoformat(next_at)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when <= now
