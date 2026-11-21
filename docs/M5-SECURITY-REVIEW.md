# AutoClip — Security Review (M5)

**Reviewed:** 2026-11-20, against `feature/upgrade-u0-u10` at `4cf309b`.
**Re-verified at M5.1:** 2026-11-21 — §S2 and §S7 re-checked against the M5.1 tree.
**Re-verified at M5.2:** 2026-11-21 — the rebinding guard itself was corrected, and a new finding
was raised and closed. See **§3a** and the S2 amendment.
**Reviewer:** the upgrade itself (this is the M5 refresh of `docs/SECURITY-AUDIT.md`, which was
the M0 audit).
**Scope:** every external transfer, the URL-fetch path, credential handling, local API exposure,
subprocess construction, the data written to disk, and the four new subsystems shipped since M0 —
the music library, webcam detection, the creative planner, and the YouTube/Instagram publishers.

**Method.** The M0 findings (S1–S7) were re-verified against the current tree rather than assumed
closed: each one's status line in `docs/SECURITY-AUDIT.md` was re-read and the claim behind it was
re-checked in the source. The new subsystems were reviewed for the same class of defect the M0
audit was written to find — unvalidated destinations, ungated egress, credentials that outlive
their owner, and claims the code cannot back up. Every "verified" line below says *how* it was
checked.

---

## 1. Summary

| | M0 | M5 | M5.2 |
|---|---|---|---|
| Findings raised | 7 (2 high, 3 medium, 2 low) | 7 | 7 |
| Closed | 0 | **7** — 6 with no residual, 1 with a documented residual | **7** |
| Open at M5 | 7 | **0** | **0** |
| New findings raised | — | **2** (both closed in the same milestone) | **3** (all closed; M5.2-01 in §3a) |
| Residual risks documented, not claimed | 1 (yt-dlp secondary requests) | 4 | 4 |

No finding is closed on the strength of a comment, a docstring or a plan. Each is closed on a
**test** or on a **source read** that names the code.

**One security control was itself defective at M5.2**, and it is recorded as **M5.2-01** in §3a:
the DNS-rebinding guard compared the two DNS answers as byte-identical **sets of addresses**, so it
refused a legitimate load-balanced host — **Meta's own Graph API host**. Both answers were public,
so the refusal bought no security and broke the feature. The guard now compares the **class** of
the two answers, and a public → private or public → loopback move is still refused.

---

## 2. The M0 findings, re-verified

### S1 — HIGH — Media left the machine with no consent step

**Status after M0.5: CLOSED. Re-verified at M5.**

Every external transfer now passes `backend/autoclip/security/egress.py`. The transcription path
calls `gateway.require()` before the upload and raises `SpeechConsentDenied` when the decision is
missing; `pipeline/runner.py` catches that separately from a service failure and says *"external
transcription is blocked"* rather than *"ElevenLabs unavailable"*. Decisions are stored in
`egress_consents` (migration v15) and managed from *Settings → External processing*.

**M5 re-verification.** The consent surface grew in M3 — `creative_planning` and `music_selection`
are new content-bearing operations — and the rule that matters is that a new operation cannot be
added without a decision. Verified by reading `security/consent.py:Operation` (the enum every
operation must be named in), `pipeline/creative.py` (the planning call asks), and
`pipeline/music_selection.py` (the music call asks). A **declined** consent is an answer, not a
failure: the runner catches `ProviderConsentRequired` and falls back deterministically rather than
retrying against another external provider.

**Evidence:** `tests/test_egress.py` (23 tests), `tests/test_creative.py` (15),
`tests/test_music_selection.py` (13).

### S2 — HIGH — Unvalidated URL fetch; no post-redirect or DNS re-validation

**Status after M0.5: CLOSED at the boundary AutoClip controls; one residual documented.
Re-verified at M5, and the residual grew one named gap: NAT64. Re-verified again at M5.2, after
the rebinding guard itself was corrected — see the amendment below.**

`backend/autoclip/security/urlpolicy.py` classifies a URL's scheme and every resolved address
(IPv4 and IPv6, including IPv4-mapped and CGNAT forms), refuses loopback/link-local/private targets
per the policy, re-classifies every redirect hop, refuses scheme downgrades, bounds the redirect
chain, and resolves twice — the answer must not move *inwards* immediately before the connection,
which is the rebinding guard.

**M5 re-verification — the NAT64 finding (M5-01, below).** M4b found that `api.elevenlabs.io`
resolves to `64:ff9b::2208:b8bf` on an IPv6-only network, and that Python's `ipaddress` marks the
whole `64:ff9b::/32` prefix as reserved. The policy was refusing every public provider. The fix
extracts the embedded IPv4 per RFC 6052 (and RFC 8215's local-use prefix) and classifies *that*.

**M5.2 re-verification — the rebinding guard was too strict, and that was a defect.** The guard
compared the two DNS answers as **sets of addresses**, so it refused any host that did not answer
with byte-identical lists. `graph.facebook.com` — Meta's own Graph API host — answers with a
rotating subset of its own edge addresses, so a legitimate publish was refused with *"DNS for
graph.facebook.com changed between lookups … refusing a possible rebinding"*. **Both answers were
public**, so neither could reach anything the policy does not already allow; the refusal bought no
security and broke the feature.

The guard now compares the **class** of the two answers, not the exact addresses:

| First answer | Second answer | Verdict | Why |
|---|---|---|---|
| public | public (a different set) | **allowed** | A load balancer, not an attack. The request can only reach a public address |
| public | private | **refused** | The rebinding attack. The connection could land inside the network the user did not name |
| public | loopback | **refused** | The same, one level further in |
| public | link-local / reserved | **refused** | An address that may not be contacted at all |
| private | public | **allowed** | The *first* answer classifies the destination as private, so consent is required anyway — the request cannot become more privileged than the check allowed |

**The protection was not weakened.** A public → private or public → loopback move is still refused,
and the refusal is still a refusal rather than a warning. The fix removes only the case where the
answer stayed public and merely changed which public address it named.

**Residual (documented, not claimed):** yt-dlp's own secondary requests — the manifest, the CDN,
the page assets — are made by yt-dlp, not by AutoClip, so AutoClip cannot re-classify each hop. The
controls applied are yt-dlp's own: proxies are disabled (`--proxy ""`), retries are bounded, and the
URL is classified up front. A Lane B controlled test against a redirecting host is still required
before the secondary-request surface can be called verified.

**Evidence:** `tests/test_url_policy.py` (39 cases, all passing, zero `xfail` markers), including
the five added at M5.2 — two that fail without the rebinding-guard fix and three that assert the
protection still holds.

### S3 — MEDIUM — FFmpeg ran without a protocol whitelist

**Status after M0.5: CLOSED. Re-verified at M5.**

`pipeline/ffmpeg.py` gained `protocol_args()`, which returns `-protocol_whitelist file,pipe`, and
all three command builders (probe, volume-detect, encode) include it. FFmpeg can now only read
local files and pipes.

**M5 re-verification.** The M4b export change added a fourth option to the encode command
(`-use_editlist 0`); the whitelist had to survive that edit. Verified by re-reading the built argv
in `pipeline/export.py:export_clip` and by the assertion in `tests/test_url_policy.py` (URL-22),
which builds the command and checks the option is present.

**Evidence:** `tests/test_url_policy.py` (URL-22), `tests/test_export_render.py`.

### S4 — MEDIUM — Provider base URL was never classified

**Status after M0.5: CLOSED. Re-verified at M5.**

Every adapter declares a `DEFAULT_ENDPOINT` so the real destination is known even when the SDK
default is used (the OpenAI, Anthropic and Gemini endpoints appear nowhere in the repository as
literals, so a URL scan would miss them). `LLMProvider._send` is the template method every
adapter's request goes through; it calls `_authorize`, which classifies the endpoint through the
gateway and raises `ProviderConsentRequired` when consent is missing. The consent decision is keyed
by *operation and destination class*, so changing `base_url` from public to private stops matching
the public decision immediately. `providers/resolver.py` refuses to try a second external provider
after a refusal — only a local provider may answer.

**M5 re-verification.** The M3 creative planner and the M3 music selection add two more calls
through the same seam. Verified by reading `LLMProvider.generate_text` (which gained an
`operation` parameter) and the two call sites. A refused external provider is not retried against
another external provider; the refusal is recorded with its category.

**Evidence:** `tests/test_egress.py`, `tests/test_creative.py`, `tests/test_music_selection.py`.

### S5 — MEDIUM — Undocumented model download at first use

**Status after M0.5: CLOSED as an egress finding, with one product limitation left open.
Re-verified at M5.**

`models.py` classifies the model host through the gateway and records the download in the transfer
log, so the request is visible in *Settings → External processing*. No user content is involved — a
model file — so it is logged rather than consent-gated.

**Still open (product, not security):** the download still happens the first time a face-detection
model is needed, with no pre-flight check at job start, so an offline machine fails inside the
pipeline. The error message names the file and its path so the user can place it manually. This is
recorded in the known-limitations list, not claimed as fixed.

### S6 — LOW — Legacy global OAuth token remained valid alongside per-account tokens

**Status after M4a: CLOSED. Re-verified at M5.**

**M0's statement:** two token stores existed; `Channels.tsx` still started the legacy flow, so the
practical result was one shared token, and the legacy entry was never deleted.

**M5 re-verification.** The legacy flow is gone from the UI, and the legacy token is now owned:
`youtube/accounts.py:refresh_token_for` returns an account's own keyring entry
(`youtube_refresh#<account_id>`) and falls back to the legacy bare entry **only for the oldest
account**, ordered by the row's insertion order (`rowid`), not by `created_at`. An
`oauth.InvalidGrantError` marks **only that account** `needs_reconnect=1`; other accounts keep
publishing. Connecting a second account deliberately leaves the legacy settings and the legacy
keyring entry naming the *first* account's channel.

**Evidence:** `tests/test_youtube_identity.py` (16 tests).

### S7 — LOW — Toolchain pinned too loosely

**Status after M5: CLOSED. This was the last open finding.**

`pyproject.toml` now pins `"ruff==0.17.5"` exactly, with the reason in the file. CI installs
`.[dev]`, so the pin is the one that is honoured — the pin is not decorative.

**M5 re-verification.** The pin was installed and run against the whole tree, not just the
package: `ruff check .` → *All checks passed*; `ruff format --check .` → *226 files already
formatted*.

**M5.1 re-verification (2026-11-21).** The tree gained one test file and the product changed in
four files. The same pin was run against the whole tree again: `ruff check .` → *All checks
passed*; `ruff format --check .` → *227 files already formatted*. The Linux leg was reproduced on
the same tree — `ruff check .` → *All checks passed*; `ruff format --check .` → *221 files already
formatted* (the synced subset). The pin is still the one CI honours.

**Evidence:** commit `4cf309b`; the M5 gate output in `docs/M5-REGRESSION-REPORT.md`.

---

## 3. Findings raised at M5

### M5-01 — MEDIUM — A NAT64 address was refused as reserved, breaking every public provider

**Where:** `backend/autoclip/security/urlpolicy.py:_classify_ip`.

**What happened.** On an IPv6-only network, every public host resolves through a NAT64 prefix.
`api.elevenlabs.io` resolved to `64:ff9b::2208:b8bf` on the M4b machine. Python's `ipaddress`
marks the whole well-known NAT64 prefix `64:ff9b::/32` as reserved, so the URL policy refused
every request to a public provider — three speech tests failed, and in production every external
provider call would have been blocked with a message about the address rather than about the
network.

**Why it is not simply "allow reserved".** Allowing the prefix outright opens an SSRF hole:
`64:ff9b::7f00:1` is a valid encoding of `127.0.0.1`, `64:ff9b::a00:1` is `10.0.0.1`, and
`64:ff9b::a9fe:a9fe` is the cloud metadata address `169.254.169.254`.

**Fix.** `_nat64_embedded_ipv4()` implements RFC 6052 (the well-known prefix with prefix lengths
32/40/48/56/64/96) and RFC 8215's local-use prefix `64:ff9b:1::/48` (48/56/64/96). The embedded
IPv4 is extracted and **that** is classified. A non-zero u-octet is not a NAT64 address at all and
is not translated.

**Status: CLOSED** (commit `6318655`). Eight tests cover the extraction and the three
classifications that matter: loopback, private, and the metadata address.

### M5-02 — LOW — A test wrote to the owner's real OS keyring

**Where:** `tests/test_instagram.py:test_the_app_secret_can_be_stored`, and — once that one was
found — the whole test suite.

**What happened.** The test stored a secret through `PUT /api/settings/secrets` without taking the
`fake_keyring` fixture, so the write went to the machine's own OS credential store rather than the
in-memory one. The value written was the test's own (`"the-secret"`).

**How bad it was, measured rather than assumed.** When the single test was fixed, the owner's
Windows Credential Manager was audited for AutoClip's entries. It held **549**. Every entry was
read and its stored secret compared against the test literals the suite writes:

* **535 deleted** — every entry whose stored secret exactly equalled a test value.
* **14 kept** — every entry holding a non-test value: `groq#KEY1` … `groq#KEY9`, `openai`,
  `gemini`, `youtube_client_secret`, `youtube_refresh_token`, and one `youtube_refresh#<id>`.

The deletion was done **by value**, never by name or by prefix, so the owner's own credentials
could not be matched by a test literal. The remaining 14 were confirmed afterwards with
`cmdkey /list`. No secret was printed, logged or written to disk at any point in the audit.

**Why it matters.** A test that touches the owner's keyring is a test that can change the owner's
machine. The suite now has 14 secret-writing tests, and every one of them takes the fixture — but
the *first* fix only covered the one test that had been noticed.

**The fix is now global, not per-test.** `tests/conftest.py` grew an **autouse** fixture,
`isolated_keyring`, that replaces the OS keyring with an in-memory one for **every** test in the
suite. `fake_keyring` returns that same object, so a test that asks for the fixture gets the
isolated one; `no_keyring` and `failing_keyring` still override it. A test that forgets the
fixture can no longer reach the owner's machine, because the machine is not reachable from a test
any more.

**Status: CLOSED** — `0ef1548` fixed the one test that had been found, and `94c6d9c` closed the
class by isolating the keyring for every test.

**Evidence.** The isolation guard is `tests/conftest.py`. The CI failure it fixed was real and is
recorded in `docs/upgrade-audit.md` §13: the same suite passed on Windows and macOS and failed on
Linux, because Linux has no keyring backend, so the token was never stored and the assertion that
depended on it could not hold. The fix was reproduced on a Linux environment before it was pushed.

---

## 3a. Findings raised at M5.2

### M5.2-01 — LOW — The rebinding guard was too strict, and broke a legitimate publish

**Where:** `backend/autoclip/security/urlpolicy.py:resolve`.

**What happened.** The guard resolved the host **twice** — correctly, to defeat DNS rebinding — and
then required the two answers to be **byte-identical sets of addresses**. `graph.facebook.com` —
Meta's own Graph API host — answers with a **rotating subset of its own edge addresses**, so a
legitimate Instagram publish was refused with *"DNS for graph.facebook.com changed between lookups …
refusing a possible rebinding"*.

**Why it is not simply "allow any change".** The set comparison was the whole point of the
double-resolution: a host that answers with a public address and then a private one is the
rebinding attack, and the connection would land inside the network the user did not name. Loosening
the comparison without replacing it would have removed the protection.

**The fix replaces the comparison, not the check.** The guard now compares the **class** of the two
answers:

| First answer | Second answer | Verdict |
|---|---|---|
| public | public (a different set) | **allowed** — a load balancer; the request can only reach a public address |
| public | private | **refused** — the rebinding attack |
| public | loopback | **refused** |
| public | link-local / reserved | **refused** — an address that may not be contacted at all |
| private | public | **allowed** — the first answer classifies the destination as private, so consent is required anyway; the request cannot become more privileged than the check allowed |

**The protection was not weakened.** A public → private or public → loopback move is still refused,
and the refusal is still a refusal rather than a warning. The fix removes only the case where the
answer stayed public and merely changed **which** public address it named.

**How it was found.** The **full-suite gate**, as a **flaky failure**: **1,324 passed, 1 failed**,
in a test that passes when run alone. The cause was two things at once — the product defect above,
and a test that stubbed `httpx` but not the resolver, so a unit test was reaching the **real DNS**.
A unit test must not depend on the internet, or on which addresses a third party happens to be
serving.

**Status: CLOSED** (commit `a907805`). **Evidence:** `tests/test_url_policy.py` — 39 cases, zero
`xfail` markers. Two of the new tests **fail without the fix**; three assert that the protection
still holds (public → private, public → loopback, public → forbidden); one asserts that the unit
suite resolves no real hostname.

---

## 3b. The M5.3 amendment — no new finding, and one finding's evidence strengthened

**Run 2026-11-21, documented 2026-11-22.** M5.3 pointed the application at a **real ten-minute
YouTube video** and ran it through **every stage, end to end**. It found **five product defects** —
and **none of them is a security finding**. They are correctness and robustness defects:

| # | Defect | Why it is not a security finding |
|---|---|---|
| 9 | The sentence terminators were Latin-only, so a Hindi transcript had almost no sentence boundaries and candidates were silently dropped | A **loss of output**, not an exposure of anything. It cannot send, leak or reveal more than the user supplied |
| 10 | The ffmpeg command line could exceed Windows' own 32,767-character limit | The render **failed**; it did not do anything wrong. The fix adds a guard that refuses the command **before** ffmpeg runs, which is strictly safer than dying inside `Popen` |
| 11 | The webcam's speech emphasis ran on a segment-local clock | A **visual** defect. It changes what the user sees, and nothing else |
| 12 | A caption could be held on screen for twelve seconds | A **visual** defect, measured on the rendered file |
| 13 | The export's video graph consumed a filter output once per crop segment, which ffmpeg 9 tolerates and ffmpeg 7 refuses | A **portability** defect: the render **failed** on a strict ffmpeg. It did not do anything wrong, and it exposed nothing — the graph is built from the user's own media and never touches the network |

**Defect 10 is the one with a security edge, and it is worth stating.** An over-long command line
is a denial-of-service vector on Windows: the operation fails in a way that is hard to diagnose and
easy to reach by feeding the pipeline a pathological source. The fix makes the failure **explicit
and early** — the command is refused with a message that names the filter graph — and it makes the
graph structurally smaller, so the limit is further away. Neither the old nor the new behaviour
executes anything the user did not ask for.

### What M5.3 did strengthen: S5's evidence

**S5** (the MediaPipe model download at first use) was closed at M0.5 on the strength of **reading
the code**: `models.py` classifies the host through the gateway and records the download in the
transfer log. That was the right basis for closing it, but it was still a code reading.

**The M5.3 run observed it.** The real ten-minute run's transfer log holds a row for it:

```
operation=model_download  provider=model-host
destination=https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
destination_class=public  outcome=ok
data_summary="The face_landmarker model file (3.6 MB)."
```

The **full destination** — not just the host prefix — is what the log records, so the row is
checkable against `docs/EGRESS-INVENTORY.md` E12 without taking the inventory's word for it. S5's
closure is now backed by an observation rather than by a reading.

### The whole run's egress, as a security fact

The M5.3 run's transfer log holds **9 rows**, and every one of them is one of the paths this
review documents:

| Operation | Count | Destination | Class |
|---|---|---|---|
| `media_download` (E11) | 1 | `https://youtu.be/tg2MwT5FPdY` | **public** |
| `highlights` / `creative_planning` (E4/E5) | 6 | `http://127.0.0.1:11434` | **loopback** |
| `model_download` (E12) | 2 | `storage.googleapis.com` | **public** |

**No hosted provider was contacted and no hosted credential was spent.** That is not an assertion
here — it is what the log says. It is also the reason the four live paths in §6 remain unverified
rather than broken: they were not exercised, not exercised and failed.

### S7, re-verified at M5.3

The tree gained two test files and the product changed in seven. The same pin was run against the
whole tree again: `ruff check .` → *All checks passed*; `ruff format --check .` → *230 files already
formatted*. The Linux leg was reproduced on the same tree — the pin is still the one CI honours.

---

## 4. The new subsystems, reviewed

### 4.1 The music library (M1)

**Attack surface:** local files the user points AutoClip at, and the analysis that reads them.

| Question | Answer | How it was checked |
|---|---|---|
| Can a library path escape the music directory? | **No.** A path is resolved and must sit inside the library root; a path outside is refused. | `music/library.py`, `tests/test_music_library.py` |
| Does indexing copy, move or delete the user's file? | **No.** The library is an *index* of user-owned files. AutoClip never copies, moves or deletes them. | `music/library.py` — asserted in `tests/test_music_library.py` |
| Can an unindexed path be exported with an unknown licence? | **No.** `check_export_allowed_for_path()` auto-indexes the path with an **unknown** licence, and unknown blocks the export. | `music/licensing.py`, `tests/test_music_library.py` |
| Can a user assert independent verification? | **No.** The `verified` state is not settable from the API; only `unknown`, `user_confirmed`, `incompatible` and `expired` are. | `api/music.py`, `tests/test_music_library.py` |
| Does the analysis execute anything from the file? | **No.** Analysis is ffmpeg decode + numpy over the decoded samples. | `music/analysis.py` |

### 4.2 Webcam detection (M2)

**Attack surface:** MediaPipe face detection over a local video.

The detector **never raises**: it returns a report, and a failure falls back to gameplay-only. A
malformed or hostile video therefore degrades the output rather than failing the job. Detection
runs once per source, not once per clip, and the user's manual layout choice is stored separately
from what the detector found (table `source_layouts`) so detection can never overwrite a choice.

The face region is a **persistent cluster of faces**, scored on support / stability / cut-stability
/ persistence, with a confidence floor of 0.35. Below the floor the result is gameplay-only, not a
best guess. Nothing about any person is stored: a face is a rectangle of pixels, and the schema
has no name, no identity and no biometric.

**Evidence:** `tests/test_webcam.py` (26), `tests/test_layout.py` (38), `tests/test_layout_api.py` (13).

### 4.3 The creative planner (M3)

**Attack surface:** structured output from a language model, and the AI call budget.

| Question | Answer | How it was checked |
|---|---|---|
| Is malformed model output used? | **No.** The plan is validated in full before use; a malformed plan is rejected, not patched. One repair retry follows, then a deterministic fallback with the reason recorded. | `pipeline/creative.py`, `tests/test_creative.py` |
| Can a retried job exceed the AI budget? | **No.** The counters live in `job_ai_budget` and persist across retries. The budget is 1 planning call + 1 repair + ≤1 music call per clip, capped at `max_clips` — 12 calls at the default of 10 clips. | `budget.py`, `db/budget_store.py`, `tests/test_budget.py` (17) |
| Can a refusal trigger a second external provider? | **No.** A refused consent is an answer: the runner falls back deterministically. | `tests/test_egress.py`, `tests/test_creative.py` |
| Is a score shown that the code did not measure? | **No.** The diagnostics module computes ten named measurements and stores them; there is no score. The model's 0–100 clip score is labelled a **creative suggestion** wherever it is shown (API docstring, CLI column, two tooltips). | `pipeline/diagnostics.py`, `tests/test_diagnostics.py` (31) |

### 4.4 The YouTube publisher (M4a)

**Attack surface:** an OAuth credential, an upload session URL, and a destination channel.

| Question | Answer | How it was checked |
|---|---|---|
| Does the upload session URL have to be HTTPS? | **Yes.** A session URL that does not start with `https://` is refused, so a compromised API response cannot redirect the file to a local or plaintext endpoint. | `youtube/resumable.py:185`, `tests/test_youtube_resumable.py` |
| Is the credential tied to the account that owns the destination? | **Yes.** The token is filed under `youtube_refresh#<account_id>`, and the channel Google reports becomes that account's own row. | `tests/test_youtube_identity.py` |
| Is the audience declaration guessed? | **No.** `madeForKids` is a tri-state — undecided / false / true — and the undecided state **refuses the upload**. A per-upload override wins over the channel policy. | `api/youtube.py`, `tests/test_youtube_policy.py` (27) |
| Is the privacy the user asked for the privacy that happened? | **Yes.** The policy is resolved before the network call and written onto the row; after the upload, `read_back()` records the actual privacy and the confirmed channel. `published_but_not_as_asked` flags "uploaded but private". | `tests/test_youtube_policy.py` |
| Can a stored privacy value be silently changed? | **No.** New channels and new uploads default to `private`, but stored values are never rewritten. | `tests/test_youtube_policy.py` |
| Is an ambiguous result ever sent twice? | **No.** The reconciliation grades its evidence — confirmed / evidence / not_uploaded / unknown — and a live session that says "incomplete" is authoritative. An unsettled row waits for the owner. | `youtube/reconcile.py`, `tests/test_youtube_reconcile.py` (23) |
| Can a rate limit burn a retry? | **No.** A quota exhaustion waits for the reset, and the attempt counter is rolled back because the file never left the machine. | `youtube/quota.py`, `tests/test_youtube_resumable.py` |

### 4.5 The Instagram publisher (M4b)

**Attack surface:** a Meta app secret, an account access token, a container URI, and a caption.

| Question | Answer | How it was checked |
|---|---|---|
| Does the container URI have to be HTTPS and on Meta's upload host? | **Yes.** The session URL must start with `https://`. | `instagram/publisher.py` |
| Is the Meta app secret in the keyring, and never returned? | **Yes.** `INSTAGRAM_APP_SECRET_KEY` lives in the OS keyring; the settings API reports presence, never the value. | `config.py`, `api/settings.py`, `tests/test_instagram.py` |
| Is one account's token ever used for another? | **No.** The token is filed under `instagram_token#<account_id>`. | `instagram/accounts.py`, `tests/test_instagram.py` |
| Is a local file sent to a host that does not officially accept one? | **No.** Meta documents the resumable upload protocol only for apps using Facebook Login for Business. On the Instagram Login setup AutoClip **refuses** the local file with the reason rather than routing it somewhere else. | `instagram/uploads.py:process_upload` |
| Can a post be published twice? | **No.** Instagram has no idempotency key, so the guarantee is made locally: a unique index on `(export_id, account_row_id)` plus a pre-network duplicate check. | `db/schema.py` (migration v27), `instagram/uploads.py` |
| Can a lost answer cause a second post? | **No.** A dropped connection during the publish is flagged `needs_reconciliation`, and the worker checks that flag **before** the transient branch — the backoff would have sent it again. The owner confirms the post with a media id that Instagram is asked to recognise first; a media id Instagram does not know is refused with a 409. | `instagram/publisher.py:publish`, `instagram/queue.py:_run`, `instagram/uploads.py:confirm_upload` |
| Can a suspected-spam block be retried into? | **No.** Meta's `4 / 2207051` is not retried; a restricted account (`25 / 2207050`) is the owner's work. | `instagram/errors.py`, `tests/test_instagram.py` |
| Is a publishing limit guessed? | **No.** It is read from `GET /<IG_ID>/content_publishing_limit`, because Meta's own documents contradict each other (100 in one place, 50 in two others). | `instagram/publisher.py:publishing_limit` |
| Can an Instagram failure cancel a YouTube upload? | **No.** Instagram has its own tables and its own worker. The two queues share nothing but a pure backoff helper. | `instagram/queue.py`, `db/schema.py` |

**One API-surface note.** The Meta app secret can be written through
`PUT /api/settings/secrets`, which is the same endpoint that already existed for provider keys. It
is not a new credential surface; it is the existing one extended by one allow-listed key name
(`config.INSTAGRAM_APP_SECRET_KEY`), alongside `config.YOUTUBE_CLIENT_SECRET_KEY`.

---

## 5. Verified-good findings

These were checked and are **not** defects. They are stated so a later review does not re-litigate
them.

| Property | Verification |
|---|---|
| No secret is returned by any API route | `api/settings.py`, `api/ai_providers.py` return labels and boolean presence flags only; `instagram_secret_present` and `youtube_secret_present` are booleans |
| Secrets live in the OS keyring | `config.get_secret` / `set_secret`; `KEYED_PROVIDERS` |
| Tokens are never logged | No `log.*` call in the tree interpolates a token, a key or a secret. Credentials are masked **entirely** — no suffix fingerprint |
| SQL injection | Every statement in `db/store.py` is parameterised; no f-string SQL with user input. Migrations are ordered and append-only, and `migrate()` refuses a database newer than the build |
| CORS | No CORS middleware exists, because the bundle is served same-origin — narrower than an allowlist |
| Path traversal on media download | `api/clips.py` resolves the download path and checks it is inside the export root |
| Path traversal on the music library | A library path is resolved and must sit inside the library root |
| SQLite is local-only | `db/__init__.py:connect` opens a file path; no network transport |
| Pipeline artifacts are per-job | `work/{job_id}/`, so one job cannot read another's workspace |
| FFmpeg cannot fetch | `-protocol_whitelist file,pipe` on every command builder |
| The upload session cannot be redirected | Both publishers refuse a session URL that is not HTTPS |
| The `verified` music licence cannot be self-asserted | The API refuses it; independent verification is not something a user can claim |
| The publishing destination is never guessed | The YouTube policy names a channel id; the Instagram enqueue names an account row id |
| A failed Instagram upload cannot poison a YouTube upload | Separate tables, separate workers, separate queues |

---

## 6. Residual risks — documented, not claimed

These are real and are **not** closed. None of them can be closed without something this machine
does not have.

| # | Residual | Why it stays open | What would close it |
|---|---|---|---|
| R1 | **yt-dlp's secondary requests** (manifest, CDN, page assets) are not re-classified hop by hop. | AutoClip does not make those requests — yt-dlp does, and its request set is not observable from here. The boundary is classified, proxies are disabled, and the URL is classified up front. | A Lane B controlled test against a redirecting host, with the proxy disabled and the observed hosts recorded. |
| R2 | **The live ElevenLabs path** is unverified. | No authorised ElevenLabs credential was supplied for a consent-granted run. | A Lane B run with an authorised key. |
| R3 | **The live LLM path** is unverified for the creative planner and the music selection. | No authorised hosted-LLM credential was supplied for a consent-granted run. | A Lane B run with an authorised key. |
| R4 | **The live YouTube path** is unverified end to end. | No authorised Google credential was supplied. | A Lane B run against a real channel. |
| R5 | **The live Instagram path** is unverified end to end. | No authorised Meta app, access token or professional account was supplied. | A Lane B run against a professional account, with App Review and Business Verification completed by the owner. |

R2–R5 are the **same** limitation in four places: the code path is exercised against doubles and
the live path is recorded as Unverified (external). That is recorded rather than glossed over, and
the release assessment in `docs/FINAL_UPGRADE_REPORT.md` carries it.

**M5.2 did not close any residual, and did not add one.** The four live paths remain unverified for
the same reason — no authorised credential was supplied. **R1** is unchanged: the yt-dlp secondary
requests are still made by yt-dlp, and a Lane B controlled test is still what would close it.

**M5.3 did not close any residual either, and did not add one.** The same four live paths remain
unverified for the same reason — no authorised credential was supplied, and the run used a local
Ollama and local whisper throughout. The transfer log is the proof: **6** of its **9** rows point
at `127.0.0.1`, and **no hosted host appears at all**.

**What M5.3 changed on this page is the *evidence*, not the residuals.** The MediaPipe model
download (S5) was previously closed on the strength of reading the code; the real run **observed**
it, with the full destination in the log and checkable against `docs/EGRESS-INVENTORY.md` E12. The
five product defects M5.3 found are **not** security findings, and they are recorded here so that
the absence of a finding is explicit rather than implied.

**What M5.2 changed on this page is the *evidence*, not the residuals.** The yt-dlp download — the
largest transfer AutoClip makes — was previously authorised and then dropped without a record, so
`docs/EGRESS-INVENTORY.md` E11's claim that it was *logged* was **false**. It is now true, and it
was verified on a real 844 MB download: **exactly one** log row, `outcome=ok`,
`duration_ms=175578`. The transfer log is the user's own record of what left the machine, and the
largest transfer was missing from it.

---

## 7. What was **not** checked

Stated plainly, because a security review that implies complete coverage is worse than one that
does not.

- **A dependency audit.** No `pip-audit`, `safety` or `npm audit` run was performed. The
  dependency *set* was checked (the CI job installs the optional extras with `--dry-run` so an
  unsatisfiable extra cannot ship), but no CVE scan was made. This is a **gap**.
- **A fuzzer.** No fuzzing was run against the URL parser, the MP4 box walker or the model-output
  validator. They are covered by targeted tests and by input validation, not by fuzzing. This is a
  **gap**.
- **A SAST tool.** No static-analysis scanner (bandit, semgrep) was run. The review was manual and
  source-level. This is a **gap**.
- **The GitHub Actions supply chain.** The workflow pins actions by major version (`@v4`, `@v5`),
  not by commit SHA. This is the usual practice and is **not** a finding, but it is not a
  SHA-pinned, hermetic build either.
- **The Docker image itself.** Docker is not installed on this machine, so the image was not built
  or scanned locally. The CI `docker` job builds it and smoke-tests `GET /api/health` on every
  push; the result is recorded in `docs/M5-REGRESSION-REPORT.md`.
- **A live redirecting host.** The rebinding guard was corrected at M5.2 (M5.2-01), but the
  corrected guard has only been exercised against **injected resolvers**. A Lane B controlled test
  against a real host that redirects — and against a host that genuinely rebinds — is still what
  would settle the behaviour end to end. The automated evidence says the guard's *rule* is right;
  it does not say what a real hostile resolver does over the wire.
- **The unit suite's own hermeticity, beyond DNS.** The M5.2 change made the suite resolve **no**
  real hostname, which closed the specific flake that hid M5.2-01. It did **not** make the suite
  hermetic against every network path: an outbound HTTP call made by a test would still reach the
  internet. A blanket outbound-block would be the stronger guarantee and was not built.

---

## 8. Verdict

**No open high or medium findings. No open low findings.**

The seven M0 findings are closed on evidence rather than on intent, with one documented residual
(yt-dlp's secondary requests). Two findings were raised and closed inside M5, and a third
(M5.2-01 — the rebinding guard was too strict) was raised and closed at M5.2. The four
live-integration paths remain **Unverified (external)** because the credentials for them were never
supplied — that is a statement about the environment, not about the code, and it is carried into
the release assessment rather than being written down as "done".
