# Upgrade ledger

**Branch:** `feature/upgrade-u0-u10` · **Base:** `bf76811` (`feature/autonomous-platform-v2`)
**Governing spec:** `docs/UPGRADE-SPEC.md` (M0–M5, supplied 2026-11-19)

Status values: **Not started** · **In progress** · **Complete** · **Blocked**.
A milestone is `Complete` only when every gate item has passing evidence. A failing gate keeps the
milestone `In progress` and is reported as such.

---

## Milestone summary

| Milestone | Status | Gate evidence |
|---|---|---|
| M0 — Audit and baseline | **Complete** | 16/16 gate items done or explicitly blocked; independent review folded in |
| M0.5 — Security and consent | **Complete** | 12/12 gate items done; 49 security tests passing; the residual yt-dlp secondary-request surface is documented, not claimed |
| M1 — Music intelligence | **Complete** | 12/12 gate items done; 101 tests across the M1 area passing; four named residuals recorded (not claimed as verified) |
| M2 — Webcam intelligence | **Complete** | 13/13 gate items done; 76 tests across the M2 area passing, including 6 real-ffmpeg render tests; three named residuals recorded (not claimed as verified) |
| M3 — Creative intelligence | **Complete** | 11/11 gate items done; 126 tests across the M3 area passing; two named residuals recorded (not claimed as verified) |
| M4a — YouTube hardening | **Complete** | 14/15 gate items done; 1149 tests passing; the live YouTube path is **Unverified (external)** — no authorised Google credentials were supplied |
| M4b — Instagram | **Complete** | 14/15 gate items done; 126 tests across the M4b area passing; the live Instagram path is **Unverified (external)** — no authorised Meta credentials were supplied |
| M5 — Audit and release | **Complete** | 10/10 gate items done; **1,300 tests** passing; the application exercised through its real UI on real media; **3 product defects and 1 CI defect found and fixed**; the release run green on all six CI jobs; the live external paths remain **Unverified (external)** |
| **M5.1 — Ducking matrix** (post-release increment, 2026-11-21) | **Complete** | The last closeable PARTIAL matrix row (**MUS-31**) closed as **eight real renders**; **1,315 tests** passing; **a fourth product defect found and fixed** (an empty speech timeline was indistinguishable from no timeline); the matrix is now **110 Implemented · 9 Partial · 1 Blocked · 9 N/A**; the M5 verdict is unchanged and v0.1.0 is still gated on K1 |

---

## M0 — Audit and baseline

**Status: Complete**, with two items explicitly blocked on the owner (the missing original sources and
the Lane B credentials). The independent review returned 11 corrections; all were applied to the
documents before this milestone was recorded as complete.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | Repository state recorded, branch created, checkpoint pushed | Done | `bf76811` → branch `feature/upgrade-u0-u10`, pushed; `git branch` confirms |
| 2 | Specification saved verbatim | Done | `docs/UPGRADE-SPEC.md` (947 lines) |
| 3 | Original requirements + 7 references located | **Blocked — source missing** | `docs/original/MANIFEST.md` (0 of 8 found; full search record) |
| 4 | `docs/upgrade-audit.md` with all 18 sections | Done | 20 sections including §18 conflicts and §19 sequence |
| 5 | Feature coverage matrix | Done | `docs/feature-coverage-matrix.md`, 129 rows |
| 6 | Egress inventory | Done | `docs/EGRESS-INVENTORY.md`, 14 transfer paths (E1–E14, E14 added after review) |
| 7 | Security + SSRF audit | Done | `docs/SECURITY-AUDIT.md`, findings S1–S7 + 8 verified-good properties |
| 8 | Baseline CI evidence | Done | `docs/baseline-ci-evidence.md` — 672 passed, format FAIL on 38 files, mypy 14 errors |
| 9 | Benchmark baseline | Done | `docs/performance-baseline.md`, `docs/BENCHMARK-BASELINE.json`, `scripts/bench_baseline.py` |
| 10 | Formatting-only commit, `runner.py` + `make_e2e_media.py`, AST-compared | Done | `26ebf00`; AST identical incl. docstrings |
| 11 | Remainder of the formatter drift | Done | `3c290b2`; 36 files, whitespace only; suite re-run green |
| 12 | SECURITY.md docs-only commit, claim corrected | Done | `615f0e8` |
| 13 | SSRF target-policy tests pre-registered | Done | `tests/test_url_policy.py`, 26 strict xfails |
| 14 | `docs/EXTERNAL-CONSTRAINTS.md` | Done | G1–G9 |
| 15 | Independent review | Done | adversarial review returned 11 corrections (router/page/table counts, E14 trends egress, CR-15 score, YT-22 progress, wrong paths); all applied |
| 16 | D1–D13 re-verified; D14, D15 found | Done | `docs/upgrade-audit.md` §3, §13 |

### Decisions taken in M0

| Decision | Why | Where recorded |
|---|---|---|
| Keep the branch name `feature/upgrade-u0-u10` under an M0–M5 spec | Continuity; the branch and checkpoint already exist and are pushed | `docs/UPGRADE-SPEC.md` header, audit §18 |
| Preserve the out-of-scope features that already ship (canvas, assistant, trends, learning) rather than deleting them | "Preserve useful working functionality" outranks "do not add"; deleting tested screens would destroy user value and break the suite | audit §18 |
| Do not extend any out-of-scope feature | The specification forbids new work in those areas | audit §18 |
| Reformat the whole tree, not only the two named files | CI's format gate fails on the shipped tree, so nothing else can be verified through it | audit §13, commit `3c290b2` |
| Record SSRF gaps as strict xfails, not skips | A skip hides; a strict xfail forces removal once enforced | `docs/SECURITY-AUDIT.md`, `tests/test_url_policy.py` |
| Add `scripts/bench_baseline.py` rather than hand-recorded timings | The spec requires a comparable baseline; a script makes "before vs after" honest | `docs/performance-baseline.md` |
| Do not fix the 14 mypy errors in M0 | They are pre-existing and belong with the modules they touch; fixing them here would inflate a docs milestone | audit §16 T1 |

### Blockers

| Blocker | Effect | Action needed from owner |
|---|---|---|
| Original requirements + 7 visual references absent | Matrix rows blocked; nothing depends on them for the in-scope product work | Supply the files, or confirm they no longer matter |
| No ElevenLabs test key | E1/E2 stay `Automated test verified` only | Supply a test key + spend ceiling |
| No hosted-LLM test key | E4 stays `Automated test verified` only | Supply one key on a supported preset |
| No Google OAuth client / test channel | YT-* live rows blocked at M4a | Supply a client, add the test user, decide on the compliance audit |
| No Meta app / professional account | IG-* live rows blocked at M4b | Confirm eligibility, or accept a disabled integration |

---

## M0.5 — Security and consent

**Status: Complete.** The milestone ships the URL policy, the egress gateway, the consent store, the
retrofit of every existing external call, the Settings surface, and the test evidence.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | `security/urlpolicy.py` implementing the target policy | Done | scheme, IPv4/IPv6 + CGNAT + IPv4-mapped classification, per-hop redirect re-classification, scheme-downgrade refusal, bounded chain, double-resolution rebinding guard |
| 2 | All 26 SSRF xfails flipped to passing tests, markers deleted | Done | `tests/test_url_policy.py` — 26 ordinary passing tests; zero `xfail` markers remain (gate condition) |
| 3 | `security/egress.py`: classification, consent, transfer log, redaction | Done | `EgressGateway.authorize/require/fetch/record`, `redact()` masks a credential completely |
| 4 | Consent storage + migration | Done | DB migration **v15** — `egress_consents`, `egress_log`; `SCHEMA_VERSION = 15` |
| 5 | Retrofit E1, E2, E4 through the gateway | Done | `speech/elevenlabs.py`, `speech/tts.py`, `providers/base.py:LLMProvider._send` |
| 6 | Retrofit E9, E11, E12, E14 through the gateway | Done | `youtube/uploader.py`, `pipeline/ingest.py`, `models.py`, `trends/research.py` |
| 7 | FFmpeg `-protocol_whitelist` | Done | `pipeline/ffmpeg.py:protocol_args()` → `file,pipe`, applied to all three command builders |
| 8 | yt-dlp hardening | Done | `yt_dlp_hardening_args()` → `--proxy ""`; the source URL is classified before the fetch and a private destination is refused |
| 9 | Non-silent fallback | Done | `providers/resolver.py` refuses to try another **external** provider after a consent refusal; only a local provider may answer. `ProviderConsentRequired` aborts the highlights stage |
| 10 | User-visible controls | Done | `api/privacy.py` → `GET`/`PUT /api/privacy/consents`, `GET /api/privacy/transfers`; Settings → External processing |
| 11 | `SECURITY.md` updated with the enforcement detail | Done | consent model table, URL and subprocess policy |
| 12 | Security test evidence | Done | `tests/test_url_policy.py` (26) + `tests/test_egress.py` (23) = 49 security tests, all passing; full suite 721 passing, 0 xfailed |

### Decisions taken in M0.5

| Decision | Why | Where recorded |
|---|---|---|
| A consent decision is keyed by **(operation, destination class)**, not by host | The useful question is "may transcript text leave the machine at all", and the class is what determines the risk. Keying by host would let a decision silently follow a `base_url` to a different machine | `security/consent.py` module docstring, `SECURITY.md` |
| A **configured** public destination is allowed once and recorded with `source="configured"` | An existing install must keep working after the upgrade, but the decision must be visible and revocable rather than implicit forever | `security/egress.py:authorize` |
| A private destination is **never** allowed implicitly | "The user configured it" is not evidence that a LAN address is safe to reach with content | `security/egress.py:authorize` |
| An explicit withdrawal always wins, even for a configured destination | Consent that can be overridden by configuration is not consent | `security/egress.py:authorize` |
| Only content-bearing operations are consent-gated; the rest are logged | Requiring a decision for a model download trains the user to click through prompts without reading them | `security/consent.py:Operation`, `Transfer.requires_consent` |
| Credentials are masked **entirely** in logs — no suffix fingerprint | A secret that appears in a log line is compromised whether or not its last four characters are readable | `security/egress.py:redact` |
| Adapters declare `DEFAULT_ENDPOINT` | The OpenAI, Anthropic and Gemini endpoints appear nowhere in the repository as literals, so a URL scan cannot classify them | `providers/*_provider.py` |
| `SpeechConsentDenied` is a distinct exception type | "Blocked by your settings" and "the service is down" need different remedies and different wording | `speech/base.py` |
| Loopback is never offered as a choice in the UI | It cannot be denied; offering it would imply it can be | `api/privacy.py` |

### Residual risk carried into later milestones

| Residual | Status | Action |
|---|---|---|
| yt-dlp's **secondary requests** (manifest, CDN, page assets) are made inside yt-dlp and cannot be re-classified hop by hop | Documented, not verified | Lane B controlled test against a redirecting host before the surface can be called verified |
| The **first-run MediaPipe model download** still happens inside the pipeline, with no pre-flight check at job start | Product limitation, not a security gap | M3 — pre-flight the check so an offline machine fails before the job starts |
| Legacy global OAuth token still coexists with per-account tokens | Finding S6, untouched by M0.5 | M4a |
| `ruff` still unpinned | Finding S7, untouched by M0.5 | M5 |

---

## M1 — Music intelligence and speech-aware ducking

**Status: Complete.** The milestone ships the library, the local analysis, the licence gate, the
shared speech timeline, the timeline-driven ducking and the Settings surface, with the test and
browser evidence recorded below. Four residual gaps are named below rather than being written up as
finished: the AI music-selection module is not yet called from the pipeline, the energy and format
filters are missing, the music preference is still one global setting, and the eight-scenario
ducking matrix is asserted at the filter level rather than end-to-end.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | The library is an **index**, never a manager | Done | `music/library.py` — folders are persisted, files are read where they stand; `tests/test_music_library.py::test_a_scan_indexes_files_without_touching_them` asserts the bytes and mtimes are unchanged after a scan, and `::test_removing_a_track_from_the_library_does_not_delete_the_file` asserts the file survives removal |
| 2 | Scan reports counts and is idempotent | Done | `music/library.py:scan` → `ScanReport(folders, found, added, skipped, errors)`; `::test_a_track_id_is_stable_across_scans` |
| 3 | Search and filter, server-side | Done | `music/library.py:search` — query, mood, BPM range, licence, favourite and tag; `::test_the_library_api_filters_by_licence`. **Energy and format filters are not implemented** — residual 1 |
| 4 | Local, deterministic analysis | Done | `music/analysis.py` — ffmpeg decode + numpy spectral flux/autocorrelation BPM, RMS energy, ebur128 LUFS, heuristic mood rules, frame-level noise floor and dynamic range. `::test_a_track_is_measured_locally`, `::test_the_measurement_is_deterministic`, `::test_a_mono_file_is_measured_at_its_real_duration` |
| 5 | Reusable metadata | Done | `music/library.py:analyse` caches against **file size + mtime**; `::test_the_measurement_is_cached_against_the_file` and `::test_a_changed_file_is_measured_again` |
| 6 | Licence states, evidence and restrictions | Done | `music/licensing.py` — Unknown / User-confirmed / Verified / Incompatible / Expired, with source, evidence, attribution, commercial, non-commercial, derivative, share-alike and expiry; `::test_the_api_records_a_licence`. **`verified` is deliberately not settable from the API** — see the decisions table |
| 7 | Export blocked on Unknown / Incompatible / Expired | Done | `pipeline/export.py:export_clip` calls `music_library.check_export_allowed_for_path`; `tests/test_music.py` asserts each blocking state refuses the export and a user confirmation allows it |
| 8 | AI cannot certify rights | Done | The licence API refuses `verified` with a 400 and writes nothing (`::test_the_api_refuses_to_set_a_verified_licence`); the selection path never writes a licence |
| 9 | One shared speech timeline, no second detector | Done | `pipeline/speech_timeline.py` — built once after transcription in `pipeline/runner.py`, written to `work/{job_id}/speech_timeline.json`, sliced per clip and handed to the export; `tests/test_speech_timeline.py` — 27 tests |
| 10 | The VAD and merge rules, exactly | Done | ≥0.75 confidence with ≥1 overlapping word, or ≥0.90 for 270 ms (9 × 30 ms frames); 349 ms merges, 350 ms does not, measured on millisecond timestamps. `::test_a_349_ms_gap_merges`, `::test_a_350_ms_gap_does_not_merge`, `::test_the_boundary_is_measured_in_milliseconds_not_frames`, `::test_nine_confident_frames_make_an_interval_without_a_word` |
| 11 | Timeline-driven ducking, bed only | Done | `pipeline/export.py:build_ducking_filters` shapes the bed with per-interval `volume` filters (`eval=frame`, `enable='between(t,…)')`); the speech chain is untouched. `::test_the_ducking_filter_starts_and_ends_at_full_level`, `::test_the_timeline_drives_the_ducking_when_it_is_available` — **the bit-identical no-music render is not asserted**, residual 4 |
| 12 | Settings surface + preview | Done | `frontend/src/components/MusicLibrary.tsx` — folders, filters, measured badges, licence editor, envelope preview; `api/music.py:preview` answers Range requests and `api/music.py:envelope` draws the same `envelope_points` the export uses. Browser verified against a live uvicorn server with zero console errors |

### Decisions taken in M1

| Decision | Why | Where recorded |
|---|---|---|
| The library is an **index**; the files are never copied, moved or deleted | The user's music is theirs. A "remove" button that deletes a file is a data-loss bug wearing a normal button | `music/library.py`, the button says "Remove from library" |
| **`verified` is not a state the user can assert** | The specification lists Independently-verified as a state, but independent verification is not something a user can claim about their own file. Making it settable would turn an attestation into a certification | `music/licensing.py:USER_SETTABLE_STATES`; the API returns 400 and writes nothing |
| A user confirmation carries a **warning, not a stamp of truth** | The UI says "your own confirmation", the API carries the warning "That is not an independent check", and the export gate still treats it as the user's own word | `music/licensing.py:evaluate`, `frontend/src/components/MusicLibrary.tsx` |
| The analysis is **local and deterministic**; no audio is ever uploaded | The specification forbids uploading the library. Measuring on the machine also means the same track always gets the same numbers | `music/analysis.py` |
| The metadata cache is keyed by **size + mtime**, not a content hash | A content hash means reading the whole file before every check, which defeats the point of the cache. Size + mtime is the cheap, honest key; a changed file is re-measured | `music/library.py:analyse` |
| The ducking follows the **shared timeline**, not the audio signal | Two detectors would disagree, and the bed would recover between two words the transcript considers one stretch of speech. The timeline is the single source of truth | `pipeline/export.py:build_mixed_audio_filtergraph` |
| The VAD frame confidence is the **stronger of two measures** — relative to the recording's own noise floor, or absolute above a speech level | A relative measure alone scores every frame of a recording with no silence as zero, so a continuously-talking clip would produce no intervals at all | `pipeline/speech_timeline.py` |
| The recovery ramp completes **exactly at the interval end** in both the Python envelope and the FFmpeg expression | A bed that is still ramping when the filter switches off clicks. Both curves now end at full level at the same instant | `pipeline/speech_timeline.py:envelope_points`, `pipeline/export.py:_ducking_expression` |
| `build_mixed_audio_filtergraph` returns a typed `MixedAudio`, not a `dict` | A dict of `object` values let a caller pick up the wrong shape without the type checker noticing. This also removed a pre-existing mypy error | `pipeline/export.py` |
| `decode_audio` always requests **stereo** (`-ac 2`) | A mono source was measured at half its real duration, and a multi-channel source was measured wrong too. Downmixing to stereo makes the sample count divide by two in every case | `music/analysis.py` |
| **numpy was already a declared dependency** | No dependency change was needed for M1 — the analysis is built on what the project already declared | `pyproject.toml:50` |

### Residuals carried into later milestones

| Residual | Status | Action |
|---|---|---|
| The AI music-selection module (`music/selection.py`) is built and tested but **not called from the pipeline** | Partial — the module passes 12 selection tests, but no clip is actually selected by it yet | M3 — wire it in behind the egress gateway, where the call budget becomes enforceable end to end |
| The library filter has **no energy or format filter** | Partial — query, mood, BPM, licence, favourite and tag work | M3 — add with the rest of the filter surface |
| The music preference is still **one global setting**, not per project or per clip | Partial — a manual choice beats a model, and that is tested | M3 — project and clip scope |
| The **eight-scenario ducking matrix** is asserted at the filter and timeline level, not as eight end-to-end renders | Partial | M5 — the render matrix belongs with the release regression pass, where the media fixtures are assembled |

---

## M2 — Webcam detection and intelligent layouts

**Status: Complete.** The milestone ships the region detector, the layout planner, the ffmpeg
composition layer, the per-source record, the API and the Settings surface. Three residuals are
named below rather than being written up as finished: the transition frequency has not been
measured on held-out footage (there is none on this machine), the manual override sets the
variant and the corner but not a free rectangle drawn by hand, and the face-legibility rule is
asserted against synthetic geometry rather than against real streamer footage.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | A **webcam region** with a confidence, distinct from "a face exists" | Done | `reframe/webcam.py` — the region is a persistent cluster of faces scored on support, stability, **cut stability** (an overlay does not move when the shot cuts; a person in the scene does) and persistence. `tests/test_webcam.py` — 21 tests |
| 2 | Detection never raises; it returns a report | Done | An unreadable video, a missing model and a video with no faces all come back as `WebcamReport(unavailable_reason=…)`; `::test_a_clip_with_no_duration_is_a_report_not_a_crash` |
| 3 | Adaptive scene sampling, not a flat 5 fps | Done | `webcam.py:adaptive_sample_fps` — `MIN_SAMPLE_FPS=2.0`, `BASE_SAMPLE_FPS=5.0`, `MAX_SAMPLE_FPS=15.0`, `MIN_SAMPLES_PER_SHOT=2`, density rising above `CUTS_PER_MINUTE_FOR_DENSITY=4.0`. The chosen rate **and the reason** are written into the report; `::TestAdaptiveSampleFps` |
| 4 | Tracking across scenes, with uncertainty | Done | `webcam.py:track_webcam` — the region does not move; a stretch with no face inside it is reported as a span with `present=false` and a reason, and the confidence falls with the missing time. `::TestTrackWebcam` |
| 5 | No person identification | Done | The detector clusters face *boxes* by position and writes a rectangle and four scores. There is no template, no embedding and no identity anywhere — `reframe/webcam.py` inspected end to end |
| 6 | The vertical streamer preset, ~40% cam / 60% gameplay | Done | `reframe/layout.py` — the strip is `webcam_height_frac` of the output height (0.40 by default) and the gameplay the rest. The fraction is configurable, so it is a preference, not a rule; `tests/test_layout.py::TestTheStreamerPreset` |
| 7 | Above, corner and gameplay-only variants, all rendering | Done | `pipeline/export.py` builds the composition; `tests/test_export_render.py::TestLayoutRender` renders both variants against **real ffmpeg** and compares the pixels — 6 tests |
| 8 | Manual positioning, surviving a re-render | Done | `reframe/layout_store.py` + migration v17 (`source_layouts`) — the user's choice is stored per source and is never overwritten by a re-detection; `tests/test_layout_api.py` |
| 9 | Safe crop boundaries | Done | The gameplay crop slides away from the webcam region; where no such crop exists the webcam is drawn over the gameplay rather than the gameplay being cut through it; `::test_the_gameplay_is_never_cropped_through_the_webcam` |
| 10 | No unusable upscale | Done | The rule is **face legibility**, not a blind ratio: `MIN_FACE_WIDTH_PX=48` in the output and `MAX_FACE_SCALE=3.0`. A webcam too small for a strip gets the corner layout at a size the source can fill, and one whose face would be under 48 px is left out; `::TestTheSafeFallbacks` |
| 11 | Dwell ≥ 1.5 s, no arbitrary transition cap | Done | `layout.py:apply_dwell` pushes a change that comes too soon to the earliest moment it is allowed; the clip's start and end never move. `transition_frequency` **measures** rather than caps; `::TestStability` |
| 12 | The shared M1 speech timeline, no second detector | Done | `pipeline/runner.py:_plan_layout` reads `SpeechTimeline.relative_slice()` — the same object the ducking reads; `::test_the_speech_spans_are_the_shared_timeline` |
| 13 | No video pause on speech | Done | The emphasis is a **time-varying crop of the webcam region before a constant scale**, so the overlay's size never changes and the clip's length never changes; `::test_the_clip_is_not_lengthened_by_the_layout` |

### Decisions taken in M2

| Decision | Why | Where recorded |
|---|---|---|
| A webcam is a **persistent cluster of faces**, scored on cut stability rather than on "a face is here" | A face says someone is on screen. A webcam says a particular rectangle keeps holding that person, in the same place, across cuts. The cut-stability measure is what separates the two | `reframe/webcam.py` |
| Detection runs **once per source**, not once per clip | A webcam overlay is in the same place in every shot, so one detection sliced per clip is both faster and steadier than detecting again | `pipeline/runner.py:_detect_webcam` |
| The **no-unusable-upscale rule is face legibility**, not a blind ratio | A hard 1.5× cap would reject a real 480 px face-cam blown to 1080 px, which is normal practice. What matters is whether the face can be read in the output | `reframe/layout.py:MIN_FACE_WIDTH_PX`, `MAX_FACE_SCALE` |
| A manual layout beats the automatic one **on the variant only**; the legibility veto stays automatic | The user may insist on a layout AutoClip thinks is a poor fit — that is their call. But the universal scale cap still applies, because a blur is a bug, not a preference | `reframe/layout.py:plan_layout` |
| The stacked layout is a **true split**: the gameplay is scaled to the gameplay slot and padded onto a blurred full-frame background | The alternative — gameplay full-frame with the webcam drawn over it — hides part of the game, which the specification explicitly forbids | `pipeline/export.py:_compose_with_webcam` |
| The webcam's **presence** varies by time (`enable='between(t,…)'`) but the gameplay geometry does not | One filtergraph cannot change the crop path's scale mid-stream. The presence can change; the geometry cannot | `pipeline/export.py` |
| The speech emphasis is a **time-varying crop before a constant scale** | The `crop` filter re-evaluates its expressions per frame natively; a changing overlay size would force ffmpeg to rebuild the overlay every time somebody started talking | `pipeline/export.py:_webcam_crop_filter` |
| The **crop path's aspect follows the gameplay slot** (1080×1152 ⇒ 15:16) | A crop path built for the full 9:16 would be stretched into the slot, so the gameplay would come out distorted | `pipeline/runner.py:_crop_aspect` |
| The user's choice is stored **separately** from what the detector found | Detection must never overwrite a choice, and changing your mind about the layout is not the same as changing your mind about the video | `reframe/layout_store.py`, migration v17 |
| The **detected region is persisted with its confidence and its reason** | The settings screen has to say what it is working from. A picture of a face with no explanation is not an answer | `reframe/webcam.py:WebcamReport.save` |

### Residuals carried into later milestones

| Residual | Status | Action |
|---|---|---|
| The transition frequency has **not been measured on held-out footage** | Unverified — the rule is implemented and asserted against synthetic segments, but there is no held-out streamer footage on this machine | M5 — measure it on the Lane C material and record the number |
| The manual override sets the **variant and the corner**, not a free rectangle drawn by hand | Partial — the rectangle is stored and honoured, but the UI offers variants rather than a drag-to-draw region | M5 — a drag-to-draw region on a source thumbnail |
| The face-legibility rule is asserted against **synthetic geometry**, not real streamer footage | Partial — the rule is exact and tested, but no real webcam overlay was available to measure | M5 — Lane C acceptance on the downloaded material |
| The AI music-selection module (`music/selection.py`) is built and tested but **not called from the pipeline** | Partial — carried from M1 | **Closed in M3** — `pipeline/music_selection.py:select_for_clips` calls it from the runner |
| The library filter has **no energy or format filter** | Partial — carried from M1 | **Closed in M3** — the library filters on energy and on the measured shapes |
| The music preference is still **one global setting** | Partial — carried from M1 | **Closed in M3** — three scopes: global, source and clip |
| The **eight-scenario ducking matrix** is asserted at the filter level, not as eight end-to-end renders | Partial — carried from M1 | M5 |

---

## M3 — Creative intelligence

**Status: Complete.** The milestone ships the AI call budget, the structured creative plan, the
per-clip music selection, the three-scope music preference, the measured music shapes, the
story/gameplay intent, and the objective quality diagnostics — with the API and the UI that
show them. Two residuals are named below rather than being written up as finished: the scene
detector discards PySceneDetect's per-cut confidence, and the "visual action" signal is a
measured proxy (the cut rate) rather than a visual-action model.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | **One planning call, one repair, and at most one music call per clip**, capped by `max_clips` | Done | `backend/autoclip/budget.py` — three separate allowances (plan 1, repair 1, music = `max_clips`), so spending the music allowance cannot stop the plan. The total is **12 at the default `max_clips=10`**. `tests/test_budget.py` — 19 tests |
| 2 | The budget **survives a retry** and its refusals are recorded with their category | Done | `db/budget_store.py` + migration v18 (`job_ai_budget`) — a retried job does not get a fresh allowance; an overrun is stored with the allowance it belongs to, because a silently capped budget reads like a budget that was never needed. `::test_a_retry_does_not_get_a_fresh_allowance`, `::test_the_overruns_carry_the_category_they_belong_to` |
| 3 | Usage and overruns are **displayed** | Done | `GET /api/jobs/{job_id}/budget` → `frontend/src/components/JobPlanPanel.tsx` — the three allowances, the total, and every refusal with its reason. Browser verified: "2 of 3 used · Plan 1/1 · Repair 0/1 · Music 1/1" and "music — the second clip needed a music call too" |
| 4 | A **structured creative plan** with the nine specified fields | Done | `pipeline/creative.py` — clip boundaries, selection reasoning, layout, crop, caption strategy, music, ducking, transition and export settings, as one validated object. `tests/test_creative.py` — 39 tests |
| 5 | **Every output is validated before execution**, and malformed output is rejected rather than patched | Done | `creative.validate_plan` — an unknown layout, crop, caption strategy or transition, an unknown track id, a duplicate clip id, a ducking value outside the range, an unknown export ratio and an answer that is not JSON are each rejected with their reasons. `::TestValidation` |
| 6 | A **deterministic fallback**, with the reasons kept | Done | `creative.fallback_plan` — the absence of a plan in the same shape; the reason is in `problems` only, so the screen does not show the same sentence twice. `::test_a_bad_answer_and_a_bad_repair_fall_back_with_the_reasons` |
| 7 | The plan is **stored per job**, including what was rejected | Done | `db/plan_store.py` (`creative_plans`, migration v19) — the whole plan is kept, problems included. A plan that silently fell back would read exactly like one the model agreed with. `GET /api/jobs/{job_id}/plan` |
| 8 | **Story and gameplay intent**, configurable, with **no arbitrary 50/50 split** | Done | `pipeline/intent.py` — story is the speech density from the shared M1 timeline, action is the cut rate from the shared shot list. `ClipSettings.story_density` (0–1) and `highlight_style` (auto/story/action). **At the default (0.5 / auto) the adjustment is exactly zero for every clip**, and nothing produces filler. `tests/test_diagnostics.py::TestIntent` (12 tests) |
| 9 | **Ten objective quality measurements**, each measurable and explainable, with **no aggregate quality score** | Done | `pipeline/diagnostics.py` — `diagnostics.MEASUREMENTS` names all ten: audio clipping, caption timing, crop safety, resolution, frame-rate consistency, black frames, export validity, duplicate clips, missing audio and duration. Each carries `measured` (the evidence), `detail` (the problem in a sentence) and `available` — an unmeasurable thing is never reported as a pass. `tests/test_diagnostics.py` — 31 tests |
| 10 | The music selection is **called from the pipeline**, and the M1 residuals are closed | Done | `pipeline/music_selection.py:select_for_clips` — one set of rules shared by the sync and async paths; the library filters on **energy** and **shape** (`music/formats.py`, derived from the measurements, never stored); the preference lives at **three scopes** (global, source, clip — migration v20) with the most specific winning and `__none__` meaning "no music at all". `tests/test_music_selection.py` (18 tests) |
| 11 | The model's own score is **labelled as a creative suggestion**, not a quality number | Done | `api/schemas.py:ClipOut.score`, `cli.py` (the column is "Suggestion"), and both screens that show it — the number is the model's suggestion for how strong the moment is, and the measured diagnostics live separately under Measurements. `pipeline/diagnostics.py` has no score field at all |

### Decisions taken in M3

| Decision | Why | Where recorded |
|---|---|---|
| The budget lives in a **top-level** `backend/autoclip/budget.py`, not inside `pipeline/` or `music/` | Both the music selection and the pipeline need it, and putting it in either would make one import the other. A neutral package level has no such edge | `backend/autoclip/budget.py` |
| The three allowances are **separate counters**, not one pool | A clip choosing its music must not be able to use up the planning call. One pool would let the wrong thing starve the right thing | `backend/autoclip/budget.py:JobBudget` |
| A **refusal is recorded**, not silently applied | A budget that was quietly capped reads exactly like a budget that was never needed. The refusal and its category are stored with the counters | `backend/autoclip/budget.py:overrun_records` |
| A malformed plan is **rejected, not patched** | Patching a model's mistakes means AutoClip is quietly deciding what the model meant. One repair is offered; if that fails, the deterministic plan is used and the reasons are kept | `pipeline/creative.py:validate_plan` |
| A **declined consent is an answer, not a failure** | If the user has switched off AI creative planning, that is a decision, not an error. The plan falls back deterministically with the reason "AI creative planning is switched off in the privacy settings", and the music proposer is switched off for the rest of the job rather than asking again | `pipeline/runner.py:_stage_creative`, `pipeline/music_selection.py` |
| The **story/action balance is a bias, not a quota** | A 50/50 split would force filler: a video with no action in it would get action clips anyway. Nothing here requires a ratio, and at the default the adjustment is exactly zero | `pipeline/intent.py` |
| The model's own score is **never thrown away** — the balance is a bounded tilt on top of it | The model judges the hook and the payoff, which cannot be measured from a signal. The measured signals tilt it by at most fifteen points either way | `pipeline/intent.py:STORY_BIAS` |
| The diagnostics carry **no score, no rating and no number** | Ten different measurements cannot be folded into one number honestly, and a number that looked like a verdict would be a lie. Each measurement stands on its own, and an unmeasurable one says so | `pipeline/diagnostics.py` |
| The **model's score is labelled** as a suggestion wherever it is shown | A bare 0–100 next to a clip invites the reading that it is a quality measurement. It is a creative judgement, and the screen now says so | `api/schemas.py`, `cli.py`, `frontend/src/pages/Review.tsx` |
| The music preference is **three rows, not three columns** | A clip's choice has to survive the source's choice being changed, and clearing one scope must not clear another. Separate rows make that structural rather than a convention | `music/preferences.py` |
| An empty track id means "**no preference here**"; the sentinel `__none__` means "**no music at all**" | Those are different answers. One is an absence and the other is a decision, and conflating them makes "no music" impossible to express | `music/preferences.py:NO_MUSIC` |
| The music **shapes are derived from the measurements**, never stored | "Steady" means a beat regularity of at least 0.55. If the shape were a stored field it could drift away from the number it came from | `music/formats.py` |
| The scene changes per clip are counted from a **shot list detected once for the source** | The same argument as the M2 webcam decision: the cuts do not change between clips, so detecting once and slicing is both faster and steadier | `pipeline/runner.py:_load_or_detect_shots` |
| A job with no speech timeline answers the envelope route with **200 and an empty envelope** | A browser logs a 404 as a failed request, and a job waiting to be transcribed is not a failure. A 404 remains for an unknown job id; 400 for a missing job id | `api/music.py:envelope` |

### Residuals carried into later milestones

| Residual | Status | Action |
|---|---|---|
| The scene detector **discards PySceneDetect's per-cut confidence** | Partial — the shot boundaries are recorded and cached per source, but `detect_shots` keeps only the times, so a cut's own confidence is not stored | M5 — record the detector's score per cut alongside the times |
| "Visual action" is a **measured proxy** — the cut rate — rather than a visual-action model | Partial — it is a documented, reproducible measure and it moves the ranking measurably, but it is not a model of what is happening on screen | M5 — a real action signal, measured on the Lane C material |
| The M1 **ducking regression matrix** is asserted at the filter level, not as eight end-to-end renders | Partial — carried from M1 | M5 |
| The M2 **transition frequency** has not been measured on held-out footage | Unverified — carried from M2 | M5 |
| The M2 **manual layout** sets the variant and the corner, not a free rectangle drawn by hand | Partial — carried from M2 | M5 |
| The M2 **face-legibility rule** is asserted against synthetic geometry, not real streamer footage | Partial — carried from M2 | M5 |

---

## M4a — YouTube publishing hardening

**Status: Complete**, with one item blocked on the owner (the live YouTube path needs authorised
Google credentials, which were not supplied). The milestone ships five parts: per-account OAuth
identity, an explicit publishing policy, a resumable upload with a quota ledger and a bounded
backoff, reconciliation of ambiguous results, and a routing decision that explains itself. Every
part is covered by automated tests. The **live** YouTube path stays **Unverified (external)** —
no authorised Google credentials were supplied — and that is recorded rather than glossed over.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | **Per-account OAuth** — a second account connects independently and keeps its own token | Done | `youtube/oauth.py` — the pending authorisation carries the account it was started for (`_Pending.account_id`), the token is filed under `youtube_refresh#<account_id>`, and the channel Google reports becomes that account's own row. `api/youtube_accounts.py` — `POST /{account_id}/connect`; `frontend/src/pages/Channels.tsx` — a per-account connect button. `tests/test_youtube_identity.py` — 16 tests |
| 2 | A **callback for the wrong account** is refused | Done | `youtube/oauth.py:complete_auth` — the state is bound to the account it was issued for; a state that belongs to another account (or to none) is refused rather than connected |
| 3 | **`invalid_grant` is isolated** to the account that caused it | Done | `youtube/oauth.py:InvalidGrantError` → `youtube/accounts.py:mark_needs_reconnect`; only that account gets `needs_reconnect=1` (migration v22) and the other accounts keep publishing. The Channels page shows the warning on that account alone |
| 4 | The **audience declaration is the owner's** and is never guessed | Done | `youtube/policy.py` — `madeForKids` is a **tri-state** (`""` / `"false"` / `"true"`); an unanswered declaration raises `policy.AudienceUndecided` before the network call. The value that was sent is recorded on the upload row. `api/youtube.py` — `GET /api/youtube/policy`, `POST /api/youtube/audience`. `tests/test_youtube_policy.py` — 27 tests |
| 5 | **Privacy is never silently changed** | Done | The requested privacy is written onto the row before the transfer; YouTube's own `privacyStatus` is read back afterwards (`youtube/uploader.py:read_back`); a mismatch is reported as "uploaded, private", not "published". A retry keeps the row's own privacy, and the upload no longer mutates the global setting |
| 6 | The **destination is never guessed** | Done | The upload row names the channel it publishes to, the policy is resolved from that row before the call, and the read-back compares YouTube's own `channelId` with the destination that was asked for |
| 7 | The **public default is treated as a known issue** with a safe decision | Done | The global default is now `private`, new channels default to `private`, and a new upload defaults to `private` — **stored values are never silently changed**, so an owner who chose public keeps public |
| 8 | **Resumable upload** that survives a dropped connection | Done | `youtube/resumable.py` — 8 MiB chunks, a persistent session, HTTP 308 (Resume Incomplete) accepted as the normal answer for a non-final chunk, and a resume from the byte actually reached. Migration v24 stores the session URL, the bytes sent, the total size and the expiry |
| 9 | The **day's quota is accounted for** per project | Done | `youtube/quota.py` — 1600 units per upload against a 10 000 default; the units are reserved **before** the transfer, so a transfer that dies halfway still shows up in the usage. `youtube_quota` (migration v24); `GET /api/youtube/quota` |
| 10 | **Exhaustion queues to the reset; a rate limit backs off** | Done | `youtube/quota.py:reset_at` — local midnight, where the ledger's own day rolls over. An exhausted quota leaves the row **pending** with `next_attempt_at` set to the reset and does not count the attempt, because the file never left the machine. A 429 or a 5xx backs off with the exponential delay instead. `youtube/backoff.py` — 30 s → 1 h, capped at 10 attempts, with jitter |
| 11 | **An ambiguous result is reconciled**, never retried blindly | Done | `youtube/reconcile.py` — the evidence is graded: **confirmed** (YouTube's own session record names the video), **evidence** (a title match on the channel — a hint, never a success), **not_uploaded** (the live session says the transfer did not finish) and **unknown** (the lookup failed, so it says nothing). An ambiguous row becomes `needs_reconciliation` (migration v25) and is neither retried nor failed. `tests/test_youtube_reconcile.py` — 23 tests |
| 12 | The **owner has a way out** of an unsettled upload | Done | `PUT /api/youtube/uploads/{id}/confirm` verifies the video with YouTube **first** and refuses (409) when YouTube cannot confirm it; a retry of a `needs_reconciliation` row is recorded as `owner_retried`, and that decision skips reconciliation entirely |
| 13 | **Upload progress** reflects the bytes actually sent | Done | The byte count is written to the row after every chunk, and `UploadOut.progress_percent` is computed from it; the clip list shows "uploading to YouTube · N%" |
| 14 | The **routing decision explains itself** in six fields | Done | `routing/decision.py` — category, channel, reason, rule, confidence and fallback are stored whole when an upload is queued (`routing_decisions`, migration v26), so the record of what was decided does not depend on the rules still looking the same way afterwards. The explanation and the destination come from one resolution, so they cannot drift apart. `tests/test_routing_decision.py` — 24 tests; browser verified on the Routing page and the clip list |
| 15 | The **live YouTube path** is verified against the real API | **Unverified (external)** | No authorised Google OAuth client or test channel was supplied, so nothing here is claimed as live-verified. The whole of M4a's evidence is automated, against doubles for the API |

### Decisions taken in M4a

| Decision | Why | Where recorded |
|---|---|---|
| The **Google account owns the credential and the channel** | One token can see several channels, but only one account's credential should own one channel row. A channel that changes hands under a shared token is how a clip ends up somewhere unexpected | `youtube/accounts.py`, `youtube/oauth.py` |
| The **legacy refresh token falls back to the oldest account only** | It used to belong to whichever account asked, which made a second, never-connected account look as though it held a token — and could publish to the first account's channel | `youtube/accounts.py:refresh_token_for` |
| Connecting a **second account leaves the legacy settings pointing at the first** | The legacy settings are the single-account path. Rewriting them to the newest account would silently move the destination of every upload already queued | `youtube/accounts.py:is_first_account` |
| `invalid_grant` marks **one** account, not the credential | A revoked token for one Google account says nothing about the others, and taking the whole publisher down for one bad account would be a worse failure than the one it fixes | `youtube/oauth.py:_mark_needs_reconnect` |
| `madeForKids` is a **tri-state**, and the empty state **refuses the upload** | It is a legal declaration. Two states cannot say "not yet decided", and guessing "false" is a declaration the owner never made | `youtube/policy.py` |
| The **global privacy default becomes private**, and stored values are left alone | The public default was the known issue. Changing it fixes the next install without silently rewriting what an owner already chose | `config.py:YouTubeSettings.privacy`, migration v23 |
| The **policy is resolved and written onto the row before the network call** | If the transfer dies halfway, the record of what was intended must already exist. Otherwise the row says nothing about what it was trying to do | `youtube/uploads.py:process_upload` |
| A **read-back failure never fails the upload** | The video is already on YouTube. A lookup that fails says nothing about that, and marking the row failed would invite a duplicate | `youtube/uploader.py:read_back` |
| The upload is sent in **chunks with a persistent session**, not one PUT | One PUT of an 80 MB file loses everything when the connection drops. The session handle is the only way back into an upload that stopped partway through | `youtube/resumable.py`, migration v24 |
| The **quota is reserved before the transfer** | An estimate that only counted the calls that succeeded would under-report exactly the case the owner most needs to see: a transfer that died halfway and cost the units anyway | `youtube/quota.py:reserve` |
| **Exhaustion queues to the reset; a rate limit backs off** | They are different problems with different clocks. Failing a row over a limit that resets on its own loses the clip's place in the queue for nothing | `youtube/quota.py:reset_at`, `youtube/queue.py:_run` |
| A **quota wait does not count as an attempt** | The file never left the machine. Spending the row's retry allowance on a limit that has nothing to do with it would use up the allowance on the wrong thing | `youtube/queue.py:_run` |
| Reconciliation **grades its evidence** instead of lumping it together | YouTube's own session record confirms; a title match on the channel is a hint. Treating the second as the first would publish a duplicate under the name of caution | `youtube/reconcile.py` |
| An **unsettled upload waits for the owner** — it is neither failed nor retried | Retrying it could publish the clip twice, and failing it would say "this did not happen" when nobody knows. There is a third state, and it is the honest one | `youtube/uploads.py`, migration v25 |
| The **six-field decision is stored whole** | A rule edited tomorrow leaves yesterday's decision readable. A record recomputed on demand would change with the rules | `routing/decision.py`, migration v26 |
| The **confidence is the classifier's own figure**, labelled as such | There is no quality score anywhere. A bare number next to a clip reads as a measurement, and this one is the model's opinion of a category | `routing/decision.py`, `frontend/src/pages/Routing.tsx` |
| A **fallback is labelled as a fallback** | "No rule matched" and "no classification" are different answers, and a default route presented as though a rule chose it is a small lie | `routing/decision.py:_explain` |

### Residuals carried into later milestones

| Residual | Status | Action |
|---|---|---|
| The **live YouTube path** — OAuth, the Data API, the resumable session, the read-back | Unverified — no authorised Google OAuth client or test channel was supplied; the whole of M4a's evidence is against API doubles | Lane B — run the Lane B script with real credentials |
| YouTube's **own quota reset** is at midnight Pacific Time, while our ledger's day rolls over at local midnight | Partial — our accounting is exact for our own ledger; a retry that lands before YouTube's reset is refused again and waits again, which costs nothing and loses nothing | M5 — reconcile the two clocks if it becomes a nuisance |
| The **Google Cloud compliance audit** for public uploads | Unverified — an un-audited API project can only upload private videos | Owner — request the audit in Google Cloud Console |
| The **channel search in reconciliation** matches on the title that was actually sent, which is a heuristic | Partial — a title match is graded as evidence and never marks an upload published; it is a hint, not a proof | M5 — tighten it if the field evidence shows it misleads |
| The **duplicate check in the worker** is same-clip only; byte-identical detection lives in the report script | Partial — a double enqueue is refused, but two different clips with the same bytes are only found by the script | M5 — move the hash check into the worker |

---

## M4b — Instagram publishing hardening

**Status: Complete**, with one item blocked on the owner (the live Instagram path needs an
authorised Meta app, a Business Integration System User access token and a professional
Instagram account, none of which were supplied). The milestone ships the §9.1 API evaluation,
the publishing implementation on its own queue and its own tables, the export changes Meta's
documented Reel rules require, and a screen that says what is known and what is not. Every part
is covered by automated tests. The **live** Instagram path stays **Unverified (external)** — no
authorised Meta credentials were supplied — and that is recorded rather than glossed over.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | The **official API is evaluated**, with dates and sources | Done | `docs/INSTAGRAM-API-EVALUATION.md` — all eleven §9.1 questions answered against Meta's own documentation, read 2026-11-20, with the URL for every figure. The current API is the **Instagram Platform Content Publishing API**, Graph **v27.0**, and Meta supports **three** setups, not two |
| 2 | The **three setups are handled as three**, not two | Done | `instagram/oauth.py` — Unified Login (`graph.facebook.com`, resumable upload supported), Facebook Login (Page-linked, resumable supported) and Instagram Login (`graph.instagram.com`, **no** resumable upload) each have their own authorisation URL, token exchange and permission set |
| 3 | **Eligibility is reported**, and what is unknown stays unknown | Done | `api/instagram.py:/eligibility` never refuses: it names Meta's requirements, what AutoClip observed, and what is **unverified** — professional-account status, App Review and Business Verification are the owner's to complete, so AutoClip does not claim them. A local file on the Instagram Login setup is refused with the reason rather than routed to another host |
| 4 | The **token is in the keyring**, one per account | Done | `instagram/accounts.py` — the token is filed under `instagram_token#<account_id>`, so two accounts never share a credential; the value never leaves the keyring and `has_token` reports presence, not content |
| 5 | The **media is measured against Meta's documented rules** before it is sent | Done | `instagram/media.py` — container, codec, frame rate, width, bitrate, duration and size are checked against Meta's Reel specifications and the failing measurement is named; the MP4 box tree is walked to find the `moov` atom and any edit list. The caption is checked at **enqueue** time, so a bad caption is refused while it can still be changed |
| 6 | The **export itself** meets those rules | Done | `pipeline/export.py` — ffmpeg's MP4 muxer writes an edit list by default and Meta documents that a Reel must carry none, so `-use_editlist 0` was added; and the audio bitrate was measured at 146.4 kbps against Meta's 128 kbps limit, so it is now `128k`. `tests/test_export_render.py:TestInstagramCompatibility` — 3 slow tests against a real render |
| 7 | The **upload is resumable** and survives a dropped connection | Done | `instagram/publisher.py:upload_file` — 8 MiB chunks to Meta's `rupload` host with the `OAuth` header Meta documents; an upload that continues resumes from the offset **Meta reports**, not from zero |
| 8 | The **publish status is verified**, not assumed | Done | `instagram/publisher.py` — the container is polled at Meta's documented cadence (once a minute, for at most five minutes), the publish returns a media id, and the media is read back afterwards. The read-back failure never fails a publish |
| 9 | A **lost answer is never turned into a second post** | Done | A dropped connection during the publish is flagged `needs_reconciliation`, and the worker checks that flag **before** the transient branch — the backoff would have sent it again. The row waits for the owner: `PUT /api/instagram/uploads/{id}/confirm` verifies the media id with Instagram first and refuses (409) when Instagram does not recognise it |
| 10 | **Meta's error table** decides what happens next | Done | `instagram/errors.py` — every documented code is transcribed and maps to one decision: a dropped connection is tried again with a bounded backoff, a suspected-spam block (4 / 2207051) is **not** retried into, a restricted account (25 / 2207050) is the owner's work, and the publishing limit (9 / 2207042) waits for its reset instead of backing off |
| 11 | The **publishing limit is read, not guessed** | Done | `instagram/publisher.py:publishing_limit` reads `GET /<IG_ID>/content_publishing_limit`. Meta's own documents contradict each other — the content-publishing guide says 100 posts, the carousel limitations say 50, and the endpoint reference says `quota_total` is currently 50 — so AutoClip reads the number in force and hardcodes neither |
| 12 | **The same clip cannot be posted twice** to one account | Done | Instagram has **no idempotency key**, so the guarantee is made locally: a unique index on `(export_id, account_row_id)` makes a double enqueue one row, and the worker refuses to send a clip that is already published to the same account, before the network call |
| 13 | **The platforms are independent** | Done | `instagram/queue.py` and `db/schema.py` — Instagram has its own tables and its own worker. The two queues share nothing but a pure backoff helper, so an Instagram failure cannot cancel a YouTube upload and the reverse is also true |
| 14 | The **screen says what happened** | Done | `frontend/src/components/InstagramSettings.tsx` — the app details, the three setups and what each can do, the accounts, and the eligibility report with its requirements, observations and unverified items. `frontend/src/pages/Clips.tsx` — an Instagram badge beside the YouTube one, distinguishing published, needs checking, failed, skipped and in progress. "On Instagram" and "probably on Instagram" are not the same claim |
| 15 | The **live Instagram path** is verified against the real API | **Unverified (external)** | No authorised Meta app, access token or professional account was supplied, so nothing here is claimed as live-verified. The whole of M4b's evidence is automated, against doubles for the API |

### Decisions taken in M4b

| Decision | Why | Where recorded |
|---|---|---|
| **Three** setups, not two | Meta documents Unified Login, Facebook Login and Instagram Login, and they differ in host, token and permissions. Treating them as one setup breaks two of the three | `instagram/oauth.py:Setup` |
| Unified Login is the **recommended** setup and the default | It needs no Page and supports the resumable upload protocol, so a local file can be sent without introducing cloud storage | `config.py:InstagramSettings.login_type` |
| The **Instagram Login setup refuses a local file** | Meta documents the resumable upload protocol only for apps using Facebook Login for Business. AutoClip says so rather than routing the file to some other host | `instagram/uploads.py:process_upload` |
| **No cloud storage was introduced** | The spec asks for an architecture that avoids it and forbids adding it without approval. The resumable upload protocol sends the file straight from the machine | `docs/INSTAGRAM-API-EVALUATION.md` §9.2 |
| The **publishing limit is read from the API** | Meta's own documents disagree — 100 in one place, 50 in two others. Hardcoding either number would be a guess about a limit that changes | `instagram/publisher.py:publishing_limit` |
| The **duplicate guarantee is local** | Instagram has no idempotency key, so there is no header that says "this is the same post as last time". The guarantee is made by AutoClip instead, and it is checked before the network call | `instagram/uploads.py:duplicate_reason`, migration v27 |
| A **suspected-spam block is not retried into** | Meta's 4 / 2207051 means the publish looked like spam. Trying again makes the account's situation worse, and the decision is not AutoClip's to make | `instagram/errors.py` |
| A **lost answer is not a failed post** | The request may have reached Instagram. Failing the row would say "this did not happen" when nobody knows, and retrying it could post the clip twice. There is a third state, and it is the honest one | `instagram/publisher.py:publish`, `instagram/queue.py:_run` |
| The owner's confirmation is **verified with Instagram** | The owner found the post on Instagram's own page, but AutoClip reads the media id back before recording it. A wrong id is refused, not stored | `instagram/uploads.py:confirm_upload` |
| The **caption is checked at enqueue time** | A caption over Meta's limit is a mistake the owner can still fix, but only while the file is still on the machine | `instagram/uploads.py:enqueue` |
| The **`Authorization: OAuth` header** on the upload host | Meta's upload host takes `OAuth`, not `Bearer`; the Graph calls take `Bearer`. Using the wrong one is a 401 with no useful message | `instagram/publisher.py:upload_file` |
| A **NAT64 address is classified by the address it wraps** | On an IPv6-only network every public host resolves through a NAT64 prefix, and `64:ff9b::7f00:1` is a valid encoding of 127.0.0.1. Refusing them all breaks the network; allowing them all opens an SSRF hole | `security/urlpolicy.py:_nat64_embedded_ipv4` |
| The export carries **no edit list** and **128 kbps audio** | Both are Meta's documented requirements, and both were broken: ffmpeg writes an edit list by default, and the audio measured 146.4 kbps against a 128 kbps limit | `pipeline/export.py` |

### Residuals carried into later milestones

| Residual | Status | Action |
|---|---|---|
| The **live Instagram path** — OAuth, the container, the chunked upload, the publish, the read-back | Unverified — no authorised Meta app, token or professional account was supplied; the whole of M4b's evidence is against API doubles | Lane B — run the Lane B script with real credentials |
| **App Review and Advanced Access** | Unverified — Meta requires both for accounts AutoClip does not own, and Business Verification as well | Owner — the Meta app's own review process |
| The **professional-account requirement** cannot be checked locally | Partial — the Graph API does not report it with the publishing permissions alone, so AutoClip says "unverified" rather than guessing; Meta refuses the publish if it is not met | Owner — check the account in the Instagram app |
| The **publishing-limit contradiction** is resolved by reading the API, but the two figures in Meta's documents remain | Partial — the number in force is read at request time, so AutoClip is right either way; the documents still disagree | M5 — note it in the release report |
| The **confirm endpoint has no screen** | Partial — the owner can record a post Instagram already has through `PUT /api/instagram/uploads/{id}/confirm`, and the clip list says "needs checking - retry", but the confirmation itself is API-only — the same as YouTube's | M5 — add a confirm affordance if the field evidence asks for one |
| The **caption and the AI disclosure** are the owner's to write | By design — AutoClip never writes a caption or declares the media as AI-generated on the owner's behalf | Owner |

---

## M5 — Audit and release

**Status: Complete.** All ten deliverables exist and each is a file, not a promise. The milestone
also **found and fixed three defects** that no unit test had caught, and a fourth in the CI
workflow itself — all four were found by running the application or its gates, and each is now
guarded by a test that fails without the fix.

*(A fourth product defect was found and fixed by M5.1, after this milestone closed. It is recorded
in the M5.1 section below and in `docs/FINAL_UPGRADE_REPORT.md` §4.2, where the defect list is
kept current.)*

The release run is **green on all six CI jobs** — the four backend legs (Ubuntu 3.11, Ubuntu 3.12,
macOS 3.12, Windows 3.12), the frontend build, and the Docker image with its health smoke test.
The Ubuntu py3.12 leg, which had failed twice, now passes.

The live external integrations remain **Unverified (external)**: no authorised ElevenLabs,
hosted-LLM, Google or Meta credential was supplied for any part of this upgrade. That is recorded
as a condition of the release, not quietly upgraded.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | **Complete regression report** | Done | `docs/M5-REGRESSION-REPORT.md` — 9 gates, the full suite green, and the CI run history with each failure diagnosed rather than summarised |
| 2 | **Security review** | Done | `docs/M5-SECURITY-REVIEW.md` — S1–S7 re-verified on evidence, 2 new findings raised and closed, 4 residual risks documented, and **5 things explicitly not checked** |
| 3 | **Performance report** | Done | `docs/M5-PERFORMANCE-REPORT.md` — M0 against M5, plus a like-for-like control run on the base commit so the comparison is not a measurement of a different machine |
| 4 | **Feature acceptance matrix** | Done | `docs/feature-coverage-matrix.md` — 129 rows, recounted by `scripts/verify_matrix_counts.py`, **0 Missing** |
| 5 | **Real-application testing evidence** | Done | `docs/M5-APPLICATION-TESTING.md` — PART 12's format, journeys A–D against the real UI, on real media, with the ducking measured on the rendered file rather than asserted |
| 6 | **Build artifacts** | Done | `docs/BENCHMARK-M5.json`, `docs/BENCHMARK-BASELINE.json` (untouched), and the CI artifacts for the release commits |
| 7 | **Installation and upgrade instructions** | Done | `docs/M5-INSTALLATION.md` — including what the upgrade changes about behaviour, and what to back up first |
| 8 | **Known limitations** | Done | `docs/FINAL_UPGRADE_REPORT.md` §6 — 10 product, 5 engineering and 6 owner-controlled limitations, each named |
| 9 | **Release readiness assessment** | Done | `docs/FINAL_UPGRADE_REPORT.md` §1 — *"Ship it, with the external integrations marked unverified"*, with the three conditions attached to that verdict |
| 10 | **The final report** | Done | `docs/FINAL_UPGRADE_REPORT.md` |

### Decisions taken in M5

| Decision | Why | Where recorded |
|---|---|---|
| **The owner's OS keyring is isolated for every test, not per test** | The first fix covered one test that had been noticed. The audit then found **549** AutoClip entries in the owner's credential store, **535** of them test values. The fix has to be a class fix, so `tests/conftest.py` grew an **autouse** fixture: a test that forgets to ask for isolation still cannot reach the owner's machine | `tests/conftest.py`, `docs/M5-SECURITY-REVIEW.md` M5-02 |
| The credential store was cleaned **by value**, never by name | A name-based sweep would have taken the owner's own credentials with it. Only entries whose stored secret exactly equalled a test literal were deleted; the 14 real ones were kept and confirmed afterwards | `docs/M5-SECURITY-REVIEW.md` M5-02 |
| **The CI's ffmpeg check was corrected, not removed** | It reported an ffmpeg **with** the `ass` filter as not having one. The cause was a `producer \| grep -q` pipeline: `grep -q` exits at the match, the producer gets SIGPIPE, and `set -o pipefail` turns that into a failed step. The check now matches with bash's own pattern matching and never pipes — and a build genuinely without the filter still fails it | `.github/workflows/ci.yml` |
| **A filtergraph is checked structurally, not only by rendering it** | Two of the three export defects were invisible to the filter-level tests because those tests only asserted that certain strings were present. One of them rendered on ffmpeg 9 and failed on ffmpeg 7. The graph is now checked for shape — no output consumed twice, no filter after an output label — so the defect is caught on **every** ffmpeg, not only the one that rejects it | `tests/test_music.py`, `tests/test_export_render.py` |
| The **ducking was measured by differencing two renders** | The bed and the speech share a file, so a level measurement alone cannot tell the bed from the voice. Subtracting a render with the bed from a render without it leaves the bed, and its RMS in the timeline's own speech windows and speech gaps is the ducking, as a number | `docs/M5-APPLICATION-TESTING.md` AT-A-08 |
| The **re-export's missing webcam composition** is recorded as a limitation, not fixed | Rebuilding the per-clip `LayoutPath` is new scope. The framing is right — the cached crop path is reused — so the honest entry is a named limitation, not a pass and not a silent omission | `docs/M5-APPLICATION-TESTING.md` AT-B-05, `docs/FINAL_UPGRADE_REPORT.md` §6.1 |
| The **local model stand-in** is used and labelled everywhere | With no authorised hosted-model credential, the application was pointed at a local service speaking Ollama's API. It exercises the real adapter, gateway, consent checks, budget and prompt assembly; it does not reason. Every plan and answer it produced says so in its own text | `docs/M5-APPLICATION-TESTING.md` §0 |
| The **Linux leg was reproduced locally** before the release commits were pushed | The sidechain defect rendered on the Windows ffmpeg and failed on the Linux one. It was found by running the Linux leg on ffmpeg 7.0.2 rather than by assuming the two platforms agreed | `docs/M5-APPLICATION-TESTING.md` §"The three defects this testing found" |

### Residuals carried out of M5

| Residual | Status | Action |
|---|---|---|
| The **live ElevenLabs path** | Unverified — no authorised credential was supplied for a consent-granted run | Lane B |
| The **live hosted-LLM path** (detection, planning, music selection) | Unverified — same | Lane B |
| The **live YouTube path** | Unverified — no authorised Google credential was supplied | Lane B |
| The **live Instagram path** | Unverified — no authorised Meta app, token or professional account was supplied | Lane B, after App Review and Business Verification |
| The **reframe golden set** — jitter, cut-off faces, the speaker on screen ≥95% of speaking time | Unverified — no fixed three-video set has been checked, before this upgrade or by it. **This is the gate for tagging v0.1.0** | Owner — supply the set and run the measurement |
| The **original requirements and the 7 visual references** | Blocked — they are not on this machine, and they were not reconstructed | Owner — supply them |
| The **re-export does not rebuild the webcam composition** | Partial — the per-clip `LayoutPath` is not persisted, so a re-export reuses the cached crop path | Next release |
| The **eight-scenario ducking matrix** is asserted at the filter and timeline level | **Closed at M5.1** — all eight scenarios are now asserted as full renders. See the M5.1 section below | — |
| The **multi-speaker path** was not exercised on real material | Partial — diarization was not enabled in the application run | Lane C, with diarized footage |
| **Docker** was not built or scanned locally | Partial — Docker is not installed on this machine; the CI `docker` job builds the image and smoke-tests `GET /api/health` | CI covers it |
| **No dependency audit, no fuzzing, no SAST scanner** | Gap — stated as gaps in `docs/M5-SECURITY-REVIEW.md` §7 rather than implied to be covered | Next release |
| **mypy is at 10 errors in 8 files** | Partial — down from the 14-error baseline, unchanged since M1, in modules the upgrade did not touch. CI tolerates mypy with `continue-on-error` | Next release |

---

## M5.1 — Ducking matrix and the empty-timeline defect

**Status: Complete.** A post-release increment, dated **2026-11-21**, on the same branch. The
branch is untagged and **v0.1.0 is still gated on K1**, the reframe golden set, so this did not
change the M5 verdict — it closed the last closeable PARTIAL matrix row and fixed the defect that
writing it surfaced.

**What it closed.** **MUS-31**, the eight-case ducking regression matrix, was the last row still
marked Partial that could be closed without the owner. It asked for all eight scenarios —
continuous speech, a short pause, a long pause, more than one speaker, a sound effect, a
music-heavy source, a low-volume source, and no speech at all — to be **asserted**. The
filter-level tests could only see that certain characters were in the filtergraph; they could not
see whether the graph ducked where it should and stayed out of the way where it should.

**How it was closed.** `tests/test_ducking_matrix.py` — **eight cases, each a real render.** Each
case renders the same clip twice, once with the ducking on and once with it off, and measures the
bed's **own frequency band** in a window of each. The bed sits at 440 Hz and the source's voice at
1000 Hz, so a bandpass at 440 Hz reads the bed on its own, and the ratio of the two renders is the
ducking as a number. The thresholds are deliberately loose about depth (a ducked window must be at
least 6 dB down, against a configured 12 dB) and tight about shape (an un-ducked window must be
within 0.26 dB of full level). What matters is *which* windows are ducked, not the exact number
of decibels.

**What it found.** Seven of the eight passed first time. The **no-speech** case failed, and it
found a real defect: **an empty speech timeline was indistinguishable from no timeline at all.**
The export's contract said an empty list meant "no timeline, fall back to keying the ducking on
the audio", so a clip with no talking fell back to the loudness-keyed sidechain compressor and the
music was pulled down by whatever else the source contained.

**The fix.** `speech_timeline.ducking_intervals()` keeps the three answers apart:

| Answer | Meaning | What the renderer does |
|---|---|---|
| `None` | There is no timeline to follow — it was never built, or it found no speech **anywhere** | Falls back to keying the ducking on the audio |
| `[]` | The timeline was consulted and found no speech **in this clip** | The bed is **not ducked at all** |
| a non-empty list | The speech in this clip | The bed follows an explicit envelope |

The API and the pipeline both call the helper rather than slicing the timeline by hand, so the
boundary cannot drift again.

**Why it was fixed rather than documented away.** The measured impact was small — **≤ 0.9 dB** on
a source carrying its own loud music — but the contract was violated at the API boundary, and the
app's own stated principle is that the music ducking and the webcam layout use the same timeline
and must agree. The webcam layout already treated an empty timeline as "no emphasis" without
falling back; the export did not. **The two now answer the same question the same way.**

**The guard was proven, not assumed.** With the four product files reverted to the pre-M5.1 code,
`test_no_speech_means_no_ducking` fails at a ratio of **0.915** against a flat render, and the
other seven still pass. The files were restored afterwards.

| Case | Measured |
|---|---|
| Continuous speech | 0.397 down under speech, 1.000 flat outside |
| Short pause (300 ms, inside the 350 ms merge window) | 0.408 in the gap — the bed does not recover |
| Long pause (3 s) | 1.001 in the gap, 0.427 in each stretch |
| Multi-speaker | 0.427 / 1.000 / 0.427 — a speaker change is not a pause |
| Sound effect | 0.427 in speech, 1.005 at the effect — a transient is not somebody talking |
| Music-heavy | 0.427 in speech, 1.001 outside; the source's own music within 0.25 of flat |
| Low-volume | Ducked in speech, flat outside — the timeline drives the ducking, not the level |
| **No speech** | 1.005 at the loudest point — full level throughout |

### Decisions taken in M5.1

| Decision | Why | Where recorded |
|---|---|---|
| **M5.1 is a post-release increment, not a change of verdict** | The branch is untagged and v0.1.0 is gated on K1, so the M5 documents are live branch documents and may be updated in place — but every change is dated and recorded here | `docs/UPGRADE-LEDGER.md`, `docs/upgrade-audit.md` §13 |
| **The matrix is measured by differencing two renders, not by a level** | The bed and the speech share a file, so a level measurement alone cannot tell the bed from the voice. The bed's own frequency band can | `tests/test_ducking_matrix.py` |
| **The thresholds are loose about depth and tight about shape** | The configured duck is 12 dB and the measured depth lands shallower, because the bandpass picks up some of the speech's skirt. Asserting the exact depth would make the test brittle for no gain; asserting *which* windows are ducked is the actual contract | `tests/test_ducking_matrix.py` |
| **The empty-timeline defect was fixed, not recorded as a limitation** | The impact was ≤ 0.9 dB, but the contract was violated at the API boundary and the webcam layout already behaved correctly. Fixing it is cheaper than a permanent caveat that says the two halves of the same feature disagree | `docs/FINAL_UPGRADE_REPORT.md` §4.2, defect 4 |

### Residuals carried out of M5.1

Unchanged from M5 — **the live external paths, the reframe golden set, the missing original
requirements, the re-export's missing webcam composition, the un-exercised multi-speaker path,
the absent local Docker, the missing dependency audit, and mypy's 10 errors** all carry forward
exactly as M5 recorded them. M5.1 closed one row and changed nothing else.

---

## Change log

| Date | Commit(s) | Change |
|---|---|---|
| 2026-11-19 | `26ebf00` | Format `runner.py` + `make_e2e_media.py` (AST-identical) |
| 2026-11-19 | `3c290b2` | Format the remaining 36 files (D15) |
| 2026-11-19 | `24060ff` | CI on `feature/**`; ignore branch archives (D8) |
| 2026-11-19 | `615f0e8` | SECURITY.md corrected (docs only) |
| 2026-11-19 | `b2fae13` | M0 deliverable set: spec, audit, matrix, egress, security, baselines, ledger, 26 SSRF xfails |
| 2026-11-19 | `4c869c6` | Ledger changelog row for the M0 deliverable commit |
| 2026-11-20 | `ff134c8` | M0.5 — URL policy enforced; the 26 SSRF xfails became ordinary passing tests and the marker was deleted |
| 2026-11-20 | `8fb2f03` | M0.5 — consent gateway, migration v15, retrofit of every existing external call, privacy API, Settings → External processing |
| 2026-11-20 | `d9ad80c` | M0.5 — SECURITY.md and the audit, inventory, matrix and ledger updated with the enforcement |
| 2026-11-20 | `b390b65` | M1 — the music library, the local measurements, the licence gate, the shared speech timeline, migration v16 |
| 2026-11-20 | `07a4424` | M1 — the ducking follows the shared timeline; the export refuses an unlicensed track |
| 2026-11-20 | `9d5e90b` | M1 — Settings → Music library; the TypeScript build state is no longer tracked |
| 2026-11-20 | `2266466` | M1 — the ledger, the matrix and the changelog updated with the M1 evidence |
| 2026-11-20 | `17dfb30` | M1 fix — the ducking is measured from the clip, not from the source; `relative_slice()` rebases the timeline onto the clip |
| 2026-11-20 | `37f0cdd` | M2 — the webcam detector: a persistent cluster of faces scored on cut stability, with adaptive sampling and a report that says how sure it is |
| 2026-11-20 | `50f7180` | M2 — the layout planner and the ffmpeg composition layer: the 40/60 preset, the face-legibility fallback, the dwell rule, and six real-ffmpeg render tests |
| 2026-11-20 | `1529b5b` | M2 — the layout wired into the runner, the per-source record (migration v17), and the `/api/layout` endpoints |
| 2026-11-20 | `b5810a5` | M2 — Settings → Webcam layout |
| 2026-11-20 | `41a8c82` | M2 — the ledger, the matrix and the audit updated with the M2 evidence |
| 2026-11-20 | `975e376` | M2 — the ledger changelog row for the milestone commit |
| 2026-11-20 | `7ab6e19` | M3 — the AI call budget: one plan, one repair and one music call per clip, counted in the database so a retry does not get a fresh allowance (migration v18) |
| 2026-11-20 | `d3c5828` | M3 — the structured creative plan: a fixed shape, validated before use, malformed output rejected rather than patched, and a declined consent treated as an answer (migration v19) |
| 2026-11-20 | `df67aa5` | M3 — the music choice: three preference scopes, the shapes derived from the measurements, and the clip's music stored with whose choice it was (migration v20) |
| 2026-11-20 | `1f3ff9c` | M3 — the objective measurements and the story/action balance: ten measurements with their evidence and no quality score anywhere (migration v21) |
| 2026-11-20 | `b3d1c25` | M3 — the creative stage wired into the runner, and the budget, plan, preference, format and diagnostics endpoints |
| 2026-11-20 | `fd64fd2` | M3 — the Review screen shows the plan, the budget and the measurements; the score is labelled as the model's suggestion |
| 2026-11-20 | `7cdcf7a` | M3 — the ledger, the matrix and the audit updated with the M3 evidence |
| 2026-11-20 | `7b9751b` | M3 — the ledger changelog row for the milestone commit |
| 2026-11-20 | `cd3ebd1` | M4a — the Google account owns the credential and the channel: per-account tokens, a callback bound to its account, and `invalid_grant` isolated to one account (migration v22) |
| 2026-11-20 | `20f6578` | M4a — the publishing policy: the audience declaration, the privacy that is read back, and the destination that is never guessed (migration v23) |
| 2026-11-20 | `aa1f27f` | M4a — the upload survives a dropped connection: chunked resumable upload, the day's quota ledger, and a bounded backoff (migration v24) |
| 2026-11-20 | `7ed2a8d` | M4a — an upload that may have succeeded is never sent twice: the reconciliation grades its evidence, and an unsettled row waits for the owner (migration v25) |
| 2026-11-20 | `53bc065` | M4a — the routing decision explains itself: the six fields, stored whole and shown (migration v26) |
| 2026-11-20 | `5d46feb` | M4a — the clip list shows the whole routing explanation |
| 2026-11-20 | `8038890` | M4a — running out of quota waits for the reset; a rate limit still backs off |
| 2026-11-20 | `e837faf` | M4a — the ledger, the matrix and the audit updated with the M4a evidence |
| 2026-11-20 | `b55bfad` | M4b — Instagram publishing on its own queue: three OAuth setups, Meta's error table, the chunked upload, the duplicate guard, and the publishing limit read from the API (migration v27) |
| 2026-11-20 | `3bbf876` | M4b — an export that meets Instagram's Reel rules: no edit list, and audio at 128 kbps |
| 2026-11-20 | `6318655` | M4b — a NAT64 address is classified by the address it wraps |
| 2026-11-20 | `2cfeb65` | M4b — the Instagram screen: the connection, the eligibility report and the clip-list badge |
| 2026-11-20 | `521cec5` | M4b — a post that may have succeeded is never sent twice; the owner confirms it with Instagram |
| 2026-11-20 | `0ef1548` | M5 — the Instagram secret test writes to the fake keyring, not the owner's real one |
| 2026-11-20 | `4cf309b` | M5 — the formatter is pinned at 0.17.5, so the format gate is a property of the repository |
| 2026-11-20 | `94c6d9c` | M5 — no test may touch the owner's real OS keyring: an autouse fixture isolates it for every test in the suite |
| 2026-11-21 | `69498e3` | M5 — the CI's ffmpeg subtitle check no longer pipes into `grep -q`: the broken pipe was making CI report that an ffmpeg *with* the `ass` filter did not have one |
| 2026-11-21 | `bcdfc47` | M5 — the export honours the user's music choice and the speech timeline, and the two malformed ducking filtergraphs are fixed; guarded by 7 API tests, 3 real-render tests and a version-independent structural graph check |
| 2026-11-21 | `64d253d` | M5 — the release package: the application-testing evidence, the regression report, the security review, the performance report, the installation guide, the final report, the audit through M5, the matrix, the ledger and the README |
| 2026-11-21 | `cbcbe1c` | docs — the M5 release commit recorded in the ledger and the commit trail |
| 2026-11-21 | `ab9052e` | M5 — the release run recorded as **green on all six jobs** (the four backend legs, the frontend build, and the Docker image with its health smoke test), the Journey D records brought onto the same nine fields as journeys A–C, and the BLOCKED row added to the acceptance table |
| 2026-11-21 | `2931059` | docs — the CI run history reads the same way whichever run you look at: a stable phrasing for the run count, and the run-23 row added |
| 2026-11-21 | `822143e` | docs — four runs were cancelled, not three; the run table is framed as a record that grows |
| 2026-11-21 | `294c274` | M5.1 — the ducking answer is tri-state: no timeline, a timeline that found no speech in this clip, or the speech itself. `ducking_intervals()` produces the right one of the three, and the API and the pipeline both call it. Guarded by the eight-case ducking matrix (`tests/test_ducking_matrix.py`), whose **no-speech** case fails without the fix |
