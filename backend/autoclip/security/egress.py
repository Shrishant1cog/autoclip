"""The single door every governed outbound request goes through.

The rule this module enforces is short: **nothing leaves the machine without
passing through here**, and nothing passes through here without its
destination being classified, its consent being checked, and the attempt being
recorded.

Two shapes of call are supported, because the callers are not uniform:

* :meth:`EgressGateway.authorize` — a permit for code that makes the request
  itself. The provider SDKs are used like this: rewriting them to speak HTTP
  would mean re-implementing retry, streaming and auth for four vendors.
* :meth:`EgressGateway.fetch` — a complete HTTP GET, for the callers that are
  already plain HTTP (the model download, the trending chart). This path goes
  through :mod:`autoclip.security.urlpolicy`, so redirects, DNS changes and
  address classification are all checked on every hop.

What is deliberately *not* here: a fallback. If a transfer is refused, the
caller is told so and decides what to do. Silently sending the data somewhere
else — a different provider, a different host — would defeat the point of
asking.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import consent as consent_module
from . import urlpolicy

__all__ = [
    "EgressError",
    "EgressGateway",
    "MemoryLogSink",
    "Permit",
    "Transfer",
    "redact",
]


class EgressError(RuntimeError):
    """A transfer was refused or failed in a way the caller must handle."""


#: Patterns that match a credential and capture its value. The value is
#: replaced entirely: a partial mask still leaks the tail of a key, and a
#: secret that appears in a log line is compromised whether or not its last
#: four characters are readable.
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+([^\s,;&\"'()]+)"),
    re.compile(
        r"(?i)\b(authorization|api[-_]?key|x-goog-api-key|x-api-key|"
        r"access[-_]?token|refresh[-_]?token|client[-_]?secret|password|secret|token)"
        r"\b\s*[:=]\s*([^\s,;&\"'()]+)"
    ),
)

#: The mask itself. Eight characters, so its length does not reveal the
#: length of what it replaced.
_MASK = "*" * 8


def redact(text: str, *, keep: int = 0) -> str:
    """Mask anything that looks like a credential in ``text``.

    Used on URLs (query strings carry tokens more often than anyone would
    like) and on error bodies that a provider echoes back.

    ``keep`` is offered for callers that want a short fingerprint of the
    original value; the default is zero, which masks it completely.
    """
    if not text:
        return text
    redacted = text
    for pattern in _CREDENTIAL_PATTERNS:

        def _mask(match: re.Match[str]) -> str:
            label, value = match.group(1), match.group(2)
            # "Authorization: Bearer <token>" — the bearer pattern already
            # masked the token; masking the word "Bearer" as well would hide
            # the fact that a bearer token was used.
            if value.lower() == "bearer":
                return match.group(0)
            tail = value[-keep:] if keep and len(value) > keep else ""
            separator = match.group(0)[len(label) : len(match.group(0)) - len(value)]
            return f"{label}{separator}{_MASK}{tail}"

        redacted = pattern.sub(_mask, redacted)
    return redacted


def _safe_url(url: str) -> str:
    """A URL with its query string removed and its path shortened.

    The host and scheme are the useful part of a log line; the query string is
    where tokens hide.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact(url)
    if not parts.scheme:
        return redact(url)
    path = parts.path if len(parts.path) <= 80 else parts.path[:77] + "..."
    return f"{parts.scheme}://{parts.netloc}{path}"


@dataclass(frozen=True)
class Transfer:
    """One outbound request, described well enough to be judged.

    ``data_summary`` says *what* leaves, in words the user can read. It is
    never the content itself — the log records that a transcript went out, not
    the transcript.
    """

    operation: str
    url: str
    data_summary: str
    provider: str = ""
    #: Whether the operation needs a stored consent decision. Operations that
    #: carry no user content (model downloads, the trending chart) are logged
    #: but not gated; operations that carry user content are gated.
    requires_consent: bool = True
    #: Set by the caller when the user has *already* made this transfer
    #: deliberately — configuring the provider, choosing the external engine.
    #: A configured transfer to a public host is allowed and recorded on first
    #: use; a private host is never allowed this way.
    configured: bool = False


@dataclass
class Permit:
    """Proof that a transfer may proceed."""

    transfer: Transfer
    destination_class: str
    allowed: bool
    reason: str = ""
    #: Set when the consent was granted implicitly by the user's configuration
    #: rather than by an explicit decision. Worth surfacing: the user should
    #: know the app is acting on their setup, not on a recorded decision.
    implied: bool = False


@dataclass
class EgressGateway:
    """Classifies, checks consent, performs, and records.

    The store and log are injectable so the gateway can be tested without a
    database, and so a future background worker can use its own sink.
    """

    store: consent_module.ConsentStore | None = None
    log_sink: Any = None
    resolver: urlpolicy.Resolver | None = None
    opener: urlpolicy.Opener | None = None
    timeout: float = 30.0
    #: Attempts for a retryable failure. One retry, because a provider that
    #: failed twice is usually wrong rather than unlucky.
    max_attempts: int = 2

    # -- policy ---------------------------------------------------------

    def classify(self, url: str) -> str:
        """Classify ``url`` as loopback, private or public."""
        return urlpolicy.classify_url(url, resolver=self.resolver)

    def _consent_store(self) -> consent_module.ConsentStore:
        return self.store or consent_module.SqliteConsentStore()

    def _write_log(self, record: consent_module.TransferRecord) -> None:
        if self.log_sink is not None:
            self.log_sink(record)
            return
        consent_module.log_transfer(record)

    def _decision(self, operation: str, destination_class: str):
        return self._consent_store().get(operation, destination_class)

    def authorize(self, transfer: Transfer) -> Permit:
        """Decide whether ``transfer`` may proceed.

        The rules, in order:

        1. The destination is classified. A refused address raises immediately.
        2. Loopback is allowed. It is the same machine; the warning about
           tunnels belongs in the UI, not in a refusal.
        3. A stored, granted decision allows the transfer.
        4. A stored, refused decision blocks it — even if the transfer is
           otherwise configured, an explicit refusal wins.
        5. An unconfigured operation to a public host is allowed once, and the
           decision is recorded as ``implied`` so the Settings screen can show
           it. This is what keeps an existing install working after the
           upgrade without inventing consent that was never given.
        6. A private host is never allowed implicitly. It has to be granted.
        """
        destination_class = self.classify(transfer.url)

        if destination_class == urlpolicy.UrlClass.LOOPBACK.value:
            return Permit(transfer, destination_class, allowed=True, reason="loopback")

        if not transfer.requires_consent:
            return Permit(transfer, destination_class, allowed=True, reason="no consent required")

        decision = self._decision(transfer.operation, destination_class)
        if decision is not None:
            if decision.granted:
                return Permit(transfer, destination_class, allowed=True, reason="consent granted")
            return Permit(
                transfer,
                destination_class,
                allowed=False,
                reason=decision.note or "you withdrew consent for this transfer",
            )

        if transfer.configured and destination_class == urlpolicy.UrlClass.PUBLIC.value:
            # The user configured this destination themselves. Record it so it
            # is visible and revocable, rather than implicit forever.
            decision = consent_module.ConsentDecision(
                operation=transfer.operation,
                destination_class=destination_class,
                granted=True,
                source="configured",
                decided_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                note="Allowed because this destination was configured in Settings.",
            )
            self._consent_store().set(decision)
            return Permit(
                transfer,
                destination_class,
                allowed=True,
                reason="destination configured in Settings",
                implied=True,
            )

        return Permit(
            transfer,
            destination_class,
            allowed=False,
            reason="no consent has been given for this transfer",
        )

    # -- performing -----------------------------------------------------

    def fetch(
        self,
        transfer: Transfer,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> bytes:
        """Perform an HTTP request under the policy.

        Returns the response body. Raises :class:`EgressError` when consent is
        missing or the request fails; :class:`urlpolicy.ConsentRequired` and
        :class:`urlpolicy.UrlRejected` propagate so the caller can tell a
        policy refusal from a network failure.
        """
        permit = self.authorize(transfer)
        if not permit.allowed:
            raise urlpolicy.ConsentRequired(
                f"{transfer.operation} is not allowed to reach "
                f"{permit.destination_class} destinations: {permit.reason}"
            )

        started = time.perf_counter()
        try:
            payload = urlpolicy.fetch_checked(
                transfer.url,
                consent=lambda _cls: True,
                resolver=self.resolver,
                opener=self.opener,
                timeout=self.timeout,
            )
        except Exception as exc:
            self._write_log(
                consent_module.TransferRecord(
                    operation=transfer.operation,
                    destination=_safe_url(transfer.url),
                    destination_class=permit.destination_class,
                    outcome="failed",
                    provider=transfer.provider,
                    data_summary=transfer.data_summary,
                    detail=redact(f"{type(exc).__name__}: {exc}"),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            raise

        self._write_log(
            consent_module.TransferRecord(
                operation=transfer.operation,
                destination=_safe_url(transfer.url),
                destination_class=permit.destination_class,
                outcome="ok",
                provider=transfer.provider,
                data_summary=transfer.data_summary,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        return payload

    def record(
        self,
        transfer: Transfer,
        outcome: str,
        *,
        detail: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Record a transfer that the caller performed itself.

        Used by the provider SDKs, which make their own requests.
        """
        try:
            destination_class = self.classify(transfer.url)
        except urlpolicy.UrlRejected:
            destination_class = "refused"
        self._write_log(
            consent_module.TransferRecord(
                operation=transfer.operation,
                destination=_safe_url(transfer.url),
                destination_class=destination_class,
                outcome=outcome,
                provider=transfer.provider,
                data_summary=transfer.data_summary,
                detail=redact(detail),
                duration_ms=duration_ms,
            )
        )

    def require(self, transfer: Transfer) -> Permit:
        """Authorize, or raise :class:`urlpolicy.ConsentRequired`."""
        permit = self.authorize(transfer)
        if not permit.allowed:
            raise urlpolicy.ConsentRequired(
                f"{transfer.operation} is not allowed to reach "
                f"{permit.destination_class} destinations: {permit.reason}"
            )
        return permit


#: The gateway the application uses. Tests construct their own.
gateway = EgressGateway()


class MemoryLogSink:
    """Collects transfer records in memory, for tests and dry runs."""

    def __init__(self) -> None:
        self.records: list[consent_module.TransferRecord] = []

    def __call__(self, record: consent_module.TransferRecord) -> None:
        self.records.append(record)
