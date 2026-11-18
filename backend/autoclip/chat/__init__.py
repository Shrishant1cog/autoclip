"""Project-aware assistant (Phase 13).

The assistant answers questions about this AutoClip installation using a
snapshot of its real state. See :mod:`autoclip.chat.agent`.
"""

from . import agent, context

__all__ = ["agent", "context"]
