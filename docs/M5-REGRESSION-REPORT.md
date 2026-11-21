# AutoClip — M5 Regression Report

**Run on:** 2026-11-20/21, `feature/upgrade-u0-u10` at `bcdfc47`.
**Re-run at M5.2:** 2026-11-21, at `a907805` — the same gates, plus the Linux leg, after the four
defects the real four-hour ingest found. See §10.
**Machine:** Intel Core i5-8279U, 4 cores / 8 threads, 7.8 GB RAM, no CUDA; Windows, Python 3.11.16,
FFmpeg 9.0.2, Node 24.21.0.
**Command used for every run below:** `.venv\Scripts\python.exe -m pytest …` with
`PYTHONIOENCODING=utf-8`.
**Also run on:** Linux — WSL, **ffmpeg 7.0.2**, Python 3.12.16 — because the CI runners are Linux
and one of the defects found at M5 renders on Windows and fails on Linux. See §2.

---

## 1. The gates, and what each one says

| # | Gate | Command | Result | Verdict |
|---|---|---|---|---|
| G1 | Lint | `ruff check .` | *All checks passed!* | **PASS** |
| G2 | Format | `ruff format --check .` | *230 files already formatted* | **PASS** |
| G3 | Types | `mypy backend/autoclip` | *Found 10 errors in 8 files (checked 137 source files)* | **BASELINE — unchanged** |
| G4 | Unit suite | `pytest -m "not slow and not golden and not e2e" -q` | **1,351 passed**, 70 deselected — and the **same 1,351 on the Linux leg** | **PASS** |
| G5 | Render suite | `pytest -m "slow and not golden and not e2e" -q` | **46 passed**, 1,375 deselected | **PASS** |
| G6 | Frontend | `npm run build` (`tsc -b && vite build`) | 59 modules transformed, built in 2.68 s | **PASS** |
| G7 | Container | `docker build -f docker/Dockerfile --target base .` + `GET /api/health` | **Not runnable locally — Docker is not installed on this machine.** Verified by the CI `docker` job on every push. | **PASS (CI)** |
| G8 | Real media | `AUTOCLIP_E2E_MEDIA=… pytest tests/test_pipeline_e2e.py -q` | See §5 | **PASS** |
| G9 | Whole suite | `pytest tests -q --ignore=tests/test_pipeline_e2e.py` | **1,397 passed**, 0 failed, 0 xfailed, 0 skipped, **454.05 s** | **PASS** |

### G3 in detail — mypy is at its baseline, and that is the claim

The M0 baseline was **14 errors in 10 files**. The M5 state is **10 errors in 8 files**. The four
that were fixed were in the modules M1 touched (`music/`, `pipeline/export.py`,
`pipeline/speech_timeline.py`). The remaining ten are in modules the upgrade did not touch:

| File | Error |
|---|---|
| `backend/autoclip/chat/context.py:285` | `Job \| None` assigned to a `Job` variable |
| `backend/autoclip/chat/context.py:286` | `Any \| None` assigned to a `YouTubeUpload` variable |
| `backend/autoclip/cli.py:231` | a `bool` assigned to a `list[str]` variable |
| `backend/autoclip/pipeline/ffmpeg.py:287` | `int(object)` — an overload the `type: ignore` did not cover |
| `backend/autoclip/pipeline/validate.py:209` | `int \| None` passed where `int` is expected |
| `backend/autoclip/pipeline/validate.py:210` | `int \| None` passed where `int` is expected |
| `backend/autoclip/pipeline/boundaries.py:91` | `int \| None` assigned to an `int` variable |
| `backend/autoclip/providers/resolver.py:78` | `chain` redefined |
| `backend/autoclip/providers/openai_provider.py:71` | unsupported right operand for `in` |

CI runs mypy with `continue-on-error: true`, so these have never blocked a build. They are
**deferred to the modules that touch them** and are recorded as a known limitation rather than
being quietly "fixed" in a release milestone by someone who does not know why the code is written
that way.

**Nothing in the upgrade made the type situation worse.** The count went down by four and no new
error appeared in a module the upgrade added. The M5 export fix did not add one either.

---

## 2. What the upgrade changed in the suite

**How the function counts are measured.** Every `test*` function in `tests/**/*.py`, counted from
the AST — module-level functions **and** the methods inside `Test…` classes — at each named
revision, with the same script. The counts in this table were re-measured at M5.2 because the
figures printed in the earlier revisions of this document were taken with a narrower count (they
excluded the class methods). The **deltas** are unaffected; the absolute numbers are now
reproducible from any revision with one command.

| | M0 (`bf76811`) | M5 (`bcdfc47`) | M5.1 (`b59605b`) | M5.2 (`a907805`) | **M5.3** | Δ M0 → M5.3 |
|---|---|---|---|---|---|---|
| Test files | 35 | **54** | **55** | **55** | **57** | +22 |
| Test functions in the tree | 658 | **1,257** | **1,272** | **1,287** | **1,322** | **+664** |
| — of which module-level | 384 | 900 | 913 | **926** | **928** | +544 |
| Tests collected | 672 (of which 26 were `xfail`) | 1,300 (of which **0** are `xfail`) | **1,315** (of which **0** are `xfail`) | **1,330** (of which **0** are `xfail`) | **1,397** (of which **0** are `xfail`) | **+725** |
| Failing | 0 | **0** | **0** | **0** | **0** | — |
| Skipped | 0 | **0** — the only `pytest.skip` calls in the tree are the e2e media gate, which is deliberate and documented | **0** | **0** | **0** | — |
| `xfail` markers | **26** (the SSRF gap, pre-registered) | **0** | **0** | **0** | **0** | −26 |
| Wall clock, unit selection | 193.77 s (672 tests, one invocation) | — | **249.81 s** (1,270 tests) | — | **230.28 s** (1,351 tests) | — |
| Wall clock, whole suite | — | — | **534.88 s** (1,315 tests) | **499.52 s** (1,330 tests) | **454.05 s** (1,397 tests) | — |
| Wall clock **per test** | 0.288 s | — | **0.407 s** (whole suite, incl. renders) | **0.375 s** (whole suite, incl. renders) | **0.325 s** (whole suite, incl. renders) | — |

**The M5.1 column, against the M5 column.** M5.1 added **one test file** and **15 tests**: the
eight-case ducking matrix (`tests/test_ducking_matrix.py`, 8 tests), four unit tests for the
tri-state `ducking_intervals()` helper, two API-boundary contract tests, and one filter-graph
test.

**The M5.2 column, against the M5.1 column.** M5.2 added **no new test file** and **15 tests**,
because every one of its four guards belongs to a file that already existed:

| File | Tests | What it asserts |
|---|---|---|
| `tests/test_ingest.py` | **+4** | The configured format selector is the one used (3), and the download is written to the transfer log (1) |
| `tests/test_diagnostics.py` | **+5** | The crop-safety check measures the clip's own face, matched **in time** |
| `tests/test_reframe.py` | **+2** | The faces travel with the crop path, and an older crop path without faces still loads |
| `tests/test_url_policy.py` | **+5** | A load-balanced public host is not a rebinding (2); the protection still holds (2); the unit suite resolves no real hostname (1) |

**The M5.3 column, against the M5.2 column.** M5.3 added **two new test files** and **35 test
functions** — **67 collected tests**, because five of the new tests are parameterised over the
terminators of nineteen writing systems:

| File | Tests | What it asserts |
|---|---|---|
| `tests/test_transcript.py` | **+6 functions, 39 collected** (new file) | Every writing system's own sentence and clause terminator is recognised — the Devanagari danda, the Arabic marks, the Ethiopic, Tibetan, Myanmar, Khmer, Ideographic, fullwidth, Armenian, Georgian, Mongolian and Balinese ones — and the Tibetan **tsheg** is deliberately **not** a clause mark |
| `tests/test_export_graph.py` | **+10 functions** (new file) | The filter graph does not grow with the number of segments; the emphasis expression appears once per stretch rather than once per segment; the real clip that failed in the field fits inside the command-line limit; and the graph is **well-formed for any ffmpeg** — no filter output consumed twice, no filter after an output label — for any number of segments, with or without a webcam, and every segment gets its own copy of the source |
| `tests/test_boundaries.py` | **+3** | The too-short range is extended to the **first word that reaches the floor**, a range that cannot reach the floor is still dropped, and a Devanagari danda is a sentence boundary |
| `tests/test_ffmpeg.py` | **+4** | A command that fits is accepted; an over-long one is refused **before** ffmpeg runs, with a message that names the filter graph; the limit is the platform's own |
| `tests/test_export_render.py` | **+1** | A **behavioural** render: the webcam's speech emphasis renders in a **later** stretch, not only in the first |
| `tests/test_captions.py` | **+8** | A caption is never held for longer than `MAX_CAPTION_S`, in **every** preset, in the ASS that gets burned in and in the `.srt` sidecar — and bounding it drops **no word** |
| `tests/test_diagnostics.py` | **+2** | A word the recogniser stretched is not a fault, and the longest caption is measured on the **rendered** captions |

> **A note on `tests/graph_shape.py`.** It is a **new file**, but it holds **no test functions** —
> it is the shared structural checker that `tests/test_music.py` and `tests/test_export_graph.py`
> both call. It is not counted in the "test files" row above, because it contains no tests. Its
> arrival is what moved the **music** graph's check out of `tests/test_music.py` and applied the
> same check to the **video** graph — which is where defect 13 was hiding.

**The 26 `xfail` markers are the important number.** At M0 the SSRF policy was specified but not
enforced, so the twenty-six target-policy tests were pre-registered as `xfail(strict=True)` — the
suite stayed honest and green for the state that actually existed, without hiding the gap. At
M0.5 the enforcement landed and **every marker was removed**. A `strict=True` xfail would have
failed the build if the test started passing without the marker being deleted, so the flip could
not have happened by accident. The final count is **zero xfailed** — there is nothing in the suite
that is allowed to fail quietly.

### The 24 e2e tests are still gated

`tests/test_pipeline_e2e.py` skips without `AUTOCLIP_E2E_MEDIA`. That gate is deliberate: the
pipeline's risky parts — ffmpeg segment tiling, whisper timing, MediaPipe face tracking, libass
caption burn-in — are exactly the parts that pass on synthetic colour bars and fail on real
footage. At M0 the 24 were skipped; at M5 they are **run against a real source** (§5).

### The same two selections, on the Linux leg

The CI runs on Linux, on a different ffmpeg from the development machine. The Linux leg is
therefore reproduced locally — WSL, **ffmpeg 7.0.2**, Python 3.12.16, the same Python as the
Ubuntu py3.12 leg — and it is run **before** the release commits are pushed, not after:

| Selection | Windows (ffmpeg 9.0.2) | Linux (ffmpeg 7.0.2) |
|---|---|---|
| Unit — `-m "not slow and not golden and not e2e"` | **1,351 passed**, 70 deselected | **1,351 passed**, 70 deselected |
| Render — `-m "slow and not golden and not e2e"` | **46 passed**, 1,375 deselected | 46 passed (CI job; locally covered by the ffmpeg-sensitive selection below) |
| ffmpeg-sensitive selection — the ducking matrix, the render tests, the music tests, the M5.3 guards and the four M5.2 guard files | — | **267 passed**, 104.89 s |
| `ruff check .` | *All checks passed* | *All checks passed* |
| `ruff format --check .` | *230 files already formatted* | *230 files already formatted* |

**The same tests, the same counts, on both platforms — and one of them only passes on one.** The
sidechain fallback consumed one filter output twice, which ffmpeg 9 accepts and ffmpeg 7 refuses.
It was found by running the Linux leg, and it would have shipped otherwise.

**The M5.2 Linux leg was re-run from the exact committed tree**, exported with `git archive` so
that what was tested was what was committed and not a working directory with edits in it. The
toolchain was **ffmpeg 7.0.2** — the version that exposed defect 3 — and the `ass` filter was
confirmed present before the renders ran. The **212-test** ffmpeg-sensitive selection passed,
including the eight-case ducking matrix's real renders.

**The M5.3 Linux leg found the same class of defect again, in the other graph.** The export's
**video** graph consumed a filter output once per crop segment; ffmpeg 9 tolerated it and ffmpeg 7
refused it. It is **defect 13**, and the leg caught it in the same way it caught defect 3 — by
running on the CI's platform rather than on the developer's. After the fix, the leg is green from
the committed tree: **267 passed** in the ffmpeg-sensitive selection and **1,351 passed / 70
deselected** in the unit selection, with ruff clean on both platforms.

---

## 3. Coverage by area

The per-file function counts below are the *functions* in the tree; the collected count is higher
because several are parameterised.

| Area | Files | Test functions | Notes |
|---|---|---|---|
| Music library, analysis, licensing | `test_music.py`, `test_music_library.py`, `test_music_selection.py` | 87 | Includes the ducking boundary cases: 349 ms merges, 350 ms does not |
| Webcam detection, tracking, layout | `test_webcam.py`, `test_layout.py`, `test_layout_api.py` | 77 | Includes the legibility veto and the manual-override-wins rule |
| Creative intelligence | `test_creative.py`, `test_creative_api.py`, `test_budget.py`, `test_diagnostics.py` | 82 | Includes the budget ceiling and the ten named diagnostics |
| Speech timeline | `test_speech_timeline.py`, `test_speech.py` | 45 | One shared detector for ducking, layout and captions |
| Security and egress | `test_url_policy.py`, `test_egress.py` | 54 | Zero xfail markers |
| YouTube publishing | `test_youtube.py`, `test_youtube_accounts.py`, `test_youtube_identity.py`, `test_youtube_policy.py`, `test_youtube_resumable.py`, `test_youtube_reconcile.py`, `test_youtube_duplicates.py`, `test_multi_channel.py` | 134 | Five sub-areas: identity, policy, resumable, reconciliation, routing |
| Instagram publishing | `test_instagram.py` | 111 | The whole Meta error table, the media rules, the duplicate guard |
| Routing decisions | `test_routing.py`, `test_routing_decision.py` | 37 | |
| Pipeline and export | `test_pipeline_stages.py`, `test_export_render.py`, `test_ffmpeg.py`, `test_captions.py`, `test_validation.py`, `test_boundaries.py` | 103 | `test_export_render.py` carries the slow, real-ffmpeg renders |
| Database and migrations | `test_db.py`, `test_paths.py`, `test_config.py` | 55 | |
| API surface | `test_api.py`, `test_frontend_api.py`, `test_errors.py` | 104 | `test_frontend_api.py` asserts the TS types and the Python schemas agree |
| The rest | 18 files | 490 | Jobs, batches, chat, providers, workflows, learning, trends, resources, restarts, notifications, CLI, system |

---

## 4. The CI runs for this branch

The workflow runs on `main` **and** on `feature/**` pushes, and on pull requests. It has four
jobs: `backend` (a four-way matrix — ubuntu 3.11, ubuntu 3.12, macos 3.12, windows 3.12), the
lint/type/unit/render steps, `frontend` (`npm ci` + `npm run build`), and `docker` (build the
image, run it, poll `GET /api/health`).

`concurrency: cancel-in-progress: true` means a newer push cancels the run for an older commit.
Four runs were cancelled for exactly that reason, and that is why they are marked cancelled
rather than failed.

**The table below is the run history as it stood at the release commit.** It is a record, and it
grows; the claim that matters is the one under it, which does not go stale.

| Run | Commit | Title | Result |
|---|---|---|---|
| 4 | `24060ff` | CI: run on feature-branch pushes and keep branch artefacts out | success |
| 5 | `4c869c6` | docs: record the M0 deliverable commit in the ledger | success |
| 6 | `d9ad80c` | M0.5: document the enforcement | **cancelled** — superseded by run 7 |
| 7 | `312cdc1` | docs: record the M0.5 commit hashes in the ledger | success |
| 8 | `2266466` | M1: document the milestone | success |
| 9 | `975e376` | M2: ledger changelog row for the milestone commit | success |
| 10 | `7b9751b` | M3: the ledger changelog row for the milestone commit | success |
| 11 | `20f6578` | M4a: the publishing policy — audience, privacy and destination | success |
| 12 | `aa1f27f` | M4a: the upload survives a dropped connection | success |
| 13 | `7ed2a8d` | M4a: an upload that may have succeeded is never sent twice | success |
| 14 | `53bc065` | M4a: the routing decision explains itself | **cancelled** — superseded by run 15 |
| 15 | `5d46feb` | M4a: the clip list shows the whole routing explanation | success |
| 16 | `8038890` | M4a: running out of quota waits for the reset | success |
| 17 | `e837faf` | M4a: the ledger, the matrix and the audit updated | success |
| 18 | `5fc04cc` | M4b: the ledger, the matrix and the audit updated | **cancelled** — superseded by run 19 |
| 19 | `4cf309b` | M5: the formatter is pinned | **failure** — the Ubuntu legs failed in Unit tests: a test wrote to the owner's real OS keyring, and Linux has no keyring backend to write to. Fixed by `94c6d9c` |
| 20 | `94c6d9c` | M5: no test may touch the owner's real OS keyring | **failure** — the Ubuntu py3.12 leg failed at *"Verify ffmpeg can burn subtitles"*. The check piped the filter list into `grep -q`; `grep -q` exits at the match, the producer gets **SIGPIPE**, and `set -o pipefail` turns that into a failed step. Fixed in `.github/workflows/ci.yml` — the check was **corrected, not removed** |
| 21 | `64d253d` | M5: the release package | **cancelled** — superseded by run 22 |
| 22 | `cbcbe1c` | docs: record the M5 release commit in the ledger and the commit trail | **success** — all six jobs green: the four backend legs, the frontend build, and the Docker image with its health smoke test |
| 23 | `ab9052e` | docs: the release run is green, and the Journey D records are complete | **success** — all six jobs green again, including the Ubuntu py3.12 leg that had failed twice |
| 24 | `2931059` | docs: the CI run history reads the same way whichever run you look at | **success** — all six jobs green |
| 25 | `822143e` | docs: four runs were cancelled, not three | **success** — all six jobs green |
| 26 | `b59605b` | M5.1: the empty-timeline fix and the eight-case ducking matrix, with their tests | **success** — all six jobs green, including the Ubuntu py3.12 leg |
| 27 | `d8db47f` | docs: the M5.1 tree is green on all six CI jobs | **success** — all six jobs green |
| 28 | `066bbf6` | Ingest: the configured yt-dlp format is the one that is used | **success** — all six jobs green. The first M5.2 code commit |
| 29 | `a907805` | Security: a load-balanced public host is not a DNS rebinding | **success** — all six jobs green. The whole M5.2 code tree: the transfer log, the crop-safety measurement and the URL policy |
| 30 | `f1cbe81` | docs: M5.2 — the real four-hour ingest, and four more defects | **success** — all six jobs green. The whole M5.2 documentation tree |
| 31 | `f190e9a` | docs: M5.3 — the complete ten-minute pipeline, and five more defects | **success** — all six jobs green — [run 44944459562](https://github.com/Shrishant1cog/autoclip/actions/runs/44944459562). The whole M5.3 tree — the four M5.3 code commits and the documentation, together. `2b5935d` (the defect-13 fix) was **not** pushed on its own, so **this** is the run that first exercised it on all six CI jobs |
| 32 | `56553ec` | docs: M5.3 — two broken references in the evidence | **success** — all six jobs green — [run 44949264565](https://github.com/Shrishant1cog/autoclip/actions/runs/44949264565). The tree with the two documentation fixes a cross-reference check found in the evidence itself |
| 33 | `6c2f9e0` | docs: M5.3 — the final CI run | **success** — all six jobs green — [run 44950193899](https://github.com/Shrishant1cog/autoclip/actions/runs/44950193899). The last commit that changes anything but this run history |

**Runs 31, 32 and 33 are green on all six jobs.** Run 31 was the first to exercise the defect-13
fix on every CI job; run 32 is the tree with the two documentation fixes; run 33 is the last
commit that changes anything but this run history. One run in between (44948642080, `f9fad75`)
was **cancelled** by the concurrency group when the next commit was pushed, with five of its six
jobs already green — a cancellation, not a failure, and the sixth (Windows) was cancelled
mid-run rather than failed.

> **Why this table stops here.** A commit that records a CI run is itself run by CI, and
> recording *its* run would need another commit — which would need another. The table therefore
> records the runs that prove the **content** of each increment, and stops at the last commit that
> changes anything but the run history. That commit's own run is green as well; it was checked
> after the push, and it needs no row here.

**Every run on this branch since the two failures was green.** Two of the runs failed, and **both
failures were real defects** — not flakes, and neither was explained away. Four runs were cancelled
by a newer push.
**Both failures were real defects**, not flakes, and neither was explained away:

* **Run 19** was a **product** defect — a test that wrote to the owner's real OS credential store.
  The symptom appeared only on Linux because Linux has no keyring backend; the cause was present
  everywhere. The fix is an **autouse** isolation fixture, so the class is closed rather than the
  one test that happened to be noticed.
* **Run 20** was a **CI** defect — the ffmpeg check reported that an ffmpeg **with** the `ass`
  filter did not have one, because the producer in the pipe was killed by SIGPIPE. The job log
  shows `printf: Broken pipe` and then the `ass` filter on the very next line.

Both were **reproduced locally before they were fixed**: run 19 on a Linux environment with no
keyring backend, run 20 with a 320 KB filter list — the old body fails it, the new body passes
it, and a build genuinely without the `ass` filter still fails the new body. A failure that is only
fixed in CI is a failure that comes back.

**The release run is green on all six jobs**, including the Ubuntu py3.12 leg that had failed
twice.

### The Linux leg is reproduced locally, on ffmpeg 7

The CI's Ubuntu legs run on a different ffmpeg from the development machine — **8.0.1** on the
runner, **9.0.2** on Windows. That difference is not academic: ffmpeg 9 accepts a filtergraph in
which one filter output is consumed twice, and ffmpeg 7 refuses it with *"Invalid stream
specifier"*. The Linux leg is therefore reproduced locally on **ffmpeg 7.0.2** (WSL, Python 3.12.16
— the same Python as the Ubuntu py3.12 leg) before the release commits are pushed, and it is what
caught the third defect in §6.

---

## 5. Lane C — the real-media run

**Source.** `materials/input/ytdownloadedvideos/59ec00754fa34edf/source.webm` — a real
68-minute 1080×1920 recording, cut to a 180 s segment at 120 s with
`scripts/make_e2e_media.py`.

> **Rights.** This is a third-party recording with no rights confirmation. It is used here for
> **technical acceptance only**. Nothing produced from it was published anywhere, and it is not a
> release artefact.

**The segment.**

| | |
|---|---|
| Duration | 180.0 s |
| Frame | 1920×1080 |
| Audio | present |
| Size | 18.4 MB |

**The run.**

```
AUTOCLIP_E2E_MEDIA=<segment> pytest tests/test_pipeline_e2e.py -q -rs -p no:randomly
```

The suite runs the **whole pipeline for real** — ffmpeg, faster-whisper, MediaPipe, libass — on
the actual video, with only the language model's *answer* scripted (clip selection is a judgement
call that needs an API key and would be non-deterministic anyway). Everything the pipeline does
with that answer is exercised end to end.

See `docs/M5-APPLICATION-TESTING.md` for the full journey evidence.

---

## 6. Regression risks that were checked on purpose

The upgrade added a great deal of new machinery. These are the interactions that could plausibly
have broken, and what was done about each.

| Risk | How it was checked | Result |
|---|---|---|
| The music ducking and the webcam layout each built their own speech detector, so the music and the talking would disagree | `pipeline/speech_timeline.py` is the **only** VAD in the tree, and both consume it | One timeline. `tests/test_speech_timeline.py` (29) |
| The ducking boundary was implemented on 30 ms frames, so a 349 ms gap and a 350 ms gap would be indistinguishable | The merge test asserts on **millisecond** timestamps | 349 ms merges, 350 ms does not. Both asserted |
| The music filtergraph and the layout filtergraph could disagree about where a clip starts | `SpeechTimeline.relative_slice()` converts source-time intervals to clip-time | Fixed at M1; `tests/test_export_render.py` renders both |
| The export handed absolute source-time speech intervals to a filtergraph whose clock starts at the clip | The same fix | Caught by a real render, not by a unit test |
| An Instagram failure could cancel a YouTube upload | Separate tables, separate workers | `tests/test_instagram.py` asserts both directions |
| A retried job could exceed the AI budget | The counters live in `job_ai_budget` and persist across retries | `tests/test_budget.py` (17) |
| A refused consent could trigger a fallback to another external provider | The resolver refuses; only a local provider may answer | `tests/test_egress.py` |
| The M4b export change could have broken the YouTube path | The edit-list and bitrate changes were measured against a real render | `tests/test_export_render.py` — 27 slow tests |
| The NAT64 fix could have opened an SSRF hole | The embedded IPv4 is classified, not the prefix | 8 tests: loopback, private and the metadata address |
| The M4b keyring bug could recur | Every secret-writing test now takes the `fake_keyring` fixture | 14 secret-writing tests, all fixture-backed — **but this was not enough**: one more test was found by CI, and the fix was raised to an **autouse** fixture covering the whole suite |
| **A test could write to the owner's real OS keyring without asking** | An **autouse** `isolated_keyring` fixture replaces the OS keyring for **every** test; `fake_keyring` returns that same object, and `no_keyring`/`failing_keyring` still override it | **Closed at the class level** (`94c6d9c`). The owner's credential store was audited: 549 AutoClip entries found, **535 deleted by value** (only entries whose stored secret exactly equalled a test literal), **14 kept** — the owner's own credentials, confirmed afterwards with `cmdkey /list` |
| **A re-export could ignore the user's music choice** | The API export path resolves the music through the same three-scope precedence the pipeline uses, and hands the renderer the job's speech timeline sliced to the clip | **7 regression tests** in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix** |
| **The ducking filtergraph could be malformed** — an output label in the middle of a chain, or one output consumed twice | A **structural** check on the graph itself: no filter output consumed twice, no filter after an output label. This is version-independent, so it catches the defect on any ffmpeg rather than only the one that rejects it | `tests/test_music.py::test_every_graph_is_well_formed_for_any_ffmpeg` — **catches both defects on any ffmpeg** — plus **3 real-render tests** in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix** |
| **The CI's ffmpeg check could report a false negative** | The check matches the filter list with bash's own pattern matching and never pipes | Reproduced with a 320 KB filter list: the old body fails, the new body passes, and a build without the `ass` filter still fails |
| **The ducking could be configured correctly and not actually happen** | Two renders of the same clip — one with the bed, one without — differenced sample by sample; the RMS of the difference in the timeline's own speech windows and speech gaps | **Measured: 0.04126** in the gaps, **0.01139** under speech → a drop of **3.62× = 11.2 dB** against a configured **−12.0 dB**. The bed's dominant frequency is **440.0 Hz** — the tone in the chosen file |
| **The configured download format could be ignored** — the setting would exist, be documented, and never reach the command line | The command line is built in **one place**, `_download_command`, and the selector is asserted against it | **3 tests** in `tests/test_ingest.py`; **2 of the 3 fail without the fix**. Proven against a real four-hour download: **12.54 GiB at 1440p60 before**, **399+140 — 1920×1080@60 after** |
| **The largest transfer AutoClip makes could leave the machine with nothing in the user's own log** | The transfer is recorded on refusal, on a failed launch, on a failed download and on success | **1 test** in `tests/test_ingest.py` — fails without the fix with `assert [] == [('ok', ...)]`. Proven on a real 844 MB download: **exactly one** row, `outcome=ok` |
| **A quality measurement could report failures that never happened** — a diagnostic that compares against a rectangle measured somewhere else | The crop plan carries the faces it was built around, in source pixels and in the clip's own time base; the check matches each keyframe to the face nearest it **in time**, and `diagnose_clip` no longer accepts a whole-source rectangle as a face | **5 tests** in `tests/test_diagnostics.py` + **2** in `tests/test_reframe.py`; the time-matching one **fails without the fix**. Proven on two real clips of a real stream: the old rule fails both, the new rule passes both |
| **A security control could be so strict that it breaks a legitimate feature** — a rebinding guard that refuses any host whose two DNS answers differ | The guard compares the **class** of the two answers, not the exact set of addresses; a move **inwards** is still refused | **2 tests fail without the fix**; **3 more** assert the protection still holds (public → private, public → loopback, public → forbidden). The whole unit suite now resolves **no** real hostname |

---

## 7. What was **not** regressed

Stated so a reviewer does not assume more than was checked.

- **No cross-version golden-set comparison.** The reframe output was not compared frame-by-frame
  against the pre-upgrade build on the same footage. The reframe acceptance bar (no visible
  jitter, no cut-off faces, the speaker on screen ≥95% of speaking time) against a fixed golden
  set is **still unverified**, exactly as it was before the upgrade. This is the gate for v0.1.0
  and it was not part of this milestone's scope.
- **No load test.** Nothing was run at volume.
- **No dependency vulnerability scan.** See `docs/M5-SECURITY-REVIEW.md` §7.
- **No fuzzing** of the URL parser, the MP4 box walker or the model-output validator.
- **No live-provider run.** See §8.
- **No Docker build on this machine.** Docker is not installed here; the CI `docker` job covers it
  on every push.
- **The full four-hour pipeline was not run** (M5.2). The **ingest** of the complete file was
  exercised twice, at two formats, and the **pipeline** was exercised on real segments cut from
  that same downloaded file. Running the complete four-hour recording through every stage would
  have needed roughly **25 hours** for the whole pipeline on this four-core machine — measured, not
  assumed. The claim is therefore about the ingest path and about the pipeline on real segments,
  **not** about the complete recording end to end. **Amended at M5.3:** a *complete* source — a
  **ten-minute** podcast — was run through **every** stage end to end, so the end-to-end claim
  now rests on a whole source rather than on pieces of a long one. The **four-hour** recording
  remains unrun, for the measured reason above.
- **No second model, and no hosted model, on the real segment.** The pipeline was exercised with
  a **local** Ollama model and **local** whisper. The hosted-LLM paths remain unverified for the
  same reason as before — no authorised credential was supplied. **The M5.3 run is the same:** a
  local `llama3.1:8b` over Ollama and local whisper `small`, and the transfer log is the proof —
  **7** of its **9** rows point at `127.0.0.1` and **no hosted host appears at all**.
- **No publishing of anything derived from the real media.** The source is a third-party creator's
  stream and was used for **technical acceptance only**. Nothing produced from it was published
  anywhere.

---

## 8. Lane B — the external integrations

**Unverified, and deliberately not claimed as verified.**

| Path | Status | Why |
|---|---|---|
| ElevenLabs transcription | **UNVERIFIED (external)** | No authorised credential was supplied for a consent-granted run |
| Hosted LLM — highlight detection, creative planning, music selection | **UNVERIFIED (external)** | Same |
| YouTube — OAuth, upload, read-back, reconciliation | **UNVERIFIED (external)** | No authorised Google credential was supplied |
| Instagram — OAuth, container, chunked upload, publish, read-back | **UNVERIFIED (external)** | No authorised Meta app, access token or professional account was supplied |

Every one of these paths has **complete automated coverage against a double**, and the code path
that the double stands in for is the same code path the real service would take. What is missing is
the credential, and the credential was never supplied. That is a statement about the environment,
not about the code, and it is the reason the release assessment says *ship with the external
integrations unverified* rather than *ship*.

---

## 9. The M5.1 amendment — the ducking matrix

**2026-11-21.** M5.1 is a post-release increment on the same branch. The branch is untagged and
v0.1.0 is still gated on the reframe golden set, so this report was updated in place rather than
superseded. **The M5 verdict does not change.** What changed is the suite and the matrix.

### What was added

| File | Tests | What it asserts |
|---|---|---|
| `tests/test_ducking_matrix.py` | **8** | The eight-case ducking matrix, each case a **real render** |
| `tests/test_speech_timeline.py` | +4 | The tri-state `ducking_intervals()` helper |
| `tests/test_api.py` | +2 | The API boundary keeps "empty slice" and "no timeline" apart |
| `tests/test_music.py` | +1 | The filter graph for an empty-but-present timeline |

**+15 tests, +1 file.** 1,300 → **1,315** collected, all passing, zero xfail.

### How the matrix is measured

Each case renders the same clip **twice** — once with the ducking on and once with it off — and
measures the bed's **own frequency band** in a window of each. The bed sits at 440 Hz and the
source's voice at 1000 Hz, so a bandpass at 440 Hz reads the bed on its own, and the ratio of the
two renders is the ducking as a number. A level measurement alone could not tell the bed from the
voice; the difference between two renders can.

The thresholds are deliberately **loose about depth and tight about shape**: a ducked window must
be at least 6 dB down (against a configured 12 dB), and an un-ducked window must be within 0.26 dB
of full level. What matters is *which* windows are ducked, not the exact number of decibels.

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

### The defect it found, and the guard

Seven of the eight passed first time. The **no-speech** case failed, and it found a real defect:
an empty speech timeline was indistinguishable from no timeline at all, so a clip with no talking
fell back to keying the ducking on the audio and the music was pulled down by whatever else the
source contained. It was fixed by making the answer tri-state — `None` (no timeline), `[]` (a
timeline that found no speech in this clip), and the speech itself — with
`speech_timeline.ducking_intervals()` as the one way to produce it.

**The guard was proven.** With the four product files reverted to the pre-M5.1 code,
`test_no_speech_means_no_ducking` fails at a ratio of **0.915** against a flat render, and the
other seven still pass. The files were restored afterwards.

The measured impact of the defect was small — **≤ 0.9 dB** on a source carrying its own loud
music — but the contract was violated at the API boundary, and the webcam layout already treated
an empty timeline as "no emphasis" without falling back. **It was fixed rather than documented
away.**

---

## 10. The M5.2 amendment — the real four-hour recording

**2026-11-21.** M5.2 is a second post-release increment on the same branch. The branch is still
untagged and v0.1.0 is still gated on the reframe golden set, so this report was updated in place
rather than superseded. **The M5 verdict does not change.** What changed is the suite and the
evidence base.

### What was run

The application was pointed at a **real four-hour YouTube live recording** and run through the
**real ingest path**. The full details are in `docs/M5-APPLICATION-TESTING.md` §M5.2 and
`docs/FINAL_UPGRADE_REPORT.md` §4.4; the regression-relevant facts are:

| | |
|---|---|
| The source | A real 4:00:10 live recording, 2560×1440p60, Hindi, published by a third-party creator |
| The ingest | The complete file, **twice** — at 360p and at the product's default 1080p |
| The pipeline | A **real 180 s segment cut from that same downloaded file**, through every stage, with a **real local model** (`llama3.1:8b` over Ollama) and a **real local transcription** (whisper `small`, `int8`) |
| The output | Two real clips and two real exports, with `.srt` sidecars in Devanagari |
| The full four-hour pipeline | **Not run** — transcription measured at ~7 minutes per 180 s, so ~9.6 hours of it and ~25 hours for the whole pipeline, on this machine. Recorded as **NOT APPLICABLE** with the measurement attached |

### What it found

Four product defects, each fixed and each guarded by a test that fails without the fix. The
guards and the counts are in §2 and §6; the full evidence is in §4.2 of the final report.

| # | Defect | Guard |
|---|---|---|
| 5 | The configured yt-dlp format was **dead** — the download hard-coded `bestvideo*+bestaudio/best`, so a four-hour stream came down at 1440p60 — **12.54 GiB** | 3 tests; **2 fail without the fix** |
| 6 | The yt-dlp download was authorised but **never written to the transfer log**, so `EGRESS-INVENTORY.md` E11's claim that it is *logged* was false | 1 test; **fails without the fix** |
| 7 | The crop-safety diagnostic compared a **per-clip** crop against the **whole-source webcam region** and called it *"the detected face"* | 7 tests; the time-matching one **fails without the fix** |
| 8 | The URL policy refused **any** host whose two DNS answers were not the same set, so `graph.facebook.com` — a load-balanced host — was treated as a DNS-rebinding attack and the publish was refused | 2 tests **fail without the fix**; 3 assert the protection still holds |

### The gate that found the last one

Defect 8 was found by the **full-suite gate**, as a **flaky failure**: **1,324 passed, 1 failed**,
in a test that passes when run alone. It was not a flake. The URL policy resolves twice on
purpose, and the Instagram publishing test stubbed `httpx` but not the resolver — so a unit test
was reaching the **real DNS**, and `graph.facebook.com` answers with a rotating subset of its own
edge addresses. Both answers were **public**; the refusal bought no security and broke the
feature.

**The test was wrong as well as the product**, and both were fixed: the guard now compares the
**class** of the two answers, and the whole unit suite now resolves **no** real hostname. A unit
test must not depend on the internet, or on which addresses a third party happens to be serving.

### The gates, re-run

| Gate | Result at `a907805` |
|---|---|
| `ruff check .` | *All checks passed* |
| `ruff format --check .` | *227 files already formatted* |
| `mypy backend/autoclip` | **10 errors in 8 files** — the M1 baseline, unchanged |
| Whole suite, Windows (ffmpeg 9.0.2) | **1,330 passed**, 0 failed, 0 skipped, 0 xfailed, 499.52 s |
| Unit selection, Linux (ffmpeg 7.0.2) | **1,285 passed**, 69 deselected |
| ffmpeg-sensitive selection, Linux (ffmpeg 7.0.2) | **212 passed**, 193.04 s — the ducking matrix's real renders included |
| CI | **Run 29 green on all six jobs** |

---

## 11. The M5.3 amendment — the complete ten-minute pipeline

**Run 2026-11-21, documented 2026-11-22.** M5.3 is a third post-release increment on the same
branch. The branch is still untagged and v0.1.0 is still gated on the reframe golden set, so this
report was updated in place rather than superseded. **The M5 verdict does not change.** What changed
is the suite, the defect count and the evidence base.

### What was run

The application was pointed at a **real ten-minute YouTube video** and run through **every stage,
end to end** — which is what §7's *four-hour pipeline* limitation said was missing. The full
details are in `docs/M5-APPLICATION-TESTING.md` §M5.3 (AT-F-01 … AT-F-15) and
`docs/FINAL_UPGRADE_REPORT.md` §4.5; the regression-relevant facts are:

| | |
|---|---|
| The source | A real 10:19 Hindi podcast, 1920×1080 AV01, published by a third-party creator |
| The ingest | The complete file — **140,602,318 B in 64.55 s**, at format 399+140 |
| The pipeline | The **whole source**, through every stage, with a **real local model** (`llama3.1:8b` over Ollama) and a **real local transcription** (whisper `small`, `int8`) — **1,128 words** |
| The output | **Three** real clips and **three** real exports, each with a `.srt` sidecar in Devanagari |
| The model's own part | **Seven** local calls: the highlight stage's **two sequential windows** per job (a 619 s source is two 480 s windows with a 60 s overlap, and a local model runs them one at a time) plus creative planning. **Job 1's plan validated on the first call; job 2's did not** — its plan and its schema-repair retry both failed, so the plan fell back with the reason recorded, and the later resume found the budget spent. The clips' **titles, hooks, reasons and scores are the highlight stage's**; what fell back was the **plan's** layout, crop, caption, music and ducking choices |
| The full four-hour pipeline | **Still not run** — ~25 hours for the whole pipeline on this machine. A complete *ten-minute* source was run instead, and that is what the end-to-end claim rests on |

### What it found

**Five** product defects, each fixed and each guarded by a test that fails without the fix. The
first four were found by the **real run**; the fifth was found by the **Linux leg**, on the CI's
platform.

| # | Defect | Guard |
|---|---|---|
| 9 | The sentence and clause terminators were **Latin-only**, so a Devanagari transcript had almost no sentence boundaries in it — and the clip-edge rule then *silently dropped* every candidate that fell short of the minimum duration | 65 tests across `tests/test_transcript.py` (new) and `tests/test_boundaries.py`; **33 fail without the fix** |
| 10 | The export's ffmpeg command line could exceed **Windows' own 32,767-character limit**, and the job died with a misleading *"filename or extension is too long"* | 7 tests fail without the export fix (6 in the new `tests/test_export_graph.py`, plus the behavioural render test); 4 more fail without the command-line guard |
| 11 | The webcam's speech emphasis was evaluated against a **segment-local** clock, so the webcam only ever magnified in the **first** segment of a clip | `tests/test_export_render.py::TestLayoutRender::test_the_speech_emphasis_renders_in_a_later_stretch` — a **behavioural** render; **fails without the fix** |
| 12 | A caption could be held on screen for **twelve seconds**, because the caption inherited the recogniser's word timing rather than bounding its own lifetime | 8 tests in `tests/test_captions.py::TestCaptionLifetime` and 2 in `tests/test_diagnostics.py`; **8 fail without the fix** |
| 13 | The export's **video** graph consumed a filter output **once per crop segment** — invalid, because a filter output may be consumed only once. ffmpeg **9** tolerates it; ffmpeg **7** refuses it | 4 tests in `tests/test_export_graph.py::TestGraphShape`; **3 fail without the fix**. The structural graph check moves to `tests/graph_shape.py` and is now applied to the **video** graph as well as the music graph |

### The guards were proven by reverting the fix

Every claim in that table was checked by **reverting the product code to `HEAD` and running the
guard against it**, then restoring the fix:

| Reverted | Result | Restored |
|---|---|---|
| `transcript.py` + `boundaries.py` | **33 failed**, 32 passed (of 65) | **65 passed** |
| `export.py` | **7 failed** (6 graph + the emphasis render) | **7 passed** |
| `ffmpeg.py` | **4 failed** (`AttributeError` — the guard does not exist) | **37 passed** |
| `captions.py` + `diagnostics.py` | **8 failed**, 70 passed (of 78) | **78 passed** |
| `export.py` (the defect-13 fix) | **3 failed** in `tests/test_export_graph.py::TestGraphShape` | **38 passed** with `tests/test_music.py`; **41 passed** with `tests/test_export_render.py` |

A guard that was never seen failing is a guard that might never fire. These were all seen failing.

### The fifth defect, and why it needed a second platform

Defect 13 is the **same class** as defect 3 — a filter output consumed twice — and it was found by
the **same** leg. ffmpeg 9.0.2 accepted the graph; ffmpeg 7.0.2 refused it with *"Invalid stream
specifier: gsrc"*. The developer's machine agreed with the developer's ffmpeg, so it rendered
there and nowhere else.

The structural check for this class of defect was **already in the tree** — it was the fix for
defect 3 — but it only ever looked at the **music** graph. The video graph was never checked, so
nothing in the suite could see this. The check now lives in `tests/graph_shape.py` and covers
**both** graphs. It also caught a **label collision** in the first version of the fix, before any
render: the split's outputs and the trims' outputs were both named `ws{index}`. A parser catches
that; a render on one ffmpeg does not.

### The guards were proven by reverting the fix

Every claim in that table was checked by **reverting the product code to `HEAD` and running the
guard against it**, then restoring the fix:

| Reverted | Result | Restored |
|---|---|---|
| `transcript.py` + `boundaries.py` | **33 failed**, 32 passed (of 65) | **65 passed** |
| `export.py` | **7 failed** (6 graph + the emphasis render) | **7 passed** |
| `ffmpeg.py` | **4 failed** (`AttributeError` — the guard does not exist) | **37 passed** |
| `captions.py` + `diagnostics.py` | **8 failed**, 70 passed (of 78) | **78 passed** |

A guard that was never seen failing is a guard that might never fire. These were all seen failing.

### Two things this increment deliberately does **not** claim

1. **The clip counts are not comparable across runs.** The detection stage runs at
   `DetectionConfig.temperature = 0.3`, so the before-run and the re-run saw **different candidate
   sets** and proposed **different titles**. The raw *"1 clip before, 3 clips after"* comparison is
   **not** a controlled measurement of the fix and is not offered as one. The controlled comparison
   is the **same ten candidates** refined by the old rule and the new rule — **2 kept against 6** —
   plus an offline sweep over **1,130** candidate ranges from the real transcript: the old rule
   kept **852**, the new one keeps **1,070**.
2. **The black-frame failure is not a pipeline defect.** `ffmpeg blackdetect` on the **raw source**
   finds the same **1.835 s** black stretch the export carries. The diagnostic is a **true positive
   about the source**, and changing it would have made the diagnostic lie.

### The gates, re-run

| Gate | Result at the M5.3 tree |
|---|---|
| `ruff check .` | *All checks passed* |
| `ruff format --check .` | *230 files already formatted* |
| `mypy backend/autoclip` | **10 errors in 8 files** — the M1 baseline, **unchanged**, and checked against a clean worktree at `HEAD` to be certain that none of the ten is new |
| Whole suite, Windows (ffmpeg 9.0.2) | **1,397 passed**, 0 failed, 0 skipped, 0 xfailed, 454.05 s |
| Unit selection, Windows (ffmpeg 9.0.2) | **1,351 passed**, 70 deselected, 230.28 s |
| Render selection, Windows (ffmpeg 9.0.2) | **46 passed**, 1,375 deselected, 231.92 s |
| Feature matrix | **129 rows, consistent** — 110 Implemented · 9 Partial · 1 Blocked · 9 Not Applicable · 0 Missing |
| Linux leg (ffmpeg 7.0.2) | **267 passed** in the ffmpeg-sensitive selection, **1,351 passed / 70 deselected** in the unit selection, ruff clean — reproduced from the committed tree. See `docs/M5-PERFORMANCE-REPORT.md` §8 |
