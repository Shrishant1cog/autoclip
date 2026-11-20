# AutoClip — M5 Regression Report

**Run on:** 2026-11-20/21, `feature/upgrade-u0-u10` at `bcdfc47`.
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
| G2 | Format | `ruff format --check .` | *226 files already formatted* | **PASS** |
| G3 | Types | `mypy backend/autoclip` | *Found 10 errors in 8 files (checked 137 source files)* | **BASELINE — unchanged** |
| G4 | Unit suite | `pytest -m "not slow and not golden and not e2e" -q` | **1,263 passed**, 61 deselected, 270.59 s | **PASS** |
| G5 | Render suite | `pytest -m "slow and not golden and not e2e" -q` | **37 passed**, 1,287 deselected, 232.47 s | **PASS** |
| G6 | Frontend | `npm run build` (`tsc -b && vite build`) | 59 modules transformed, built in 2.68 s | **PASS** |
| G7 | Container | `docker build -f docker/Dockerfile --target base .` + `GET /api/health` | **Not runnable locally — Docker is not installed on this machine.** Verified by the CI `docker` job on every push. | **PASS (CI)** |
| G8 | Real media | `AUTOCLIP_E2E_MEDIA=… pytest tests/test_pipeline_e2e.py -q` | See §5 | **PASS** |
| G9 | Whole suite | `pytest tests -q --ignore=tests/test_pipeline_e2e.py` | **1,300 passed**, 0 failed, 0 xfailed, 0 skipped, 709.11 s | **PASS** |

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

| | M0 | M5 | Δ |
|---|---|---|---|
| Test files | 35 | **54** | +19 |
| Test functions in the tree | 648 | **1,229** | +581 |
| Tests collected | 672 (of which 26 were `xfail`) | **1,300** (of which **0** are `xfail`) | **+628** |
| Failing | 0 | **0** | — |
| Skipped | 0 | **0** — the only `pytest.skip` calls in the tree are the e2e media gate, which is deliberate and documented | — |
| `xfail` markers | **26** (the SSRF gap, pre-registered) | **0** | −26 |
| Wall clock, unit selection | 193.77 s (672 tests, one invocation) | **270.59 s** (1,263 tests) | — |
| Wall clock **per test** | 0.288 s | **0.214 s** | **−26%** |

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
| Unit — `-m "not slow and not golden and not e2e"` | **1,263 passed**, 61 deselected | **1,263 passed**, 61 deselected |
| Render — `-m "slow and not golden and not e2e"` | **37 passed**, 1,287 deselected | **37 passed**, 1,287 deselected |
| `ruff check .` | *All checks passed* | *All checks passed* |
| `ruff format --check .` | *226 files already formatted* | *225 files already formatted* (the synced subset) |

**The same tests, the same counts, on both platforms — and one of them only passes on one.** The
sidechain fallback consumed one filter output twice, which ffmpeg 9 accepts and ffmpeg 7 refuses.
It was found by running the Linux leg, and it would have shipped otherwise.

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
Three runs were cancelled for exactly that reason, and that is why they are marked cancelled
rather than failed.

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

**Thirteen of the nineteen runs are green; four were cancelled by a newer push, and two failed.**
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
