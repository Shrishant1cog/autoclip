"""Instagram Platform publishing.

A separate package from ``autoclip.youtube`` on purpose: the two
platforms have different APIs, different limits and different failure
modes, and the spec requires them to be independent. Nothing in this
package imports the YouTube one, and nothing in the YouTube one imports
this.

The modules are:

``accounts``
    The Instagram accounts this install publishes to, and their tokens.
``oauth``
    The three sign-in flows Meta supports, and the token each one gives.
``media``
    Measuring a rendered file against Instagram's documented limits.
``publisher``
    The Graph calls: container, upload, status, publish, read-back.
``uploads``
    The orchestration, the duplicate prevention and the retry.
``queue``
    The worker, which is separate from the YouTube one.
``errors``
    Meta's error codes, and what AutoClip does about each one.
"""

from __future__ import annotations

__all__ = [
    "accounts",
    "errors",
    "media",
    "oauth",
    "publisher",
    "queue",
    "uploads",
]
