# External platform constraints

**Rule:** every external fact here is either **verified** against current official documentation on
the stated date, or explicitly **unverified**. Nothing is asserted from memory. The application must
detect and explain each constraint rather than failing silently.

Last reviewed: **2026-11-19**.

---

## G1 — Google OAuth "Testing" refresh tokens expire

**Fact (unverified — documentation not reached from this environment):** Google documents that an
OAuth consent screen left in *Testing* publishing status issues refresh tokens that expire after a
short window (commonly cited as 7 days).

**Status:** `Unverified: external compliance requirement incomplete`. I could not reach
`developers.google.com` from the build environment to confirm the current window.

**How the app must behave regardless:**
- A refresh attempt that returns `invalid_grant` marks **that account only** as
  "needs re-authorisation".
- Other accounts keep working; the blocked account raises one actionable notification.
- The account is never silently retried in a loop.

**Current behaviour:** `youtube/oauth.py` surfaces the token error, but there is no per-account
"needs re-authorisation" state and no isolation of one failing account from the rest. **Gap.**

**Owner milestone:** M4a.

**Owner action required:** publish the OAuth app (or accept weekly re-consent), and add test users.

---

## G2 — API uploads may be forced private on unaudited projects

**Fact (unverified — documentation not reached):** videos uploaded through the YouTube Data API from
projects that have not passed YouTube's API compliance audit may be forced to `private`, regardless
of the requested privacy status.

**Status:** `Unverified: external compliance requirement incomplete`.

**How the app must behave regardless:**
- After an upload, read the video back and compare the actual `privacyStatus` with the requested one.
- If it differs, report plainly: *"Uploaded but private — your Google Cloud project has not completed
  YouTube's API compliance audit."*
- Never present such an upload as published.

**Current behaviour:** no read-back, no comparison, no such message. **Gap.**

**Owner milestone:** M4a.

**Owner action required:** complete YouTube's API compliance audit if public autonomous publishing is
wanted.

---

## G3 — Minimum OAuth scopes

**Fact (verified from the code, not from Google):** the app requests `youtube.upload` and
`youtube.readonly` only (`youtube/oauth.py:SCOPES`).

**Status:** `Verified` — this is a property of the repository.

**Consequence:** Analytics collection would need `yt-analytics.readonly`, which is **out of scope**
under the M0–M5 specification. Existing grants therefore do **not** need re-consent for this
upgrade, which removes one blocker the earlier specification had.

---

## G4 — yt-dlp breaks when YouTube changes

**Fact:** yt-dlp's extraction is coupled to YouTube's private web client and breaks periodically.

**Status:** `Verified` as a class of failure (it is a historical, observable pattern); the specific
current breakage is not asserted.

**How the app must behave:**
- Classify download failures (bot check, unsupported URL, extraction error, network error).
- Show an actionable "update yt-dlp" message for extraction failures.
- Never mark a download successful without a verified, probeable file.

**Current behaviour:** `pipeline/ingest.py` classifies stderr patterns and keeps partial files
between retries; `_probe_and_validate` verifies the file. Partially covered. The "update yt-dlp"
action is not surfaced in the UI. **Partial.**

**Owner milestone:** M0.5 (surfacing) / M5 (verification).

---

## G5 — Proxy environment variables are honoured implicitly

**Fact (verified in this repository's dependency behaviour, and in yt-dlp's documented behaviour):**
yt-dlp and `urllib`/`httpx` honour `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY` from the
environment. AutoClip neither sets nor clears them.

**Status:** `Verified` as behaviour that exists; not documented to the user.

**Consequence for SSRF:** a proxy turns every destination into "the proxy's destination". The URL
policy must either disable proxying or classify the proxy itself.

**Owner milestone:** M0.5.

---

## G6 — ElevenLabs Scribe uploads the whole audio file

**Fact (verified in code):** `speech/elevenlabs.py` posts the extracted `audio.wav`.

**Status:** `Verified` from `backend/autoclip/speech/elevenlabs.py`.

**Consequence:** the transfer is the entire source audio, not a sample. Consent copy must say so.

---

## G7 — FreeLLMAPI contract

**Fact (verified from the upstream repository present on this machine at
`git_other_projects\freellm\docs\en\api\01-rest-api.md`, read 2026-11-19):**

- OpenAI-compatible surface; any OpenAI-compatible client works.
- Default base URL `http://localhost:3001/v1`.
- Auth: unified key from the dashboard, as `Authorization: Bearer <freellmapi-…>`.
- Model selection: `model: "auto"` or `auto:<profile>`.
- `GET /v1/usage` reports monthly usage; unified-key-only auth.
- Self-hosted by design; `freellmapi.co` is the **catalogue**, not an inference endpoint.

**Status:** `Verified against upstream documentation in-repo`. **Live probe impossible** — no
credential supplied, so runtime behaviour is `Unverified`.

**Consequence for AutoClip:** the `freellmapi` preset correctly has `default_base_url=None` and must
remain user-configured. Its base URL is loopback in the common case, so it classifies as **loopback**
and needs no external consent — but the gateway must still log it, and must not assume loopback
because the *name* suggests it.

**Owner milestone:** M0.5 (classification/logging). No functional integration work is in scope.

---

## G8 — M0.5 / M1 / M3 provider and consent prerequisites

**Fact:** live provider verification needs credentials the agent must not invent.

**Status:** `Blocked by missing credentials` for Lane B.

**What is needed from the owner, stated exactly:**
1. An **ElevenLabs test key** (a key that may be used for STT and, if voiceover is tested, TTS).
2. **One hosted LLM provider key** on a provider already supported by a preset (for example OpenAI,
   Anthropic, Groq or Together).
3. Confirmation that those keys may be used for automated test calls, and a spend ceiling if the
   provider bills per call.

Until supplied, every ElevenLabs / hosted-LLM behaviour is verified only against fake endpoints and
is reported as `Automated test verified`, never as external integration verified.

---

## G9 — Instagram publishing eligibility

**Fact (unverified — Meta documentation not reached from this environment):** publishing requires a
Meta app with the relevant permissions granted through app review, plus an Instagram **professional**
account linked to a Facebook Page. Rate limits and media constraints apply per account.

**Status:** `Unverified: external compliance requirement incomplete`.

**Consequence:** M4b can implement the official flow and verify it against fake endpoints, but cannot
claim live publishing. That will be reported as `Blocked` until the owner confirms eligibility.

**Owner action required:** confirm whether a professional account and an approved Meta app exist. If
not, M4b delivers a documented, disabled integration rather than a live one.

---

## Summary table

| ID | Constraint | Verified? | Blocks |
|---|---|---|---|
| G1 | Testing-mode refresh tokens expire | Unverified (doc unreachable) | M4a live |
| G2 | Unaudited project ⇒ forced private | Unverified (doc unreachable) | M4a live public |
| G3 | Minimum scopes are upload+readonly | **Verified (code)** | Nothing (analytics out of scope) |
| G4 | yt-dlp breaks on YouTube changes | Verified (class) | M0.5 messaging |
| G5 | Proxy env vars honoured | Verified | M0.5 SSRF |
| G6 | Scribe uploads whole audio | **Verified (code)** | M0.5 consent copy |
| G7 | FreeLLMAPI is OpenAI-compatible, localhost by default | **Verified (upstream docs)** | Runtime `Unverified` |
| G8 | Provider credentials | Blocked — none supplied | Lane B for M0.5–M3 |
| G9 | Instagram eligibility | Unverified | M4b live |
