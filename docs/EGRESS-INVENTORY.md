# AutoClip — Egress Inventory (M0)

**Audited:** 2026-11-19 against `feature/upgrade-u0-u10`.
**Method:** every outbound destination was extracted from the source (`Select-String` over
`backend/autoclip/**/*.py` for `https?://`), then each call site was read. Nothing here is inferred
from documentation.

## Destination classes

| Class | Definition | Consent rule (target for M0.5) |
|---|---|---|
| **Loopback** | Resolves to `127.0.0.0/8`, `::1`, or `localhost`. | No external consent required. Activity still logged. The UI warns that a localhost tunnel or reverse proxy can forward traffic off-machine. |
| **Private network** | Resolves to RFC1918, CGNAT, link-local, or ULA addresses, including a public hostname that resolves to a private address. | Explicit consent required. |
| **Public network** | Everything else, **including a hostname that does not resolve**. | Explicit consent required. |
| **File / process** | Local filesystem or subprocess, no network. | Not consent-gated; still logged for diagnostics. |

Classification must be recomputed whenever `base_url` changes **or** the DNS answer changes.

**M0.5 status:** classification is now implemented in
`backend/autoclip/security/urlpolicy.py` and applied by the gateway on every
request. The target rule in the table above is the rule that runs.

---

## 1. External AI and speech transfers

### E1 — ElevenLabs speech-to-text (transcription)

| Field | Value |
|---|---|
| Component | `speech/elevenlabs.py:ElevenLabsSTT.transcribe` |
| Destination | `https://api.elevenlabs.io/v1/speech-to-text` — **public** |
| Data transferred | The extracted `audio.wav` for the whole source, upload as multipart; the response contains the transcript |
| Trigger | Pipeline `transcribe` stage when `settings.transcription.engine` is `"elevenlabs"`, or `"auto"` **and** an ElevenLabs key resolves from the keyring |
| Consent | **Enforced (M0.5).** The upload is refused unless the `transcription` operation has a granted decision for the `public` class. A missing decision raises `SpeechConsentDenied`. |
| Credential | ElevenLabs API key from the OS keyring (`config.ELEVENLABS_API_KEY = "elevenlabs"`), sent in a header |
| Logging | Logs HTTP status and the error body on failure. Does not log the key. Does not log audio content. The transfer itself is recorded in `egress_log` with a description, never the audio. |
| Failure | Raises `SpeechError` with the status and body. Under `auto`, `runner.py` falls back to local Whisper and records a notice. Under `elevenlabs` (pinned), the job fails. |
| Fallback invented? | No. Verified in `speech/base.py:resolve_engine` and `pipeline/runner.py:366-404`. |

**Important nuance.** Under `auto`, the *fallback* is local, but the *preference* is external: if a
key exists, audio is uploaded first. So the presence of a key silently changes whether media leaves
the machine.

### E2 — ElevenLabs text-to-speech (voiceover)

| Field | Value |
|---|---|
| Component | `speech/tts.py:synthesize_speech` |
| Destination | `https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` — **public** |
| Data transferred | The narration **text** generated for a clip (derived from the transcript) |
| Trigger | Export stage, per clip, when `settings.transcription.voiceover == "muxed"` (`runner.py:723-746`). Off by default. |
| Consent | **Enforced (M0.5).** The `voiceover` operation needs a granted decision for the `public` class. |
| Credential | ElevenLabs API key (keyring) |
| Logging | Status only; the transfer is recorded in `egress_log`. |
| Failure | Logged; the clip is exported without narration rather than failing the export (`runner.py` returns `destination`) |

### E3 — ElevenLabs subscription probe

| Field | Value |
|---|---|
| Component | `api/settings.py:160-178` (speech/entitlement status route; it calls ElevenLabs directly rather than through `speech/tts.py`) |
| Destination | `https://api.elevenlabs.io/v1/user/subscription` — **public** |
| Data | No user content; account/entitlement metadata response |
| Trigger | Status/entitlement display |
| Consent | Not content-bearing, but still a public request and must be logged |

### E4 — LLM provider highlight detection / chat

| Field | Value |
|---|---|
| Components | `providers/openai_provider.py`, `anthropic_provider.py`, `gemini_provider.py`; used from `pipeline/highlights.py` and `chat/agent.py` |
| Destination | The resolved `base_url` for the active preset. **Nine presets hardcode a public host** (`openrouter.ai/api/v1`, `api.groq.com/openai/v1`, `api.cerebras.ai/v1`, `api.deepseek.com/v1`, `api.mistral.ai/v1`, `api.together.xyz/v1`, `router.huggingface.co/v1`, `integrate.api.nvidia.com/v1`). **Three presets leave `default_base_url=None` and inherit the vendor SDK default**: `openai` → `api.openai.com/v1`, `anthropic` → `api.anthropic.com`, `gemini` → `generativelanguage.googleapis.com` — these hosts appear nowhere as a literal string in this repository, so an inventory built by grepping for URLs would miss them. **Four presets point at loopback** (`localhost:11434`, `:1234/v1`, `:8001/v1`, `:8080/v1`), and `freellmapi` is user-supplied. |
| Data transferred | Transcript windows (text), system prompt, and the user's `improve.txt` standing instructions (`providers/base.py:275`). **No video or audio is ever sent to an LLM provider** — verified: the provider interface accepts text only. |
| Trigger | Highlights stage; assistant; any ad-hoc AI task |
| Consent | **Enforced (M0.5).** The `highlights` operation needs a granted decision for the destination class — `public` or `private`. Loopback needs none. |
| Credential | Provider API key(s) from keyring, rotated by `keypool.py` |
| Logging | Request outcome and latency; no prompt content logged at info level. Debug logging of response errors is possible. The transfer is recorded in `egress_log`. |
| Failure | Retryable vs auth classification (`providers/base.py:looks_like_auth_failure/looks_like_transient_failure`); under the highlights stage a reachable local Ollama is used as fallback. A **consent refusal** is not a failure: it aborts the stage and no other external provider is tried. |
| Classification risk | **Addressed in M0.5.** Every adapter declares a `DEFAULT_ENDPOINT` (the vendor SDK defaults, which appear nowhere as literals), `LLMProvider._send` classifies the endpoint on every call, and the decision is keyed by class — so changing `base_url` from public to private stops matching the public decision. |

### E5 — Local model inference

| Field | Value |
|---|---|
| Component | `providers/ollama_provider.py`, and OpenAI-compatible presets pointed at loopback |
| Destination | `http://localhost:11434`, `:1234/v1`, `:8001/v1`, `:8080/v1` — **loopback** |
| Data | Transcript windows / prompts |
| Consent | None required, but must be logged, and the UI must warn that a tunnel can forward it |
| Failure | Health-checked before use as a fallback (`runner.py:_provider_healthy`) |

---

## 2. Google / YouTube transfers

### E6 — OAuth authorization redirect

| Field | Value |
|---|---|
| Component | `youtube/oauth.py:authorize_url` |
| Destination | `https://accounts.google.com/o/oauth2/v2/auth` — **public** (browser navigation) |
| Data | Client id, redirect URI, scopes, PKCE challenge, state |
| Trigger | User clicks Connect |
| Consent | The user is literally performing the action; still log the attempt |
| Scopes requested | `youtube.upload`, `youtube.readonly` (D12 — no analytics scope) |

### E7 — OAuth token exchange / refresh / revoke

| Field | Value |
|---|---|
| Component | `youtube/oauth.py:_post_token`, revocation |
| Destinations | `https://oauth2.googleapis.com/token`, `https://oauth2.googleapis.com/revoke` — **public** |
| Data | Authorization code + PKCE verifier, or refresh token; client secret |
| Credential | Google OAuth client secret from keyring (`config.YOUTUBE_CLIENT_SECRET_KEY`) |
| Logging | Must never log the code, verifier, refresh token or secret. Verified: no such logging exists. |

### E8 — Channel / video read

| Field | Value |
|---|---|
| Component | `youtube/accounts.py` (channel discovery), `youtube/uploads.py` (processing status) |
| Destinations | `https://www.googleapis.com/youtube/v3/channels`, `https://www.googleapis.com/youtube/v3/videos` — **public** |
| Data | Channel id / video id; response is channel or video metadata |
| Trigger | Connect, verification after upload |

### E9 — Video upload

| Field | Value |
|---|---|
| Component | `youtube/uploader.py:upload_video` (`:41`); the streaming PUT is at `:101-109` |
| Destination | `https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable` then the returned session URI — **public** |
| Data | The rendered clip (the whole file), metadata (title, description, tags, category), privacy status, `selfDeclaredMadeForKids` (currently hardcoded `False`, D4) |
| Trigger | Auto Upload effective-on, or a manual publish |
| Consent | Classified and logged (M0.5). Publishing is an explicit owner action, so it is not consent-gated, but it passes the gateway and appears in the transfer log. M4a must keep it explicit and never guess the audience declaration. |
| Credential | Per-account OAuth token — **in practice the legacy global token, because the UI cannot create a second account (D14)** |
| Logging | Status and error body; no content |
| Failure | `YouTubeError`; `process_upload` stores metadata before the call and marks the attempt failed; **no reconciliation** (D11) |
| Session URI | Not persisted. An interrupted upload cannot be resumed or queried. |

### E10 — Thumbnail upload

| Field | Value |
|---|---|
| Component | `youtube/uploader.py` (thumbnail) |
| Destination | `https://www.googleapis.com/upload/youtube/v3/thumbnails/set` — **public** |
| Data | The generated thumbnail image |

---

## 3. Media acquisition

### E11 — yt-dlp download

| Field | Value |
|---|---|
| Component | `pipeline/ingest.py:download` (`command.append(source.url)` at `:180`) |
| Destination | Whatever the user-supplied URL points at, **plus every host yt-dlp itself chooses** (manifest, CDN, page assets) — **public, unclassified** |
| Data | An HTTP GET of the page and media; the response is the video |
| Trigger | A YouTube source is processed |
| Consent | The user supplied the URL, but the *set of destinations* is not known in advance. Classified and logged (M0.5); a private destination is refused outright. |
| Validation | The URL is classified through the gateway before yt-dlp runs: scheme, every resolved address (IPv4 and IPv6), and the class. A private or link-local destination is refused. **M0.5 residual:** yt-dlp's own secondary requests (manifest, CDN, page assets) are made by yt-dlp and cannot be re-classified hop by hop; proxies are disabled (`--proxy ""`) and the boundary classification is enforced. A Lane B controlled test is still required before the secondary-request surface can be called verified. |
| Proxy | yt-dlp's proxy is disabled explicitly (`yt_dlp_hardening_args()` → `--proxy ""`), so `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` cannot redirect the fetch. |
| Failure | Classified by yt-dlp stderr patterns; partial files are kept between attempts |

### E12 — MediaPipe model download

| Field | Value |
|---|---|
| Component | `models.py:ensure` called from `pipeline/reframe/faces.py:113` and `cli.py:687` |
| Destination | `https://storage.googleapis.com/mediapipe-models/face_landmarker/...` — **public** |
| Data | A GET; the response is a `.task` model file cached locally |
| Trigger | First reframe that needs face detection, or `autoclip doctor` |
| Consent | Classified and logged (M0.5). No user content is involved — a model file — so it is logged rather than consent-gated. The first-run surprise remains open as a product limitation (M3 pre-flight). |
| Failure | `URLError`/timeout surfaces as `FaceDetectionUnavailable` → centre-crop fallback |

### E13 — Whisper model acquisition

faster-whisper fetches model weights from Hugging Face / its configured mirror on first use, and
WhisperX diarization needs a Hugging Face token (`transcribe.py:223`). This is a **public** transfer
of a model download (no user content). It is not consent-gated today and should be, because it is
the first-run surprise on a fresh install.

### E14 — YouTube trending chart (trends research)

| Field | Value |
|---|---|
| Component | `trends/research.py:34` (`TRENDING_URL`), request at `:207-212` |
| Destination | `https://www.googleapis.com/youtube/v3/videos?chart=mostPopular` — **public** |
| Data transferred | A GET with `part`, `chart=mostPopular`, `regionCode` and the caller's OAuth bearer token. **No user content** — no clip, transcript or identifier of the user's own video is sent |
| Trigger | User refreshes trends (`POST /api/trends/refresh`) or the trends page loads a staleness-expired cache |
| Consent | Classified and logged (M0.5). Read-only public-chart data, so the privacy stake is lower than E1/E2/E4, but it is still an outbound request carrying an OAuth token and it is now recorded in the transfer log. |
| Credential | The connected account's YouTube access token |
| Logging | Failure path logs `httpx.HTTPError`; no token logged |
| Failure | Returns a stale or empty trend list; never fabricates trending data |
| Cache | Results cached for 6 hours (`research.py`, freshness constant) |

**Why it was missed.** The M0 inventory was built by reading the eleven known transfer paths and
then grepping `https?://`. `TRENDING_URL` is a named constant assigned on its own line, so a scan for
literal `https://` call sites skipped it. This entry was added after an independent review.

---

## 4. Local process and file activity (not egress, logged for completeness)

| Activity | Detail |
|---|---|
| FFmpeg | Every invocation is a local subprocess over local files. Since M0.5 all three command builders pass `-protocol_whitelist file,pipe`, so FFmpeg cannot open `http`, `https`, `tcp`, `udp` or `rtmp`. |
| SQLite | `~/.autoclip/autoclip.db` |
| Artifacts | `work/{job_id}/`, `~/.autoclip/music/`, exports |
| Keyring | OS credential store |

---

## 5. Summary matrix

| ID | Destination class | User content leaves machine | Consent before M0.5 | M0.5 enforcement |
|---|---|---|---|---|
| E1 ElevenLabs STT | Public | **Yes — audio** | No | **Consent-gated** (`transcription` / public) + logged |
| E2 ElevenLabs TTS | Public | **Yes — narration text** | No | **Consent-gated** (`voiceover` / public) + logged |
| E3 ElevenLabs subscription | Public | No | No | Logged path; content-free probe |
| E4 LLM provider | Public / private / loopback, **now classified** | **Yes — transcript text** | No | **Consent-gated** (`highlights` / public + private) + logged; loopback always allowed |
| E5 Local model | Loopback | No | N/A | Allowed, logged |
| E6 OAuth authorize | Public (browser) | No | User action | Browser navigation; out of the gateway |
| E7 OAuth token | Public | No (credential) | N/A | Credential path; never logged |
| E8 YouTube read | Public | No | N/A | Read path |
| E9 YouTube upload | Public | **Yes — rendered clip** | User-initiated | Classified + logged; explicitly owner-controlled, M4a |
| E10 Thumbnail | Public | Yes — image | User-initiated | Part of the publish path, M4a |
| E11 yt-dlp | Public, **bounded at the boundary** | No (download) | No | Classified before the fetch; private refused; proxies disabled; logged. Secondary requests remain a documented residual |
| E12 MediaPipe model | Public | No | No | Classified + logged |
| E13 Whisper weights | Public | No | No | Third-party library fetch; recorded by the library, not by AutoClip |
| E14 YouTube trending chart | Public | No | No | Classified + logged |

**Every "No" in the old consent column is now either consent-gated or explicitly
logged.** The gateway covers E1, E2, E4, E9, E11, E12 and E14 — not only the new
AI features — and the transfer log (`egress_log`) records every governed
transfer with its destination class and outcome.

**Operations without user content are logged, not gated.** Model downloads, the
trending chart, source downloads and publishing carry no private content, so
requiring a decision for each would train the user to click through prompts.
The content-bearing operations — transcription, voiceover and AI analysis — are
the ones that ask.

## 6. Where the enforcement lives

| Concern | Module |
|---|---|
| Destination classification, redirect and DNS policy | `backend/autoclip/security/urlpolicy.py` |
| The single door every governed transfer passes through | `backend/autoclip/security/egress.py` |
| Consent decisions and the transfer log | `backend/autoclip/security/consent.py` |
| Storage (DB migration v15) | `egress_consents`, `egress_log` |
| User controls | `backend/autoclip/api/privacy.py` → *Settings → External processing* |
| Tests | `tests/test_url_policy.py` (26), `tests/test_egress.py` (23) |

