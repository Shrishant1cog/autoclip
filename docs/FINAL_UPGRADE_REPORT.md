# AutoClip — Final Upgrade Report

**Milestone:** M5 — independent audit and release
**Branch:** `feature/upgrade-u0-u10`
**Base commit:** `bf76811` (`feature/autonomous-platform-v2`)
**Report date:** 2026-11-21
**Governing specification:** `docs/UPGRADE-SPEC.md` (M0–M5, supplied 2026-11-19)

---

## 1. The verdict

**Ship it, with the external integrations marked unverified.**

Every milestone from M0 to M5 is complete, and **M5.1** closed the last closeable partial matrix
row afterwards. The full automated suite is green — **1,315 tests, zero failures, zero skips,
zero xfails** — and the application was exercised through its real UI against real media, not only
through unit tests.

The one thing this report will not do is call the live external integrations verified. They were
not: no authorised ElevenLabs, hosted-LLM, Google or Meta credential was supplied for any part of
this upgrade. Every one of those paths is covered by automated tests against a double, and the
double stands in for the same code path the real service would take — but "the code is right" and
"it works against the live API" are different claims, and only the first one is supported.

| | |
|---|---|
| **Milestones complete** | **8 of 8** — M0, M0.5, M1, M2, M3, M4a, M4b, M5 |
| **Gate items** | 94 across M0–M4b: **91 done**, **1 blocked on the owner**, **2 unverified (external)**. M5's 10 are in §4. |
| **Feature coverage** | **129 rows**: 110 Implemented · 9 Partial · 1 Blocked · 9 Not Applicable · **0 Missing** |
| **Tests** | **1,315 passing** — 1,270 in the unit selection, 45 in the render selection — 0 failing, 0 skipped, 0 xfailed, plus 24 real-media e2e tests run against a real source |
| **New runtime dependencies** | **Zero.** The whole upgrade was built on the dependency set the project already had. |
| **Schema** | v14 → **v27**, 19 → **32 live tables**, thirteen migrations, no user data destroyed |
| **API surface** | 18 routers / 108 routes → **21 routers / 162 routes** |
| **CI** | **Every run on this branch since the two failures was green.** Two of the runs failed — both were real defects, diagnosed and fixed rather than explained away — and four were cancelled by a newer push. The release run is green on all six jobs, on all four platforms. See §4.1. |
| **Defects found by running the application** | **4 product defects** and **1 defect in the CI workflow itself**, all fixed, all guarded by tests that fail without the fix. See §4.2. |
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
| 1 | Complete regression report | `docs/M5-REGRESSION-REPORT.md` | Done — 9 gates, 1,315 tests, the CI run history |
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

| Runs | Result | What happened |
|---|---|---|
| 4, 5, 7–13, 15–17, **22**, **23**, **24**, **25** | **success** | green |
| 6, 14, 18, **21** | **cancelled** | each superseded by a newer push — the concurrency group cancelled the older run |
| **19** (`4cf309b`) | **failure** | the Ubuntu legs failed in **Unit tests**; Windows and macOS passed the same tests. A test wrote to the owner's real OS keyring. On Linux there is no keyring backend, so the token was never stored and the assertion could not hold — the test passed on Windows and macOS *because those machines had a real keyring to write to*. Fixed by `94c6d9c`, an **autouse** isolation fixture so no test can reach the owner's credential store |
| **20** (`94c6d9c`) | **failure** | the Ubuntu py3.12 leg failed at *"Verify ffmpeg can burn subtitles"*. The check piped the ffmpeg filter list into `grep -q`; `grep -q` exits at the match, the producer gets **SIGPIPE**, and GitHub's `set -o pipefail` turns that into a failed step. The runner's ffmpeg 8 has a filter list large enough to fill the pipe, so CI reported that an ffmpeg **with** the `ass` filter did not have one — the job log shows `printf: Broken pipe` and then the `ass` filter listed on the very next line. **Corrected, not removed**: the check now matches with bash's own pattern matching and never pipes, and a build genuinely without the filter still fails it |

**The release run is green on all six jobs** — the four backend legs (Ubuntu 3.11, Ubuntu 3.12,
macOS 3.12, Windows 3.12), the frontend build and the Docker image with its health smoke test.
The Ubuntu py3.12 leg, which had failed twice, now passes.

**Both failures were reproduced before they were fixed.** Run 19 was reproduced on a Linux
environment with no keyring backend. Run 20 was reproduced with a 320 KB filter list: the old body
fails it, the new body passes it, and a no-`ass` build still fails the new body. A failure that is
only fixed in CI is a failure that comes back.

### 4.2 Four product defects, found by running the application

The full-suite gates were green while the application was broken. These four defects were found
by **running the application and its gates**, not by reading the code, and each is now guarded by a
test that fails without the fix.

| # | Defect | Found by | Fix | Guard |
|---|---|---|---|---|
| 1 | The API export path ignored the user's music preference and passed no speech intervals, so a re-exported clip had **neither the chosen track nor any ducking** | clicking *Export this clip* on a clip with a track chosen | `api/clips.py` resolves the music through the same three-scope precedence the pipeline uses, and hands the renderer the job's speech timeline sliced to the clip | 7 regression tests in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix** |
| 2 | The timeline-driven ducking filtergraph was **malformed** — an output label in the middle of the bed's chain — and ffmpeg refused the whole graph | the export failing, with ffmpeg's own stderr in the response | the bed chain carries no output label; the label is added where the bed is used | 3 real-render tests in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix** |
| 3 | The sidechain fallback consumed one filter output **twice**, which **ffmpeg 9 accepts and ffmpeg 7 refuses** | the Linux CI leg, reproduced locally on ffmpeg 7.0.2 | the speech is split with `asplit=2` into a mix copy and a key copy, both on the bed's channel layout | the same 3 render tests, plus a **structural** check in `tests/test_music.py` that no filter output is consumed twice and no filter follows an output label — version-independent, so it catches the defect on any ffmpeg |
| 4 | **An empty speech timeline was indistinguishable from no timeline at all**, so a clip with no talking fell back to keying the ducking on the audio — and the music was pulled down by whatever else the source contained | the **no-speech** case of the eight-case ducking matrix, at M5.1 | `speech_timeline.ducking_intervals()` keeps the three answers apart: no timeline (`None`), a timeline that found no speech in this clip (`[]`), and the speech itself. `[]` means the bed is not ducked at all | `tests/test_ducking_matrix.py::test_no_speech_means_no_ducking` — **fails without the fix**, at a measured ratio of 0.915 against a flat render — plus 4 unit tests for the helper and 2 for the API boundary |

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
| **The installation and upgrade guide** | `docs/M5-INSTALLATION.md` |
| **This report** | `docs/FINAL_UPGRADE_REPORT.md` |
| The Instagram API evaluation | `docs/INSTAGRAM-API-EVALUATION.md` |
| The original requirements matrix | `docs/ORIGINAL_REQUIREMENTS-MATRIX.md` → `docs/ORIGINAL_REQUIREMENTS_MATRIX.md` |
| The missing-source search record | `docs/original/MANIFEST.md` |
| The baseline CI evidence | `docs/baseline-ci-evidence.md` |
| The performance baseline (M0, untouched) | `docs/performance-baseline.md`, `docs/BENCHMARK-BASELINE.json` |
| The M5 performance measurement | `docs/BENCHMARK-M5.json` |
| The external constraints register | `docs/EXTERNAL-CONSTRAINTS.md` |
| The architecture notes | `docs/ARCHITECTURE.md` |

---

## 8. What a reviewer should do next

1. **Read `docs/M5-APPLICATION-TESTING.md`.** It is the evidence that the application works, and
   it is also the record of the three defects that the application testing found. (A fourth was
   found afterwards, by M5.1 — §4.3.)
2. **Read `docs/M5-SECURITY-REVIEW.md`.** It says what was *not* checked as plainly as what was.
3. **Read the ledger's M0–M5.1 sections.** Every milestone records its decisions and its
   residuals, and the residuals are the honest edges of this release.
4. **Run the gates.** `ruff check . && ruff format --check . && pytest -m "not slow and not golden
   and not e2e" && pytest -m "slow and not golden and not e2e"`. About ten minutes.
5. **Run the gates on an older ffmpeg too, if you can.** One of the four defects this milestone
   found renders on ffmpeg 9 and fails on ffmpeg 7. The suite's structural graph check now catches
   it on any version, but the habit of reproducing the Linux leg locally is what found it.
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
| — | The M5.1 documentation: the matrix, the ledger, the audit, the regression report, the performance report, the security review and this report | Documentation only, in its own commit, so the product diff stays reviewable |

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

Every one of those was found by measuring the real thing, not by reading the code and feeling
satisfied. The tests that caught them are in the tree, and they will catch them again.

That is the main reason to trust this release. Not the feature count.
