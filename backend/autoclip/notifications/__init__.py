"""Notification centre (Phase 14).

A local inbox of pipeline events. Nothing is pushed anywhere — the rows live
in the AutoClip database and the UI polls them. See
:mod:`autoclip.notifications.events`.
"""

from . import events

__all__ = ["events"]
