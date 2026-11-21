# AutoClip — Final Upgrade Report

**Milestone:** M5 — independent audit and release
**Amendment:** M5.1 — the ducking matrix and the empty-timeline defect (2026-11-21)
**Amendment:** M5.2 — the real four-hour ingest, and four more defects (2026-11-21)
**Amendment:** M5.3 — the complete ten-minute pipeline, and five more defects (2026-11-21)
**Branch:** `feature/upgrade-u0-u10`
**Base commit:** `bf76811` (`feature/autonomous-platform-v2`)
**Report date:** 2026-11-21
**Governing specification:** `docs/UPGRADE-SPEC.md` (M0–M5, supplied 2026-11-19)

---

## 1. The verdict

**Ship it, with the external integrations marked unverified.**

Every milestone from M0 to M5 is complete, and **M5.1**, **M5.2** and **M5.3** closed the last
closeable partial matrix row and then took the application to real media afterwards — the last of
them all the way through the **complete pipeline** on a whole source. The full automated suite is
green — **1,397 tests, zero failures, zero skips, zero xfails** — and the application was exercised
through its real UI against real media, not only through unit tests.

The one thing this report will not do is call the live external integrations verified. They were
not: no authorised ElevenLabs, hosted-LLM, Google or Meta credential was supplied for any part of
this upgrade. Every one of those paths is covered by automated tests against a double, and the
double stands in for the same code path the real service would take — but "the code is right" and
"it works against the live API" are different claims, and only the first one is supported.

| | |
|---|---|
| **Milestones complete** | **8 of 8** — M0, M0.5, M1, M2, M3, M4a, M4b, M5 — plus **M5.1**, **M5.2** and **M5.3**, post-release increments that are not one of the specification's milestones (see the amendments below) |
| **Gate items** | 94 across M0–M4b: **91 done**, **1 blocked on the owner**, **2 unverified (external)**. M5's 10 are in §4. |
| **Feature coverage** | **129 rows**: 110 Implemented · 9 Partial · 1 Blocked · 9 Not Applicable · **0 Missing** |
| **Tests** | **1,397 passing** — 1,351 in the unit selection, 46 in the render selection — 0 failing, 0 skipped, 0 xfailed, plus 24 real-media e2e tests run against a real source |
| **Real-media evidence** | A **real 4-hour live recording** ingested twice (360p, and the product's default 1080p); the pipeline exercised on real segments cut from that same file, with a real local model, producing two real clips and two real exports — **and, at M5.3, a real ten-minute video run through every stage end to end**, producing three real clips and three real exports |
| **New runtime dependencies** | **Zero.** The whole upgrade was built on the dependency set the project already had. |
| **Schema** | v14 → **v27**, 19 → **32 live tables**, thirteen migrations, no user data destroyed |
| **API surface** | 18 routers / 108 routes → **21 routers / 162 routes** |
| **CI** | **Every run on this branch since the two failures was green.** Two of the runs failed — both were real defects, diagnosed and fixed rather than explained away — and four were cancelled by a newer push. The release run is green on all six jobs, on all four platforms. See §4.1. |
| **Defects found by running the application** | **13 product defects** and **1 defect in the CI workflow itself**, all fixed, all guarded by tests that fail without the fix. See §4.2. |
| **Open security findings** | **0** high, **0** medium, **0** low. 4 residual risks documented, 5 things not checked — all in §6. |

### The three conditions attached to the verdict

1. **The external integrations are unverified.** Four live paths (ElevenLabs, hosted LLM, YouTube,
   Instagram) have never been run against the real service. This is a credential problem, not a
   code problem, and it is the reason the verdict is "ship with the external integrations
   unverified" rather than "ship".
2. **The reframe golden set is still unverified.** The acceptance bar for the reframe stage — no
   visible jitter, no cut-off faces, the speaker on screen ≥95% of speaking time — has never been
   checked against a fixed three-video golden set. That was true before this upgrade and it is
   still true. **It is the gate for tagging v0.1.0**, and this milestone did not attempt it.
3. **The original requirements were never available.** The specification refers to an original
   requirements document and seven visual references. Neither is on this machine. They were not
   reconstructed, and the matrix rows that depend on them are marked *Blocked — source missing*
   rather than quietly assumed satisfied.

### Amendment — M5.1, 2026-11-21

M5 was closed on **2026-11-21**. This report was updated in place afterwards by **M5.1**, a
post-release increment that closed the last closeable PARTIAL matrix row (**MUS-31**, the
eight-case ducking matrix) with eight real renders — and fixed the defect that writing them
surfaced. **The verdict does not change.** What changed is the matrix (**110 Implemented · 9
Partial**, was 109 · 10) and the defect count (**four product defects**, was three). See **§4.3**
for the matrix and the defect, and `docs/UPGRADE-LEDGER.md` for the dated record.

### Amendment — M5.2, 2026-11-21

M5.2 did the thing the specification asked for and the earlier milestones had only approximated:
it pointed the application at a **real four-hour YouTube live recording** and ran it through the
**real ingest path**. It found **four more product defects** — the configured download format was
dead, the download was never written to the transfer log, the crop-safety measurement reported
failures that had not happened, and the URL policy mistook a load-balanced host for a DNS-rebinding
attack.

**The verdict does not change.** The matrix is unchanged at **110 Implemented · 9 Partial · 1
Blocked · 9 Not Applicable · 0 Missing** — no row was closed and none was opened. What changed is
the **defect count** (four → **eight**), the **test count** (1,315 → **1,330**), and the **evidence
base**: the ingest path and the pipeline are now verified against real media, not only against
doubles. See **§4.4**, and `docs/M5-APPLICATION-TESTING.md` for the per-journey record.

### Amendment — M5.3, 2026-11-21

M5.2 left one thing on the table, and named it: **the complete pipeline had never been run on a
complete source.** The four-hour recording was ingested in full but only *segmented*; the pipeline
ran on pieces cut from it. M5.3 closed that by choosing a source short enough to run **whole** —
a ten-minute podcast — and pushing it through **every stage**, from the paste to the finished
vertical clip.

It found **five more product defects**, and they are the most consequential set of the whole
upgrade, because they are the ones a user in **Hindi** would have hit on their first real video:

* the sentence and clause terminators were **Latin-only**, so a Devanagari transcript had almost
  no sentence boundaries in it, and the clip-edge refinement then silently dropped every candidate
  that fell short of the minimum duration;
* the export's ffmpeg command line could exceed **Windows' own 32,767-character limit**, and the
  job died with a misleading *"filename or extension is too long"*;
* the webcam's speech-emphasis was evaluated against a **segment-local** clock, so the webcam only
  magnified in the *first* segment of a clip;
* a caption could be held on screen for **twelve seconds**, because the caption inherited the
  recogniser's word timing rather than bounding its own lifetime;
* and the export's video graph **consumed a filter output once per crop segment**, which ffmpeg 9
  tolerates and ffmpeg 7 refuses — so a multi-segment clip exported on the developer's machine and
  failed on every strict ffmpeg. The Linux leg found it.

**The verdict does not change.** The matrix is unchanged at **110 Implemented · 9 Partial · 1
Blocked · 9 Not Applicable · 0 Missing**. What changed is the **defect count** (eight → **thirteen**),
the **test count** (1,330 → **1,397**), and the **evidence base**: a complete real source has now
been ingested, transcribed, highlighted, laid out, captioned and exported **end to end**. See
**§4.5**, and `docs/M5-APPLICATION-TESTING.md` AT-F-01 … AT-F-15 for the per-journey record.

---

## 2. What was built

### M0 — Audit and baseline
A 20-section audit of the existing product, a **129-row** feature coverage matrix, a **14-path**
egress inventory, a security and SSRF audit, CI baseline evidence, a performance baseline, an
external-constraints register, and a full search record for the missing original sources. An
independent adversarial review returned **11 corrections**, all applied before the milestone was
recorded complete.

Two commits were deliberately kept separate: a formatting-only commit
(`26ebf00` + `3c290b2`, AST-compared so the docstrings survived) and a docs-only `SECURITY.md`
correction (`615f0e8`).

### M0.5 — Security and consent
A single egress gateway (`security/egress.py`) and a URL policy (`security/urlpolicy.py`) that
**every** external transfer now passes through — including the ones that already existed
(ElevenLabs STT/TTS, all four LLM adapters, yt-dlp, FFmpeg, the MediaPipe model download, the
YouTube trending chart, the YouTube upload). Destinations are classified as loopback, private or
public; redirects are re-classified hop by hop; DNS is resolved twice to defeat rebinding; IPv4,
IPv6 and IPv4-mapped forms are all classified; FFmpeg runs with `-protocol_whitelist file,pipe`;
yt-dlp runs with its proxy disabled.

The **26 SSRF tests** that were pre-registered as `xfail(strict=True)` at M0 became ordinary
passing tests, and every marker was deleted. The final count of `xfail` markers in the tree is
**zero**.

### M1 — Music intelligence and speech-aware ducking
A music library that **indexes** the user's files and never copies, moves or deletes them; local,
deterministic analysis (spectral flux, autocorrelation BPM, RMS energy, ebur128 LUFS, heuristic
mood); a licensing model with five states where **unknown blocks the export** and where *verified*
deliberately cannot be set by a user; and a **single shared speech timeline** that drives both the
ducking and the webcam layout — there is no second detector in the tree.

The ducking boundary is exact: a **349 ms** gap merges, a **350 ms** gap does not, and the merge
is computed on millisecond timestamps rather than on 30 ms frames.

### M2 — Webcam detection and intelligent layouts
A webcam region detected as a **persistent, stable cluster of faces**, scored on support,
stability, cut-stability and persistence, with adaptive sampling that raises the frame rate where
the cuts are dense. Below a confidence floor of 0.35 the result is gameplay-only, not a guess.
The stacked layout is a true split — gameplay scaled to its slot over a blurred background, the
webcam cut from the same source in parallel trims so it stays in sync with the crop-path concat.
The user's choice is stored separately from what the detector found, and the detector never
overwrites a choice.

### M3 — Creative intelligence
A structured creative plan that is **validated in full before use** — a malformed plan is
rejected, not patched — with one repair retry and then a deterministic fallback whose reason is
recorded. An **AI call budget** of 1 planning call + 1 repair + ≤1 music call per clip, capped at
`max_clips` (**12 calls** at the default of 10), with the counters persisted in `job_ai_budget` so
a retried job does not get a fresh allowance. And **ten named objective diagnostics** — no score,
no rating, no invented quality figure. The model's own 0–100 clip score is labelled a *creative
suggestion* everywhere it appears.

### M4a — YouTube publishing hardening
Five parts, each separately tested. **Per-account OAuth** — the Google account owns the credential
and the channel, the token is filed under `youtube_refresh#<account_id>`, and an
`invalid_grant` marks only that account for reconnection. **An explicit publishing policy** —
`madeForKids` is a tri-state whose *undecided* state **refuses the upload**, and the privacy that
was asked for is read back after the fact so the UI can say "uploaded, private" rather than "on
YouTube". **A resumable upload** with a chunked session, a quota ledger and a bounded backoff.
**Reconciliation** that grades its evidence — confirmed, evidence, not-uploaded, unknown — and
never turns an ambiguous result into a second upload. And a **routing decision** that explains
itself, recorded whole at enqueue time so the record survives a later rule edit.

### M4b — Instagram publishing hardening
The current official API — the **Instagram Platform Content Publishing API**, Graph **v27.0** —
evaluated against Meta's own documentation, read on 2026-11-20, with the URL for every figure.
Meta supports **three** setups, not two, and they are not interchangeable: two can take a local
file and one cannot, so AutoClip **refuses** a local file on the Instagram Login setup rather than
routing it somewhere else. Meta's error table is transcribed into the code, and each code maps to
one decision. The publishing limit is **read from the API** because Meta's own documents contradict
each other (100 in one place, 50 in two others). Instagram runs on **its own worker and its own
tables**, so an Instagram failure cannot cancel a YouTube upload and the reverse is also true.

Two real export bugs were found by measuring the file rather than by reading the documentation:
ffmpeg writes an MP4 edit list by default and Meta documents that a Reel must carry none, and the
audio was measuring 146.4 kbps against Meta's 128 kbps limit.

### M5 — Audit and release
This report and its companions. See §4.

---

## 3. Acceptance status

Every acceptance item, by the status the evidence supports.

| Status | Meaning | Count |
|---|---|---|
| **VERIFIED** | The criterion has passing automated evidence, or was checked against the real application and the evidence is recorded. | 91 gate items + 110 matrix rows |
| **PARTIAL** | Part of the criterion is met and the rest is not. **The gap is named in §5.** | 9 matrix rows |
| **FAILED** | The criterion is not met and it was supposed to be. | **0** |
| **UNVERIFIED** | The code is present and the automated evidence passes, but the criterion can only be settled against a live external system that was not available. | 2 gate items + 4 live paths |
| **BLOCKED** | The criterion cannot be settled because a required source is missing, not because the work was skipped. Named in §5. | 1 matrix row |
| **NOT APPLICABLE** | Out of scope by the specification. | 9 matrix rows |

**Every one of the 129 matrix rows is accounted for**: 110 VERIFIED + 9 PARTIAL + 1 BLOCKED + 9
NOT APPLICABLE = 129. **0 Missing.** The recount is mechanical —
`scripts/verify_matrix_counts.py` reads the table and fails if the summary and the rows disagree.

### The two UNVERIFIED gate items, and the four UNVERIFIED live paths

| Item | Status | Why | What would settle it |
|---|---|---|---|
| M4a gate 15 — the live YouTube path | **UNVERIFIED (external)** | No authorised Google credential was supplied. | A Lane B run against a real channel with an authorised OAuth client |
| M4b gate 15 — the live Instagram path | **UNVERIFIED (external)** | No authorised Meta app, access token or professional account was supplied. | A Lane B run against a professional account, with App Review and Business Verification completed by the owner |
| ElevenLabs transcription | **UNVERIFIED (external)** | No authorised credential for a consent-granted run | A Lane B run with an authorised key |
| Hosted LLM — detection, planning, music selection | **UNVERIFIED (external)** | Same | A Lane B run with an authorised key |

**What *is* verified about those paths.** Every one of them is covered by automated tests against a
double, and the tests assert the things that matter: the destination is classified, the consent
decision is required and honoured, the credential is read from the keyring and never logged, the
request shape matches the documented API, the error codes map to the right decision, the retry
budget is bounded, and a lost answer is never turned into a second upload. The live paths are
unverified in the sense that **no real credential was used** — not in the sense that the code is
missing or wrong.

---

## 4. The M5 deliverables

| # | Deliverable | Where | State |
|---|---|---|---|
| 1 | Complete regression report | `docs/M5-REGRESSION-REPORT.md` | Done — 9 gates, 1,397 tests, the CI run history |
| 2 | Security review | `docs/M5-SECURITY-REVIEW.md` | Done — S1–S7 re-verified, 2 new findings, 4 residuals, 5 things not checked |
| 3 | Performance report | `docs/M5-PERFORMANCE-REPORT.md` | Done — M0 vs M5, plus a like-for-like control on the base commit |
| 4 | Feature acceptance matrix | `docs/feature-coverage-matrix.md` | Done — 129 rows, recounted by script |
| 5 | Real-application testing evidence | `docs/M5-APPLICATION-TESTING.md` | Done — journeys A–D against the real UI, on real media, with the ducking **measured** on the rendered file |
| 6 | Build artifacts | `docs/BENCHMARK-M5.json`, `docs/BENCHMARK-BASELINE.json` (untouched), the CI artifacts for the release commits | Done |
| 7 | Installation and upgrade instructions | `docs/M5-INSTALLATION.md` | Done — including what the upgrade changes about behaviour |
| 8 | Known limitations | §6 of this report, and `docs/M5-SECURITY-REVIEW.md` §6–7 | Done |
| 9 | Release readiness assessment | §1 of this report | Done |
| 10 | The final report | This file | Done |

### 4.1 The CI runs on this branch

The run history is release evidence, not noise. **Every run on this branch since the two failures
was green.** The two that failed were **real defects** — one in the product, one in the CI itself.
Neither was a flake, and neither was explained away. Four runs were cancelled by a newer push.

**The table below is the run history as it stands at the M5.3 commit.** It is a record, and it
grows; the claim that matters is the one above it, which does not go stale.

| Runs | Result | What happened |
|---|---|---|
| 4, 5, 7–13, 15–17, **22**, **23**, **24**, **25**, **26**, **27**, **28**, **29**, **30**, **31** | **success** | green |
| 6, 14, 18, **21** | **cancelled** | each superseded by a newer push — the concurrency group cancelled the older run |
| **19** (`4cf309b`) | **failure** | the Ubuntu legs failed in **Unit tests**; Windows and macOS passed the same tests. A test wrote to the owner's real OS keyring. On Linux there is no keyring backend, so the token was never stored and the assertion could not hold — the test passed on Windows and macOS *because those machines had a real keyring to write to*. Fixed by `94c6d9c`, an **autouse** isolation fixture so no test can reach the owner's credential store |
| **20** (`94c6d9c`) | **failure** | the Ubuntu py3.12 leg failed at *"Verify ffmpeg can burn subtitles"*. The check piped the ffmpeg filter list into `grep -q`; `grep -q` exits at the match, the producer gets **SIGPIPE**, and GitHub's `set -o pipefail` turns that into a failed step. The runner's ffmpeg 8 has a filter list large enough to fill the pipe, so CI reported that an ffmpeg **with** the `ass` filter did not have one — the job log shows `printf: Broken pipe` and then the `ass` filter listed on the very next line. **Corrected, not removed**: the check now matches with bash's own pattern matching and never pipes, and a build genuinely without the filter still fails it |

**The release run is green on all six jobs** — the four backend legs (Ubuntu 3.11, Ubuntu 3.12,
macOS 3.12, Windows 3.12), the frontend build and the Docker image with its health smoke test.
The Ubuntu py3.12 leg, which had failed twice, now passes.

**Run 26 is the M5.1 tree, and it is green on all six jobs too** — the same six jobs, with the
eight-case ducking matrix in the render selection.

**Run 29 is the whole M5.2 code tree, and it is green on all six jobs** — the same six jobs, with
the ingest, the crop-safety and the URL-policy guards in the unit selection.

**Run 30 is the M5.2 documentation tree, and it is green on all six jobs too** — the same six jobs,
with the M5.2 evidence in the tree.

**Run 31 is the whole M5.3 tree — the four M5.3 code commits and the documentation, together — and
it is green on all six jobs too**
([run 44944459562](https://github.com/Shrishant1cog/autoclip/actions/runs/44944459562)).
`2b5935d`, the defect-13 fix, was **not** pushed on its own, so **that** is the run that first
exercised it on every CI job.

**Both failures were reproduced before they were fixed.** Run 19 was reproduced on a Linux
environment with no keyring backend. Run 20 was reproduced with a 320 KB filter list: the old body
fails it, the new body passes it, and a no-`ass` build still fails the new body. A failure that is
only fixed in CI is a failure that comes back.

### 4.2 Thirteen product defects, found by running the application

The full-suite gates were green while the application was broken. These defects were found
by **running the application and its gates**, not by reading the code, and each is now guarded by a
test that fails without the fix.

| # | Defect | Found by | Fix | Guard |
|---|---|---|---|---|
| 1 | The API export path ignored the user's music preference and passed no speech intervals, so a re-exported clip had **neither the chosen track nor any ducking** | clicking *Export this clip* on a clip with a track chosen | `api/clips.py` resolves the music through the same three-scope precedence the pipeline uses, and hands the renderer the job's speech timeline sliced to the clip | 7 regression tests in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix** |
| 2 | The timeline-driven ducking filtergraph was **malformed** — an output label in the middle of the bed's chain — and ffmpeg refused the whole graph | the export failing, with ffmpeg's own stderr in the response | the bed chain carries no output label; the label is added where the bed is used | 3 real-render tests in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix** |
| 3 | The sidechain fallback consumed one filter output **twice**, which **ffmpeg 9 accepts and ffmpeg 7 refuses** | the Linux CI leg, reproduced locally on ffmpeg 7.0.2 | the speech is split with `asplit=2` into a mix copy and a key copy, both on the bed's channel layout | the same 3 render tests, plus a **structural** check in `tests/test_music.py` that no filter output is consumed twice and no filter follows an output label — version-independent, so it catches the defect on any ffmpeg |
| 4 | **An empty speech timeline was indistinguishable from no timeline at all**, so a clip with no talking fell back to keying the ducking on the audio — and the music was pulled down by whatever else the source contained | the **no-speech** case of the eight-case ducking matrix, at M5.1 | `speech_timeline.ducking_intervals()` keeps the three answers apart: no timeline (`None`), a timeline that found no speech in this clip (`[]`), and the speech itself. `[]` means the bed is not ducked at all | `tests/test_ducking_matrix.py::test_no_speech_means_no_ducking` — **fails without the fix**, at a measured ratio of 0.915 against a flat render — plus 4 unit tests for the helper and 2 for the API boundary |
| 5 | **`ingest.ytdlp_format` was dead.** The download hard-coded `bestvideo*+bestaudio/best`, so a four-hour live stream came down at 1440p60 — **12.54 GiB** — instead of the 1080p the configuration's own comment promises | the **real ingest** of a four-hour YouTube live recording, at M5.2 | the command line is built in one place, `_download_command`, and the format selector comes from the settings | 3 tests in `tests/test_ingest.py`; **2 of the 3 fail without the fix** (`assert 'height<=1080' in 'bestvideo*+bestaudio/best'`) |
| 6 | **The yt-dlp download was authorised but never written to the transfer log**, so `EGRESS-INVENTORY.md` E11's claim that it is *logged* was false, and the largest thing AutoClip ever sends left the machine with nothing in the user's own log | reading *Settings → External processing* after a **5.52 GB** download: **0 rows** | the transfer is recorded on refusal, on a failed launch, on a failed download and on success, with the duration | `tests/test_ingest.py::test_the_download_is_recorded_in_the_transfer_log` — **fails without the fix** (`assert [] == [('ok', ...)]`) |
| 7 | **The crop-safety diagnostic compared a per-clip crop against the whole-source webcam region** and called it *"the detected face"*, so it reported *"the crop cuts through the detected face"* on a clip that tracks the face perfectly, and on a clip with **no face in it at all** | the application's own diagnostics on two real clips of a real stream | the crop plan carries the faces it was built around, in source pixels and in the clip's own time base; the check compares each keyframe against the face nearest it **in time**, and `diagnose_clip` no longer accepts a whole-source rectangle as a face | 5 tests in `tests/test_diagnostics.py` and 2 in `tests/test_reframe.py`; the time-matching test **fails without the fix** |
| 8 | **The URL policy refused any host whose two DNS answers were not the same set of addresses**, so a legitimate load-balanced host — `graph.facebook.com` — was treated as a DNS-rebinding attack and the publish was refused | the **full-suite gate**, as a flaky failure in the Instagram publishing tests — it passes alone and fails in a full run | the rebinding guard compares the **class** of the two answers, not the exact addresses: an answer that moved *inwards* (public → private or loopback) is refused, and an answer that moved between two **public** addresses is a load balancer and is allowed | 2 tests in `tests/test_url_policy.py` **fail without the fix**; 3 more assert that the protection still holds, and 1 asserts the unit suite never resolves a real hostname |
| 9 | **The sentence and clause terminators were Latin-only.** `SENTENCE_END` matched `. ! ?` and `CLAUSE_END` matched a small set of ASCII marks, so a Devanagari transcript had **almost no sentence boundaries in it** — and the clip-edge refinement then *silently dropped* every candidate that fell short of the minimum duration, because the too-short branch had no fallback at all | the **real ten-minute Hindi source**: the danda `।` appears in **5** of its **1,128** words, and the old pattern matched **1** | the terminator sets carry the marks of the other writing systems — every code point verified against the Unicode database — and `_clamp_duration`'s too-short branch now falls back to the **first word that reaches the minimum duration**, instead of dropping the candidate | 65 tests across `tests/test_transcript.py` (new) and `tests/test_boundaries.py`; **33 fail without the fix** |
| 10 | **The export's ffmpeg command line could exceed Windows' own 32,767-character limit**, and the job died with `FileNotFoundError: [WinError 206] The filename or extension is too long` — a message about a *filename* for what is really an over-long *filter graph* | the **real export** of a clip with **20 crop segments** and **11 speech-emphasis spans**: the command was **36,743 characters**, and it failed at progress 0.88 **every time** | the webcam crop and scale are applied **once, after the segment concat** rather than once per segment. They are per-frame operations, so the picture is the same — but the graph no longer grows with the segment count, and the emphasis expression is evaluated against the **clip's** timeline | a new `tests/test_export_graph.py` (6 tests) and `tests/test_ffmpeg.py::TestCommandLineLength` (4 tests); **7 fail without the export fix** and **4 more** without the command-line guard. The real command drops **36,743 → 10,697** characters |
| 11 | **The webcam's speech emphasis was evaluated against a segment-local clock.** The crop was applied to each PTS-reset segment, so the emphasis expression's `t` restarted at every segment boundary — the webcam only ever magnified in the **first** segment of a clip | the same real clip, read against `croppath.axis_expression`, which subtracts `offset_s` for exactly this reason | applying the crop **after** the concat restores the clip-relative timeline, so the emphasis expression means the same thing it means everywhere else in the product | `tests/test_export_render.py::TestLayoutRender::test_the_speech_emphasis_renders_in_a_later_stretch` — a **behavioural** render test: it compares the webcam strip at a quiet moment with the webcam strip at a talking moment, in the **second** stretch. It **fails without the fix** |
| 12 | **A caption could be held on screen for twelve seconds.** The caption inherited the recogniser's word timing, and one Whisper alignment estimate stretched a single Hindi word across **7.84 seconds** of silence | the application's **own diagnostic** on a real clip: *"3 word(s) are held on screen too long"*. The exported `.srt` carried a cue of `00:00:09,080 --> 00:00:21,650` — **12.57 seconds** | the caption's lifetime is the **renderer's** business, not the recogniser's: `captions.MAX_CAPTION_S = 2.5` bounds every caption, the grouping breaks on a start-span ceiling, and `captions.caption_spans()` is the single source of the caption timing — shared by the renderer and the diagnostic | 8 tests in `tests/test_captions.py::TestCaptionLifetime` and 2 in `tests/test_diagnostics.py`; **8 fail without the fix**. The longest caption drops **12.57 s → 2.50 s**, with the text fully preserved |
| 13 | **The export's video graph consumed a filter output once per crop segment.** The source was split in **two**, and then *each* segment read from the same output again — which is invalid, because a filter output may be consumed only once | the **Linux leg**, on **ffmpeg 7.0.2** — the version that reproduces the CI's platform. ffmpeg **9** tolerates it; ffmpeg **7** refuses it with *"Invalid stream specifier"*, so a multi-segment clip exported on the developer's machine and failed on every strict ffmpeg | the source is split **once per consumer**, so every segment has a copy of its own. The shape was measured against **both** ffmpeg builds before it was chosen: `split=64` is accepted by 7.0.2 and 9.0.2 alike, while a multi-output `trim` would need a `setpts` per output because `setpts` has only one | 4 tests in `tests/test_export_graph.py::TestGraphShape`; **3 fail without the fix**. The structural graph check moves to `tests/graph_shape.py` and is now applied to the **video** graph as well as the music graph — it was already written for this class of defect, but only ever looked at the music graph |

**Defect 3 is the one that would have shipped.** It rendered on the machine the code was written
on and would have failed on the CI runners and on every user with an ffmpeg older than 9. It was
caught by reproducing the Linux leg locally rather than assuming the two platforms agreed.

**And a fifth defect, in the CI itself** — the broken-pipe check above. It was found while
confirming the first three.

**The ducking was then measured, not asserted.** The same clip was exported twice through the
UI, once with the chosen bed and once with *No music at all*. Subtracting the two renders leaves
the bed, and the RMS of that difference in the timeline's own speech windows and speech gaps is
the ducking as a number: **0.04126** in the gaps, **0.01139** under speech — a measured drop of
**3.62× = 11.2 dB** against a configured **−12.0 dB**. The bed's dominant frequency in the
difference signal is **440.0 Hz**, the tone in the chosen file, so the bed in the file is the bed
that was chosen. Full method in `docs/M5-APPLICATION-TESTING.md` AT-A-08.

### 4.3 M5.1 — the ducking matrix, and the defect it found

M5 was closed on **2026-11-21** with one matrix row left partly open: **MUS-31**, the eight-case
ducking regression matrix. The row asked for all eight scenarios — continuous speech, a short
pause, a long pause, more than one speaker, a sound effect, a music-heavy source, a low-volume
source, and no speech at all — to be **asserted**. The filter-level tests could only see that
certain characters were in the filtergraph. They could not see whether the graph ducked where it
should and stayed out of the way where it should.

**M5.1 closed that row with real renders.** Each case renders the same clip twice — once with
the ducking on and once with it off — and measures the bed's **own frequency band** in a window
of each. The bed sits at 440 Hz and the source's voice at 1000 Hz, so a bandpass at 440 Hz reads
the bed on its own, and the ratio of the two renders is the ducking as a number.

| Case | What it asserts | Measured |
|---|---|---|
| Continuous speech | The bed is down for the whole stretch, and back once the speech ends | 0.397 down, 1.000 flat outside |
| Short pause (300 ms) | The bed does **not** recover in a gap inside the 350 ms merge window | 0.408 in the gap |
| Long pause (3 s) | The bed **does** come back in a real gap, and goes down again after it | 1.001 in the gap, 0.427 in each stretch |
| Multi-speaker | A speaker change is not a pause — both stretches are ducked, the gap is not | 0.427 / 1.000 / 0.427 |
| Sound effect | A loud transient is not somebody talking, so the bed does not move for it | 0.427 in speech, 1.005 at the effect |
| Music-heavy | The source's **own** music is untouched; only the added bed is shaped | 0.427 in speech, 1.001 outside; the source's music within 0.25 of flat |
| Low-volume | A quiet speaker is still a speaker — the timeline drives the ducking, not the level | ducked in speech, flat outside |
| **No speech** | A clip with no talking gets its music at **full level** | 1.005 at the loudest point |

**Seven of the eight passed first time. The eighth found a real defect** — an empty speech
timeline was indistinguishable from no timeline at all, so a clip with no talking fell back to
keying the ducking on the audio and the music was pulled down by whatever else the source
contained. It was **defect 4** in §4.2, and the fix is the tri-state contract: no timeline
(`None`), a timeline that found no speech in this clip (`[]`), and the speech itself.

The guard was **proven**, not assumed: with the four product files reverted to the pre-M5.1 code,
`test_no_speech_means_no_ducking` fails at a ratio of **0.915** against a flat render, and the
other seven still pass. The impact was small — **≤ 0.9 dB** on a source with its own loud music —
but the contract was violated at the API boundary, and the app's own stated principle is that the
music ducking and the webcam layout use the same timeline and must agree. **It was fixed rather
than documented away.**

**M5.1 is a post-release increment, not a change of verdict.** The M5 verdict stands; the branch
is untagged and **v0.1.0 is still gated on K1**, the reframe golden set. What changed is the
matrix: **110 Implemented · 9 Partial · 1 Blocked · 9 Not Applicable · 0 Missing**, out of 129.
The dates, the counts and the commit trail are in `docs/UPGRADE-LEDGER.md`; the audit trail is
in `docs/upgrade-audit.md` §13.

### 4.4 M5.2 — the real four-hour recording, and four more defects

Every earlier milestone tested AutoClip against **doubles**: a fake provider, a synthetic clip, a
stubbed filesystem. That is the right way to test a pipeline, and it is not the same as running
it. M5.2 pointed the application at a **real four-hour YouTube live recording** and ran it through
the **real ingest path**.

**The source.** `https://www.youtube.com/live/l-oEKLu4Y3w` — *"BACK AT IT AGAIN IN THE VICE CITY!!!
| NO PROMOTIONS"*, channel **CarryisLive**, uploaded **2026-11-19**, **4:00:10** long,
**4,032,307 views**, public, no age limit, a **Hindi** audio track with ASR captions, and a best
stream of **2560×1440p60** AV01 + Opus — **12.54 GiB**. It is a third-party creator's stream, and
it was used for **technical acceptance only — nothing was published anywhere.**

**What ran, and what it produced.**

| Run | What | Result |
|---|---|---|
| **Ingest 1** | The full 4:00:10 file at 360p | **653 MiB** (684,877,097 B), 640×360, 30 fps, 14410.118 s. Cancelled at the stage boundary |
| **Ingest 2** | The full 4:00:10 file at the **product's default** | Format **399+140** (1920×1080@60, `av01.0.09M.08` + `mp4a.40.2` @ 129.471 kbps), **5,529,989,793 B**, 14410.048 s. Cancelled after the download |
| **Ingest 3** | The full file at 360p muxed, after defect 6 was fixed | Format 18, **844,513,587 B**, and **exactly one** transfer-log row: `operation=media_download`, `provider=yt-dlp`, `destination=https://www.youtube.com/live/l-oEKLu4Y3w` (query stripped), `destination_class=public`, `outcome=ok`, `duration_ms=175578` |
| **Pipeline** | A **real 180 s segment cut from that same downloaded file**, through the whole pipeline, with a **real local model** | **done** in **1,136 s**: prepare 10 s → transcribe 432 s (284 words, `hi`) → highlights 342 s → creative 242 s → reframe 20 s → export 90 s |
| **Output** | Two real clips and two real exports | `the-biggest-challenge-in-making-money_9x16.mp4` (h264 1080×1920, 30 fps, AAC stereo 48 kHz, 26.97 s) and `why-nobody-tells-you-this-about-scaling_9x16.mp4` (24.97 s), each with a `.srt` sidecar in Devanagari |

**The model was a real Ollama** (`llama3.1:8b` at `127.0.0.1:11434`, `active_provider=ollama`), so
no hosted credential was spent, and transcription was pinned to `engine=local`, whisper `small`,
`compute_type=int8`, language auto-detected as `hi`.

**The four-hour pipeline itself was not run, and the reason is measured, not assumed.**
Transcription took about **7 minutes per 180 s** on this four-core laptop, so the full recording
would have needed roughly **9.6 hours** of transcription — **≈17 hours** with the highlight stage,
which took **342 s for 180 s** of speech on the same machine, and **≈25 hours** for the whole
pipeline. The **ingest** of the complete file was
exercised, twice, at two formats; the **pipeline** was exercised on real segments cut from that
same downloaded file. This is recorded as **NOT APPLICABLE** in the evidence table, with the
measurement attached, rather than quietly passed.

#### The four defects it found

**Defect 5 — the configured download format was dead.** `ingest.ytdlp_format` existed in the
settings and its own comment promised a 1080p cap, but `download_youtube` hard-coded
`bestvideo*+bestaudio/best`. The real ingest proved it: the default configuration produced
**12.54 GiB of 1440p60** where the configuration said 1080p. The command line is now built in one
place and the format selector comes from the settings. After the fix, the same setting produced
**399+140 — 1920×1080@60**.

**Defect 6 — the download was never written to the transfer log.** The yt-dlp transfer was
authorised through the egress gateway and then simply not recorded, which made
`docs/EGRESS-INVENTORY.md` E11's claim that it is *logged* **false** — and it meant the largest
thing AutoClip ever sends left the machine with nothing in the user's own log. Reading *Settings
→ External processing* after a **5.52 GB** download showed **0 rows**. The transfer is now
recorded on refusal, on a failed launch, on a failed download and on success, with the duration.
Ingest 3 is the proof: **exactly one row**, `outcome=ok`, `duration_ms=175578`.

**Defect 7 — the crop-safety measurement reported failures that had not happened.** The check
compared a **per-clip** crop against the **whole-source webcam region** — the rectangle the
detector found once for the entire recording — and called that rectangle *"the detected face"*.
On two real clips it reported *"the crop cuts through the detected face"* for both: one clip that
tracks the face perfectly, and one clip with **no face in it at all**. MediaPipe's own
observations settle it — **99 observations at 2 fps**; **51 inside the first clip's window**,
tracking the real face; **none at all** inside the second clip's window. The crop plan now carries
the faces it was built around, in source pixels and in the clip's own time base, and the check
matches each keyframe to the face nearest it **in time**. `diagnose_clip` no longer accepts a
whole-source rectangle as a face — the parameter is **gone**, so the mistake cannot be made again
by accident.

The proof was read back through the application's own endpoint, on the rebuilt crop paths, with
the stored report cleared so the measurement was fresh:

| Clip | The old rule, same crop paths | The app's own diagnostics, after the fix |
|---|---|---|
| `2e78863daafc4c6e` — tracks the real face | **FAIL** — *"the crop cuts through the detected face"* | **PASS** — `1 segment(s), 123 face(s) tracked` |
| `23bb845bc10d453a` — no face in the window | **FAIL** — *"the crop cuts through the detected face"* | **PASS** — `1 segment(s), no face tracked` |

**Defect 8 — a load-balanced host was mistaken for a DNS-rebinding attack.** The full-suite gate
failed once: **1,324 passed, 1 failed**. The failing test was an Instagram publishing test that
**passes when run alone** — the signature of a flake. It was not one. The URL policy resolves
**twice** on purpose, to defeat DNS rebinding, and the check was *"the two answers must be the
same set of addresses"*. `graph.facebook.com` — **Meta's own Graph API host** — answers with a
rotating subset of its own edge addresses, so a legitimate publish was refused with *"DNS for
graph.facebook.com changed between lookups … refusing a possible rebinding"*. **Both answers were
public**, so neither could reach anything the policy does not already allow; the refusal bought no
security and broke the feature. The guard now compares the **class** of the two answers, not the
exact addresses: an answer that moved **inwards** — public on the first lookup, private or
loopback on the second — is still refused, and so is an answer that moved to an address that may
not be contacted at all. Only a move between two public addresses is allowed, because that is a
load balancer.

And the test was wrong too: the Instagram test stubbed `httpx` but not the resolver, so a unit
test was reaching the **real DNS** — slow, non-deterministic, and the reason a product defect
looked like a flake. The whole unit suite now resolves nothing.

#### One thing that looked like a defect and was not

The M5.2 pipeline was re-run on the same segment. It produced **zero clips**. That is not a
defect: the transcription differed between the two runs (**284 words** against **243**), and the
model's candidates all failed the **20–90 s** duration refinement. The application's own Review
screen explains it — *"No clips came back. The model found nothing self-contained enough to stand
alone — which is a real answer for some source material, not necessarily a failure."* It is
recorded as a **model-quality observation**, and the zero-clip result is reported as it is.

**M5.2 did not change the verdict.** No matrix row was closed and none was opened. What changed is
the **evidence**: the ingest path and the pipeline are now verified against real media, and the
defect count went from four to **eight**.

### 4.5 M5.3 — the complete ten-minute pipeline, and five more defects

M5.2 left one thing on the table, and named it as a limitation: **K22 — the complete pipeline had
never been run on a complete source.** The four-hour recording was ingested in full, but only
*segmented*; the pipeline ran on pieces cut from it. The reason was measured, not assumed:
transcription took about seven minutes per 180 s on this four-core machine, so four hours would
have needed roughly **9.6 hours** of transcription — and roughly **25 hours** for the whole
pipeline.

**A ten-minute source does not have that problem.** M5.3 chose one, and pushed it through **every
stage** — paste the link, ingest, prepare, transcribe, highlight, lay out, export, caption,
diagnose — and inspected what came out.

> **The four-hour arithmetic, corrected (2026-11-22).** The M5.2 documents said *"roughly
> **16 hours** of transcription alone"*. That does not reproduce from the rates they quote:
> 14,410 s ÷ 180 s × 432 s is **9.6 hours**, not 16. **17.2 hours** is the transcription **plus**
> the highlight stage, and the **whole** pipeline is **≈25 hours** — which is the figure that
> matches the measured segment rate of 1,136 s per 180 s. The number was most likely the
> transcription-and-highlight total, mislabelled. **The verdict does not change** — the four-hour
> pipeline was still not run and was still impractical — but the arithmetic is now right, and it
> makes the reason stronger rather than weaker. See `docs/M5-PERFORMANCE-REPORT.md` §7.

**The source.** `https://youtu.be/tg2MwT5FPdY?si=CEj6REktSyC2O_An` — *"PODCAST OF THE DECADE🥵|
CARRYMINATI"*, channel **CarryMinati**, uploaded **2026-09-14**, **10:19** long, **29,316,913
views**, **1,193,759 likes**, public, no age limit, a **Hindi** audio track, **no manual
subtitles**, and **50 formats** — of which **not one** was muxed; the best was **2560×1440@30**
AV01 + Opus. It is a third-party creator's video, and it was used for **technical acceptance only
— nothing was published anywhere.**

It was also **harder** than M5.2's source. A podcast with intercut b-roll: a full-screen face at
5 s, an AI-generated animation at 120 s with **no face**, a **pillarboxed vertical** clip at 240 s
with **no face**, and a different, wider framing at 600 s.

#### What ran, and what it produced

| Stage | What | Result |
|---|---|---|
| **Acceptance** | The short link through the real UI and the real API | `ingest.is_youtube_url` accepts `youtu.be`; `POST /api/sources/youtube` → **201**, source id **`47d64e9e7fc14313`**; the frontend posts the URL **unchanged** |
| **Ingest** | The whole file, through the real yt-dlp path | Format **399+140** (1920×1080 AV01 `av01.0.08M.08` + `mp4a.40.2` @ 129.482 kbps), **140,602,318 B** in **64.55 s**. The source row holds the right title and channel, duration **618.811791 s**, **1920×1080**, **29.97002997 fps** |
| **The transfer log** | The one row the download must leave | **exactly one**: `operation=media_download`, `provider=yt-dlp`, `destination=https://youtu.be/tg2MwT5FPdY` (query stripped), `destination_class=public`, `outcome=ok`, `duration_ms=64550` |
| **Transcribe** | The whole file, local whisper `small`, language auto-detected | **1,346 s** (22.4 min) for 619 s of audio. `transcript.json` written: language `hi`, model `small`, **1,128 words**, **193 segments** |
| **Highlight** | A real local Ollama (`llama3.1:8b` at `127.0.0.1:11434`) | **10 raw candidates** proposed; the fixed refinement kept **6**. The old refinement kept **2** |
| **Export** | All three deduplicated clips, through the real renderer | `why-most-agencies-die-at-10-clients_9x16.mp4` (40,539,188 B), `alien-interview_9x16.mp4` (34,941,233 B), `the-problem-with-marriage_9x16.mp4` (28,552,646 B) — each 1080×1920, 29.97 fps, AAC stereo, **0.000 % full-scale**, and each with a `.srt` sidecar |
| **Diagnose** | The application's own ten measurements, on each clip | Clip 2 and clip 3: **every measurement `ok: true`**. Clip 1: `ok: false` on **`black_frames` only** — and that one is a **true positive about the source**, not a defect (below) |
| **The whole pipeline** | **3,746 s (62.4 min)** for 619 s of source | ≈ **6.05× real time**, measured as the job's own `started_at → finished_at`. M5.2 measured the *segment* pipeline at **1,136 s per 180 s** — **≈6.3×** — so two different sources and two different measurements agree within **4%** |

**No hosted credential was spent and no hosted call was made.** Both pipeline stages build a single
provider from `active_provider`, and `active_provider=ollama`.

**The title is stored exactly as yt-dlp returned it** — the emoji's U+1F975 code point intact, no
U+FFFD, no lone surrogates, and the database row identical to what the API returns. The mojibake
that appeared in the earlier console output was **the PowerShell cp1252 console**, not the data.

#### What the model chose, and what it did not

The run made **seven** model calls, and they did not all have the same outcome. The table below is
the whole of it, and it is recorded because a summary that said "the model did the planning"
would have been wrong for the second job.

| | Job 1 — `1075820ea45841fe` | Job 2 — `f4648116d6ba49e4` |
|---|---|---|
| Highlight stage | 2 calls, **425.1 s** | 2 calls, **656.8 s** |
| Creative-planning calls | **1** — 98.2 s | **2** — 148.7 s + 96.6 s = **245.3 s** |
| Did the plan validate? | **Yes, first try** | **No** — neither the plan nor its schema-repair retry |
| The stored plan | `source='ai'`, `problems=[]` | `source='fallback'`, `problems=['the creative-planning budget was spent']` |
| The budget counters | `plan_used=1, repair_used=0` | `plan_used=1, repair_used=1` |
| What the plan chose | `caption_strategy='clean_lower'`, `ducking_db=-12.0` | `caption_strategy=''`, `ducking_db=0.0`, `reason=''` — the deterministic defaults |

The highlight stage makes **two sequential calls** because a 619 s source is split into **two
windows** of 480 s with a 60 s overlap, and a local model runs them **one at a time**
(`LOCAL_CONCURRENCY = 1`) rather than contending with itself.

**The second job's plan fell back, and the database says so.** The planning budget is **one plan
call and one repair retry per job**. Job 2 spent both: the model answered, the answer did not
match the schema, the repair answer did not match it either, and the plan fell back with the
reason recorded. The later **defect-12 resume** asked for a plan again, found the budget spent,
and wrote the fallback again — **without** silently spending another call.

**What fell back was the plan, not the clips.** The three clips' **titles, hooks, reasons and
scores** are the **highlight stage's** — they came from the model's own candidates in the first
place (*"Hook is not strong, but payoff is a specific and concrete statement."*). What took the
deterministic defaults was the **creative plan's** layer: `layout='auto'`, `crop='auto'`,
`caption_strategy=''`, `music_track_id=''`, `ducking_db=0.0`, `transition='cut'`, `reason=''`.

This is also where the **stochasticity** shows up. Detection runs at
`DetectionConfig.temperature = 0.3`, so the before-run and the re-run saw **different candidate
sets** and proposed different titles — which is why the controlled comparison is the **A/B on the
identical candidate list** plus the **offline sweep** over 1,130 plausible ranges, and not the
raw 1-vs-3 end-to-end clip counts (see "Two things that looked like defects and were not",
below).

#### Defect 9 — the sentence terminators were Latin-only

Whisper emits the terminator of the language it transcribed: a full stop for English, the **danda**
`।` for Hindi. The detector only knew Latin punctuation, so a Hindi transcript had almost no
sentence boundaries in it — and the clip-edge refinement then *silently dropped* every candidate
that fell short of the minimum duration, because the too-short branch had no fallback at all.

Measured on the real transcript: **1,128 words**; the old `SENTENCE_END` matched **1** of them,
the old `CLAUSE_END` **28**; the danda appears in **5** words; `?` once; no `॥`; one U+FFFD.

The impact was quantified offline, over **1,130 plausible candidate ranges** drawn from the real
transcript:

| | Old | New |
|---|---|---|
| Candidates kept | **852** (75 %) | **1,070** (94 %) |
| Candidates dropped | **278** | **60** |
| Mean kept duration | 61.1 s | 52.9 s |

And then measured **inside the product**, on the re-run's own identical list of ten candidates: the
old refinement kept **2**, the new one kept **6** — and the pipeline's own deduplication turned
those into the **three clips** that were exported.

The fix has two halves. The terminator sets now carry the marks of the other writing systems —
every code point checked against the Unicode database — and `_clamp_duration`'s too-short branch
falls back to the **first word that reaches the minimum duration** instead of dropping the
candidate. One mark is **deliberately excluded**: the Tibetan **tsheg** `་` separates syllables,
not clauses, and treating it as a clause end would split Tibetan speech into one word per segment.
A test pins that.

#### Defect 10 — the ffmpeg command line could exceed Windows' own limit

Windows refuses a command line longer than **32,767 characters**. The export's command was
**36,743** — and the job died with `FileNotFoundError: [WinError 206] The filename or extension is
too long`, a message about a *filename* for what is really an over-long *filter graph*. It failed
at progress 0.88 **every time**, on the real clip with **20 crop segments** and **11 speech-emphasis
spans**.

The root cause was a single line of arithmetic: the webcam crop spelled the whole speech-emphasis
expression out once per crop segment, so a **293-character** term was repeated **80 times** —
**23,440** of the real clip's **36,588** graph characters.

**The fix is to apply the webcam crop and scale once, after the segment concat**, rather than once
per segment. They are per-frame operations, so the picture is the same. The real command drops
**36,743 → 10,697** characters — **0.33×** of the limit:

| Clip | Before | After |
|---|---|---|
| *Why most agencies die at 10 clients* | 6,817 | 6,972 |
| *Alien interview* — the one that failed | **36,743** | **10,697** |
| *The problem with marriage* | 7,609 | 7,764 |

A **sub-fix was tried and rejected**: using the crop's `out_w`/`out_h` for the crop centre instead
of the explicit x/y expression. It was empirically disproved — ffmpeg does **not** update `out_w`
for a dynamic width, so the emphasis died — and the existing render test caught it. The rejection
and its reason are recorded in the code.

There is now also a **guard before the failure**: `ffmpeg.check_command_line_length` refuses an
over-long command **before** `Popen`, with a message that names the filter graph rather than
blaming a filename. The limit is overridable so the check itself is testable on Linux CI.

#### Defect 11 — the speech emphasis ran on a segment-local clock

The same change fixed a second defect that had been hiding behind the first. The emphasis
expression is written against **clip-relative** speech spans — and `croppath.axis_expression`
subtracts `offset_s` for exactly that reason. But the webcam crop was applied to each PTS-reset
(`setpts=PTS-STARTPTS`) segment, so the expression's `t` restarted at every segment boundary: the
webcam only ever magnified in the **first** segment of a clip.

Applying the crop after the concat restores the clip-relative timeline, so the emphasis expression
means the same thing it means everywhere else in the product. The guard is a **behavioural**
render test, not a string check: it renders the webcam strip at a quiet moment and at a talking
moment in the **second** stretch and asserts the two differ. It fails on the old code.

#### Defect 12 — a caption could be held on screen for twelve seconds

The application's **own diagnostic** caught this one: *"3 word(s) are held on screen too long"*, on
the clip *The problem with marriage*. The cause was an alignment estimate — Whisper stretched one
Hindi word, `में`, across **7.84 seconds** of silence, and the caption inherited it.

The ground truth, measured on the rendered file rather than on the transcript:

| | Before | After |
|---|---|---|
| `bold_pop` (one caption per word) | **7.84 s** | **2.05 s** |
| The group styles (`karaoke_fill`, `clean_lower`) | **12.57 s** | **2.50 s** |
| The exported `.srt` cue | `00:00:09,080 --> 00:00:21,650` — `ने, नहीं, साइड में` | `ने, नहीं,` (9.080…11.580) and `साइड में` (11.760…14.260) |

**The text is fully preserved.** The *waiting* is what was cut short: a caption is read, not
watched, and once the text has been read, holding it on screen is noise.

The fix belongs to the **caption layer**, not the transcript layer, and deliberately so. The
recogniser's word timings are estimates and several consumers want them as they are; it is the
**caption's own lifetime** that needs a bound. So `captions.MAX_CAPTION_S = 2.5` bounds every
caption, the grouping breaks on a start-span ceiling so a stretched word does not drag the words
before it along, and `captions.caption_spans()` is now the **single source** of the caption
timing — shared by the renderer and the diagnostic, so the diagnostic measures the captions that
are actually burned into the export rather than the recogniser's opinion of them.

The diagnostic's *"held too long"* check was **removed** rather than re-tuned, because once the
renderer guarantees the bound it is unreachable; the longest caption is now reported as a
**measurement**. The fresh diagnostics read `"20 words, 0 overlap(s), longest caption 2.05s"`, and
the clip's overall verdict is `ok: true`. Across the three re-exported clips the longest captions
are **2.500 s / 2.500 s / 2.380 s** — none over the bound.

#### Defect 13 — the video graph consumed a filter output once per crop segment

This one was found by the **Linux reproduction leg**, on **ffmpeg 7.0.2** — the version that
reproduces the CI's platform — and it is the reason that leg exists.

The export's video graph split the source in **two** and then read from the same output again,
once per crop segment:

```
[0:v]split=2[gsrc][wsrc];
[gsrc]trim=start=0.0000:end=2.5000,setpts=PTS-STARTPTS[s0];
[gsrc]trim=start=2.5000:end=5.0000,setpts=PTS-STARTPTS[s1];   ← the same output again
```

**A filter output may be consumed only once.** ffmpeg **9.0.2** tolerates the violation;
ffmpeg **7.0.2** refuses it with *"Invalid stream specifier: gsrc"* and *"Error binding
filtergraph inputs/outputs: Invalid argument"*. The developer's machine agreed with the
developer's ffmpeg, so it rendered there and nowhere else — the same way defect 3 did, and for
the same reason.

The fix is to split the source **once per consumer**, so every segment has a copy of its own:

```
[0:v]split=4[gsrc0][gsrc1][wsrc0][wsrc1];   ← one output per consumer
```

The shape was **measured on both ffmpeg builds** before it was chosen, rather than read out of
the documentation:

| Graph | ffmpeg 7.0.2 | ffmpeg 9.0.2 |
|---|---|---|
| **today** — each output used twice | **FAIL** — `Invalid stream specifier` | OK |
| **split=N**, one output per consumer | **OK** | OK |
| one `trim` with several ranges | OK, but `setpts` has only **one** output, so it needs a `setpts` per output | same |

`split=N` is accepted up to **64** outputs by both builds. The alternative — one `trim` with
several start/end pairs — was rejected because `setpts` has only one output, so each range would
need its own `setpts`, which is a larger change for no benefit.

**The structural check for this class of defect was already written.** It was the fix for defect
3, the M5 sidechain bug — but it only ever looked at the **music** graph. The video graph was never
checked, so nothing in the suite could see this. The check now lives in `tests/graph_shape.py` and
is applied to **both** graphs.

It earned its keep immediately. The first version of the fix named the split's outputs and the
trims' outputs `ws{index}` — the same label, twice. **The check caught it before any render.**
That is the kind of mistake a parser catches and a render on one ffmpeg does not.

#### Two things that looked like defects and were not

**The black stretch is in the source.** One clip reports `black_frames` not-ok. `ffmpeg blackdetect`
on the **raw source** finds `black_start:601.534267 black_end:603.369433 black_duration:1.835167`,
plus a second **0.53 s** stretch at 154.49 s — and the export carries the **identical** 1.835 s
stretch. The measurement is right; the source has a black frame in it. It was not "fixed".

**The clip counts are not comparable across runs.** The detection stage runs at
`DetectionConfig.temperature = 0.3`, so the before-run and the re-run saw **different candidate
sets** and proposed different titles. The raw "1 clip before, 3 clips after" comparison is therefore
**not** a controlled measurement of the fix. The controlled comparison is the one in §4.5 above: the
**same ten candidates**, refined by the old code and by the new code — **2 kept against 6** — plus
the offline sweep over 1,130 candidate ranges. Those are the numbers the claim rests on.

#### M5.3 did not change the verdict

No matrix row was closed and none was opened: the count is unchanged at **110 Implemented · 9
Partial · 1 Blocked · 9 Not Applicable · 0 Missing**. What changed is the **defect count** (eight
→ **thirteen**) and the **evidence base**: a complete real source has now been ingested, transcribed,
highlighted, laid out, captioned, exported and diagnosed **end to end**, which is what **K22**
said was missing.

---

## 5. Every PARTIAL item, named

Nothing is hidden behind an aggregate. These are the nine matrix rows that are not fully
implemented, and what is missing in each.

| ID | Item | What is met | What is not |
|---|---|---|---|
| MUS-16 | Manual music override | The manual choice always beats an AI choice, no model is consulted, and the source is recorded as `user` | The override is stored per scope (global / source / clip); the **original single global setting** is not the only way to set it |
| MUS-17 | Five licence states | All five states exist and unknown is the default | **`verified` is deliberately not settable from the API** — independent verification is not something a user can assert. The API returns 400 and writes nothing |
| MUS-26 | Duck only the added music | The speech chain is untouched and only the bed is shaped. **Measured at M5** on the rendered file: the speech windows of a paired render (with the bed, without the bed) differ by 0.00079 RMS — the encoder, not the ducking. **Measured again at M5.1** on a source carrying its own music: the source's music comes out of the ducked render within 0.25 of the flat render's, while the added bed drops by at least 6 dB | The **bit-identical** render against a no-music render is **not asserted** — a bit-identical comparison is not possible once the bed is mixed in, so the guarantee is structural plus measured, not bitwise |
| CR-01 | Scene detection | Shots are detected **once per source** and cached; the per-clip cut count drives the action signal and the music context | The detector's **own per-cut confidence is discarded** — only the boundaries are stored |
| CR-02 | Visual action / intensity | Action is a documented, reproducible measure — the cut rate normalised by `ACTION_CUTS_PER_MINUTE=8.0` | It is a **proxy** for visual action, not a model of what is happening on screen |
| CR-04 | Multi-signal highlight detection | Loudness is **not** a signal at all; the measured speech density and cut rate tilt the model's own score, and the story/action instruction changes what the model is asked for | Visual action and reaction are **inferred by the model from the transcript**, not measured |
| CR-06 | Sentence/silence/scene-aware context | The edges snap to the nearest **sentence** boundary and pull back into the **silence** before the first word | The **scene boundary is not part of the clip-edge rule** |
| GOV-11 | The original requirements matrix | The matrix exists and every row records its status | The rows that depend on the **missing original requirements** are blocked |
| GOV-17 | yt-dlp network restriction | The URL is classified before the fetch, a private destination is refused, proxies are disabled, and FFmpeg runs with `-protocol_whitelist file,pipe` | **yt-dlp's own secondary requests** — the manifest, the CDN, the page assets — are made by yt-dlp and cannot be re-classified hop by hop. A Lane B controlled test is still required |

**MUS-31 was the tenth, and it was closed at M5.1.** The eight-case ducking matrix is now asserted
as **eight full renders**, each measured on the bed's own frequency band. It is described in
§4.3.

**M5.2 closed no rows and opened none.** The count is unchanged at **9 Partial · 1 Blocked**, and
that is the honest answer: the four defects M5.2 fixed were not matrix rows. But M5.2 did change
the **evidence** behind two of the rows above. **GOV-14** (the egress gateway) claimed the yt-dlp
download was logged, and it was not — the transfer was authorised and then silently dropped. It is
now recorded, and that was proven on a real 844 MB download. **GOV-17** (yt-dlp network
restriction) stays **Partial** for exactly the reason it always did: yt-dlp's own secondary
requests — the manifest, the CDN, the page assets — are made by yt-dlp, not by AutoClip, so
AutoClip cannot re-classify each hop. That is unchanged and still needs a Lane B controlled test.

**And one BLOCKED item:**

| ID | Item | Why |
|---|---|---|
| GOV-10 | The original requirements and the 7 visual references | They are **not on this machine**. A full search was recorded in `docs/original/MANIFEST.md` — 0 of 8 found. They were not reconstructed. |

---

## 6. Known limitations

### 6.1 Product

| # | Limitation |
|---|---|
| K1 | **The reframe golden set is unverified.** No fixed three-video set has been checked for jitter, cut-off faces, or the speaker being on screen ≥95% of speaking time. **This is the gate for v0.1.0.** |
| K2 | **The original requirements and 7 visual references are missing.** The visual design could not be checked against them. |
| K3 | **The first face-detection model download still happens at first use**, with no pre-flight check at job start. An offline machine fails inside the pipeline. The error names the file and its path, so it can be placed by hand. |
| K4 | **AutoClip does not take its own database backup before migrating.** The migrations are additive and transactional, so they do not destroy data — but a copy of `autoclip.db` before upgrading is still worth taking. |
| K5 | **The Instagram confirmation is API-only.** `PUT /api/instagram/uploads/{id}/confirm` records a post the owner found on Instagram, and the clip list says "needs checking - retry", but the confirmation itself has no screen — the same as YouTube's. |
| K6 | **The professional-account requirement cannot be checked locally.** The Graph API does not report it with the publishing permissions alone, so AutoClip says *unverified* rather than guessing. Meta refuses the publish if it is not met. |
| K7 | **Meta's own publishing-limit documentation contradicts itself** — 100 in one place, 50 in two others. AutoClip reads the number in force and hardcodes neither, but the contradiction remains in Meta's documents. |
| K8 | **There is no emergency-stop route, and a job can only be cancelled or retried** — not paused and resumed. |
| K9 | **The `verified` music licence state cannot be reached through the API.** By design. |
| K10 | **A re-export from the Review page does not rebuild the webcam composition.** The per-clip `LayoutPath` is not persisted, so a re-export at 9:16 reuses the job's cached **crop path**. The framing is right — the resolution, the crop and the duration all match the requested ratio — but a stacked webcam/gameplay composition from the layout planner is **not** reconstructed. Rebuilding it is new scope, so it is recorded here as a limitation rather than presented as a pass. Found during the M5 application test (`docs/M5-APPLICATION-TESTING.md` AT-B-05). |
| K22 | **The complete four-hour pipeline was still not run.** The **ingest** of the complete file was exercised twice, at two formats, and the **pipeline** was exercised on real segments cut from that same downloaded file. Transcription measured at **432 s per 180 s** on this four-core machine, so the full recording would have needed roughly **9.6 hours** of transcription and roughly **25 hours** for the whole pipeline. The claim is about the ingest path and about the pipeline on real segments — **not** about the complete recording end to end. Found at M5.2. **Amended at M5.3:** a *complete* source — a ten-minute podcast — has now been run through **every** stage end to end, so the claim is no longer "pieces of a real source" but "a whole real source". The **four-hour** one remains unrun, for the measured reason above. **Corrected at M5.3:** the "16 hours of transcription alone" this row originally quoted did not reproduce from its own rate; see §4.5. |
| K23 | **The pipeline was exercised with local models only** — a local Ollama model and local whisper. The hosted-LLM paths remain unverified for the reason they always were: no authorised credential was supplied. Found at M5.2. |
| K24 | **The caption lifetime is one constant for every style and every language.** `captions.MAX_CAPTION_S = 2.5` is the same for a punchy social caption and for a lecture, and for English and for Hindi. A style with a deliberately slower reading pace may have its caption cut short. Found at M5.3. |
| K25 | **The caption bound hides the symptom rather than correcting the alignment.** A word that genuinely was spoken across a long pause now produces a caption that leaves the screen early, so the words after it appear with a gap in the subtitle. The bound was chosen over rewriting the recogniser's timings because several consumers want the timings as the recogniser reported them; the trade-off is recorded here rather than hidden. Found at M5.3. |
| K26 | **The ffmpeg command line is still built inline.** ffmpeg 9.0.2 removed `-filter_complex_script`, and neither `-filter_complex @file` nor `-filter_complex /file` reads a file — so there is no way to move a long graph off the command line. The M5.3 fix keeps the graph **0.33×** of the limit for the shape that failed, and the command line is now **refused before ffmpeg runs** rather than failing obscurely, but a clip with very many more segments could still approach the limit. Found at M5.3. |
| K27 | **The ffmpeg-version coverage is two builds wide.** The export's filter graph was measured against **ffmpeg 7.0.2** and **ffmpeg 9.0.2**, and it now uses only constructs both accept. An ffmpeg **older than 7**, or a build with a different filter set, is **not** covered by evidence. What *is* established is that the graph no longer depends on a newer ffmpeg's leniency — and that the structural check, not the ffmpeg, is what catches this class of defect now. Found at M5.3. |

### 6.2 Engineering

| # | Limitation |
|---|---|
| K11 | **mypy is at 10 errors in 8 files.** Down from the 14-error baseline, unchanged since M1. The errors are in modules the upgrade did not touch, and are deferred to whoever changes them. CI tolerates mypy with `continue-on-error`. |
| K12 | **The cold import is ~40% slower than at M0** — 93 → 132 `autoclip` modules, about 1.5 s → 2.4 s on this machine. It is a one-off server-start cost, not a runtime path, and the growth is FastAPI building 21 routers instead of 18 rather than a new dependency. Explained in `docs/M5-PERFORMANCE-REPORT.md` §3. |
| K13 | **The cold-start model download** (Whisper weights from Hugging Face) is a third-party library fetch that AutoClip records but does not gate. |
| K14 | **No dependency vulnerability scan, no fuzzing, no SAST scanner** was run. Listed as gaps in `docs/M5-SECURITY-REVIEW.md` §7 rather than implied to be covered. |
| K15 | **No load test** and **no peak-memory sampling** during a render. |

### 6.3 Owner-controlled

These are not defects. They are the owner's to complete, and AutoClip will not do them on their
behalf.

| # | Item |
|---|---|
| K16 | **Live credentials** for ElevenLabs, a hosted LLM, Google and Meta. |
| K17 | **Google OAuth compliance.** An un-audited API project can only upload private videos. |
| K18 | **Meta App Review, Advanced Access and Business Verification.** |
| K19 | **The `madeForKids` declaration** on every channel, and the licensing claims on every music track. |
| K20 | **Public publishing.** Every upload is an explicit owner action, and the audience and privacy are recorded rather than guessed. |
| K21 | **Paid subscriptions and budgets**, including the LLM providers and the ElevenLabs tier. |

---

## 7. The evidence index

| Deliverable | File |
|---|---|
| The governing specification | `docs/UPGRADE-SPEC.md` |
| The audit — 20 sections, the original 18 plus the conflicts and the sequence | `docs/upgrade-audit.md` |
| The milestone ledger — gate items, decisions and residuals, per milestone | `docs/UPGRADE-LEDGER.md` |
| The feature coverage matrix — 129 rows, recounted by script | `docs/feature-coverage-matrix.md` |
| The egress inventory — 14 transfer paths | `docs/EGRESS-INVENTORY.md` |
| The M0 security audit | `docs/SECURITY-AUDIT.md` |
| **The M5 security review** | `docs/M5-SECURITY-REVIEW.md` |
| **The M5 regression report** | `docs/M5-REGRESSION-REPORT.md` |
| **The M5 performance report** | `docs/M5-PERFORMANCE-REPORT.md` |
| **The M5 real-application testing evidence** | `docs/M5-APPLICATION-TESTING.md` |
| **The M5.1 ducking matrix — eight cases, each a real render** | `tests/test_ducking_matrix.py` |
| **The M5.2 real-media evidence — the four-hour ingest, the segment pipeline, the four defects** | `docs/M5-APPLICATION-TESTING.md` §M5.2, AT-E-01 … AT-E-12 |
| **The M5.2 crop-safety proof — the old rule and the new rule, on the same crop paths** | `docs/M5-APPLICATION-TESTING.md` §"The gate that found the last defect" |
| **The M5.2 ingest guards** | `tests/test_ingest.py` — the format selector and the transfer-log row |
| **The M5.2 crop-safety guards** | `tests/test_diagnostics.py`, `tests/test_reframe.py` |
| **The M5.2 URL-policy guards** | `tests/test_url_policy.py` — 39 cases, zero `xfail` markers |
| **The M5.3 complete-pipeline evidence — a whole ten-minute source, end to end, and five more defects** | `docs/M5-APPLICATION-TESTING.md` §M5.3, AT-F-01 … AT-F-15 |
| **The M5.3 script-aware terminator guards** | `tests/test_transcript.py` — 39 cases across 19 writing systems, with the Tibetan tsheg deliberately excluded |
| **The M5.3 clip-edge fallback guards** | `tests/test_boundaries.py` — the too-short branch and the Devanagari danda |
| **The M5.3 filter-graph and command-line guards** | `tests/test_export_graph.py` (new) and `tests/test_ffmpeg.py::TestCommandLineLength` |
| **The M5.3 emphasis-timeline guard** | `tests/test_export_render.py::TestLayoutRender::test_the_speech_emphasis_renders_in_a_later_stretch` — a behavioural render |
| **The M5.3 caption-lifetime guards** | `tests/test_captions.py::TestCaptionLifetime` and `tests/test_diagnostics.py` |
| **The M5.3 graph-shape guard — the video graph as well as the music graph** | `tests/graph_shape.py` (new) and `tests/test_export_graph.py::TestGraphShape` |
| **The installation and upgrade guide** | `docs/M5-INSTALLATION.md` |
| **This report** | `docs/FINAL_UPGRADE_REPORT.md` |
| The Instagram API evaluation | `docs/INSTAGRAM-API-EVALUATION.md` |
| The original requirements matrix | `docs/ORIGINAL_REQUIREMENTS_MATRIX.md` — **INCOMPLETE**, blocked on the missing source material |
| The missing-source search record | `docs/original/MANIFEST.md` |
| The baseline CI evidence | `docs/baseline-ci-evidence.md` |
| The performance baseline (M0, untouched) | `docs/performance-baseline.md`, `docs/BENCHMARK-BASELINE.json` |
| The M5 performance measurement | `docs/BENCHMARK-M5.json` |
| The external constraints register | `docs/EXTERNAL-CONSTRAINTS.md` |
| The architecture notes | `docs/ARCHITECTURE.md` |

---

## 8. What a reviewer should do next

1. **Read `docs/M5-APPLICATION-TESTING.md`.** It is the evidence that the application works, and
   it is also the record of the **thirteen** defects that the application testing and the gates
   found — three at M5, one at M5.1 (§4.3), four at M5.2 (§4.4) and five at M5.3 (§4.5).
2. **Read `docs/M5-SECURITY-REVIEW.md`.** It says what was *not* checked as plainly as what was.
3. **Read the ledger's M0–M5.3 sections.** Every milestone records its decisions and its
   residuals, and the residuals are the honest edges of this release.
4. **Run the gates.** `ruff check . && ruff format --check . && pytest -m "not slow and not golden
   and not e2e" && pytest -m "slow and not golden and not e2e"`. About ten minutes.
5. **Run the gates on an older ffmpeg too, if you can.** Two of the **thirteen** defects this
   milestone found render on ffmpeg 9 and fail on ffmpeg 7. The suite's structural graph check
   now catches them on any version, but the habit of reproducing the Linux leg locally is what
   found them — and it is what keeps finding things the developer's machine agrees with.
6. **Run the real-media suite.** `python scripts/make_e2e_media.py --run` — it cuts a three-minute
   segment and runs the 24 e2e tests against it.
7. **If you have credentials**, close the four UNVERIFIED live paths. They are the only thing
   standing between this build and a fully verified release.
8. **If you can supply the reframe golden set**, close K1. It is the gate for v0.1.0, and nothing
   else on this list stands in its way.

---

## 9. The commit trail

Every commit is on `feature/upgrade-u0-u10`. No force-push, no history rewrite, no other branch
touched. The branch was created from `bf76811` and every commit since is in front of it.

| Milestone | Commits |
|---|---|
| M0 | `26ebf00` (format, AST-compared) · `3c290b2` (format, the rest of the tree) · `24060ff` (CI on `feature/**`) · `615f0e8` (`SECURITY.md`, docs only) · `b2fae13` (the M0 deliverable set) · `4c869c6` (the ledger row) |
| M0.5 | The consent layer, the URL policy, the egress gateway, the retrofit into every existing transfer, and the 26 xfail markers removed |
| M1 | `b390b65` · `07a4424` · `9d5e90b` · `2266466` · `17dfb30` |
| M2 | `37f0cdd` · `50f7180` · `1529b5b` · `b5810a5` · `41a8c82` · `975e376` |
| M3 | `7ab6e19` · `d3c5828` · `df67aa5` · `1f3ff9c` · `b3d1c25` · `fd64fd2` · `7cdcf7a` · `7b9751b` |
| M4a | `20f6578` · `aa1f27f` · `7ed2a8d` · `53bc065` · `5d46feb` · `8038890` · `e837faf` |
| M4b | `b55bfad` · `3bbf876` · `6318655` · `2cfeb65` · `521cec5` · `5fc04cc` |
| M5 | `0ef1548` (the keyring test fix) · `4cf309b` (the formatter pin) · `94c6d9c` (no test may touch the owner's real OS keyring) · `69498e3` (the CI ffmpeg-check fix) · `bcdfc47` (the export and ducking fixes, with their tests) · `64d253d` (the release package) |
| M5.1 | `294c274` (the empty-timeline fix and the eight-case ducking matrix, with their tests) |
| M5.2 | `066bbf6` (the configured yt-dlp format is the one that is used) · `5574a8d` (the download is written to the transfer log) · `78f1781` (the crop-safety check measures the clip's own face) · `a907805` (a load-balanced public host is not a DNS rebinding) |
| M5.3 | `a7fc82d` (the terminators each script actually uses) · `09f8a29` (the webcam crop is built once, not once per segment) · `a3aecab` (a caption is read, not watched) · `2b5935d` (every segment gets its own copy of the source) |

**The M5 commits, in order, and what each one is for.**

| Commit | What it does | Why it is separate |
|---|---|---|
| `0ef1548` | The one Instagram secret test that reached the real keyring, fixed | The first fix — for the one test that had been noticed |
| `4cf309b` | `ruff` pinned at `0.17.5` | Closes **D15** and **T2**; the format gate becomes a property of the repository rather than of the day it ran |
| `94c6d9c` | The **autouse** `isolated_keyring` fixture | Closes the **class**, not the instance. The first fix covered one test; CI then found another. This one is for every test in the suite |
| `69498e3` | `.github/workflows/ci.yml` — the ffmpeg `ass`-filter check no longer pipes into `grep -q` | A change to the **workflow**, not to the product. It is kept apart so the product diff stays reviewable |
| `bcdfc47` | `api/clips.py` (the user's music choice and the speech timeline), `pipeline/export.py` (the malformed filtergraphs), and the three test files | The product fix and its guards travel together — the tests are the evidence that the fix is real, and **6 of the 7 API tests and 2 of the 3 render tests fail without it** |
| `64d253d` | The M5 deliverables, the matrix, the ledger, the audit, this report, the README | Documentation only |

**The M5.1 commit, and what it is for.**

| Commit | What it does | Why it is separate |
|---|---|---|
| `294c274` | `pipeline/speech_timeline.py` (`ducking_intervals()`), `pipeline/export.py` (the tri-state contract and the no-ducking graph), `pipeline/runner.py` and `api/clips.py` (the two call sites), `tests/test_ducking_matrix.py` (the eight-case matrix) and the four test files it touched | The product fix and its guards travel together, as they did at M5. **The no-speech case of the matrix fails without the fix**, at a measured ratio of 0.915 against a flat render — the guard is proven, not assumed |
| `b59605b` | The M5.1 documentation: the matrix, the ledger, the audit, the regression report, the performance report, the security review and this report | Documentation only, in its own commit, so the product diff stays reviewable |

**The four M5.2 commits, and what each one is for.** They are one commit per defect, and each
carries its own guards.

| Commit | What it does | Why it is separate |
|---|---|---|
| `066bbf6` | `pipeline/ingest.py` — the download command is built in one place, `_download_command`, and the format selector comes from the settings instead of a hard-coded `bestvideo*+bestaudio/best` | The first defect the real ingest found. **2 of its 3 tests fail without the fix.** The real 4-hour download then came down at **399+140 — 1920×1080@60** instead of **12.54 GiB at 1440p60** |
| `5574a8d` | `pipeline/ingest.py` — the transfer is recorded on refusal, on a failed launch, on a failed download and on success, with the duration | The second defect. Its guard is **one test**, and it fails without the fix with `assert [] == [('ok', ...)]`. The **5.52 GB** download that exposed it had left **0 rows** in the user's own log |
| `78f1781` | `pipeline/reframe/croppath.py` (`FaceRect`, `CropPath.faces`), `pipeline/reframe/__init__.py` (the plan records the faces it framed), `pipeline/diagnostics.py` (the face nearest the keyframe **in time**; `diagnose_clip` loses the `face_rect` parameter **entirely**) and `pipeline/runner.py` | The third defect, and the one that is also a **structural** guard: removing the parameter means the mistake cannot be made again by accident. **7 tests**, and the time-matching one fails without the fix |
| `a907805` | `security/urlpolicy.py` (the rebinding guard compares the **class** of the two answers, not the exact set), `tests/conftest.py` (the unit suite resolves no real hostname) and `tests/test_url_policy.py` | The fourth defect — found by the **full-suite gate** as a flake. **2 tests fail without the fix**; 3 more assert that the protection still holds (public → private, public → loopback, public → forbidden) |

**The four M5.3 commits, and what each one is for.** They are one commit per defect-cluster, and
each carries its own guards. The two that were found by the same change — defects 10 and 11 — are
one commit, because they are one change.

| Commit | What it does | Why it is separate |
|---|---|---|
| `a7fc82d` | `pipeline/transcript.py` (the terminator sets carry the marks of the other writing systems; the Tibetan tsheg deliberately excluded) and `pipeline/boundaries.py` (the too-short branch falls back to the **first word that reaches the floor**), with the new `tests/test_transcript.py` and the additions to `tests/test_boundaries.py` | The first defect the complete run found, and it is **two** halves: the boundaries did not exist, and the rule dropped what it could not place. **33 of the 65 tests fail without the fix.** The **1,130-range** sweep over the real transcript is the measurement the claim rests on |
| `09f8a29` | `pipeline/export.py` (the webcam crop and scale are applied **once, after the segment concat**) and `pipeline/ffmpeg.py` (`check_command_line_length`, `command_line_length`, `command_line_limit`, called in `run()` before `Popen`), with the new `tests/test_export_graph.py`, the additions to `tests/test_ffmpeg.py` and the behavioural render test in `tests/test_export_render.py` | Defects 10 and 11 are **one change** — the same crop, two different clocks. **7 tests fail without the export fix and 4 more** without the command-line guard. The rejected `out_w`/`out_h` sub-fix is recorded in the code, so the idea does not get re-tried from scratch |
| `a3aecab` | `pipeline/captions.py` (`MAX_CAPTION_S`, the start-span break in `group_words`, `caption_spans()` as the single source), `pipeline/diagnostics.py` (the diagnostic measures the **rendered** captions), `pipeline/runner.py` and `api/clips.py` (the two call sites), with the new `tests/test_captions.py::TestCaptionLifetime` and the additions to `tests/test_diagnostics.py` | The fourth defect, and the one the application's **own diagnostic** caught. **8 tests fail without the fix.** The bound belongs to the caption layer, not the transcript layer, and the commit message says so |
| `2b5935d` | `pipeline/export.py` (the source is split **once per consumer**, so every segment has a copy of its own), the new `tests/graph_shape.py` (the structural graph check, moved out of the music test), `tests/test_export_graph.py::TestGraphShape` and `tests/test_music.py` | The fifth defect, found by the **Linux leg** on **ffmpeg 7.0.2** — the version that reproduces the CI's platform. **3 tests fail without the fix.** The structural check was already written for this class of defect, but only ever looked at the **music** graph; it now looks at the **video** graph too. The shape was measured against **both** ffmpeg builds before it was chosen |

The full, dated list is in `docs/UPGRADE-LEDGER.md` §Change log.

---

## 10. One closing note

This upgrade added a great deal of machinery: a consent layer, a URL policy, a music library, a
face detector, a creative planner, two publishers, three queues and thirteen migrations. The
thing worth saying plainly is that most of the work was **not** in writing the features. It was in
the failures.

The ducking boundary was implemented on 30 ms frames, which made 349 ms and 350 ms
indistinguishable. The speech timeline was handed to the filtergraph in absolute source time while
the filtergraph's clock started at the clip. The export carried an MP4 edit list Meta documents
that a Reel must not have, and audio at 146.4 kbps against a 128 kbps limit. A NAT64 prefix was
refused as reserved, which on an IPv6-only network meant every public provider was unreachable. A
test wrote to the owner's real OS keyring. And ffmpeg's HTTP **308** — which is the *normal*
response for a non-final chunk — was being rejected as an error.

The last milestone added three more to that list, and they are the clearest argument for the way
this release was produced:

* **The re-export ignored the user's music choice** and passed no speech intervals, so the clip
  came out with neither the chosen track nor any ducking. The choice was in the database and on
  the screen; the file did not have it.
* **The ducking filtergraph was malformed** — a label in the middle of a chain — and ffmpeg
  refused the whole graph. The filter-level tests passed, because they only checked that certain
  strings were in the graph.
* **The sidechain fallback consumed one filter output twice.** ffmpeg 9 accepts that. ffmpeg 7
  does not. It would have shipped, because it rendered on the machine the code was written on.
* And **the CI's own ffmpeg check was wrong** — it reported that an ffmpeg *with* the `ass`
  filter did not have one, because `grep -q` exited at the match and SIGPIPE killed the producer.

M5.1 added a fifth, and it is the smallest and the most instructive of them: **an empty speech
timeline was indistinguishable from no timeline at all**, so a clip with no talking had its music
pulled down by whatever else the source contained. The impact was under a decibel. It was still
worth fixing, because the two halves of the same feature — the music ducking and the webcam
layout — were answering the same question differently, and the app's own principle is that they
must agree. **It was found by closing a matrix row, not by a report.** The row asked for eight
scenarios to be asserted; the assertions were written as eight *real renders* rather than eight
string checks, and the render that failed was the one that mattered.

M5.2 added four more, and they are the clearest argument of all, because **every one of them was
invisible to the whole test suite**:

* **The configured download format was dead.** The setting existed, was documented, had a comment
  promising a 1080p cap — and the download hard-coded something else. A four-hour stream came
  down at **12.54 GiB** instead of 5.52 GB, and no unit test could see it, because the test was
  about a string in a command line and the command line was never assembled from the setting.
* **The download was never written to the transfer log.** The egress gateway authorised it, the
  file came down, and the user's own *External processing* screen showed **0 rows**. The
  inventory said it was logged. It was not.
* **The crop-safety diagnostic lied.** It compared a per-clip crop against a rectangle the
  detector found once for the **whole recording**, and called that rectangle *"the detected face"*.
  It reported *"the crop cuts through the detected face"* on a clip that tracks the face
  perfectly, and on a clip with **no face in it at all**. A measurement that reports failures that
  did not happen is worse than no measurement, because it sends the user looking for a fault that
  is not there.
* **The DNS-rebinding guard was too strict to be true.** It refused any host whose two answers
  were not byte-identical — and `graph.facebook.com`, Meta's own Graph API host, answers with a
  rotating subset of its own edge addresses. Both answers were **public**; the refusal bought no
  security and broke a legitimate publish. It was found as a **flaky failure** — a test that
  passes alone and fails in a full run — which is exactly the shape a real defect takes when the
  test suite is reaching the live network.

M5.3 added five more, and they are the ones a user in **Hindi** would have met on their first real
video. Every one of them was invisible to the whole test suite, and every one of them is a
statement about how the product behaves in the world rather than about its internals:

* **The sentence terminators were Latin-only.** Whisper emits the danda for Hindi; the detector
  only knew `. ! ?`. A Devanagari transcript therefore had almost no sentence boundaries in it, and
  the clip-edge rule — which had no fallback for a too-short range — dropped the candidates
  **silently**. It was found by running a complete Hindi source through the pipeline and counting
  the candidates that came back: the old rule kept **852** of 1,130 plausible ranges; the new one
  keeps **1,070**.
* **The ffmpeg command line could exceed Windows' own limit.** The job died with *"The filename or
  extension is too long"* — a message about a *filename* for what is really an over-long *filter
  graph*. The real clip's command was **36,743** characters against a limit of **32,767**, and the
  cause was one line of arithmetic: a **293-character** emphasis expression repeated **80 times**.
  It failed at progress 0.88 **every time**.
* **The webcam's speech emphasis ran on a segment-local clock.** The crop was applied to each
  PTS-reset segment, so the expression's `t` restarted at every boundary and the webcam only ever
  magnified in a clip's **first** segment. It was hiding behind the defect above — the same
  expression, the same crop, two different clocks.
* **A caption could be held on screen for twelve seconds.** The application's **own diagnostic**
  caught it: *"3 word(s) are held on screen too long"*. Whisper had stretched one Hindi word across
  **7.84 seconds**, the caption inherited it, and the exported `.srt` carried a cue of **12.57
  seconds**. The fix belongs to the caption layer, not the transcript layer, because the
  recogniser's timings are estimates and several consumers want them as they are — it is the
  caption's own lifetime that needs a bound.
* **The video graph consumed a filter output once per crop segment.** ffmpeg 9 accepts that.
  ffmpeg 7 does not. It would have shipped for the same reason defect 3 would have — it rendered
  on the machine the code was written on — and it was caught by the **same** leg, because that leg
  exists to run the gates on the CI's platform rather than on the developer's.

Every one of those was found by measuring the real thing, not by reading the code and feeling
satisfied. The tests that caught them are in the tree, and they will catch them again.

One of them deserves its own note, because it is the kind of defect that hides behind a *passing*
test. The structural check that found the last one — "no filter output is consumed twice" — was
**already in the tree**. It was the fix for defect 3. But it only ever looked at the **music**
graph, so the **video** graph went unexamined and the same mistake was sitting in it. A test that
checks the right *property* on the right *thing* is worth more than a test that checks a
*different* property; so the check moved to `tests/graph_shape.py` and now covers both graphs. It
also caught a label collision in the first version of the fix, before any render — which is the
whole argument for a parser rather than a screenshot.

That is the main reason to trust this release. Not the feature count.
