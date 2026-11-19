# AutoClip — Security and SSRF Audit (M0)

**Audited:** 2026-11-19. **Scope:** every external transfer, the URL-fetch path, credential
handling, local API exposure, and subprocess construction.

Findings are severity-ranked. Each has a concrete verification method and an explicit owner
milestone. Nothing in this document is a guess: the "Verified by" line says how it was checked.

---

## S1 — HIGH — Media leaves the machine with no consent step

**Where:** `backend/autoclip/speech/base.py:resolve_engine` (55-88), used by
`pipeline/runner.py:366`.

**What happens.** `settings.transcription.engine` defaults to `"auto"`. In `auto`, if an ElevenLabs
key resolves from the keyring, the runner posts the extracted `audio.wav` — the entire source's
audio — to `https://api.elevenlabs.io/v1/speech-to-text`. The user is never asked, and the UI does
not say that adding a key changes where audio goes.

**Verified by:** reading `resolve_engine` in full; tracing the call from `runner.py:_stage_transcribe`;
and searching `backend/` and `frontend/src/` for a consent layer. The word `consent` *does* appear —
`youtube/oauth.py:102,123,125` uses it in Google's OAuth prompt text, and the value is a path segment
there — but no module, setting, model field, route or UI control records, stores or checks user
consent for a transfer. The accurate statement is: **no consent layer exists**, not that the word
is absent.

**Impact.** A user who adds an ElevenLabs key for one purpose silently routes every future
transcription — including third-party video they merely have a URL for — through a US-hosted
service.

**Fix owner:** M0.5 (§4.1/§4.2). Retrofit the existing path; do not build a gateway for new
features only.

---

## S2 — HIGH — Unvalidated URL fetch; no post-redirect or DNS re-validation

**Where:** `pipeline/ingest.py:download` — `command.append(source.url)` (`:180`).

**What happens.** `is_youtube_url()` checks only the *hostname string* against
`("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")` to decide how to label a source.
The download then hands the raw URL to yt-dlp. There is:

- no redirect following/validation,
- no DNS resolution and IP classification,
- no guard against `http://169.254.169.254/` (cloud metadata), RFC1918 or loopback targets,
- no control over yt-dlp's own secondary requests (manifest, CDN, page assets),
- no control over proxy environment variables.

**Verified by:** reading `ingest.py` end to end; exhaustive search for `protocol_whitelist`,
`is_private`, `ipaddress`, `socket.gethostbyname` across the tree (no hits in the fetch path).

**Impact.** A hostile or mistyped URL can make the server issue requests to internal services.

**Limitation I cannot remove:** yt-dlp's internal request set is not fully observable from
AutoClip, and real DNS-rebinding cannot be simulated reliably in a unit test. The plan is:
enforce at the boundary AutoClip controls (pre-flight classification + a resolving policy on the
initial host, plus yt-dlp's own `--proxy`/`--no-check-certificates` hardening and an explicit
allowlist of permitted schemes), then record a **Lane B controlled** test for the residual
secondary-request surface. That residual is reported as a documented limitation, not as verified.

**Fix owner:** M0.5 (§4.3).

---

## S3 — MEDIUM — FFmpeg runs without a protocol whitelist

**Where:** `pipeline/ffmpeg.py` (all subprocess construction at `:156-180`, `:377`).

**What happens.** No invocation passes `-protocol_whitelist`. FFmpeg's default protocol set includes
`http`, `https`, `tcp`, `udp`, `rtmp`, `file`, and others. AutoClip's own inputs are local files, so
the permissive set is unnecessary.

**Verified by:** exhaustive search for `protocol_whitelist` (zero hits).

**Impact.** A crafted playlist or manifest that reached FFmpeg through a future feature could
instruct it to fetch remote or local resources. Today the exposure is small because inputs are
local, but it becomes real the moment any URL is passed to FFmpeg.

**Fix owner:** M0.5. Restrict to `file,pipe` for local work; permit network schemes only through a
gateway decision.

---

## S4 — MEDIUM — Provider base URL is never classified

**Where:** `config.py:ProviderSettings.base_url`, consumed by `providers/resolver.py:34-57`.

**What happens.** A user (or a restored config) can set any `base_url`. Nothing validates the
scheme, resolves the host, or distinguishes loopback from private from public. An
"OpenAI-compatible" endpoint is assumed to be benign.

**Verified by:** `resolver.py:28-57` read in full; no validation call exists.

**Impact.** Two directions. (a) Transcript text silently leaves for an unexpected destination.
(b) A private/LAN URL is treated as if it were a public provider for consent purposes.

**Fix owner:** M0.5 §4.2 — classify on every use and re-classify when the URL or DNS answer changes.

---

## S5 — MEDIUM — Undocumented model download at first use

**Where:** `models.py:37` (`https://storage.googleapis.com/mediapipe-models/face_landmarker/...`),
called from `reframe/faces.py:113`.

**What happens.** The first reframe that needs face detection performs a public HTTPS download with
no notice, no consent, and no user-visible progress. `models.ensure` caches the file, so it happens
once per machine.

**Verified by:** `models.py:64-90`; call sites at `faces.py:113` and `cli.py:687`.

**Impact.** A surprise egress; an offline install fails inside the pipeline with a face-detection
error rather than a clear "this needs a model download" message.

**Fix owner:** M0.5. Classify, notify, consent, and pre-flight the check before a job starts.

---

## S6 — LOW — Legacy global OAuth token remains valid alongside per-account tokens

**Where:** `youtube/oauth.py:_token_cache` / `_tokens_by_account`;
`youtube/accounts.py:claim_legacy_token` deliberately keeps the legacy keyring entry.

**What happens.** Two token stores exist. `Channels.tsx` still starts the legacy flow, so the
practical result is one shared token (D14). The legacy entry is never deleted.

**Impact.** Credential confusion: an upload intended for account B can use account A's token. There
is no test that asserts "the token used belongs to the account that owns the destination".

**Fix owner:** M4a §8.1/§8.4. Account-scoped state, account-scoped tokens, and a wrong-account
callback rejection test.

---

## S7 — LOW — Toolchain pinned too loosely

**Where:** `pyproject.toml:85` — `ruff>=0.7`.

**What happens.** CI installs whatever ruff is current. The shipped tree did not satisfy the current
formatter, so the format gate failed on a clean checkout (D15). Any gate that can change without a
commit is not a gate.

**Fix owner:** M0 (this milestone records it) → pin in M5 with the rest of the reproducible-build
work.

---

## Verified-good findings

These were checked and are *not* defects; they are stated so later reviews do not re-litigate them.

| Property | Verification |
|---|---|
| No secret is returned by any API route | `api/settings.py` and `api/ai_providers.py` return labels and boolean "configured" flags only |
| Secrets live in the OS keyring | `config.get_secret`/`set_secret`; `KEYED_PROVIDERS` |
| Tokens are never logged | grep for `token` near `log.` finds only ids/counts, no values |
| SQL injection | every `store.py` statement is parameterised; no f-string SQL with user input |
| CORS | no CORS middleware exists because the bundle is served same-origin (`app.py:3-6`) — narrower than an allowlist |
| Path traversal on media download | `api/clips.py` download resolves and checks the path is inside the export root |
| SQLite is local-only | `db/__init__.py:connect` opens a file path; no network transport |
| Pipeline artifacts are per-job | `work/{job_id}/`, so one job cannot read another's workspace |

---

## SSRF target policy (the rule M0.5 must enforce)

A URL may be fetched only if **all** of the following hold, evaluated at the moment of the request:

1. **Scheme** ∈ `{https, http}` (and `http` only for loopback). Anything else — `file`, `ftp`,
   `gopher`, `data`, `rtmp` — is refused.
2. **Host resolves** to at least one address, and **every** returned address is classified.
3. **Classification** is loopback, private, or public. Loopback is allowed without consent; private
   and public require a recorded consent for the endpoint class.
4. **No redirect** may leave the permitted class, and no redirect may add a scheme. Each hop is
   re-resolved and re-classified.
5. **Rebinding:** after resolution, the connection is made to the resolved IP (or the resolution is
   repeated immediately before connect and must match). A second resolution that differs aborts the
   request.
6. **IPv6** is classified with the same rules as IPv4 (including IPv4-mapped forms such as
   `::ffff:127.0.0.1`).
7. **Secondary requests** (yt-dlp) are constrained to the permitted class through explicit yt-dlp
   options, and the residual risk is documented.
8. **Proxies** from the environment are either disabled or treated as a destination that must itself
   pass this policy.

### Pre-registered tests

`tests/test_url_policy.py` contains the target-policy tests. While enforcement is absent they are
marked `xfail(strict=True)` with the reason "M0.5 enforcement not implemented", so the suite stays
honest and green for the *current* state without hiding the gap. Each must be converted to a normal
passing test in M0.5 — a permanently-skipped security test is a lie. The M0.5 gate fails if any
`xfail` marker remains in that file.

Test IDs (registered here so the set cannot quietly shrink):

| ID | Case |
|---|---|
| URL-01 | `http://127.0.0.1:8080/` classifies loopback |
| URL-02 | `http://localhost/` classifies loopback |
| URL-03 | `http://[::1]/` classifies loopback |
| URL-04 | `http://[::ffff:127.0.0.1]/` classifies loopback, not public |
| URL-05 | `http://10.0.0.5/` classifies private |
| URL-06 | `http://192.168.1.10/` classifies private |
| URL-07 | `http://172.16.0.1/` classifies private |
| URL-08 | `http://169.254.169.254/` classifies private/link-local and is refused |
| URL-09 | `http://100.64.0.1/` (CGNAT) classifies private |
| URL-10 | `https://example.com/` classifies public |
| URL-11 | An unresolvable hostname classifies **public** (not "allowed by default") |
| URL-12 | A public hostname that resolves to `10.0.0.5` classifies private |
| URL-13 | `file:///etc/passwd` is refused |
| URL-14 | `gopher://…`, `ftp://…`, `data:…` are refused |
| URL-15 | A 302 to a private address is refused |
| URL-16 | A 302 that changes scheme from https to http is refused |
| URL-17 | A redirect chain of 5+ hops is bounded and each hop is re-classified |
| URL-18 | DNS answer changing between resolve and connect aborts the request (rebinding) |
| URL-19 | Private/public fetch without consent raises a consent error, not a connection error |
| URL-20 | The same fetch with recorded consent proceeds |
| URL-21 | yt-dlp is invoked with the hardened option set (asserted on the built argv) |
| URL-22 | FFmpeg is invoked with an explicit `-protocol_whitelist` (asserted on the built argv) |
| URL-23 | An OpenAI-compatible base URL is classified before use |
| URL-24 | Changing `base_url` triggers re-classification |

**Test lane:** URL-01…URL-10, 13–16, 19–24 are Lane A (deterministic, fake endpoints).
URL-11, 12, 17, 18 involve DNS/redirect behaviour that cannot be made deterministic everywhere;
they use an injected resolver in Lane A and additionally a Lane B controlled test where the real
resolver is exercised. Both results are recorded separately.
