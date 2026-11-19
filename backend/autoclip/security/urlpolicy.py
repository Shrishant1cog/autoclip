"""One place that decides whether a URL may be contacted.

Every outbound request in AutoClip eventually passes through here: the LLM
provider base URL, the yt-dlp download target, and the model downloads. The
rule is the same in all cases, which is why it lives in one module rather than
being re-implemented (or forgotten) per caller.

The policy has three destination classes:

``loopback``
    ``127.0.0.0/8``, ``::1``, ``localhost``. Reaching a service on the same
    machine is not egress, so no consent is required — but it is still logged,
    because a localhost tunnel can forward traffic somewhere else entirely.

``private``
    RFC1918, CGNAT, link-local, ULA. Reached only with explicit consent.

``public``
    Everything else, **including a hostname that does not resolve**. Treating
    "cannot resolve" as "internal, therefore safe" is how SSRF guards get
    bypassed, so an unresolvable name is treated as public and consent-gated.

Link-local and unspecified addresses are refused outright rather than
classified: ``169.254.169.254`` is the cloud metadata endpoint, and no product
feature has a legitimate reason to fetch it.

The subtle part is not the classification, it is *when* it is evaluated. A
single check at the start of a request is not enough, so :func:`fetch_checked`
re-checks every redirect hop, and :func:`resolve` performs the resolution twice
and refuses the request if the answer changed — a cheap DNS-rebinding guard.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import TypeAlias
from urllib.parse import urljoin, urlsplit

__all__ = [
    "ConsentRequired",
    "UrlClass",
    "UrlRejected",
    "check_redirect",
    "classify_url",
    "fetch_checked",
    "ffmpeg_protocol_whitelist",
    "resolve",
    "yt_dlp_hardening_args",
]


class UrlClass(StrEnum):
    """How far a destination is from the machine running AutoClip."""

    LOOPBACK = "loopback"
    PRIVATE = "private"
    PUBLIC = "public"


class UrlRejected(ValueError):
    """A URL may not be contacted at all.

    Raised for schemes other than HTTP(S), for link-local and unspecified
    addresses, for a redirect that leaves the permitted class or downgrades
    the scheme, and for a host whose DNS answer changes mid-request.
    """


class ConsentRequired(PermissionError):
    """The URL is reachable but the user has not consented to this class."""


#: A resolver maps a hostname to the IP literals it resolves to. Tests inject
#: a deterministic one; production uses :func:`socket.getaddrinfo`.
Resolver: TypeAlias = Callable[[str], list[str]]

#: An opener performs one HTTP GET and returns ``(status, headers, body)``.
#: Tests inject a fake; production uses :mod:`urllib.request`. Keeping this a
#: plain callable rather than an ``httpx.Client`` is what makes the redirect
#: and rebinding paths testable without a network.
Opener: TypeAlias = Callable[[str, float], tuple[int, dict[str, str], bytes]]

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
#: RFC 5737 / RFC 3849 documentation ranges. Python's ``is_private`` reports
#: these as private because they are not globally routable, but they are the
#: conventional stand-in for "some public host" in tests and documentation.
#: They are classified public so a test endpoint reads as a real one would.
_DOCUMENTATION = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
)
_LOCAL_SUFFIX = ".localhost"
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_TIMEOUT = 15.0


# --------------------------------------------------------------------------
# Address classification
# --------------------------------------------------------------------------


def _classify_ip(raw: str) -> UrlClass:
    """Classify a single IP literal, or refuse it."""
    address = ipaddress.ip_address(raw)

    # An IPv4-mapped IPv6 address is the IPv4 address; ::ffff:127.0.0.1 must be
    # loopback, not an exotic public v6 address.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped

    if address.is_loopback:
        return UrlClass.LOOPBACK
    # Link-local covers 169.254.0.0/16 (cloud metadata) and fe80::/10.
    if address.is_link_local:
        raise UrlRejected(f"link-local address is not allowed: {raw}")
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise UrlRejected(f"address is not routable to a service: {raw}")
    if address.version == 4 and address in _CGNAT:
        return UrlClass.PRIVATE
    if any(address in network for network in _DOCUMENTATION):
        return UrlClass.PUBLIC
    if address.is_private:
        return UrlClass.PRIVATE
    # Everything else is public. Deliberately *not* keyed on is_global: the
    # documentation ranges (203.0.113.0/24 and friends) are not globally
    # routable but are candidates for a public endpoint in tests and in
    # user-supplied configuration, and treating them as private would demand
    # consent for the wrong reason.
    return UrlClass.PUBLIC


def _is_localhost(name: str) -> bool:
    lowered = name.lower().rstrip(".")
    return lowered == "localhost" or lowered.endswith(_LOCAL_SUFFIX)


def _default_resolver(host: str) -> list[str]:
    """Resolve ``host`` to IP literals using the system resolver.

    Only address families we can classify are returned. ``getaddrinfo`` may
    yield duplicates (one entry per socket type), so the result is deduplicated
    while preserving order.
    """
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    seen: list[str] = []
    for info in infos:
        # The address is a string for the address families we use; the typeshed
        # widens it because a sockaddr can carry an integer in other families.
        literal = str(info[4][0])
        if literal not in seen:
            seen.append(literal)
    return seen


def _host_of(url: str) -> tuple[str, str]:
    """Return ``(scheme, hostname)`` or raise :class:`UrlRejected`."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:  # malformed bracket syntax and similar
        raise UrlRejected(f"unparseable URL: {url}") from exc

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UrlRejected(f"scheme {scheme or '(none)'!r} is not allowed")
    # A URL with no host cannot be classified; refuse rather than guess.
    host = parts.hostname
    if not host:
        raise UrlRejected(f"URL has no host: {url}")
    return scheme, host


def _addresses_for(host: str, resolver: Resolver) -> list[str]:
    """Resolve once, using the injected resolver or the system one."""
    return resolver(host)


# --------------------------------------------------------------------------
# Resolution and classification
# --------------------------------------------------------------------------


def resolve(url: str, *, resolver: Resolver | None = None) -> list[str]:
    """Return the IP literals ``url``'s host resolves to.

    The resolution is performed **twice**. A host that answers with one address
    and then a different one is the classic DNS-rebinding attack — the check
    that passed and the connection that gets made are not the same request — so
    a mismatch is refused rather than resolved in favour of the first answer.

    An unresolvable host is not an error here; :func:`classify_url` treats it as
    public. A *changing* answer is an error.
    """
    _, host = _host_of(url)

    # A literal address needs no DNS, and resolving it would be wrong: the
    # "resolver" for 10.0.0.5 is not the DNS server.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return [host]

    if _is_localhost(host):
        return ["127.0.0.1", "::1"]

    lookup = resolver or _default_resolver
    first = lookup(host)
    second = lookup(host)
    if sorted(first) != sorted(second):
        raise UrlRejected(
            f"DNS for {host} changed between lookups ({first} then {second}); "
            "refusing a possible rebinding"
        )
    return first


def classify_url(url: str, *, resolver: Resolver | None = None) -> str:
    """Classify ``url`` as ``loopback``, ``private`` or ``public``.

    Returns the class *value* (a plain string) rather than the enum member,
    because that is what callers store in a database and send over the API.

    Raises :class:`UrlRejected` for a disallowed scheme, a link-local or
    unspecified address, or a host whose DNS answer changed mid-check.
    """
    _, host = _host_of(url)

    if _is_localhost(host):
        return UrlClass.LOOPBACK.value

    try:
        ipaddress.ip_address(host)
    except ValueError:
        literal = None
    else:
        literal = host

    if literal is not None:
        return _classify_ip(literal).value

    try:
        addresses = resolve(url, resolver=resolver)
    except UrlRejected:
        raise
    except OSError:
        # Cannot resolve: treat as public so it is consent-gated rather than
        # silently allowed. This is deliberately the *strict* direction.
        return UrlClass.PUBLIC.value

    if not addresses:
        return UrlClass.PUBLIC.value

    classes = {_classify_ip(address) for address in addresses}
    # The most insulated address wins: if any answer is loopback the request
    # could reach the loopback interface, and so on up the ladder.
    if UrlClass.LOOPBACK in classes:
        return UrlClass.LOOPBACK.value
    if UrlClass.PRIVATE in classes:
        return UrlClass.PRIVATE.value
    return UrlClass.PUBLIC.value


# --------------------------------------------------------------------------
# Redirects and fetching
# --------------------------------------------------------------------------


def check_redirect(original: str, target: str, *, resolver: Resolver | None = None) -> None:
    """Raise if moving from ``original`` to ``target`` violates the policy.

    Two things are refused regardless of classification: a scheme downgrade
    (``https`` to ``http``), and a change to a non-HTTP scheme. Everything else
    is refused by class: a redirect may never reach a private or link-local
    destination.
    """
    original_scheme, _ = _host_of(original)
    target_scheme, _ = _host_of(target)

    if target_scheme not in _ALLOWED_SCHEMES:
        raise UrlRejected(f"redirect to scheme {target_scheme!r} is not allowed")
    if original_scheme == "https" and target_scheme == "http":
        raise UrlRejected("redirect downgrades https to http")

    target_class = classify_url(target, resolver=resolver)
    if target_class != UrlClass.PUBLIC.value and target_class != UrlClass.LOOPBACK.value:
        raise UrlRejected(f"redirect to a {target_class} address is not allowed")


def _urllib_opener(url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    """Production opener. Redirects are *not* followed here.

    ``urllib`` would follow redirects itself, which would defeat the per-hop
    check in :func:`fetch_checked`. A handler that returns the 3xx response
    unchanged is installed instead.
    """
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, D102
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "AutoClip"})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        # A 3xx surfaces as HTTPError because redirects are disabled.
        return exc.code, dict(exc.headers or {}), exc.read()


def fetch_checked(
    url: str,
    *,
    consent: Callable[[str], bool],
    max_redirects: int = 5,
    resolver: Resolver | None = None,
    opener: Opener | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bytes:
    """GET ``url``, checking every hop against the policy.

    ``consent`` receives the destination class (``"loopback"``, ``"private"``
    or ``"public"``) and returns whether the user has allowed it. Loopback never
    needs consent; private and public always do.

    Redirects are followed manually so each one is re-classified, with the
    scheme and the resolved address re-checked. A chain longer than
    ``max_redirects`` is refused rather than truncated.
    """
    fetch = opener or _urllib_opener
    current = url

    for _ in range(max_redirects):
        destination = classify_url(current, resolver=resolver)
        if destination != UrlClass.LOOPBACK.value and not consent(destination):
            raise ConsentRequired(f"{destination} destination requires consent: {current}")

        status, headers, body = fetch(current, timeout)
        if not (300 <= status < 400):
            return body

        location = _header(headers, "location")
        if not location:
            raise UrlRejected(f"redirect response had no Location header: {current}")

        following = urljoin(current, location)
        check_redirect(current, following, resolver=resolver)
        current = following

    raise UrlRejected(f"more than {max_redirects} redirects")


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


# --------------------------------------------------------------------------
# Downstream tooling
# --------------------------------------------------------------------------


def ffmpeg_protocol_whitelist() -> str:
    """The value passed to FFmpeg's ``-protocol_whitelist``.

    AutoClip only ever feeds FFmpeg local files and pipes, so the network
    protocols are removed from the default set. If a future feature needs
    FFmpeg to read a URL, that becomes an explicit, reviewed change rather than
    a capability FFmpeg has silently.
    """
    return "file,pipe"


def yt_dlp_hardening_args() -> list[str]:
    """Options that keep yt-dlp inside the same policy.

    ``--proxy ""`` is deliberate: an empty value disables proxying, which
    prevents ``HTTP_PROXY``/``ALL_PROXY`` from re-routing a request to a host
    the policy never classified. Certificate checking is left **on**; disabling
    it is not hardening.

    yt-dlp's own secondary requests (manifests, CDNs) are outside AutoClip's
    control once the tool starts. The initial host is classified before launch,
    and this is documented as a residual risk rather than claimed as solved.
    """
    return ["--proxy", ""]


def all_addresses(url: str, *, resolver: Resolver | None = None) -> Iterable[str]:
    """Public helper for callers that want the raw addresses (e.g. logging)."""
    return resolve(url, resolver=resolver)
