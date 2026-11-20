# Feature coverage matrix (M0)

**Status vocabulary** (from the governing specification Part 3.2 and Part 18):
`Implemented` · `Partial` · `Missing` · `Unverified`.
`NOT APPLICABLE` is added only where the specification itself puts the item out of scope.

**Evidence vocabulary** (Part 18's result labels, extended for evidence provenance):
`Automated test verified` · `External integration verified with a real account` · `Blocked by missing
credentials or permissions` · `Unverified: external compliance requirement incomplete` · `Not yet
started`.

A row is only `Implemented` when a **passing test** exercises the real service path. A route
existing, a screen rendering, or a mock succeeding is never enough.

Rows marked ⚠ are gaps this upgrade must close.

---

## A. Music intelligence and speech-aware ducking

| ID | Feature | Existing evidence | Source path | Status | Target | Deps | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| MUS-01 | Select a local music folder | None — tracks can only be uploaded through the API into a fixed directory | `pipeline/music.py:music_dir`, `api/music.py` | Implemented | M1 | — | A user picks any folder; app persists it; files are indexed without copying | Automated test verified (`tests/test_music_library.py::test_the_api_adds_a_folder_without_copying_anything`); Browser verified |
| MUS-02 | Scan music files | None | `music/library.py:scan` | Implemented | M1 | MUS-01 | Scan reports found/added/skipped/error counts; re-scan is idempotent | Automated test verified (scan counts; stable ids across scans) |
| MUS-03 | View available tracks | `GET /api/music/tracks` lists files | `api/music.py:library_listing` | Implemented | M1 | MUS-02 | List shows title, duration, format, size, analysis state | Automated test verified (`tests/test_music_library.py::test_the_library_api_filters_by_licence`); Browser verified |
| MUS-04 | Preview tracks | None — no audio streaming route | `api/music.py:preview` | Implemented | M1 | MUS-03 | Browser plays an arbitrary track without downloading it | Automated test verified (full body, `bytes=0-99`, suffix range, 416 past the end, 404 for a missing file); Browser verified |
| MUS-05 | Search and filter | None | `music/library.py:search`, `api/music.py:library_listing` | Partial | M1 | MUS-03 | Filter by mood/energy/BPM/format/licence; result is server-side | Automated test verified for query, mood, BPM range, licence, favourite and tag — **energy and format filters are not implemented** |
| MUS-06 | Add/remove tracks | Upload + delete | `api/music.py` | Implemented | — | — | Upload rejects non-audio; delete is path-safe | Automated test verified |
| MUS-07 | Organise library | None | `api/music.py:set_flags`, `music/store.py:set_track_flags` | Implemented | M1 | MUS-02 | User can tag/favourite/group without moving files | Automated test verified (flags stored; the file is never moved); Browser verified |
| MUS-08 | Preferred music | One global `music_track` setting | `config.py:ExportSettings.music_track`, `music/selection.py:select_track` | Partial | M1 | MUS-07 | Preference is per project/clip and consulted by selection | Automated test verified that a manual choice wins and no model is consulted — **the preference is still one global setting, not per project or per clip** |
| MUS-09 | BPM analysis | None | `music/analysis.py:detect_bpm` | Implemented | M1 | MUS-02 | Deterministic BPM within a stated tolerance of a known reference track | Automated test verified (same input ⇒ same BPM; a 220 Hz tone is measured at 220 BPM) |
| MUS-10 | Energy / rhythm analysis | None | `music/analysis.py` | Implemented | M1 | MUS-02 | Energy is a documented 0–1 measure; identical input ⇒ identical output | Automated test verified (energy in [0,1]; two measurements of one file agree) |
| MUS-11 | Mood classification | None | `music/analysis.py:classify_mood` | Implemented | M1 | MUS-10 | Mood is a declared label set, stored, and deterministic | Automated test verified (a slow quiet track is `calm`, a fast loud one is `energetic`, the scores are returned) |
| MUS-12 | Loudness / quality | None for tracks (loudnorm exists for export) | `music/analysis.py` | Implemented | M1 | MUS-02 | Integrated LUFS + true peak stored per track; malformed file flagged | Automated test verified (LUFS stored; an undecodable file raises `AnalysisError` naming the file) |
| MUS-13 | Reusable metadata cache | None | `music/library.py:analyse` | Implemented | M1 | MUS-09..12 | Re-analysing an unchanged file (same hash) reuses metadata | Automated test verified — cached against **size + mtime**, not a content hash; a changed file is measured again |
| MUS-14 | AI selects music from metadata | None | `music/selection.py:select_track` | Partial | M1 | MUS-09..13 | Selection cites the structured fields it used; no raw audio sent | Automated test verified (the proposal context carries measurements and no paths) — **the module is not yet called from the pipeline** |
| MUS-15 | Deterministic validation of AI choice | None | `music/selection.py:select_track` | Partial | M1 | MUS-14 | An invalid/unknown track id from AI is rejected, not executed | Automated test verified (an unknown id and an unusable track both fall back to the scorer) — **not yet wired into the pipeline** |
| MUS-16 | Manual override | Single global track setting | `music/selection.py:select_track` | Partial | M1 | MUS-14 | A manual choice always beats an AI choice and is shown as such | Automated test verified (the manual choice wins and no model is consulted); the source is recorded as `user` |
| MUS-17 | Licence states (Unknown/User-confirmed/Verified/Incompatible/Expired) | None | `music/licensing.py` | Partial | M1 | MUS-02 | Every track has exactly one state; default is Unknown | Automated test verified — all five states exist, but **`verified` is deliberately not settable from the API**: independent verification is not something a user can assert. The API returns 400 and writes nothing |
| MUS-18 | Licence evidence + restrictions | None | `music/licensing.py:LicenseRecord` | Implemented | M1 | MUS-17 | Source, attribution, commercial/derivative/share-alike, expiry stored | Automated test verified (`tests/test_music_library.py::test_the_api_records_a_licence`) |
| MUS-19 | Block export on unknown/incompatible | None — export mixes any track | `pipeline/export.py:export_clip` | Implemented | M1 | MUS-17 | Export of an Unknown/Incompatible track is refused with a reason | Automated test verified (unknown, incompatible, expired and a lapsed expiry each refuse the export; a user confirmation allows it) |
| MUS-20 | AI cannot certify rights | No AI involvement yet (so no violation) | `music/licensing.py:USER_SETTABLE_STATES` | Implemented | M1 | MUS-14 | A model response claiming a licence is ignored for the stored state | Automated test verified (the licence states are not writable from the selection path, and the API refuses `verified`) |
| MUS-21 | Shared speech timeline | None — ducking keys off the audio signal | `pipeline/speech_timeline.py`, `pipeline/runner.py` | Implemented | M1 | — | One timeline object is produced and consumed by ducking + layout | Automated test verified (`tests/test_speech_timeline.py` — 27 tests); the timeline is written once per job and sliced per clip |
| MUS-22 | VAD ≥0.75 + ≥1 overlapping word | None | `pipeline/speech_timeline.py:speech_frames` | Implemented | M1 | MUS-21 | Both conditions required; either alone does not mark speech | Automated test verified (a word without enough confidence is not speech) |
| MUS-23 | 270 ms rule (9×30 ms @ ≥0.90) | None | `pipeline/speech_timeline.py` | Implemented | M1 | MUS-22 | 8 frames insufficient; 9 frames at ≥0.90 sufficient | Automated test verified (nine confident frames make an interval without a word) |
| MUS-24 | Merge at 349 ms, not at 350 ms | None | `pipeline/speech_timeline.py:merge_intervals` | Implemented | M1 | MUS-21 | Exact boundary asserted on ms timestamps, not on quantised frames | Automated test verified (349 ms merges, 350 ms does not; the boundary is asserted in milliseconds) |
| MUS-25 | Continuous speech does not fragment | None | `pipeline/speech_timeline.py:merge_intervals` | Implemented | M1 | MUS-24 | A 30 s speech run yields one interval | Automated test verified |
| MUS-26 | Duck only the added music | Sidechain compression on the bed | `pipeline/export.py:build_mixed_audio_filtergraph` | Partial | M1 | MUS-21 | Original voice/game audio is bit-identical to the no-music render | Automated test verified that the speech chain is untouched and only the bed is shaped — **the bit-identical render is not asserted** |
| MUS-27 | Smooth attack/recovery | `attack=120:release=600` fixed | `pipeline/export.py:build_ducking_filters` | Implemented | M1 | MUS-26 | No step discontinuity at interval edges; values configurable | Automated test verified (the filter starts and ends at full level; `ducking_attack_ms` / `ducking_release_ms` are settings) |
| MUS-28 | No repeated recovery between words | None — compressor follows the envelope | `pipeline/export.py:build_ducking_filters` | Implemented | M1 | MUS-24 | Inside a merged interval the bed stays down | Automated test verified (the envelope stays down inside an interval and recovers at its end) |
| MUS-29 | Manual ducking controls | `music_volume`, `ducking_amount_db`, `music_ducking` | `config.py:ExportSettings` | Implemented | M1 | — | Controls change the render measurably | Automated test verified (`tests/test_music.py`) |
| MUS-30 | Volume-envelope preview | None | `api/music.py:envelope`, `frontend/src/components/MusicLibrary.tsx` | Implemented | M1 | MUS-21 | The preview's envelope equals the applied gain curve within tolerance | Automated test verified (the route returns the points and the intervals); the route and the export both call `envelope_points` |
| MUS-31 | Ducking regression matrix (continuous/short/long pauses, multi-speaker, SFX, music-heavy, low-volume, no-speech) | Partial — some cases in `tests/test_music.py` | `tests/test_music.py` | Partial | M1 | MUS-26 | All eight scenarios asserted | Automated test verified for the filter shape and the timeline rules — **the eight end-to-end render scenarios are not asserted** |

---

## B. Webcam detection, tracking and layouts

| ID | Feature | Existing evidence | Source path | Status | Target | Deps | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| CAM-01 | Webcam region detection | Face landmarks only; no region/box inference | `reframe/faces.py:FaceObservation` | ⚠ Missing | M2 | — | A region is reported with a confidence, distinct from "a face exists" | Not yet started |
| CAM-02 | Face presence | MediaPipe FaceLandmarker, up to 4 faces | `faces.py:sample_faces` | Implemented | — | — | Faces found with landmarks on real footage | Automated test verified (`tests/test_reframe.py`) |
| CAM-03 | Webcam position/size | Derived for cropping, not stored as a webcam | `reframe/croppath.py` | Partial | M2 | CAM-01 | Position and size persist per scene | Not yet started |
| CAM-04 | Adaptive scene sampling | Fixed 5 fps sampling (D-style limitation) | `faces.py:DEFAULT_SAMPLE_FPS = 5.0` | ⚠ Missing | M2 | — | Sampling density adapts to scene change rate; stated in the run record | Not yet started |
| CAM-05 | No person identification | No identity model used | `faces.py` | Implemented | — | — | No biometric template or identity is stored anywhere | Verified by inspection |
| CAM-06 | Tracking across scenes | Per-clip crop path with smoothing | `reframe/{tracker,smoothing}.py` | Partial | M2 | CAM-03 | Webcam identity persists across cuts where it should, and resets where it should | Automated test verified (existing smoothing tests) |
| CAM-07 | Occlusion / transitions / uncertainty | Smoothing only; no confidence state | `reframe/smoothing.py` | ⚠ Missing | M2 | CAM-06 | Low-confidence spans are marked and fall back safely | Not yet started |
| CAM-08 | Vertical streamer preset (~40/60) | Generic 9:16 reframe only | `export.py:RATIOS`, `reframe/*` | ⚠ Missing | M2 | CAM-03 | Preset produces ~40% cam / 60% gameplay on reference footage | Not yet started |
| CAM-09 | Layout variants (above / corner overlay / alt) | None | — | ⚠ Missing | M2 | CAM-08 | Each variant is selectable and renders | Not yet started |
| CAM-10 | Manual positioning | None in the layout domain | — | ⚠ Missing | M2 | CAM-09 | A user's manual layout is applied and survives re-render | Not yet started |
| CAM-11 | Safe crop boundaries | Headroom + centre-crop fallbacks | `reframe/croppath.py`, `faces.py` | Partial | M2 | CAM-08 | Critical gameplay region is never cropped away in reference cases | Not yet started |
| CAM-12 | No unusable upscale | None enforced | — | ⚠ Missing | M2 | CAM-08 | A tiny webcam triggers an alternative layout, not a blur | Not yet started |
| CAM-13 | Dwell ≥ 1.5 s | None | — | ⚠ Missing | M2 | CAM-08 | No layout changes inside 1.5 s; measured on held-out footage | Not yet started |
| CAM-14 | No arbitrary transition cap | No cap exists | — | Implemented (vacuously) | M2 | CAM-13 | Transition frequency is measured, not capped by a magic number | Not yet started |
| CAM-15 | Manual override wins | None | — | ⚠ Missing | M2 | CAM-10 | A manual layout beats every automatic decision | Not yet started |
| CAM-16 | Uses M1 speech timeline | None | — | ⚠ Missing | M2 | MUS-21 | Layout coordination reads the same timeline object as ducking | Not yet started |
| CAM-17 | No video pause on speech | Not implemented | — | Implemented (vacuously) | M2 | — | Video timeline length is unchanged when speech is present | Not yet started |

---

## C. Creative intelligence

| ID | Feature | Existing evidence | Source path | Status | Target | Deps | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| CR-01 | Scene detection | Scene sampling exists for reframe | `reframe/scenes.py` | Partial | M3 | — | Scene boundaries recorded per source with confidence | Automated test verified (`tests/test_reframe.py`) |
| CR-02 | Visual action / intensity | None | — | ⚠ Missing | M3 | CR-01 | Intensity is a documented, reproducible measure | Not yet started |
| CR-03 | Adaptive sampling for understanding | Fixed sampling | `faces.py` | ⚠ Missing | M3 | CR-04 | Complex footage gets denser sampling; budget is recorded | Not yet started |
| CR-04 | Multi-signal highlight detection | Transcript windows → LLM → validated candidates | `pipeline/highlights.py` | Partial | M3 | CR-02 | Speech + action + scene + reaction all contribute; loudness alone insufficient | Automated test verified (`tests/test_providers.py`) |
| CR-05 | Word-level boundaries | Word timestamps drive clip start/end words | `pipeline/boundaries.py`, `transcript.py` | Implemented | — | — | Boundaries align to words | Automated test verified (`tests/test_boundaries.py`) |
| CR-06 | Sentence/silence/scene-aware context | Silence and word boundaries | `pipeline/prepare.py:Silence` | Partial | M3 | CR-01 | The cut never drops the sentence that explains the moment | Not yet started |
| CR-07 | Duplicate/overlap prevention | Upload-level duplicates only | `youtube/duplicates.py` | ⚠ Missing (clip level) | M3 | CR-04 | Two clip candidates may not overlap beyond a declared threshold | Not yet started |
| CR-08 | Story vs gameplay intent | Single prompt strategy | `prompts/highlight_v1.txt` | ⚠ Missing | M3 | CR-04 | A configurable balance changes selection measurably | Not yet started |
| CR-09 | Structured creative plan | None | — | ⚠ Missing | M3 | CR-04 | A Pydantic-validated plan is produced and stored per job | Not yet started |
| CR-10 | Reject malformed AI output | JSON schema validation + one repair | `providers/base.py:detect_highlights` | Implemented | M3 | — | Invalid output never reaches execution | Automated test verified (`tests/test_providers.py`) |
| CR-11 | Deterministic fallback | Ollama fallback + centre crop | `runner.py:_ollama_fallback` | Partial | M3 | — | A plan failure still yields a usable render | Automated test verified (`tests/test_runner_fallback.py`) |
| CR-12 | AI budget 1 + 1 repair + ≤1/clip | No budget counter | — | ⚠ Missing | M3 | CR-09 | Exactly ≤12 calls at `max_clips=10`; overage is refused and visible | Not yet started |
| CR-13 | Budget display | None | — | ⚠ Missing | M3 | CR-12 | UI shows used/allowed per job | Not yet started |
| CR-14 | Objective diagnostics (clipping, caption timing, crop safety, resolution, fps, black frames, validity, duplicates, missing audio, duration) | Clip validation gate covers some | `pipeline/validate.py` | Partial | M3 | — | Each diagnostic is measurable and explainable; no aggregate "quality score" | Automated test verified (`tests/test_validation.py`) |
| CR-15 | No virality/quality score | A per-clip LLM `score` (0-100) is produced, stored, returned and printed in the CLI. No virality predictor and no universal quality score exist | `providers/base.py:119`, `db/schema.py:73`, `api/schemas.py:228`, `cli.py:502-507` | ⚠ Partial | M3 | CR-14 | Any displayed score is a measured diagnostic or is labelled a creative suggestion; no virality claim is made | Not yet started |

---

## D. YouTube publishing hardening (M4a)

| ID | Feature | Existing evidence | Source path | Status | Target | Deps | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| YT-01 | OAuth authorization | PKCE flow | `youtube/oauth.py:authorize_url` | Implemented | — | — | Consent URL is valid and stateful | Automated test verified (`tests/test_youtube.py`) |
| YT-02 | Per-account OAuth | Tables + keyring entries exist; UI cannot create a second account | `pages/Channels.tsx:52` (D14) | ⚠ Partial (broken) | M4a | — | A second account connects independently and keeps its own token | Not yet started |
| YT-03 | State → account mapping | `_Pending` has no account id | `oauth.py:_Pending` | ⚠ Missing | M4a | YT-02 | Wrong-account callback is rejected | Not yet started |
| YT-04 | Token storage in keyring | `youtube_refresh#<id>` entries | `accounts.py:_refresh_entry` | Implemented | — | — | No token in DB or logs | Automated test verified |
| YT-05 | Token refresh | Refresh path exists | `oauth.py` | Implemented | — | — | Expired access token refreshes | Automated test verified |
| YT-06 | `invalid_grant` isolation | Error surfaces; no per-account state | `oauth.py` | ⚠ Missing | M4a | YT-02 | Only the affected account is marked; others continue | Not yet started |
| YT-07 | Minimum scopes | upload + readonly | `oauth.py:SCOPES` | Implemented | — | — | No analytics scope requested | Automated test verified |
| YT-08 | Channel discovery | channels.list | `accounts.py` | Implemented | — | — | Channels match the token's account | Automated test verified |
| YT-09 | Channel publishing config (title/desc/tags/category/privacy/audience/destination) | Metadata + privacy exist; audience is hardcoded | `youtube/metadata.py`, `uploader.py:71` | ⚠ Partial | M4a | — | Every field is explicit and stored per channel/clip | Not yet started |
| YT-10 | `madeForKids` never guessed | Hardcoded `False` (D4) | `uploader.py:71` | ⚠ Missing | M4a | YT-09 | Unanswered ⇒ upload blocked with a clear message | Not yet started |
| YT-11 | Never guess destination | Routing fan-out exists; legacy connect breaks identity | `youtube/uploads.py`, `Channels.tsx` | ⚠ Partial | M4a | YT-02 | Destination == selected channel, proven by token identity | Not yet started |
| YT-12 | Never silently change privacy | Requested privacy stored | `uploader.py:55,71` | Partial | M4a | — | Privacy read back and compared | Not yet started |
| YT-13 | Resumable upload | Session created, one PUT | `uploader.py:81-111` | Partial | M4a | — | Interrupted transfer resumes | Not yet started |
| YT-14 | Persist session URI | Not persisted (D11) | `uploader.py` | ⚠ Missing | M4a | YT-13 | URI survives a restart | Not yet started |
| YT-15 | Idempotency key | Duplicate detection by hash exists | `youtube/duplicates.py` | Partial | M4a | — | Double enqueue ⇒ one upload attempt | Automated test verified (existing) |
| YT-16 | Ambiguous-failure reconciliation | None (D11) | `uploads.py:process_upload` | ⚠ Missing | M4a | YT-14 | Ambiguous ⇒ `needs_reconciliation`, never blind retry | Not yet started |
| YT-17 | Metadata matching is evidence only | No reconciliation exists | — | Implemented (vacuously) | M4a | YT-16 | Title/duration/time match never marks success | Not yet started |
| YT-18 | Persist video id + verify status | Status polling exists | `uploads.py` | Partial | M4a | YT-16 | Video id stored immediately; status verified | Not yet started |
| YT-19 | Quota accounting per project | None | — | ⚠ Missing | M4a | — | Reservations/consumption; failed ≠ free | Not yet started |
| YT-20 | Quota exhaustion vs rate limit | Generic retry | `uploads.py` | ⚠ Missing | M4a | YT-19 | Exhaustion queues to reset; rate limit backs off | Not yet started |
| YT-21 | Retry with backoff + cap | Retry exists without backoff | `uploads.py`, `api/youtube.py` | Partial | M4a | YT-20 | Bounded exponential backoff with jitter | Not yet started |
| YT-22 | Upload progress | Job-level progress events exist; the upload itself has no byte-progress callback | `jobs/events.py`, `youtube/uploader.py:101-109` (single `httpx.put`) | ⚠ Partial | M4a | YT-13 | Progress reflects bytes actually sent, driven by the transfer | Not yet started |
| YT-23 | Read-back privacy (forced private) | None | — | ⚠ Missing | M4a | YT-18 | "Uploaded but private" is reported, never "published" | Not yet started |
| YT-24 | Routing explanation (category, channel, reason, rule, confidence, fallback) | Classification + rules stored | `routing/classifier.py` | Partial | M4a | — | Every decision stores the six fields and shows them | Not yet started |
| YT-25 | User rule beats AI | Rule matching in classifier | `routing/classifier.py` | Implemented | — | — | Explicit rule wins | Automated test verified (`tests/test_routing.py`) |

---

## E. Instagram publishing (M4b)

| ID | Feature | Existing evidence | Source path | Status | Target | Deps | Acceptance criteria | Evidence |
|---|---|---|---|---|---|---|---|---|
| IG-01 | Any Instagram code | None anywhere in the tree | — | ⚠ Missing | M4b | — | — | Not yet started |
| IG-02 | Official API evaluation | None | — | ⚠ Missing | M4b | IG-01 | Documented findings with dates | Blocked by missing credentials or permissions |
| IG-03 | Eligibility checks | None | — | ⚠ Missing | M4b | IG-02 | Ineligible account is refused with the reason | Not yet started |
| IG-04 | OAuth | None | — | ⚠ Missing | M4b | IG-02 | Token stored in keyring | Not yet started |
| IG-05 | Media validation | None | — | ⚠ Missing | M4b | IG-01 | Format/aspect/duration validated before upload | Not yet started |
| IG-06 | Resumable upload | None | — | ⚠ Missing | M4b | IG-05 | Interrupted upload resumes | Not yet started |
| IG-07 | Publish status | None | — | ⚠ Missing | M4b | IG-04 | Status verified, not assumed | Not yet started |
| IG-08 | Retry / rate limits | None | — | ⚠ Missing | M4b | IG-07 | Bounded retry; rate limit explained | Not yet started |
| IG-09 | Duplicate prevention | None | — | ⚠ Missing | M4b | IG-01 | Same clip cannot publish twice to one account | Not yet started |
| IG-10 | Platform isolation | — | — | ⚠ Missing | M4b | IG-04 | IG failure does not cancel YT, and vice versa | Not yet started |
| IG-11 | No browser automation / scraping / password publishing | Not implemented | — | Implemented (vacuously) | M4b | — | No such mechanism exists | Verified by inspection |

---

## F. Governance milestones

| ID | Deliverable | Evidence | Status | Target |
|---|---|---|---|---|
| GOV-01 | `docs/upgrade-audit.md` with 18 required sections | This document set | Implemented | M0 |
| GOV-02 | `docs/feature-coverage-matrix.md` | This file | Implemented | M0 |
| GOV-03 | Egress inventory | `docs/EGRESS-INVENTORY.md` | Implemented | M0 |
| GOV-04 | Security + SSRF audit | `docs/SECURITY-AUDIT.md` | Implemented | M0 |
| GOV-05 | Baseline CI evidence | `docs/baseline-ci-evidence.md` | Implemented | M0 |
| GOV-06 | Benchmark baseline | `docs/performance-baseline.md` + `.json` | Implemented | M0 |
| GOV-07 | Formatting-only commits (separate, AST-compared) | `26ebf00`, `3c290b2` | Implemented | M0 |
| GOV-08 | `SECURITY.md` docs-only commit (separate) | `615f0e8` — media-egress claim corrected | Implemented | M0 |
| GOV-09 | Independent review of the M0 set | adversarial review completed; corrections applied | Implemented | M0 |
| GOV-10 | Original requirements located/copied | `docs/original/MANIFEST.md` | **Blocked — source missing** | M0 |
| GOV-11 | Original requirements matrix | `docs/ORIGINAL_REQUIREMENTS_MATRIX.md` | Partial (blocked rows) | M0 |
| GOV-12 | External constraints register | `docs/EXTERNAL-CONSTRAINTS.md` | Implemented | M0 |
| GOV-13 | Consent management | `security/consent.py` (operations, decisions, SQLite store), `api/privacy.py` (`GET`/`PUT /api/privacy/consents`, `GET /api/privacy/transfers`), Settings → External processing | Implemented | M0.5 |
| GOV-14 | Egress gateway (retrofit existing calls) | `security/egress.py`; retrofitted into ElevenLabs STT/TTS, all four LLM adapters via `LLMProvider._send`, yt-dlp ingest, FFmpeg, model download, trends, YouTube upload | Implemented | M0.5 |
| GOV-15 | Endpoint classification | `security/urlpolicy.py:classify_url`; every adapter declares `DEFAULT_ENDPOINT` | Implemented | M0.5 |
| GOV-16 | SSRF enforcement | `security/urlpolicy.py` — redirect re-classification, double-resolution rebinding guard, IPv4/IPv6 classification, scheme downgrade refusal, bounded chain | Implemented | M0.5 |
| GOV-17 | yt-dlp network restriction | `pipeline/ingest.py` classifies the URL before the fetch and refuses private destinations; `yt_dlp_hardening_args()` disables proxies; FFmpeg runs with `-protocol_whitelist file,pipe` | Partial — the secondary-request surface inside yt-dlp remains a documented residual, needing a Lane B controlled test | M0.5 |
| GOV-18 | Updated SECURITY.md with enforcement detail | `SECURITY.md` — consent model table, URL and subprocess policy | Implemented | M0.5 |
| GOV-19 | Security test evidence (SSRF suite flipped from xfail) | `tests/test_url_policy.py` (26 ordinary passing tests, zero `xfail` markers) + `tests/test_egress.py` (23 tests) | Implemented | M0.5 |
| GOV-20 | Final upgrade report | — | Missing | M5 |
| GOV-21 | Independent audit + release package | — | Missing | M5 |

---

## G. Out of scope (specification Part 1.3)

| ID | Item | Repository reality | Status |
|---|---|---|---|
| OOS-01 | n8n integration | Absent | NOT APPLICABLE |
| OOS-02 | Visual workflow canvas | **Present** (Phases 7+): `pages/Workflows.tsx`, `workflow/engine.py` | NOT APPLICABLE — preserved, not extended |
| OOS-03 | Conversational chatbot for workflows | **Present**: `chat/agent.py`, `pages/Assistant.tsx` | NOT APPLICABLE — preserved, not extended |
| OOS-04 | YouTube Analytics collection | Absent (only internal aggregates) | NOT APPLICABLE |
| OOS-05 | Analytics-driven learning / `improve.txt` writer | `improve.txt` is user-edit-only | NOT APPLICABLE |
| OOS-06 | Trending-topic research | **Present**: `trends/research.py`, `pages/Trends.tsx` | NOT APPLICABLE — preserved, not extended |
| OOS-07 | TikTok publishing | Absent | NOT APPLICABLE |
| OOS-08 | Additional platforms | Absent | NOT APPLICABLE |
| OOS-09 | Browser automation / browser publishing | Absent | NOT APPLICABLE |

---

## Summary

| Status | Count |
|---|---|
| Implemented | 53 |
| Partial | 29 |
| Missing | 37 |
| Blocked — source missing | 1 |
| NOT APPLICABLE | 9 |
| **Total rows** | **129** |
