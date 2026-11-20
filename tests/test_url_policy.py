"""Target-policy tests for URL fetching (SSRF).

These were registered in M0 against a policy that did not exist yet, as strict
xfails. M0.5 implemented :mod:`autoclip.security.urlpolicy` and every case here
now runs as an ordinary passing test; the xfail marker is gone, which is what
the M0.5 gate requires.

Do not delete a case to make the file green. See ``docs/SECURITY-AUDIT.md`` for
the policy each ID encodes.

The module under test is ``autoclip.security.urlpolicy``. Its surface:

    class UrlClass(str, Enum):
        LOOPBACK = "loopback"
        PRIVATE = "private"
        PUBLIC = "public"

    class UrlRejected(ValueError): ...       # scheme/host refused outright
    class ConsentRequired(PermissionError): ...

    def classify_url(url: str, *, resolver=None) -> str:
        '''Return the UrlClass value, or raise UrlRejected.'''

    def resolve(url: str, *, resolver=None) -> list[str]:
        '''Return the IP literals the host resolves to.'''

    def fetch_checked(url: str, *, consent, max_redirects=5, resolver=None,
                      opener=None) -> bytes:
        '''Fetch, re-classifying every redirect hop and the pre-connect resolution.'''

    def check_redirect(original: str, target: str, *, resolver=None) -> None:
        '''Raise if moving from `original` to `target` violates the policy.'''

    def ffmpeg_protocol_whitelist() -> str: ...
    def yt_dlp_hardening_args() -> list[str]: ...
"""

from __future__ import annotations

import pytest

# --------------------------------------------------------------------------
# Helpers - imported lazily so a missing module is a clear failure here rather
# than a collection error somewhere else.
# --------------------------------------------------------------------------


def _policy():
    from autoclip.security import urlpolicy

    return urlpolicy


def _resolver(mapping: dict[str, list[str]]):
    """A deterministic resolver: host -> list of IP addresses."""

    def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"no such host: {host}")
        return mapping[host]

    return resolve


# --------------------------------------------------------------------------
# URL-01 .. URL-10: classification
# --------------------------------------------------------------------------


def test_url_01_loopback_v4():
    assert _policy().classify_url("http://127.0.0.1:8080/") == "loopback"


def test_url_02_loopback_localhost():
    assert _policy().classify_url("http://localhost/") == "loopback"


def test_url_03_loopback_v6():
    assert _policy().classify_url("http://[::1]/") == "loopback"


def test_url_04_ipv4_mapped_v6_is_loopback():
    # ::ffff:127.0.0.1 must not be treated as a distinct public address.
    assert _policy().classify_url("http://[::ffff:127.0.0.1]/") == "loopback"


# --------------------------------------------------------------------------
# NAT64: an IPv6-only network reaches an IPv4 service through an IPv6
# address with the IPv4 one embedded in it.
# --------------------------------------------------------------------------


def test_a_nat64_address_is_classified_by_the_ipv4_it_stands_for():
    # 64:ff9b::2208:b8bf is 34.8.184.191 — a public address.
    assert _policy().classify_url("http://[64:ff9b::2208:b8bf]/") == "public"


def test_a_nat64_address_that_stands_for_loopback_is_loopback():
    # 64:ff9b::7f00:1 is 127.0.0.1. A name that resolves to it must not
    # be treated as a public address.
    assert _policy().classify_url("http://[64:ff9b::7f00:1]/") == "loopback"


def test_a_nat64_address_that_stands_for_a_private_address_is_private():
    # 64:ff9b::0a00:1 is 10.0.0.1.
    assert _policy().classify_url("http://[64:ff9b::a00:1]/") == "private"


def test_a_nat64_address_that_stands_for_the_metadata_address_is_refused():
    # 64:ff9b::a9fe:a9fe is 169.254.169.254 — the cloud metadata address.
    with pytest.raises(_policy().UrlRejected):
        _policy().classify_url("http://[64:ff9b::a9fe:a9fe]/latest/meta-data/")


def test_a_nat64_address_with_a_non_zero_u_octet_is_not_translated():
    # The u-octet must be zero for the address to be a NAT64 address.
    # 64:ff9b:0:1::2208:b8bf is some other address, and it is reserved.
    with pytest.raises(_policy().UrlRejected):
        _policy().classify_url("http://[64:ff9b:0:1::2208:b8bf]/")


def test_a_nat64_address_for_a_documentation_range_is_public():
    # 64:ff9b::c000:201 is 192.0.2.1.
    assert _policy().classify_url("http://[64:ff9b::c000:201]/") == "public"


def test_the_local_use_nat64_prefix_is_understood_too():
    # RFC 8215's prefix, in its /96 form: 64:ff9b:1::2208:b8bf is
    # 34.8.184.191.
    assert _policy().classify_url("http://[64:ff9b:1::2208:b8bf]/") == "public"


def test_the_local_use_nat64_prefix_still_refuses_loopback():
    # 64:ff9b:1::7f00:1 is 127.0.0.1.
    assert _policy().classify_url("http://[64:ff9b:1::7f00:1]/") == "loopback"


def test_url_05_private_10_slash_8():
    assert _policy().classify_url("http://10.0.0.5/") == "private"


def test_url_06_private_192_168():
    assert _policy().classify_url("http://192.168.1.10/") == "private"


def test_url_07_private_172_16():
    assert _policy().classify_url("http://172.16.0.1/") == "private"


def test_url_08_link_local_metadata_refused():
    with pytest.raises(_policy().UrlRejected):
        _policy().classify_url("http://169.254.169.254/latest/meta-data/")


def test_url_09_cgnat_is_private():
    assert _policy().classify_url("http://100.64.0.1/") == "private"


def test_url_10_public_host():
    assert (
        _policy().classify_url(
            "https://example.com/", resolver=_resolver({"example.com": ["93.184.216.34"]})
        )
        == "public"
    )


# --------------------------------------------------------------------------
# URL-11 .. URL-12: unresolvable and DNS-lying hosts
# --------------------------------------------------------------------------


def test_url_11_unresolvable_is_public():
    # "Cannot resolve" must never mean "internal, therefore allowed".
    assert _policy().classify_url("https://nope.invalid/", resolver=_resolver({})) == "public"


def test_url_12_public_name_to_private_ip():
    resolver = _resolver({"evil.example": ["10.0.0.5"]})
    assert _policy().classify_url("https://evil.example/", resolver=resolver) == "private"


# --------------------------------------------------------------------------
# URL-13 .. URL-14: schemes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "gopher://x/", "ftp://x/", "data:text/plain,hi"]
)
def test_url_13_14_schemes_refused(url):
    with pytest.raises(_policy().UrlRejected):
        _policy().classify_url(url)


# --------------------------------------------------------------------------
# URL-15 .. URL-18: redirects and rebinding
# --------------------------------------------------------------------------


def test_url_15_redirect_to_private_refused():
    with pytest.raises(_policy().UrlRejected):
        _policy().check_redirect(
            "https://example.com/a",
            "http://10.0.0.5/b",
            resolver=_resolver({"example.com": ["93.184.216.34"], "10.0.0.5": ["10.0.0.5"]}),
        )


def test_url_16_redirect_downgrade_refused():
    with pytest.raises(_policy().UrlRejected):
        _policy().check_redirect("https://example.com/a", "http://example.com/b")


def test_url_17_redirect_chain_bounded():
    calls = {"n": 0}

    def opener(url: str, _timeout: float) -> tuple[int, dict[str, str], bytes]:
        calls["n"] += 1
        return 302, {"location": f"https://example.com/hop{calls['n']}"}, b""

    with pytest.raises(_policy().UrlRejected):
        _policy().fetch_checked(
            "https://example.com/start",
            consent=lambda cls: True,
            max_redirects=5,
            resolver=_resolver({"example.com": ["93.184.216.34"]}),
            opener=opener,
        )
    assert calls["n"] <= 5


def test_url_18_rebinding_aborts():
    # The resolver returns a public address, then a private one before connect.
    answers = iter([["93.184.216.34"], ["10.0.0.5"]])

    def flaky(_host: str) -> list[str]:
        return next(answers)

    with pytest.raises(_policy().UrlRejected):
        _policy().resolve("https://flip.example/", resolver=flaky)


# --------------------------------------------------------------------------
# URL-19 .. URL-20: consent
# --------------------------------------------------------------------------


def test_url_19_consent_required_for_private():
    with pytest.raises(_policy().ConsentRequired):
        _policy().fetch_checked(
            "http://10.0.0.5/x",
            consent=lambda cls: False,
            resolver=_resolver({"10.0.0.5": ["10.0.0.5"]}),
            opener=lambda url, timeout: (200, {}, b"ok"),
        )


def test_url_20_consent_allows_fetch():
    body = _policy().fetch_checked(
        "http://10.0.0.5/x",
        consent=lambda cls: True,
        resolver=_resolver({"10.0.0.5": ["10.0.0.5"]}),
        opener=lambda url, timeout: (200, {}, b"ok"),
    )
    assert body == b"ok"


# --------------------------------------------------------------------------
# URL-21 .. URL-24: downstream tooling and provider endpoints
# --------------------------------------------------------------------------


def test_url_21_yt_dlp_hardening_args_present():
    args = _policy().yt_dlp_hardening_args()
    assert "--no-check-certificates" not in args
    assert any("--proxy" in a for a in args)


def test_url_22_ffmpeg_protocol_whitelist_present():
    whitelist = _policy().ffmpeg_protocol_whitelist()
    assert "file" in whitelist.split(",")
    assert "http" not in whitelist.split(",")


def test_url_23_provider_base_url_classified():
    from autoclip.config import ProviderSettings

    policy = _policy()
    local = ProviderSettings(base_url="http://localhost:11434")
    remote = ProviderSettings(base_url="https://api.example.com/v1")
    assert policy.classify_url(local.base_url) == "loopback"
    assert (
        policy.classify_url(
            remote.base_url, resolver=_resolver({"api.example.com": ["203.0.113.10"]})
        )
        == "public"
    )


def test_url_24_base_url_change_reclassifies():
    policy = _policy()
    resolver = _resolver({"api.example.com": ["203.0.113.10"], "10.0.0.9": ["10.0.0.9"]})
    first = policy.classify_url("https://api.example.com/v1", resolver=resolver)
    second = policy.classify_url("http://10.0.0.9/v1", resolver=resolver)
    assert first != second
