# AutoClip — Final Upgrade Report

**Milestone:** M5 — independent audit and release
**Amendment:** M5.1 — the ducking matrix and the empty-timeline defect (2026-11-21)
**Amendment:** M5.2 — the real four-hour ingest, and four more defects (2026-11-21)
**Amendment:** M5.3 — the complete ten-minute pipeline, and five more defects (2026-11-21)
**Amendment:** M5.4 — a second real source, and a local model that could not answer (2026-11-23)
**Amendment:** M5.5 — subtitles, framing, and MeowPower (2026-11-24)
**Branch:** `feature/upgrade-u0-u10`
**Base commit:** `bf76811` (`feature/autonomous-platform-v2`)
**Report date:** 2026-11-21
**Governing specification:** `docs/UPGRADE-SPEC.md` (M0–M5, supplied 2026-11-19)

---

## 1. The verdict

**Ship it, with the external integrations marked unverified.**

Every milestone from M0 to M5 is complete, and **M5.1**, **M5.2**, **M5.3**, **M5.4** and **M5.5**
closed the last closeable partial matrix row and then took the application to real media afterwards —
the last three of them all the way through the **complete pipeline** on a whole source. The full
automated suite is green — **1,538 tests, zero failures, zero skips, zero xfails** — and the
application was exercised through its real UI against real media, not only through unit tests.

The one thing this report will not do is call the live external integrations verified. They were
not: no authorised ElevenLabs, hosted-LLM, Google or Meta credential was supplied for any part of
this upgrade. Every one of those paths is covered by automated tests against a double, and the
double stands in for the same code path the real service would take — but "the code is right" and
"it works against the live API" are different claims, and only the first one is supported.

| | |
|---|---|
| **Milestones complete** | **8 of 8** — M0, M0.5, M1, M2, M3, M4a, M4b, M5 — plus **M5.1**, **M5.2**, **M5.3**, **M5.4** and **M5.5**, post-release increments that are not one of the specification's milestones (see the amendments below) |
| **Gate items** | 94 across M0–M4b: **91 done**, **1 blocked on the owner**, **2 unverified (external)**. M5's 10 are in §4. |
| **Feature coverage** | **129 rows**: 110 Implemented · 9 Partial · 1 Blocked · 9 Not Applicable · **0 Missing** |
| **Tests** | **1,538 passing** — 1,489 in the unit selection, 49 in the render selection — 0 failing, 0 skipped, 0 xfailed, plus 24 real-media e2e tests run against a real source |
| **Real-media evidence** | A **real 4-hour live recording** ingested twice (360p, and the product's default 1080p); the pipeline exercised on real segments cut from that same file, with a real local model, producing two real clips and two real exports — **and, at M5.3, M5.4 and M5.5, three more real videos run through every stage end to end**: **three** real clips and **three** real exports from the first, **nine** real clips and **nine** real exports from the second — after its nine defects were fixed — and **six** real clips and **six** real exports from the third, every one of them **1080×1920** with the webcam's slot at exactly **40 %** |
| **New runtime dependencies** | **Zero.** The whole upgrade was built on the dependency set the project already had. |
| **Schema** | v14 → **v27**, 19 → **32 live tables**, thirteen migrations, no user data destroyed |
| **API surface** | 18 routers / 108 routes → **21 routers / 162 routes** |
| **CI** | **Every run on this branch since the three failures either passed or was cancelled by a newer push.** Three of the runs failed — each one a **real defect**, diagnosed and fixed rather than explained away: one in the product, and two in the CI workflow itself. Five were cancelled by a newer push. The release run is green on all six jobs, on all four platforms. See §4.1. |
| **Defects found by running the application** | **36 product defects** and **2 defects in the CI workflow itself**, all fixed, all guarded by tests that fail without the fix. See §4.2. |
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

### Amendment — M5.4, 2026-11-23

M5.3 proved the pipeline runs on a complete source. It did **not** prove the pipeline survives a
source whose **highlight detection** is the hard part: M5.3's ten-minute podcast produced a
transcript the local model handled in **425 s**.

M5.4 pointed the application at a **second real, third-party YouTube video** — a **9:35** CarryMinati
clip, used for **technical acceptance only, nothing published anywhere** — and ran it from the
paste through the whole pipeline. The highlight stage **failed**, twice, with one line of output:

> *Highlight detection failed in every window. Original error: Ollama timed out.*

Four defects sat behind that one line, and they are a different class from everything before them:
they are about **the request itself**, not about the content.

* the **600-second timeout was hard-coded**, and one legitimate call over this window was measured
  at **1,993 s** on this box — so the ceiling cut off calls that were about to succeed, and the
  advice printed with the failure (*"try again"*) reproduced the failure exactly;
* the failure message blamed **"a small GPU"** on a machine with `size_vram: 0` — **no GPU at
  all** — and told a local-only user to *use a hosted provider*;
* the server was **still generating the abandoned request** when the client gave up, so the next
  window queued behind the orphan, burned its own 600 s **without ever starting**, and the stage
  then claimed *every* window had failed;
* and the request **did not fit the model's context**: window 0's prompt measured **5,861 tokens**
  against a **4,096-token** context, while the product asked for `num_predict: 4096` — an answer
  budget as large as the entire context. The model server truncates an overflowing prompt
  **without saying so**, so this one would have produced **wrong clips rather than no clips**.

The last of those is the important one, and it was settled by an experiment rather than an
argument: the **same** payload with `num_ctx: 8192` returned **HTTP 200** after **1,992.9 s** with
`prompt_eval_count: 5862` — the estimate exactly — and a valid JSON answer.

When the pipeline finally finished, **its own diagnostics** found five more defects in its output:
two clips with the same model-chosen title **overwrote each other's exports**; the crop-safety
measurement compared the crop against the **largest** face in the shot rather than the face it
follows, and reported **6 of the 9 clips**; the pipeline's de-duplication compared **word ranges**
instead of time, and so kept two pairs of clips that were the same footage; a clip could open
**inside** its first word; and a face track could **jump to a smaller face** beside the speaker.
Each was read back against the source before anything was changed, each is fixed, and each is
guarded by a test that was observed failing against the pre-fix code — **17** of the **20** new
tests, the other three being non-regression guards.

**The verdict does not change.** The matrix is unchanged at **110 Implemented · 9 Partial · 1
Blocked · 9 Not Applicable · 0 Missing**. What changed is the **defect count** (thirteen →
**twenty-two**), the **test count** (1,397 → **1,441**), and the **evidence base**: a **second**
complete real source has now been ingested, transcribed, highlighted, laid out, captioned, exported
and diagnosed **end to end** — twice, the second time with every fix in the tree. See **§4.6**, and
`docs/M5-APPLICATION-TESTING.md` AT-G-01 … AT-G-17 for the per-journey record.

### Amendment — M5.5, 2026-11-24

M5.4 closed defects and widened the evidence. **M5.5 changed the surface** — it is the first
increment since M5 that **added product surface**, and it did so against three things the owner
asked for:

* **English subtitles by default, changeable at any time.** The setting is `export.subtitle_language`,
  defaulting to `"en"`. The decision lives in one module, the **spoken** language is detected once
  and recorded **separately** from the language the words are in, and a transcript in the wrong
  language is not reused.
* **A vertical split-screen that is actually right.** The webcam's **own frame** is **measured** by
  the **steps** at its edges, and the crop **follows it** as the streamer changes its size. The
  gameplay crop is held **clear** of it, so the streamer is never shown twice. **Auto** mode now
  produces the **40/60** split rather than falling back to a corner.
* **A simple "MeowPower" UX that hides processing complexity.** The job page opens with **one
  sentence** and **one number**. The pipeline's six technical stages are one disclosure away, not
  deleted.

It was accepted against a **third real, third-party YouTube video** — **38:00**, **1920×1080 AV1**
at **59.94 fps**, spoken in **Hindi**, used for **technical acceptance only, nothing published
anywhere** — and run from the paste through the whole pipeline on the **local Ollama**, so **no
hosted credential was spent** and the hosted paths stay **Unverified (external)**.

The run found **fourteen** more defects, all guarded by tests that fail without the fix, and the
running count is **twenty-two → thirty-six**. The two that would have shipped without this
increment are the **ordering** of the detection windows — rank order is not position, and the
decoder refused to seek backwards, so every clip came out as plain gameplay — and the **per-frame
zoom**, which ffmpeg refuses inside a `scale` filter because that filter's size is evaluated once,
at init.

**The verdict does not change here either.** The matrix is unchanged at **110 Implemented · 9
Partial · 1 Blocked · 9 Not Applicable · 0 Missing**; five rows — **CAM-01**, **CAM-02**, **CAM-08**,
**CAM-11** and **CAM-12** — gained **stronger evidence**, and no row's status moved. The **six
exported clips** were measured against the source they were cut from: every one is **1080×1920**,
the webcam's slot is exactly **40 %** of the height and the gameplay's exactly **60 %**, the
gameplay's crop clears the webcam's region exactly, every webcam path **moves**, and the captions
are **English**. See **§4.7**, and `docs/M5-APPLICATION-TESTING.md` AT-H-01 … AT-H-13 for the
per-journey record.

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
| 1 | Complete regression report | `docs/M5-REGRESSION-REPORT.md` | Done — 9 gates, 1,441 tests, the CI run history |
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

The run history is release evidence, not noise. **Every run on this branch since the three failures
either passed or was cancelled by a newer push.** The three that failed were **real defects** —
one in the product, **two in the CI itself**. None was a flake, and none was explained away. The
third was found at M5.5: run **44** failed on the Windows leg because Chocolatey's **metadata**
endpoint was unreachable, so `ffmpeg` was never installed, and the caption check reported the
missing `ass` filter instead of the missing ffmpeg. The same endpoint was measured timing out
**from this machine** in the same minutes, so the outage was not the runner's; the **package** URL
on the same host answered **200** throughout. The workflow now installs ffmpeg through a script
that tries Chocolatey first and falls back to that package URL, and a failure names itself. Five
runs were cancelled by a newer push.

**The table below is the run history as it stands at the M5.5 documentation commit.** It is a
record, and it grows; the claim that matters is the one above it, which does not go stale. The
numbers are **GitHub's own** — each workflow run's `run_number` — so a reader who opens the
Actions page for the branch finds the same numbering.

> **The numbering is the repository's, not the branch's.** Runs **1, 2 and 3** are on `main` — all
> three failures, before this branch existed — and **run 4 is this branch's first workflow run**.
> The table starts there.

| Runs | Result | What happened |
|---|---|---|
| 4, 5, 7–13, 15–17, **22**, **23**, **24**, **25**, **26**, **27**, **28**, **29**, **30**, **31**, **33**, **34**, **35**, **36**, **37**, **38**, **39**, **40**, **41**, **42**, **43**, **45** | **success** | green |
| 6, 14, 18, **21**, **32** | **cancelled** | each superseded by a newer push — the concurrency group cancelled the older run |
| **19** (`4cf309b`) | **failure** | the Ubuntu legs failed in **Unit tests**; Windows and macOS passed the same tests. A test wrote to the owner's real OS keyring. On Linux there is no keyring backend, so the token was never stored and the assertion could not hold — the test passed on Windows and macOS *because those machines had a real keyring to write to*. Fixed by `94c6d9c`, an **autouse** isolation fixture so no test can reach the owner's credential store |
| **20** (`94c6d9c`) | **failure** | the Ubuntu py3.12 leg failed at *"Verify ffmpeg can burn subtitles"*. The check piped the ffmpeg filter list into `grep -q`; `grep -q` exits at the match, the producer gets **SIGPIPE**, and GitHub's `set -o pipefail` turns that into a failed step. The runner's ffmpeg 8 has a filter list large enough to fill the pipe, so CI reported that an ffmpeg **with** the `ass` filter did not have one — the job log shows `printf: Broken pipe` and then the `ass` filter listed on the very next line. **Corrected, not removed**: the check now matches with bash's own pattern matching and never pipes, and a build genuinely without the filter still fails it |
| **44** (`06b9608`) | **failure** | the Windows leg failed at *"Verify ffmpeg can burn subtitles"*, saying the build had no `ass` filter. There was no build: Chocolatey's **metadata** endpoint was unreachable — `504` on one attempt, `503` on the next — so `choco install ffmpeg-full` installed **nothing** and still **exited 0**, and the install step reported success. The same endpoint was measured timing out **from this machine** in the same minutes, so the outage was not the runner's; the **package** URL on the same host answered **200** throughout. **Corrected, not removed**: the install now runs a script that tries Chocolatey first and falls back to that package URL, and a failure names itself. Guarded by **6** tests |

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

**Run 32 was cancelled** — the evidence-correction commit (`f9fad75`) was superseded by the next
push, with five of its six jobs already green: a cancellation, not a failure.

**Run 33 is green on all six jobs too**
([run 44949264565](https://github.com/Shrishant1cog/autoclip/actions/runs/44949264565)) — the two
documentation fixes that a cross-reference check found in the evidence itself, and the tree that
carries run 32's corrections with it.

**Run 34 and run 35 are green on all six jobs too**
([run 44950193899](https://github.com/Shrishant1cog/autoclip/actions/runs/44950193899) and
[run 44951500363](https://github.com/Shrishant1cog/autoclip/actions/runs/44951500363)) — the final
CI run, and then the run history itself.

**Run 35 is the last of the M5.3 runs.** Runs **36**, **37** and **38** are the three
documentation commits that closed the M5.3 record, each one green on all six jobs, and each one
verified against GitHub's own API rather than by eye.

**Run 39 is the whole M5.4 code tree — the three M5.4 code commits together — and it is green on
all six jobs too.** That is the run that first exercised the provider-limit guards, the export-name
guards, the crop-safety guards, the shared duplicate rule, the boundary clamp and the tracker
tolerance on every CI job. One commit on this branch has **no workflow run at all** — `9fdc6ae`,
a documentation-only M5.3 commit — and that is recorded in `docs/M5-REGRESSION-REPORT.md` rather
than glossed over; the claim that is made is the narrower one that a script checks.

**Run 40 is the M5.4 documentation tree — the eight files that carry the second source's evidence —
and it is green on all six jobs too**
([run 45146983505](https://github.com/Shrishant1cog/autoclip/actions/runs/45146983505)).

**Run 41 is the tree that carries the two-run comparison, **K32** and **R8** — and it is green on
all six jobs too**
([run 45161730246](https://github.com/Shrishant1cog/autoclip/actions/runs/45161730246)).

**Run 42 is the M5.4 documentation tree with run 41 recorded in it, and the detection-time claim
tightened against the two runs it was measured from — green on all six jobs too**
([run 45164085498](https://github.com/Shrishant1cog/autoclip/actions/runs/45164085498)).

**Run 43 is the whole M5.5 tree — the three M5.5 code commits together — and it is green on all six
jobs too**
([run 45322909082](https://github.com/Shrishant1cog/autoclip/actions/runs/45322909082)). That is
the run that first exercised the subtitle-language guards, the webcam-frame detector, the tiled face
detector, the crop-plan fingerprint, the saved-report window check and the per-frame speech
emphasis on every CI job. One push of three commits produced **one** run — GitHub ran the tip of
the push, and the concurrency group never started the two before it — so run 43 is the run of the
whole M5.5 tree rather than of one commit in it.

**Run 45 is the CI fix — the install step that now says where ffmpeg came from — and it is green on
all six jobs too**
([run 45333883376](https://github.com/Shrishant1cog/autoclip/actions/runs/45333883376)). The
outage had ended by the time it ran, so the Windows leg took the **primary** path, and its log
reads `ffmpeg from chocolatey: C:\ProgramData\Chocolatey\bin\ffmpeg.EXE` and then
`ass filter present`. The fallback itself is proved by the **local** download-and-unpack, not by
that run.

**The table stops at the last run recorded in it, and the commits after it change the record, not
the content it reports.** Each one's own run was verified after the push and is green, and the
branch's history can be read directly from GitHub, where the run numbers are the same ones used
here.

**Both failures were reproduced before they were fixed.** Run 19 was reproduced on a Linux
environment with no keyring backend. Run 20 was reproduced with a 320 KB filter list: the old body
fails it, the new body passes it, and a no-`ass` build still fails the new body. A failure that is
only fixed in CI is a failure that comes back.

### 4.2 Thirty-six product defects, found by running the application

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
| 14 | **The request timeout was a hard-coded 600 s.** On a machine with **no GPU**, one legitimate detection call over an eight-minute window was measured at **1,993 s** — so the ceiling cut off calls that were about to succeed, and the advice it gave (*"try again"*) reproduced the failure exactly | the **second real source**, at M5.4. The highlight stage failed with *"Ollama timed out."* twice, and the transfer log carries two `highlights` rows of **600,086 ms** and **600,450 ms** — both exactly the ceiling | the timeout is a **per-provider setting** (`ProviderSettings.timeout_s`, 0 = the provider's own default) with a generous **3,600 s** default, and it reaches the HTTP client and the vendor SDKs — Anthropic, OpenAI and Gemini, the last in milliseconds, because that is what its SDK counts | 7 tests in `tests/test_provider_limits.py::TestTheTimeout`; **6 fail without the fix** |
| 15 | **The timeout message blamed hardware the machine did not have.** It said *"Large transcripts on a small GPU can exceed the limit. Try a smaller model, or use a hosted provider for this video."* — on a machine with **no GPU** (`size_vram: 0`, an Intel Iris Plus iGPU), and for a user with no hosted provider | the same run. The message was read against the machine's own facts | the message now states what happened — *how long it waited* — and the hint says what a local model actually does (it runs on the **CPU** when no GPU is present) and points at the **setting** that changes it | 2 more tests in the same file; **both fail without the fix** |
| 16 | **A timed-out window left the server still generating the abandoned request**, so the next window queued behind the orphan and burned its own timeout without ever starting — and the stage then reported *"failed in every window"*, when some windows had never been tried at all | the same run: two windows, two timeouts, and the message claiming every window had failed | the stage **stops at the first timeout**, names the windows that were **not analysed**, and records that count in the job's own usage — so a job that analysed part of a video says so | 5 tests in `tests/test_provider_limits.py::TestATimeoutStopsTheStage`; **5 fail without the fix** |
| 17 | **The detection request did not fit the model's context window.** The prompt for one eight-minute window measured **5,861 tokens** against a **4,096-token** context, and the product asked for `num_predict: 4096` — an answer budget as large as the entire context. The model server truncates a prompt that does not fit **without saying so**, so the model would have answered from a partial transcript | the same run, measured with llama-server's own tokenizer, and then confirmed by an experiment: the **same** payload with `num_ctx: 8192` returned **HTTP 200** after **1,992.9 s** with `prompt_eval_count: 5862` and a valid JSON answer | the request asks for the context it needs (`ProviderSettings.context_tokens`, **8,192** by default), caps the answer to the room that remains (**2,048**), sizes the transcript windows to the provider's budget, and **reports** a prompt that still overflows instead of answering from a partial transcript | 8 tests in `tests/test_provider_limits.py` — the context, the answer budget, the window sizing and the overflow guard; **8 fail without the fix** |
| 18 | **Two clips with the same title overwrote each other.** The export's file name came from the title alone, and the titles are the **model's** choice — so when the model gave two clips the same title, the second export replaced the first, subtitles and all | the **second real source**, read back from the export directory: clip `61e1d3ec8c3e4dce` was recorded as **14,272,780 B**, and the file on disk was **54,024,088 B** — the *other* clip's — with **one** `.srt` where there should have been two | the name is made unique against the **whole set of the job's clips**: a title that is not shared keeps the user's own words, and a title that is shared gains the clip's **rank**, which is unique within the job. Both the pipeline and the re-export path compute the same name from the same list | 5 tests in `tests/test_export_graph.py::TestExportFilenames` and 2 in `tests/test_api.py::TestClipsWithTheSameTitle`; **6 fail without the fix** |
| 19 | **The crop-safety diagnostic measured the wrong face.** It took *"the largest face within half a second"* as the subject, while the crop follows the **tracked** speaker — so a clip that tracked its speaker perfectly was reported as cutting a face that was never its subject | the same run's own diagnostics: **6 of the 9 clips** were reported as *"the crop cuts through the detected face"*. Rebuilding the plans and measuring them against the face each one actually followed showed the cut at **0** keyframes in four of the six | the crop plan now carries, **per segment**, the faces that segment was built around — the person it follows, or the people a wide shot holds. The diagnostic measures against those, and keeps the old *"largest face"* rule only as the fallback for plans written before the change | 5 tests in `tests/test_diagnostics.py` (`TestCropSafetyMeasuresTheFollowedFace`, `TestCropSafetyTolerance`); **5 fail without the fix** |
| 20 | **Two clips of the same footage survived the pipeline.** The de-duplication compared the candidates' **word ranges**, and a clip *inside* another one has almost no words in common with it: the shorter clip of the first real pair covered **14** words, the longer **104**, of which those 14 were a part — a common share of a fifth, well under the threshold. In **time**, though, the shorter clip was wholly inside the longer one | the same run's diagnostics: **4 of the 9 clips** were reported as *"overlaps another one by 100%"*, and the diagnostic's own rule (overlap ≥ half of the shorter) disagreed with the pipeline's | one shared definition of *"the same clip"* — `pipeline/duplicates.py` — used by **both** the pipeline and the diagnostic: two clips are duplicates when the overlap covers at least **half of the shorter one**. The higher score survives | 5 tests in `tests/test_highlights.py::TestDuplicateClips` (new file); **3 fail without the fix** |
| 21 | **A clip could open in the middle of a word.** The boundary alignment pulls the cut back into the silence before the first word, but it could also push it *past* the word's own start when the silence detector and the recogniser disagreed by a few tens of milliseconds — which breaks the code's own documented invariant, *"alignment only ever widens a clip"* | the same run's diagnostics: **2 of the 9 clips** were reported as *"1 word(s) fall outside the clip"*. Rank 1's first word started at **533.800 s** and the clip opened at **533.852 s** — **52 ms inside the word** | the alignment may only ever widen the clip: the result is clamped to the first word's own start, so the cut is at or before the word, never inside it | 2 tests in `tests/test_boundaries.py::TestSilenceAlignment`; **2 fail without the fix** |
| 22 | **A face track could jump to a smaller face beside it.** The tracker's proximity fallback scaled its tolerance by the **larger** of the two faces, so a track could hop onto a smaller face-shaped object near the speaker — and the crop would then pan away from the speaker to follow it | found while **verifying defect 19** against the real source: the track of one segment held two different people, and the crop followed the wrong one. A real frame shows what the detector saw: the speaker, leaning forward, and a Pikachu plush on the shelf behind them | the tolerance is scaled by the **smaller** of the two faces — the person's own face width — which is what the rule always said. A track stays with its person | 1 test in `tests/test_reframe.py::TestTracking`; **fails without the fix** |
| 23 | **The face detector could not see the streamer at all.** MediaPipe scales its input to about **128 px** on the short side, so a face **120 px** wide in a **1920 px** frame is smaller than one pixel of what it looks at | over **2,100 s** of the **third real source** the detector found **0** faces | the detector **tiles** the frame instead of shrinking it — **640 px** tiles with **15 %** overlap. The same source then gave **56** observations over 2,100 s | 3 tests in `tests/test_faces.py`; the tiled-detection test **fails without the fix** |
| 24 | **The tiles were read with the wrong strides.** A tile cut out of a frame is a **non-contiguous view**, and MediaPipe read it as if it were contiguous, so every tiled frame came back with **zero** faces | the tiled detector over the same source, returning **0** observations where the untiled detector had found some | each tile is copied with `np.ascontiguousarray` before it is handed to the detector | 2 tests in `tests/test_faces.py`; the contiguous-tile test **fails without the fix** |
| 25 | **The edge search looked in the wrong place.** The webcam's **horizontal** edges were searched for in a narrow band around the face rather than over the **columns the box occupies** — so the bright panel of a game menu won the vote | the new edge detector over 30 s of the reference video: the **horizontal** edges were wrong, and the box it produced did not match the webcam | the horizontal edges are searched over the **columns the box occupies**. On the same 30 s the detector now finds **all four** edges: `x=1274, w=638, y=9, h=426` | 7 tests in `tests/test_webcam_box.py`; the horizontal-axis test **fails without the fix** |
| 26 | **The first frame of a clip was read from before the clip began** — a negative clip-relative timestamp | the clip-relative timestamp arithmetic in `_iter_frames`, checked against a clip that starts part-way into the source | the timestamp is clamped at zero | 1 test in `tests/test_faces.py`; **fails without the fix** |
| 27 | **The webcam spilled out of its own 40 % strip** when it could not fill the band without blurring the face | the layout's own geometry, checked against a webcam whose aspect does not match the strip | `_fit_in_strip` fits the webcam **inside** the strip on both axes at once, and returns nothing when it cannot | 2 tests in `tests/test_layout.py::TestTheSplitScreen`; the spill test **fails without the fix** |
| 28 | **The gameplay crop did not keep clear of the webcam**, so the streamer was shown **twice** — once in the strip, once inside the gameplay | comparing the gameplay window against the webcam's region in the plan | `ReframeConfig.avoid` carries the webcam's region, and a **final pass over the finished plan** holds every fallback clear too | 6 tests in `tests/test_reframe.py::TestTheWebcamIsKeptOutOfTheGameplay`; the fallback tests **fail without the fix** |
| 29 | **The progress page lost the video's title** the moment the event stream opened, because the server's `snapshot` event carried no source | opening the running job's page in the browser and reading the DOM | the snapshot carries the source, and the client **merges** rather than substitutes | 1 test in `tests/test_api.py::TestEventStream::test_the_snapshot_carries_the_source`; **fails without the fix** |
| 30 | **The webcam's path grew an ffmpeg expression past Windows' own 32,767-character limit** — every measured box became a keyframe, and a path of **600** boxes produced a **50,019-character** filter graph | building the filter graph from a path of 600 measured boxes | the path is thinned to at most **48** keyframes, the same budget the gameplay crop path uses | 6 tests in `tests/test_webcam.py::TestTheWebcamPath`; the length and the budget tests **fail without the fix** |
| 31 | **The detector was asked for the stretches in the wrong order, and refused.** The clips come in **rank** order and rank is not position, so the detector asked the decoder to seek backwards; the decoder refused with *"Input timestamp must be monotonically increasing"*, the webcam was never found, and **every clip was rendered without the split-screen** | the real run: the saved report said `"unavailable_reason": "Input timestamp must be monotonically increasing."`, no track, and the six exports came out as plain gameplay | the stretches are walked in the order they sit in the **source**, whatever order they are given in | 2 tests in `tests/test_faces.py::TestTheClock` and 1 in `tests/test_pipeline_cache.py::TestTheOrderTheWindowsAreAskedFor`; **fail without the fix**, with the production error |
| 32 | **A saved crop plan was reused after the layout had changed.** The plan was cached under the clip's name alone, with nothing saying what it was made *for* | the run after defect 31 was fixed: the plan on disk was still **608×1080** (9:16) while the layout asked for **1012×1080** (15:16) | the plan records a **fingerprint** of the settings it was built for, and a saved plan is only reused when the settings still match | 4 tests in `tests/test_pipeline_cache.py::TestTheSavedCropPlan`; the stage test **fails without the fix** |
| 33 | **A detection that could not run was kept as a final answer** — the report said *why* the webcam was not found, and a report with a reason was reused as-is | the same report that defect 31 produced: an error message, cached as if it were an answer | a report says whether the detection **failed** or simply found nothing, and only a real answer is reused. A report written by an **older version** of the detector is not reused either | 4 tests in `tests/test_pipeline_cache.py::TestTheSavedWebcamReport`; **fail without the fix** |
| 34 | **A re-export would have stretched a plan made for another shape** — found while fixing defect 32, by reading the path rather than by running it | reading `api/clips.py::_crop_path_for` while fixing defect 32, and checking what it would do with the plan the fix produces | a saved plan is only reused when its **own shape** is the shape being exported | 2 tests in `tests/test_pipeline_cache.py::TestTheReExportPath`; **fail without the fix** |
| 35 | **The saved webcam report was never reused, because the windows never matched exactly.** The report rounds its windows to **3 decimal places** while a clip's end time is `1303.9599999999998`, so the exact comparison never matched and every retry paid for the detection again | the last run of the job: the report on disk carried **02:35:40** while the layouts beside it were rewritten at **02:56:29** — the detection had been done again even though the windows had not moved | the comparison is tolerant to **0.01 s**, which is smaller than the rounding the report applies and far smaller than the difference between two different stretches | 1 test in `tests/test_pipeline_cache.py::TestTheSavedWebcamReport::test_a_report_for_the_same_windows_is_reused`; **fails without the fix** |
| 36 | **The speech-emphasis zoom broke the render.** The zoom was computed in a `scale` filter, and ffmpeg evaluates a `scale` filter's `w` and `h` **once**, at init — so a per-frame expression in them is refused: *"Expressions with frame variables 'n', 't', 'pos' are not valid in init eval_mode."* Every clip with a moving webcam failed to render | rendering a moving webcam with a speech emphasis through the real ffmpeg: the export failed with `[Parsed_scale_90 ...] Expressions with frame variables 'n', 't', 'pos' are not valid in init eval_mode.` | the scale is evaluated **per frame** (`eval=frame`) and the centred crop that follows it is evaluated the same way | 1 test in `tests/test_export_render.py::TestLayoutRender::test_a_moving_webcam_with_speech_renders` — a **behavioural** render test that reproduces the exact production error; **fails without the fix** |

**Defect 3 is the one that would have shipped.** It rendered on the machine the code was written
on and would have failed on the CI runners and on every user with an ffmpeg older than 9. It was
caught by reproducing the Linux leg locally rather than assuming the two platforms agreed.

**And a fifth defect, in the CI itself** — the broken-pipe check above. It was found while
confirming the first three.

**And a second defect in the CI itself, found at M5.5** — the same step, failing for a different
reason. The Windows leg of the M5.5 documentation commit (run **44**) said the build had no
`ass` filter, and there was no build at all: Chocolatey's **metadata** endpoint was unreachable,
so `choco install ffmpeg-full` installed **nothing** and still **exited 0**, and the install step
reported success. The check then looked for the filter in a program that was never installed, and
named the wrong cause. The job was re-run **nine times** — **ten attempts**, all the same. The
install now runs `scripts/install_ffmpeg_windows.py`: **Chocolatey first**, exactly as before, and
only if that produced no ffmpeg, Chocolatey's own **package** URL on the same host — the same
package, the same version, the same binaries. Proved locally before it was written (the package
downloaded, unpacked, and the ffmpeg it produced checked for its `ass` filter) and guarded by
**6** tests.

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

### 4.6 M5.4 — a second real source, and a local model that could not answer

M5.3 proved that the whole pipeline runs on a complete source. It did **not** prove that the
pipeline survives a source whose **highlight detection** is the hard part: M5.3's ten-minute
podcast produced a transcript the local model handled in **425 s**.

M5.4 pointed the application at a **second real, third-party YouTube video** — supplied by the
owner — and ran it from the paste through the whole pipeline. The highlight stage **failed**,
twice, with the same line and the same two numbers in the transfer log.

> **Rights.** This is another creator's video. It is used here for **technical acceptance only**.
> Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

**The environment.** A separate application instance on **port 8804** with its own home, so the
owner's own instance and its database were untouched. The model is the same real local **Ollama**
(`llama3.1:8b` at `127.0.0.1:11434`), and `active_provider=ollama` means **no hosted call and no
hosted spend**. The settings are the ones M5.3 used, so the two runs are comparable.

**The source.**

| | |
|---|---|
| Video id | `bMTlNeKqV4o` |
| Title | UNEMPLOYMENT ON PEAK 📈 \| CARRYMINATI |
| Channel | CarryMinati |
| Duration | 574.879637 s — **9:35** |
| Resolution / rate | 1920×1080 at 29.970059515628723 fps |
| Audio track | Hindi (`hi`), **no manual subtitles** |
| Source id / job id | `b5bf5a6f740a40ee` / `f65fb40febe141d7` |

#### The failure, as the application's own records show it

The highlight stage failed at **05:23:19 UTC** on **2026-11-22**, at progress **0.55**, with the
error *"Highlight detection failed in every window. Original error: Ollama timed out."* The
transfer log carries **two** `highlights` rows, each `failed`, each lasting the provider's whole
ceiling: **600,086 ms** and **600,450 ms**. The retry was clicked in the browser and it failed
the same way.

One line of output. Four defects behind it:

| # | What the one line was hiding |
|---|---|
| **14** | The **600 s ceiling was hard-coded**, and one legitimate call over this window was measured at **1,993 s** on this box |
| **15** | The advice printed with the failure blamed **"a small GPU"** — on a machine with `size_vram: 0`, **no GPU at all** — and told a local-only user to *use a hosted provider* |
| **16** | The server was **still generating the abandoned request** when the client gave up, so the next window queued behind the orphan, burned its own 600 s **without ever starting**, and the stage then claimed *every* window had failed |
| **17** | The request **did not fit the model's context**: window 0's prompt measured **5,861 tokens** against a **4,096-token** context, and the product asked for `num_predict: 4096` — an answer budget as large as the entire context |

Defect 17 is the one that would have produced **wrong clips rather than no clips**, and it was
invisible until the request was measured with the model server's **own tokenizer**:

```
system prompt chars: 3635
max_output_tokens requested: 4096

== window 0 ==
  words 0..884 (885)
  user prompt chars: 8486
  prompt tokens:     5861
  context length:    4096
  room for output:  -1765
  ** THE PROMPT ALONE DOES NOT FIT THE CONTEXT **

== window 1 ==
  words 756..1059 (304)
  user prompt chars: 3182
  prompt tokens:     2673
  context length:    4096
  room for output:  1423
  ** PROMPT + REQUESTED OUTPUT DO NOT BOTH FIT **
```

**The model server truncates a prompt that does not fit, without saying so.** So the defect was not
"the request was slow" — it was "the request was wrong, and the answer would have come from a
partial transcript".

#### The experiment that closed defect 17

The **same** window-0 payload, sent with `num_ctx: 8192` and `num_predict: 1024`:

| | |
|---|---|
| HTTP status | **200** |
| Elapsed | **1,992.9 s** |
| `prompt_eval_count` | **5,862** — the estimate exactly |
| `eval_count` | 875 |
| `done_reason` | `stop` |
| The answer | a valid JSON object with **11** clips |

`/api/ps` then reported `context_length: 8192` and the model's resident size growing from
**5.58 GB** to **6.26 GB** — about **680 MB** of extra KV cache. A context of **16,384** would
have added roughly **2.7 GB**, which does not fit this **8.4 GB** machine. So the default is the
largest context that leaves room for the model itself.

#### The fix

| | What changed |
|---|---|
| **Defect 14** | The timeout is a **per-provider setting** (`ProviderSettings.timeout_s`, 0 = the provider's own default) with a generous **3,600 s** default. It reaches the HTTP client **and** the vendor SDKs — Anthropic, OpenAI and Gemini, the last in **milliseconds**, because that is what its SDK counts |
| **Defect 15** | The message states what happened — *how long it waited* — and the hint says what a local model actually does (it runs on the **CPU** when no GPU is present) and points at the **setting** that changes it |
| **Defect 16** | The stage **stops at the first timeout**, names the windows that were **not analysed**, and records that count in the job's own usage — so a job that analysed part of a video says so |
| **Defect 17** | The request asks for the context it needs (`ProviderSettings.context_tokens`, **8,192** by default), caps the answer to the room that remains (**2,048**), sizes the transcript windows to the provider's budget, and **reports** a prompt that still overflows instead of answering from a partial transcript |

The window sizing was changed from an **average-per-word estimate** to the **exact per-word
rendering cost**, so *"a window never exceeds the character budget"* holds exactly rather than
approximately. The budget itself is measured against the provider's own prompt: **3,886** fixed
characters (the system prompt and the instructions), leaving **8,402** for the transcript inside
a **12,288-character** prompt at a **2.0 characters-per-token** bound — the conservative side of
the measured **2.07** for Devanagari and **≈4** for English.

**The guards.** `tests/test_provider_limits.py` (**22 tests**) and two settings tests in
`tests/test_api.py`. Against the pre-fix tree, **20 of the 21 original tests fail**; the one that
passes is a non-regression guard (a provider with no limit keeps its windows as they were). Both
API tests fail too. The twenty-second test — *"the windows that were not analysed are recorded"* —
was observed failing against the pre-fix code as well.

#### The re-run

The same job, resumed from the stage that failed. The transcript was **reused** — it had already
been transcribed, and the runner skips what is done.

| | Before the fix | After the fix |
|---|---|---|
| **Window 0** | **600,086 ms** — timed out | **881,989 ms** — answered |
| **Window 1** | **600,450 ms** — timed out | **426,775 ms** — answered |
| **The highlight stage** | **failed** — *"Ollama timed out."* | **9 clips**, all inside the 20–90 s window |
| **Windows not analysed** | not recorded | **0** |
| **The creative plan** | never reached | the first attempt did not match the schema; the **repair retry** did, and the plan's `source` is **`ai`** |

The creative plan's first answer is worth a line of its own. It named music tracks
**`track_1` … `track_6`** — identifiers that are not in the library — and the validator refused it:
*"music_track_id 'track_1' is not in the library"*. The repair retry answered with
`music_track_id: ""`, and the stored plan has `source='ai'`, `caption_strategy='clean_lower'`,
`ducking_db=-12.0`. The budget counters say `plan_used=1`, `repair_used=1` — both spent, neither
overrun. **The plan was the model's, not the fallback's**, and that is the difference from M5.3's
second job, where the repair also failed and the plan fell back.

#### Then the run's own diagnostics, and five more defects

The pipeline finished. The diagnostics it produced on its own output were not all green, and four
of the nine clips were reported more than once. **Every one of those reports was read back against
the source before anything was changed**, because a diagnostic that is wrong is worse than no
diagnostic — and defect 7 of this upgrade was exactly that.

The measurements were:

| Diagnostic | Clips reported | What the measurement found |
|---|---|---|
| `caption_timing` | **2** (ranks 1, 6) | *"1 word(s) fall outside the clip"* — a clip that opened **52 ms inside** its first word |
| `crop_safety` | **6** (ranks 2, 3, 4, 5, 7, 9) | *"the crop cuts through the detected face"* — against the **largest** face in the shot, not the one the crop follows |
| `duplicate_clips` | **4** (ranks 1, 2, 7, 8) | *"overlaps another one by 100%"* — the pipeline had kept both clips of each pair |
| `black_frames` | **2** (ranks 3, 7) | *"0.83 s of black frames"* — and this one is **true**: `blackdetect` on the raw source finds `105.973–106.807` and `572.505–574.774`. The source has black stretches in it. **It was not "fixed".** |

Reading those four numbers against the source produced **five more product defects**:

* **Defect 18 — two clips with the same title overwrote each other.** The export's name came
  from the title alone, and the titles are the **model's** choice. Two of the nine clips were
  called *"The language of love in videos"*. The export directory held **one** file for them:
  the second clip's **54,024,088 B** had replaced the first clip's **14,272,780 B**, and the
  first clip's subtitles with it. Read back from the database, clip `61e1d3ec8c3e4dce` was
  recorded as **14,272,780 B** — a file that no longer existed.
* **Defect 19 — the crop-safety diagnostic measured the wrong face.** It took *"the largest face
  within half a second"* as the subject, while the crop follows the **tracked** speaker.
  Rebuilding the plans and measuring them against the face each one actually followed showed the
  cut at **0** keyframes in four of the six clips.
* **Defect 20 — two clips of the same footage survived the pipeline.** The de-duplication
  compared the candidates' **word ranges**, and a clip *inside* another one has almost no words
  in common with it: the shorter clip of the first pair covered **14** words, the longer **104**,
  of which those 14 were a part — a common share of a fifth, well under the threshold. In
  **time**, the shorter clip was wholly inside the longer one.
* **Defect 21 — a clip could open in the middle of a word.** The boundary alignment pulls the cut
  back into the silence before the first word, but it could also push it *past* the word's own
  start when the silence detector and the recogniser disagreed by tens of milliseconds. Rank 1's
  first word started at **533.800 s**; the clip opened at **533.852 s**.
* **Defect 22 — a face track could jump to a smaller face beside it.** Found while *verifying*
  defect 19 against the real source: one segment's track held **two different people**, and the
  crop followed the wrong one. A frame from the source shows what the detector saw — the
  speaker, leaning forward, and a Pikachu plush on the shelf behind them.

**The fix.**

| | What changed |
|---|---|
| **Defect 18** | The export's name is made unique against the **whole set of the job's clips**: a title that is not shared keeps the user's own words, and a title that is shared gains the clip's **rank**, which is unique within the job. The pipeline and the re-export path compute the same name from the same list |
| **Defect 19** | The crop plan now carries, **per segment**, the faces that segment was built around — the person it follows, or the people a wide shot holds. The diagnostic measures against those. The old *"largest face"* rule remains only as the fallback for plans written before the change |
| **Defect 20** | One shared definition of *"the same clip"* — `pipeline/duplicates.py` — used by **both** the pipeline and the diagnostic: two clips are duplicates when the overlap covers at least **half of the shorter one**. The higher score survives |
| **Defect 21** | The alignment may only ever **widen** the clip: the result is clamped to the first word's own start, so the cut is at or before the word, never inside it |
| **Defect 22** | The tracker's proximity tolerance is scaled by the **smaller** of the two faces — the person's own face width — which is what the rule always said. A track stays with its person |

**A stated tolerance, and why.** Defect 19's fix measures the followed face against the crop
window, and it allows a **sliver** of the detector's bounding box outside: the crop must keep at
least **90%** of the face. Two reasons, both measured rather than assumed. The box is loose — it
includes hair and chin, and it can run **past the edge of the picture**, because the face is half
out of shot; no crop can contain what the source does not have. And the crop follows a moving
subject along a **smoothed** curve, so at the instant the subject moves fastest the curve is a few
pixels behind. On the real source the worst case is **19 px of a 549 px face (3.5%)** at one
keyframe, and a second case where the box ran **56 px** past the edge of the frame while the crop
was the **whole frame**. A sliver of a bounding box is not something a viewer can see; half a face
is. The measurement is in `diagnostics._face_inside_fraction` and the threshold is
`diagnostics.FACE_KEEP_RATIO`.

**The guards.** Seventeen new tests, in five files, and every one of them was observed **failing
against the pre-fix tree** before the fix was written:

| File | Tests | Fail without the fix |
|---|---|---|
| `tests/test_export_graph.py::TestExportFilenames` | 5 | **4** |
| `tests/test_api.py::TestClipsWithTheSameTitle` | 2 | **2** |
| `tests/test_diagnostics.py::TestCropSafetyMeasuresTheFollowedFace`, `::TestCropSafetyTolerance` | 5 | **5** |
| `tests/test_highlights.py::TestDuplicateClips` (new file) | 5 | **3** |
| `tests/test_boundaries.py::TestSilenceAlignment` | 2 | **2** |
| `tests/test_reframe.py::TestTracking` | 1 | **1** |
| | **20** | **17** |

The three that pass against the pre-fix tree are non-regression guards: a title that is *not*
shared keeps its plain name, clips that only **touch** are kept, and clips that share a **quarter**
are kept.

#### The verification run — the whole pipeline again, with every fix in

The fixes were then committed (`74ec3eb`) and the **whole application was run again, from the
paste, through the real UI** — a **new** job, not a resumed one, so nothing could be inherited
from the failed attempt.

| | |
|---|---|
| **The paste** | `https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP` into the ingest field. `POST /api/sources/youtube` → **201**, body byte-for-byte the pasted URL → source **`651525f6355b4b28`**; `POST /api/jobs` → **201** → job **`3db75213de894350`** |
| **The job** | `status=done`, `progress=1.0`, `error=null`, started **06:56:15 UTC**, finished **08:16:06 UTC** — **4,791 s (79.8 min)** for **574.880 s** of source, ≈ **8.33× real time** |
| **The download** | **225,722,498 B in 60,693 ms** — the same video as the first run, **17%** slower on the wire this time |
| **The transcript** | whisper `small`, language `hi` — **1,277 words** in **246 segments**. The recogniser is **not** bit-deterministic: the first run on this same file produced **1,060 words** in **220 segments**. That is **measured, not asserted** — the byte-level comparison and the recogniser's own fallback log are below, and the finding is recorded as **K32** |
| **The detection** | two windows, **933,665 ms** and **634,943 ms**, both `ok`, **`windows_skipped = 0`**. The windows were **900** and **525** words — **8,402** and **5,264** prompt characters — because the transcript grew |
| **The creative plan** | the plan (**430,699 ms**) and its **repair retry** (**335,078 ms**); the stored plan has `source='ai'` and `problems='[]'` — **the model's own plan**, not the fallback. `plan_used=1`, `repair_used=1`, `overruns=[]` |
| **The output** | **9 clips**, all `status='exported'`, **268,664,639 B** over **11** ffmpeg runs and **448.5** ffmpeg-seconds |
| **The usage ledger** | `llm_calls=2`, `llm_input_tokens=10055`, `llm_output_tokens=1535` — the two detection windows, counted once each |

**The two runs, compared at the byte level.** The verification run was the **second** time this
source went through the pipeline, so the two runs can be compared — and the comparison is the
sharpest evidence in this report, because it separates what the **media** did from what the
**recogniser** did.

| | First attempt (`f65fb40febe141d7`) | Verification run (`3db75213de894350`) |
|---|---|---|
| The source row | `b5bf5a6f740a40ee` | `651525f6355b4b28` — the same URL, ingested again |
| The download | **225,722,498 B in 51,703 ms** | **225,722,498 B in 60,693 ms** |
| The container | the two files differ in **exactly one byte** — offset **407**, the mp4 creation-date metadata | the same |
| The decoded audio | **byte-identical** 16 kHz mono PCM — **18,396,148 B**, sha256 `4a87c5bd…8b7`, **574.880 s** | the same |
| `audio.wav` | **18,396,226 B**, sha256 `5e468f32…` | **byte-identical** |
| `silences.json` · `shots.json` · `webcam_report.json` | **2,812 B** · **9,437 B** · **45,951 B** | **byte-identical** |
| The **115** thumbnails | folder sha256 `a7eb34b3…` | **byte-identical** |
| `transcript.json` | **110,326 B** — **1,060 words**, **220** segments | **131,534 B** — **1,277 words**, **246** segments |
| `speech_timeline.json` | **6,123 B** | **5,756 B** |
| The detection windows | **885** and **304** words — **8,233** and **2,926** prompt characters | **900** and **525** words — **8,402** and **5,264** prompt characters |
| The detection time | **881,989 ms** + **426,775 ms** = **1,308,764 ms** | **933,665 ms** + **634,943 ms** = **1,568,608 ms** |
| The usage ledger | `llm_input_tokens=8536`, `llm_output_tokens=1623` | `llm_input_tokens=10055`, `llm_output_tokens=1535` |
| The export | **9** ffmpeg runs, **490.4** ffmpeg-seconds, **328,836,840 B** | **11** ffmpeg runs, **448.5** ffmpeg-seconds, **268,664,639 B** |

**Everything the pipeline derives from the media is identical; the transcript is not** — and the
difference is in the **recogniser**, not in the media. Read word record by word record, the two
transcripts are **identical for the first 246 records**, up to **101.02 s**, and then they part: at
**101.02 s** the first attempt says `बलवेंदर` and the verification run says `बलविंदर`, and the
**timings do not move at all** — segment 55 is `101.02 → 104.38` in both. Only **248 of the 1,060**
word records match at the same index, and the speech the two transcripts cover is **348.12 s**
against **414.86 s**.

**The mechanism was measured, not guessed.** A **40 s** excerpt of the same audio was decoded
**twice**, with the product's exact call and with the recogniser's own logging captured. The two
decodes differ — **10** segments against **9** — and the log says why:

| The recogniser's own log | Run 1 | Run 2 |
|---|---|---|
| The segments decoded | **10** | **9** |
| `Compression ratio threshold is not met with temperature 0.0` | **6.897436 > 2.400000** | **6.897436 > 2.400000** |
| `… with temperature 0.2` | **6.460317 > 2.400000** | **4.840909 > 2.400000** |
| `… with temperature 0.4` | **8.479167 > 2.400000** | **16.370370 > 2.400000** |
| `… with temperature 0.6` | **9.767442 > 2.400000** | **6.490566 > 2.400000** |
| The pass at 0.8 | `Reset prompt. prompt_reset_on_temperature threshold is met 0.800000 > 0.500000` | `Log probability threshold is not met with temperature 0.8 (-1.533331 < -1.000000)` |

The recogniser's confidence check **fails** on this passage even at temperature 0, so it falls back
— and every fallback pass above zero **samples** (`beam_size=1`, `sampling_topk=0`,
`sampling_temperature=temperature`) from a generator that faster-whisper **1.2.1** does not seed;
that version has no `seed` argument to pin it with. Two runs of the same audio therefore take
different branches. The full detail, and what it would cost to fix, is **K32**.

**The measurements.** Ninety of them — nine clips × ten — and **89 are `ok`**. The one that is not
is rank 2's `black_frames`: *"The clip goes black for 0.83 seconds."* That is a **true positive
about the source**, measured rather than asserted: `ffmpeg blackdetect` on the **raw source**
from 90 s finds `black_start:15.973 black_end:16.807 black_duration:0.834` — source time
**105.973–106.807 s**, inside that clip's own **90.829–132.750 s**. It was **not** "fixed"; the
diagnostic is right, and the source has black stretches in it.

**Everything the run's own diagnostics had complained about is now green.** `crop_safety` is `ok`
on **all nine** — the six that were falsely reported last time are green — and `duplicate_clips`
is `ok` on **all nine**, with **no pair** overlapping by half of the shorter one, checked by the
**same shared rule** the pipeline uses.

**And the export-name fix was exercised by the run itself, not only by a test.** The model chose
the same title twice again — *"Why I'm not like them"*, for ranks 2 and 3 — and the two exports
came out as `why-im-not-like-them-2_9x16.mp4` and `why-im-not-like-them-3_9x16.mp4`. Under the
pre-fix code that pair would have been **one file and one set of subtitles**, and the first clip
would have been gone. **Nine clips, nine distinct names, no collision**; every recorded size
equals the size on disk; every `.srt` sidecar is present, with **0** overlapping cues and a
longest cue of **2.500 s**; every export is **1080×1920** at **29.97 fps** with an AAC track and
**0.000%** of samples at full scale.

#### M5.4 did not change the verdict

No matrix row was closed and none was opened: the count is unchanged at **110 Implemented · 9
Partial · 1 Blocked · 9 Not Applicable · 0 Missing**. What changed is the **defect count**
(thirteen → **twenty-two**) and the **evidence base**: a **second** complete real source has now
been ingested, transcribed, highlighted, laid out, captioned, exported and diagnosed **end to
end** — **twice**, the second time with every fix in the tree — and the run found a failure mode
that the first source could not reach, because the first source's transcript was small enough for
the model's context and this one was not.

### 4.7 M5.5 — Subtitles, framing, and MeowPower

**What this increment is.** A **fifth** post-release increment on the same branch, run and
documented on **2026-11-23** and **2026-11-24**. It is the first increment since M5 that **added
product surface**: M5.1–M5.4 closed defects and widened the evidence, and this one closes three
things the owner asked for.

| # | The ask | What was built |
|---|---|---|
| 1 | **English subtitles by default, changeable at any time** | `export.subtitle_language`, defaulting to `"en"`, in **Settings → Export → Subtitles**. The decision lives in one module — `pipeline/language.py` — and the **spoken** language is detected once and recorded **separately** from the language the words are in |
| 2 | **A vertical split-screen that is actually right** | The webcam's **own frame** is now **measured** by finding the **steps** at its edges, and the crop **follows it** as the streamer changes its size. The gameplay crop is held **clear** of it, so the streamer is never shown twice. **Auto** mode now produces the **40/60** split rather than falling back to a corner |
| 3 | **A simple "MeowPower" UX that hides processing complexity** | The job page opens with **one sentence** and **one number**. The pipeline's six technical stages are one disclosure away, not deleted |

**The source.** `https://youtu.be/BgIISP2mi3o?si=jAM8h8iYFz9cgLRrV` — *"I Stole The RAREST FERRARI
in GTA 6"*, **38:00** long (**2,279.108 s**), **1920×1080 AV1** at **59.94005994005994 fps**, with
an AAC audio track. The spoken language is **Hindi**.

> **Rights.** This is a third-party creator's video. It is used here for **technical acceptance
> only**. Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

#### The run, measured

Every number below was read back from the run's own artefacts — the files the application wrote, the
rows it wrote to the scratch database, and the render on disk. None of it is estimated.

| | |
|---|---|
| The application | the scratch instance on **port 8804**, with its own home, so the owner's own instance and its database were never touched |
| The model | the **local Ollama** (`llama3.1:8b` at `127.0.0.1:11434`); the job row records `provider=ollama`, so **no hosted credential was spent** |
| The prepare stage | `audio.wav` written at **20:42:20** — **72,931,542 B** |
| The transcription | whisper `small`, **1,836 s** for **2,279.1 s** of audio — **1.24× real time**, faster than the video plays |
| The scene detection | `shots.json` written at **01:13:01** — **466 shots** across the source |
| The highlight windows | **nine** windows over **5,648 words**. Each holds at most **8,402** rendered characters, which is the local model's context budget; **74,262** characters in all |
| The webcam detection | `webcam_report.json` written at **02:35:40** — **1,011 s** for the **194.5 s** the six clips actually use |
| The crop plans | six plans written between **02:37:33** and **02:44:49** — **436 s** |
| The export | six files between **02:57:35** and **03:05:06** — **451 s** for **194.5 s** of footage, **2.32× real time**. The job's own accounting agrees: `ffmpeg_runs=6`, `ffmpeg_seconds=444.455` |
| The bytes | **221,460,397** across the six files — exactly the `export_bytes` the job recorded |
| The job | `status=done`, `progress=1.0`, `provider=ollama` |

#### The run — the real application, the real video, end to end

The run used a **separate application instance** on **port 8804** with its own home, so the owner's
own instance and its database were never touched. The model was the same **local Ollama**
(`llama3.1:8b` at `127.0.0.1:11434`) that M5.3 and M5.4 used, so **no hosted credential was
spent** and the hosted paths stay **Unverified (external)**.

**The subtitle decision, measured on real audio.** The source is spoken in **Hindi**. The settings
were at their defaults, so the subtitle language was **`en`** — and the recogniser was asked to
**translate**:

| | |
|---|---|
| The transcript's `language` | **`en`** — the language the **words** are in |
| The transcript's `source_language` | **`hi`** — the language **spoken** |
| The model | whisper `small`, local, `source=whisper` |
| The size | **5,648 words** in **1,140 segments** |
| The words that are not Latin script | **0** |
| The first words | *"Oh this car, wait what, this is a classic car, that famous car of YCT, wow, I want this car, this is such a rare car, I am seeing this…"* |
| The coverage | the first word at **0.000 s**, the last at **2,273.860 s** — the whole **38 minutes** |

The two languages are **separate facts**, and the run is what shows that the product keeps them
apart: the words are English and the speech was Hindi, and both are written down. The `transcripts`
row in the scratch database agrees: `language=en`, `word_count=5648`, `source=whisper`.

**The MeowPower surface, read from the running application.** The job page's DOM, taken while the
job was running:

| | |
|---|---|
| The eyebrow | `MEOWPOWER` |
| The sentence | *"Listening to what is being said"* — and *"Picking out the moments worth keeping"* in the detection stage |
| The number | **40 %** |
| The line | *"You can leave this page. It keeps working."* |
| The technical stages | collapsed behind **"› What MeowPower is doing"**, `details.open === false` |
| The masthead | the title, **37:59 · 1920×1080 · ollama**, and the **Cancel** button — all still there |
| The console | **no errors** |

#### The run was interrupted five times, and the product handled every one

The scratch server was killed four times while the job was running — once by the session
restarting, three times by shell timeouts. The fifth restart was deliberate: the job was put back
to `running` so the **export** would be re-rendered with the fixed framing code, because the
re-export path does not rebuild the webcam composition (that is **K10**, and it is why the job had
to be requeued rather than re-exported).

All five are facts about the harness, not about the product. The product's answer is the same every
time, and it is recorded in the application's own `app_restarts` table — five rows carry this job's
id with `jobs_resumed=1`:

| | |
|---|---|
| On startup | the job was **requeued** and picked up again. The application recorded **five** restarts for this job, each with `jobs_resumed=1` |
| The transcript | **not** transcribed again. `transcript.json` was written **once**, at 21:12:56, and was still the same file when the last run finished — the saved transcript was in the requested language, so it was reused and the **thirty minutes** of transcription were not paid twice |
| The shots | **not** detected again. `shots.json` was written **once**, at 01:13:01, and the six clips were reused from the database |
| The webcam report | **not** detected again on the last run. `webcam_report.json` still carries the timestamp of **02:35:40** while the layouts beside it carry **02:56:29** — the saved report was read and reused, and the **seventeen minutes** of detection were not paid a second time |
| The crop plans | **not** rebuilt either: the six crop files still carry timestamps between **02:37:33** and **02:44:49**, while the layouts that use them were rewritten at **02:56:29** |
| The progress | back to **0.40**, which is exactly where it was — the two completed stages' weight, and not a restart from zero |

This is the **reuse rule** doing its job in production, not in a test: a saved transcript in the
right language is reused; a saved transcript in the **wrong** one is not, and is transcribed again.
It is also the two cache fixes of this increment, observed outside a test: the saved report is only
reused when the **windows** it was made for still match (**defect 35**), and a saved crop plan is
only reused when the **fingerprint** of the settings it was built for still matches (**defect 32**).

#### Every clip, inspected against every requirement

The six files were **measured**, not eyeballed. A script read the run's own records — the
transcript, the webcam report, the layout and the crop plan for each clip — and then compared the
**rendered pixels** against the **source** at three moments in each clip: the top 40 % against the
source at the webcam's own crop window for that moment, and the bottom 60 % against the source at
the gameplay's crop window. The path is a **piecewise-linear series**, so the window at a moment is
interpolated between the keyframes, exactly as the filtergraph reads it. The script's own verdict,
at the end, was **`NO PROBLEMS FOUND`**.

**The files**

| # | The clip | Its window in the source | The file | Bytes | The shape | The split-screen |
|---|---|---|---|---|---|---|
| 1 | *We killed that shark* | 530.31–562.88 (**32.57 s**) | `we-killed-that-shark_9x16.mp4` | 30,365,300 | **1080×1920** | **27.48 s / 32.57 s — 84.4 %** |
| 2 | *$400 taxi or $5 toll?* | 958.74–990.41 (**31.67 s**) | `400-taxi-or-5-toll_9x16.mp4` | 64,771,117 | **1080×1920** | **31.66 s / 31.67 s — 100.0 %** |
| 3 | *Police Behind Me* | 1273.12–1303.96 (**30.84 s**) | `police-behind-me_9x16.mp4` | 28,793,347 | **1080×1920** | **29.33 s / 30.84 s — 95.1 %** |
| 4 | *Biggest building of YCT* | 1139.25–1175.23 (**35.98 s**) | `biggest-building-of-yct_9x16.mp4` | 32,534,789 | **1080×1920** | **29.34 s / 35.98 s — 81.6 %** |
| 5 | *We got 50,000* | 562.90–594.65 (**31.75 s**) | `we-got-50000_9x16.mp4` | 31,900,979 | **1080×1920** | **27.64 s / 31.75 s — 87.1 %** |
| 6 | *Road rash* | 1031.06–1062.75 (**31.69 s**) | `road-rash_9x16.mp4` | 33,094,865 | **1080×1920** | **31.68 s / 31.69 s — 100.0 %** |

**The measurements.** The differences are the mean absolute difference between the exported strip
and the source at the same window, on a 0–255 scale; a smaller number is a closer match.

| # | The top 40 % is the webcam | The bottom 60 % is the gameplay | The two halves differ | The gameplay clears the webcam | The webcam's crop moves | The captions |
|---|---|---|---|---|---|---|
| 1 | **6.6 – 31.6** | **3.4 – 6.8** | yes, at all three moments | yes — x = **452** | **141** keyframes, **33** distinct centres | **64** cues, English |
| 2 | **8.3 – 39.0** | **4.7 – 24.8** | yes, at all three moments | yes — x = **452** | **48** keyframes, **22** distinct centres | **91** cues, English |
| 3 | **4.1 – 4.2** | **3.5 – 3.6** | yes, at both stacked moments | yes — x = **452** | **30** keyframes, **10** distinct centres | **121** cues, English |
| 4 | **36.4** | **4.2** | yes, at the stacked moment | yes — x = **452** | **94** keyframes, **23** distinct centres | **78** cues, English |
| 5 | **4.4 – 22.2** | **1.4 – 5.3** | yes, at all three moments | yes — x = **452** | **96** keyframes, **42** distinct centres | **86** cues, English |
| 6 | **4.4 – 37.5** | **5.3 – 16.8** | yes, at all three moments | yes — x = **452** | **46** keyframes, **17** distinct centres | **50** cues, English |

**The 40/60 split.** Every clip is **1080×1920**, and the webcam's slot in the layout is
`(0, 0, 1080, 768)` — exactly **40 %** of the height — with the gameplay's slot at
`(0, 768, 1080, 1152)`, exactly **60 %**. The gameplay's crop is **1012×1080**, the **15:16** shape
the bottom slot requires, and its left edge sits at **x = 452**, which is exactly where it must be:
the webcam's region starts at **x = 1464**, and `1464 − 1012 = 452`. The streamer is never shown
twice.

**The crop really follows the webcam.** The webcam's own frame was **measured**, not guessed:
**2,502** boxes over **194.5 s**, with **134** distinct widths between **134 px** and **540 px** —
the reference video's webcam really does change size during it. Every clip's path is a series of
keyframes and every one of them **moves**: between 10 and 42 distinct centres per clip, and every
path is within the **48**-keyframe budget that keeps the filtergraph under Windows' own
**32,767-character** limit.

**Where the split-screen is not shown.** Between **1.50 s** and **6.62 s** per clip, the layout is
`gameplay_only` — the reason recorded in the layout is *"no face was seen inside the region"*. In
those stretches the gameplay is shown on its own rather than a blank strip, which is the honest
answer when the streamer cannot be framed. Across the six clips the split-screen covers
**81.6 %** to **100 %** of each one.

**The captions.** **490** cues and **43,272** characters across the six clips, and **0** characters
outside the Latin script in any of them. The first cue of each clip is the clip's own opening
line — *"WHAT?"*, *"IT'S $400 NOW."*, *"OH MY GOD."*, *"WE'LL LOOK FOR THE"*, *"50,000."*,
*"LOOK AT THIS."*

#### What M5.5 cost

The run found **fourteen** defects, and the running count is **twenty-two → thirty-six**. Six are
in the **webcam framing** — the detector could not see the streamer at all (**23**), the tile fix
read the tiles wrongly (**24**), the edge search looked in the wrong place (**25**), the first frame
was read from before the clip (**26**), the webcam spilled out of its own strip (**27**), and the
gameplay crop did not keep clear of it (**28**). Two are elsewhere: the progress page lost the
video's title the moment the event stream opened (**29**), and the webcam's path grew an ffmpeg
expression past **Windows' own 32,767-character limit** (**30**). The **first complete run** of the
new framing found **three more**: the detector was asked for the stretches in the wrong order and
refused (**31**), a saved crop plan was reused after the layout had changed (**32**), and a failed
detection was kept as a final answer (**33**). A fourth was found while fixing **32** — a re-export
would have stretched a plan made for another shape (**34**). The last **two** came out of the
re-export that finally produced the clips above: the saved report was never reused because the
windows never matched exactly (**35**), and the speech-emphasis zoom broke the render because
ffmpeg evaluates a `scale` filter's size **once**, at init (**36**).

Every one of them is guarded by a test that was observed failing against the pre-fix code. The full
table, with the evidence for each, is in `docs/M5-APPLICATION-TESTING.md` §M5.5 and the defect table
there.

#### What M5.5 did not change

No matrix row was closed and none was opened: the count is unchanged at **110 Implemented · 9
Partial · 1 Blocked · 9 Not Applicable · 0 Missing**. Five rows — **CAM-01**, **CAM-02**, **CAM-08**,
**CAM-11** and **CAM-12** — gained **stronger evidence**, which is recorded in
`docs/feature-coverage-matrix.md`. The M5 verdict is unchanged and **v0.1.0 is still gated on K1**.

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
| K28 | **The provider's context window is a setting, not a measurement.** The M5.4 default of **8,192** tokens was chosen because it is the largest that leaves room for the model itself on this **8.4 GB** machine — the extra KV cache measured about **680 MB**, and **16,384** would have added roughly **2.7 GB**, which does not fit. On a **smaller** machine the default is too large and the setting must be lowered; on a **larger** one it is conservative. The product reports a prompt that still overflows rather than truncating it, but it cannot know the user's RAM. Found at M5.4. |
| K29 | **A local model can be slow enough to look broken.** One detection call over an eight-minute window measured **1,993 s** on this box — about **33 minutes** for one request, and the highlight stage makes **two** of them, one after the other. The **3,600 s** default timeout is generous enough for that, but a longer source on a slower CPU is not bounded by anything the product controls. There is no progress message inside a single window. **The gap is measured, not guessed.** The four M5.4 detection windows fit a straight line — **time ≈ 165 s + 0.089 s per prompt character** — to within **2.1 %**, so the difference *between the two M5.4 runs* is explained by their prompts. The gap *against* M5.3 is not: M5.3's first window — the opening **480 s** of a **1,128-word** transcript — took **174.8 s**, where M5.4's **885**-word window took **882.0 s**. It is **not** machine load — the transcription rate on this machine was **2.17×** real time at M5.3 and **2.38×** at M5.4 — and it is **not** the request shape alone, because the **same** payload, hand-sent to the same server with `num_ctx: 8192`, took **1,992.9 s** against the application's **881,989 ms**, a **2.26×** spread on identical work. The request shape **did** change between the two increments (`num_ctx` **4,096 → 8,192**, the change defect 17 introduced), and it remains a candidate; it is **not** proven. Found at M5.4. |
| K30 | **The crop-safety tolerance is a fixed 90% keep-ratio, not a per-shot judgement.** The crop must keep at least **90%** of the face it follows; a sliver of the detector's bounding box outside is tolerated. That is one constant for every shot, every face size and every camera, and it is a **judgement** — a loose detector box on a small face may make the ratio harsher than the picture deserves. The worst case measured on the real source is **19 px of a 549 px face (3.5%)**. Found at M5.4. |
| K31 | **"The same clip" is a fixed 50%-overlap threshold.** Two clips are duplicates when the overlap covers at least **half of the shorter one** — one constant, used by both the pipeline and the diagnostic so they cannot disagree. A shorter clip that is a genuine *highlight* inside a longer clip's range will be removed with it. The higher score survives, so the longer clip is the one that is kept. Found at M5.4. |
| K32 | **The transcript is not reproducible from run to run.** The same file, transcribed twice, gave **two different transcripts**: identical word records for the first **246** — up to **101.02 s** — and then different text with the **same timings** (**1,060** words in **220** segments against **1,277** in **246**). The media were byte-identical and the code was unchanged, so the difference is in the **recogniser**: faster-whisper's confidence check **fails** on hard passages — measured on a **40 s** excerpt of this very source, where `Compression ratio threshold is not met with temperature 0.0 (6.897436 > 2.400000)` — and every fallback pass above zero **samples** from a generator faster-whisper **1.2.1** does not seed; that version has no `seed` argument to pin it with. Two decodes of the same excerpt gave **10** segments against **9**. **What it costs:** the transcript — and therefore the windows, the prompts and the clips — differ between runs, which is why the two M5.4 runs are not a one-to-one comparison. **What it would cost to fix:** pinning the sampler's seed makes the transcript repeatable, and that was **measured, not assumed** — seeding CTranslate2's generator (`ctranslate2.set_random_seed(0)`) before the call made two decodes of the same real excerpt **identical**, with the fallback still running and the quality escape it provides intact. It is **not** applied in this increment, because it changes the transcript the acceptance evidence was gathered on, and the evidence would then no longer describe the shipped code; it needs its own acceptance run. The end-to-end output was never promised to be reproducible — the highlight model runs at temperature **0.3** — so this is recorded as a limitation, not as a broken promise. Found at M5.4. |
| K33 | **Only the English subtitle path was measured on real audio.** The default target, `en`, was run against a **Hindi** source and the captions were inspected — **5,648 words**, **0** of them outside the Latin script. A target that is **neither** English nor the spoken language takes the **pinned-transcription** path: Whisper *speaking* in a target language rather than translating into it. That path is implemented, guarded and reachable, and what it is worth for a given pair was **not measured**. The honest reading is that the feature's **default** is verified and its **other** targets are not. Found at M5.5. |
| K34 | **The webcam-box detector's thresholds are one video's constants.** `MIN_EDGE_CONTRAST = 16`, `MIN_VERTICAL_COVERAGE = 0.55`, `MIN_HORIZONTAL_COVERAGE = 0.85`, `COVERAGE_RATIO = 0.25` and `SEARCH_FACTOR = 0.9` were chosen from the reference video's own material. A different game's art direction — a brighter UI, a flatter webcam, a face against a busy wall — may need different numbers. They are recorded as limitations rather than presented as truths. Found at M5.5. |
| K35 | **The MeowPower wording is a judgement, and nobody outside this increment has read it.** The six stage-to-sentence phrases are the author's. The **structure** — one sentence, one number, the technical detail one disclosure away — is what the tests and the screenshots hold up; the **phrasing** is not evidence of anything except that it reads plainly to the person who wrote it. Found at M5.5. |

### 6.2 Engineering

| # | Limitation |
|---|---|
| K11 | **mypy is at 10 errors in 8 files.** Down from the 14-error baseline, unchanged since M1. The errors are in modules the upgrade did not touch, and are deferred to whoever changes them. CI tolerates mypy with `continue-on-error`. |
| K12 | **The cold import is ~40% slower than at M0** — 93 → 132 `autoclip` modules, about 1.5 s → 2.4 s on this machine. It is a one-off server-start cost, not a runtime path, and the growth is FastAPI building 21 routers instead of 18 rather than a new dependency. Explained in `docs/M5-PERFORMANCE-REPORT.md` §3. |
| K13 | **The cold-start model download** (Whisper weights from Hugging Face) is a third-party library fetch that AutoClip records but does not gate. |
| K14 | **No dependency vulnerability scan, no fuzzing, no SAST scanner** was run. Listed as gaps in `docs/M5-SECURITY-REVIEW.md` §7 rather than implied to be covered. |
| K15 | **No load test** and **no peak-memory sampling** during a render. |
| K36 | **The Windows CI leg still gets its ffmpeg from one external host.** The metadata endpoint that failed on run 44 is no longer the only path — the install now falls back to Chocolatey's own **package** URL on the same host, and a failure names itself instead of blaming the filter — but if that host is unreachable altogether, the leg cannot run. The build itself is unchanged: the package carries the same **9.1 full** build Chocolatey would have installed, with `libass`. Found at M5.5. |

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
| **The M5.4 second-source evidence — a whole second real source, end to end, and nine more defects** | `docs/M5-APPLICATION-TESTING.md` §M5.4, AT-G-01 … AT-G-17 |
| **The M5.4 provider-limit guards — the timeout, the context, the answer budget, the window sizing and the overflow guard** | `tests/test_provider_limits.py` — 22 tests |
| **The M5.4 settings-API guards** | `tests/test_api.py::TestSettings` — the timeout is validated, and the stored value is read back |
| **The M5.4 export-name guards — two clips, one title** | `tests/test_export_graph.py::TestExportFilenames` and `tests/test_api.py::TestClipsWithTheSameTitle` |
| **The M5.4 crop-safety guards — the face the crop follows, and the stated tolerance** | `tests/test_diagnostics.py::TestCropSafetyMeasuresTheFollowedFace`, `::TestCropSafetyTolerance` |
| **The M5.4 duplicate-rule guards — one rule, used by the pipeline and the diagnostic** | `tests/test_highlights.py::TestDuplicateClips` (new file) |
| **The M5.4 boundary guards — a clip may only widen** | `tests/test_boundaries.py::TestSilenceAlignment` |
| **The M5.4 tracker guard — a track stays with its person** | `tests/test_reframe.py::TestTracking` |
| **The M5.4 two-run comparison — the same source, byte by byte, and the recogniser's own fallback log** | `docs/M5-APPLICATION-TESTING.md` §M5.4, AT-G-17 |
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
   it is also the record of the **thirty-six** defects that the application testing and the gates
   found — three at M5, one at M5.1 (§4.3), four at M5.2 (§4.4), five at M5.3 (§4.5), **nine** at
   M5.4 (§4.6) and **fourteen** at M5.5 (§4.7).
2. **Read `docs/M5-SECURITY-REVIEW.md`.** It says what was *not* checked as plainly as what was.
3. **Read the ledger's M0–M5.5 sections.** Every milestone records its decisions and its
   residuals, and the residuals are the honest edges of this release.
4. **Run the gates.** `ruff check . && ruff format --check . && pytest -m "not slow and not golden
   and not e2e" && pytest -m "slow and not golden and not e2e"`. About ten minutes.
5. **Run the gates on an older ffmpeg too, if you can.** Two of the **thirty-six** defects this
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
| M5.4 | `168f4ee` (the request that fits, and a timeout that tells the truth) · `b4f924a` (a job that analysed part of a video says so) · `74ec3eb` (the five defects the run's own diagnostics found) |

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

**The three M5.4 commits, and what each one is for.** They are one commit per defect-cluster, and
each carries its own guards.

| Commit | What it does | Why it is separate |
|---|---|---|
| `168f4ee` | `config.py` (`ProviderSettings.timeout_s` and `ProviderSettings.context_tokens`), `providers/base.py` (`PromptBudget`, `CHARS_PER_TOKEN`, `ProviderError.code`, the prompt budget), `providers/ollama_provider.py` (the timeout, the requested context, the answer budget, the overflow guard, the truthful message), `providers/{anthropic,openai,gemini}_provider.py` (the timeout reaches the SDKs — Gemini in milliseconds, because that is what its SDK counts), `providers/__init__.py` and `providers/resolver.py` (both settings, both construction paths), `pipeline/highlights.py` (the exact-cost window budget, the stop-at-first-timeout, the accurate error), `errors.py`, `api/settings.py` (the provider update is validated), and `frontend/src/api.ts` + `frontend/src/pages/Settings.tsx` (the two new fields) — with the new `tests/test_provider_limits.py` (**21 tests**) and two settings tests in `tests/test_api.py` | The four defects are **one failure seen four ways**, and the fix is one change: the request now fits the model's context, and a timeout says what happened. **20 of the 21 new tests fail without the fix**; the one that passes is a non-regression guard. The **same payload** that the product sent, with `num_ctx: 8192`, returned **HTTP 200** after **1,992.9 s** — the experiment that settled the root cause |
| `b4f924a` | `pipeline/highlights.py` (the windows that were **not analysed** are counted, recorded in the job's usage and said in the log) and one more test in `tests/test_provider_limits.py` | Stopping at the first timeout is only half the answer. A job that analysed the first window and skipped the rest must not look, from the outside, like a job that analysed the whole video. The test was **observed failing** against the pre-fix code |
| `74ec3eb` | `pipeline/export.py` (`output_filename(suffix=)`, `unique_output_filename`), `pipeline/runner.py` and `api/clips.py` (the two export-name call sites), `pipeline/reframe/croppath.py` (`CropSegment.faces`), `pipeline/reframe/__init__.py` (the faces each segment was built around), `pipeline/reframe/tracker.py` (the tracker's proximity tolerance), `pipeline/diagnostics.py` (`FACE_KEEP_RATIO`, `_faces_at`, `_face_inside_fraction`), the new `pipeline/duplicates.py`, `pipeline/highlights.py` (the time-based de-duplication) and `pipeline/boundaries.py` (the alignment may only widen a clip) — with the new `tests/test_highlights.py` and the additions to `tests/test_export_graph.py`, `tests/test_api.py`, `tests/test_diagnostics.py`, `tests/test_boundaries.py` and `tests/test_reframe.py` | The five defects the run's **own diagnostics** found, after it had finished. They are all in the pipeline's **output**, and they are kept together because they are one story: **the product measured itself, and four of the five measurements were wrong** — or, in the tracker's case, right about the wrong face. **17 of the 20 new tests fail without the fix**; the other three are non-regression guards |
| `722afb7` | The eight documents that carry M5.4's evidence: `docs/FINAL_UPGRADE_REPORT.md`, `docs/M5-APPLICATION-TESTING.md`, `docs/M5-REGRESSION-REPORT.md`, `docs/M5-PERFORMANCE-REPORT.md`, `docs/upgrade-audit.md`, `docs/UPGRADE-LEDGER.md`, `docs/EGRESS-INVENTORY.md` and `docs/feature-coverage-matrix.md` | The M5.4 record: the second real source, the **22** defects, the verification run with every fix in, the gates and the CI runs. **Run 40** is that tree, green on all six jobs |

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

The last milestone added **three more** to that list — and a fourth of its own, in the **CI's own
workflow** rather than in the product — and they are the clearest argument for the way this release
was produced:

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

M5.4 added four more, and they are a class the previous sixteen did not contain: they are not
about the **content**, they are about the **request**.

* **The timeout was a hard-coded 600 seconds.** One legitimate call over an eight-minute window
  was measured at **1,993 s** on this box — so the ceiling cut off calls that were about to
  succeed, and the advice printed with the failure (*"try again"*) reproduced the failure exactly.
* **The failure message blamed a GPU the machine did not have.** It said *"Large transcripts on a
  small GPU can exceed the limit"*, on a machine with `size_vram: 0`, and told a local-only user
  to *use a hosted provider* — advice the product's own settings screen does not let that user
  follow.
* **A timed-out window left the server still generating the abandoned request.** The next window
  queued behind the orphan, burned its own 600 s without ever starting, and the stage then
  reported *"failed in every window"* — including the window that was never tried.
* And **the request did not fit the model's context.** Window 0's prompt measured **5,861 tokens**
  against a **4,096-token** context, while the product asked for `num_predict: 4096` — an answer
  budget as large as the entire context. The model server truncates an overflowing prompt
  **without saying so**. This is the one that would have shipped as a *success*: the pipeline would
  have produced clips, and they would have been clips of a **partial transcript**.

That last one is the strongest argument in this report for the way the release was produced. The
defect was not visible in the code, because the code was asking for a reasonable thing — a prompt
and an answer — and the *combination* was impossible. It was not visible in the logs, because the
server truncates silently. It was found by **measuring the request with the model server's own
tokenizer**, and it was settled by **re-running the same payload with a context that fits**:
HTTP 200, after **1,992.9 s**, with `prompt_eval_count: 5862` — the estimate exactly.

And then, **after the run had finally finished**, the pipeline's own diagnostics found **five more**
— and this time they were in the pipeline's **output**:

* **Two clips with the same title overwrote each other.** The export's name came from the title
  alone, and the titles are the **model's** choice. Two of the nine clips were called *"The
  language of love in videos"*; the export directory held **one** file for them, and the second
  clip's **54,024,088 B** had replaced the first clip's **14,272,780 B** — with its subtitles
  gone too. The database still said the first clip was **14,272,780 B**: a file that no longer
  existed.
* **The crop-safety diagnostic measured the wrong face.** It took *"the largest face within half
  a second"* as the subject, while the crop follows the **tracked** speaker, and it reported **6
  of the 9 clips** as cutting a face that was never their subject.
* **The pipeline and the diagnostic had two different definitions of "the same clip".** The
  pipeline compared **word ranges**; a clip *inside* another one has almost no words in common
  with it, so two pairs of the same footage were both kept — and the diagnostic, which compares
  **time**, said so.
* **A clip could open in the middle of a word** — **52 ms** inside, on rank 1 — which breaks the
  code's own documented invariant, *"alignment only ever widens a clip"*.
* And **a face track could jump to a smaller face beside it.** The tracker's proximity tolerance
  was scaled by the **larger** of the two faces, so a track could hop onto a smaller face-shaped
  object near the speaker — a **Pikachu plush** on the shelf behind them — and the crop panned
  away from the speaker to follow it.

Every one of those five reports was read back against the source **before** anything was changed.
That is the discipline the whole upgrade has followed, and this increment is where it mattered
most: four of the five were the **measurement** being wrong, not the product. A diagnostic that
reports failures that did not happen sends the user looking for a fault that is not there — and
defect 7 of this upgrade was exactly that. The **tolerance** the new measurement allows is
stated, measured and defended in §4.6: the crop must keep **90%** of the face, and the worst case
on the real source is **19 px of a 549 px face (3.5%)**.

The lesson is the same one the last milestone taught, in a different place. A passing test is not
evidence unless it checks the right *property* on the right *thing*; a green run is not evidence
unless it ran the thing that was broken. The structural graph check was the fix for defect 3 and
it only ever looked at the **music** graph. The prompt-budget check is the fix for defect 17 and
it has to look at the **request the provider actually receives** — because that is where the
constraint lives.

One of them deserves its own note, because it is the kind of defect that hides behind a *passing*
test. The structural check that found the last one — "no filter output is consumed twice" — was
**already in the tree**. It was the fix for defect 3. But it only ever looked at the **music**
graph, so the **video** graph went unexamined and the same mistake was sitting in it. A test that
checks the right *property* on the right *thing* is worth more than a test that checks a
*different* property; so the check moved to `tests/graph_shape.py` and now covers both graphs. It
also caught a label collision in the first version of the fix, before any render — which is the
whole argument for a parser rather than a screenshot.

And the last thing to say is the **verification run**, because a fix that is only ever proved by a
test is a fix whose *proof* is the test. The application was pointed at the **same** video again —
a **new** job, from the paste, through the real UI — with every fix in the tree. It finished
**done**, in **4,791 s**, with **nine** clips, **nine distinct exports**, and **89 of 90**
measurements `ok`. The one that is not is a **true positive about the source**: the video really
does go black for **0.83 s** in the middle of one of its own clips, and `blackdetect` on the raw
file says so.

And the run **reproduced the condition that caused the defect**: the model chose the **same title
twice** again — *"Why I'm not like them"* — so the export-name fix was exercised by the run
itself, not only by a test. Under the code as it was, that pair would have been one file and one
set of subtitles, and the first clip would have been gone. It was not gone. That is the difference
between a fix that is **proven** and a fix that is **assumed**.

That is the main reason to trust this release. Not the feature count.
