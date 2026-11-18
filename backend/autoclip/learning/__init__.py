"""Learning engine (Phase 11).

AutoClip gets better at picking clips the same way a human editor does: by
looking at what was kept, what was thrown away, and what was said about it.

Three pieces:

* :mod:`analytics` — honest outcome counts (score bands, per-channel).
* :mod:`improve` — a human-editable feedback file (``improve.txt``) that is
  injected into the highlight prompt, plus per-channel metadata feedback
  (``channels/<channel_id>.md``) for upload titles.
* ``api/learning.py`` — HTTP surface for the UI.

Nothing here fabricates performance data: until real YouTube analytics are
connected (quota-gated), learning is driven by the user's own keep/discard/
trim decisions and validation outcomes.
"""

from . import analytics, improve

__all__ = ["analytics", "improve"]
