# AutoClip — Performance Report (M5)

**Measured:** 2026-11-20, on `feature/upgrade-u0-u10` at `4cf309b`.
**Reference hardware:** Intel Core i5-8279U, 4 cores / 8 threads, 7.8 GB RAM, Intel Iris Plus 655
(no CUDA — every GPU-accelerated path runs on CPU here), Windows, Python 3.11.16, FFmpeg 9.0.2,
Node 24.21.0.
**Machine-readable:** `docs/BENCHMARK-BASELINE.json` (the M0 baseline, untouched) and
`docs/BENCHMARK-M5.json` (this measurement).
**Reproduce:** `.venv\Scripts\python.exe scripts\bench_baseline.py`

---

## 1. Headline

| | |
|---|---|
| **New runtime dependencies** | **Zero.** The whole M0.5 → M5 upgrade was built on the dependency set the project already had. The only `pyproject.toml` change is the dev-tool pin `ruff==0.17.5`. |
| **Encoder output** | **Byte-identical.** The 5 s 1080×1920 reference encode is 3,691,703 bytes at both M0 and M5 — the same number, to the byte. The encoder did not change. |
| **Migration cost** | +13 migrations, **+0.5%** on a fresh migrate (239.47 ms → 240.61 ms). |
| **Cold import** | **Slower.** 93 → 132 `autoclip` modules; the controlled same-session comparison is 1,462 ms → 2,400 ms median. This is a one-time server-start cost and it is explained in §3. |
| **Suite wall clock** | 193.77 s for 672 tests at M0 → 270.59 s for 1,263 tests at M5 → **499.52 s for 1,330 tests at M5.2**. Per test, the M5 unit selection went **0.288 s → 0.214 s** — the suite got *faster per test* while nearly doubling in size. **No speed-up is claimed at M5.2**: the whole-suite number moved by machine load, not by code. |

**Nothing in this report is a claim of improvement that was not measured.** Where a number moved the
wrong way, it is reported the wrong way.

---

## 2. Deterministic measurements, M0 → M5

The same script, the same machine, the same reference inputs.

| Measurement | M0 min | M0 median | M0 max | M5 min | M5 median | M5 max | Δ median |
|---|---|---|---|---|---|---|---|
| Cold import `autoclip.app` | 698 | **755** | 2,283 | 1,029 | **1,053** | 3,474 | **+40%** |
| Cold import `autoclip.pipeline.runner` | 102 | **110** | 144 | 142 | **194** | 268 | **+76%** |
| Open existing DB + `PRAGMA user_version` | 2.19 | **2.72** | 31.75 | 2.40 | **3.00** | 13.57 | +10% |
| `store.list_jobs()` | 1.18 | **1.43** | 4.81 | 0.32 | **0.34** | 3.77 | −76% |
| Fresh DB, **all** migrations | 225 | **239** | 285 | 240 | **241** | 253 | **+0.5%** |
| Build music/ducking filtergraph | 0.02 | **0.02** | 0.08 | 0.01 | **0.02** | 0.07 | — |
| Encode 5 s 1080×1920 (veryfast, CRF 23, + AAC) | 1,314 | **1,518** | 1,541 | 1,192 | **2,045** | 2,338 | +35% |

Two of these need a word of explanation, and one needs a correction.

**`store.list_jobs()` is not a speed-up.** The M0 measurement ran against a populated database; the
M5 measurement ran against a scratch database with no jobs in it. A 76% "improvement" that is
really an empty table is not an improvement, and it is not counted as one. The honest reading is
**unchanged**.

**The encode number is machine noise, and it is reported as such.** The M5 *minimum* (1,192 ms) is
**faster** than the M0 minimum (1,314 ms), which is what a real speed-up would look like. The
median moved the other way because the machine was carrying background load (OneDrive, antivirus,
and a test run finishing) during the M5 measurement. The deterministic evidence that the encoder did
not change is the output size: **3,691,703 bytes at both ends**, exactly.

**The fresh-migrate number is the one that matters most for the upgrade.** Thirteen new migrations
— including three SQLite table rebuilds — cost **1.14 ms** in total. A v14 database migrating to
v27 is not a slow operation.

### Suite-level measurement

| | M0 | M5 | M5.1 |
|---|---|---|---|
| Mandatory suite (CI selection 1) | 672 passed in 193.77 s | **1,263 passed, 61 deselected in 270.59 s** | **1,270 passed, 69 deselected in 249.81 s** |
| Render suite (CI selection 2) | (not separated) | **37 passed, 1,287 deselected in 232.47 s** | **45 passed, 1,294 deselected in 299.24 s** |
| Whole suite, one invocation | 672 passed in 193.77 s | **1,300 passed in 709.11 s** | **1,315 passed in 534.88 s** |
| Wall clock **per test** | 0.288 s | **0.214 s** | **0.197 s** |

The suite grew by 643 tests (96%) and the per-test cost went *down* by 32%. The M5 whole-suite
number is roughly double the sum of the two CI selections because a single invocation pays the
import and model-load cost once and then re-runs the slow tests in the same process; CI's split is
the figure to compare against.

**The M5.1 column, against the M5 column.** M5.1 added 15 tests, eight of which are **real
renders** — each case renders the same clip twice and measures the bed's own frequency band. That
is why the render selection's wall clock rose by **28%** for **8 more tests**: the eight-case
ducking matrix is the most expensive thing in the render selection, because each case is two
ffmpeg encodes plus four band-limited measurements. The unit selection got *faster* per test
(0.214 s → 0.197 s) because the seven tests it gained are ordinary unit tests, and the machine was
otherwise idle.

**The same two selections were also run on Linux** — WSL, ffmpeg 7.0.2, Python 3.12.16, the same
Python as the Ubuntu py3.12 leg — because the CI runners are Linux and one of the defects found
at M5 renders on Windows and fails on Linux. The counts are identical (**1,263** and **37**); the
Linux wall clock is higher (315.39 s and 267.42 s) because the two legs shared the machine with
each other.

**The M5.1 tree was reproduced on Linux too**, before it was pushed. The counts are identical
again — **1,270** in the unit selection (51.35 s) and **45** in the render selection (176.73 s) —
and `ruff check` and `ruff format --check` are clean on both platforms. The Linux wall clock is
*lower* than the Windows one here, because the two legs were not sharing the machine with each
other this time.

---

## 3. The cold import regression, explained

This is the one number that moved against the upgrade, so it gets a full explanation rather than a
footnote.

### What was measured

The M0 baseline was taken on the pre-upgrade tree. To compare like with like, the base commit
(`bf76811`) was checked out into a separate worktree and **both** trees were measured in the same
session, on the same machine, in three fresh interpreters each:

| Tree | Samples | Median | Min | `autoclip` modules loaded |
|---|---|---|---|---|
| Base `bf76811` | 2,997 / 1,460 / 1,462 ms | **1,462 ms** | 1,460 ms | **93** |
| M5 `4cf309b` | 1,870 / 2,400 / 5,753 ms | **2,400 ms** | 1,870 ms | **132** |

**+39 modules, +938 ms median.** The variance is large on this machine — the fastest M5 sample
(1,870 ms) is faster than the slowest base sample (2,997 ms) — so the exact figure is uncertain.
The *direction* is not: the M5 tree loads more code and takes longer to load it.

### Where the time goes

`-X importtime` on the M5 tree:

| Contributor | Cumulative | Note |
|---|---|---|
| `fastapi` | 652 ms | third-party, pre-existing |
| `httpx` | 219 ms | third-party, pre-existing |
| `numpy` | 174 ms | third-party, pre-existing |
| `autoclip.api` (all 21 routers) | 1,123 ms | **the growth** |
| The heaviest single router, `autoclip.api.music` | 30 ms self | pydantic model construction |
| The heaviest single autoclip module, `autoclip.app` | 129 ms self | module body |

The growth is **not** a new heavy dependency. It is FastAPI building route objects and pydantic
models for **21 routers instead of 18**, plus the new `instagram` package (8 modules), the
`security` package (3), the `music` package (6) and the M3 modules (`budget`, `creative`,
`diagnostics`, `intent`, `formats`, `preferences`).

### Why it was not "fixed"

1. **It is paid once per server start**, not per request and not per clip. A request handler never
   pays it.
2. **The fix is a restructuring**, not a tweak: making the routers lazy means the first request to
   each route pays its import instead. That trades a one-off startup cost for a per-route first-hit
   cost across 21 routers, and it touches every route decorator in the tree.
3. **The risk/benefit is poor this late.** M5 is the release milestone. A change of that shape, in
   the code that every request depends on, is a poor trade against roughly one second of server
   startup.

**It is recorded as a known regression**, not as a rounding error. §4 lists it as a known
limitation, and the release assessment carries it.

---

## 4. Known performance limitations

| # | Limitation | Effect | Status |
|---|---|---|---|
| P1 | The cold import is ~40% slower than at M0 (93 → 132 modules; ~1.5 s → ~2.4 s on this machine) | One-off server-start cost | Open, explained in §3. Not a runtime path. |
| P2 | The `store.list_jobs()` comparison is against a different dataset | The number is not comparable | Corrected in §2; no claim is made. |
| P3 | The encode median moved +35% while the minimum moved −9% | Machine noise | Reported as noise; the byte-identical output is the deterministic evidence. |
| P4 | Peak memory, CPU and GPU during a real render were not sampled | Unknown | Open. |
| P5 | AI latency was not measured | Unknown | Needs an authorised provider — Lane B. |
| P6 | yt-dlp import time was not measured | Unknown | Needs the network — Lane B. |
| P7 | Transcription time on real media was not measured against a pre-upgrade baseline | Unknown | The M5 Lane C run measures it once; there is no M0 counterpart to compare it with. |

---

## 5. What the specification actually asked for

The M0–M5 specification sets **no numeric performance targets**. What it requires (Part 11.3) is
that a baseline exists before optimisation and that no speed claim is made without a comparable
measurement. Both are satisfied:

- A baseline exists (`docs/BENCHMARK-BASELINE.json`, 2026-11-19) and it is **still in the tree,
  unmodified**.
- This report makes no speed claim. The one number that improved (`list_jobs`) was corrected to
  "unchanged" because the measurement was not comparable, and the one number that regressed
  (the cold import) is reported as a regression.

The targets in the superseded U0–U10 document are not carried forward, for the reason recorded in
`docs/performance-baseline.md`.

The **in-scope** requirements the baseline has to serve are these, and each is answered:

| Requirement | Answer |
|---|---|
| Long media work must not run in an HTTP handler | **Satisfied.** Every stage runs on the job queue. The M5 work added no synchronous media work to a handler; the Instagram publisher's polling loop is on its own worker, and the YouTube resumable upload is chunked on the upload worker. |
| A blocked upload must not delay another lane | **Satisfied, and strengthened.** M4b gave Instagram its **own** worker and its own tables. A YouTube upload waiting on a quota reset cannot delay an Instagram post, and the reverse is also true. |
| Rendering must remain within the resource ceilings the monitor reports | **Satisfied.** `max_parallel_ffmpeg` is unchanged, the Instagram chunked upload is 8 MiB at a time rather than one large body, and the resource monitor still accounts for ffmpeg time and disk. |
| The AI call budget must be enforced | **Satisfied and measured.** The budget is 1 planning call + 1 repair + ≤1 music call per clip, capped at `max_clips` — **12 calls at the default of 10 clips** — and the counters persist across job retries. This is a *cost* ceiling rather than a latency one, and it is the reason the M5 upgrade adds no unbounded AI surface. |

---

## 6. Lane C — real media

The deterministic measurements above deliberately avoid real media, because real media is not
repeatable. The real-media evidence is the Lane C run, and it is recorded in
`docs/M5-APPLICATION-TESTING.md` with the timings it produced:

- a full pipeline run on a real 180 s 1080×1920 source with real speech and a real face;
- the transcript's word timings, the detected webcam region and the composed layout;
- the rendered export inspected with `ffprobe` and with an MP4 box walk.

That run is a **technical acceptance** run. The source is a third-party recording with no rights
confirmation, so nothing produced from it is published anywhere.

---

## 7. The M5.2 amendment — real media, measured

**2026-11-21.** M5.2 pointed the application at a **real four-hour YouTube live recording** and ran
it through the **real ingest path**. That produced the first real-media timings in this project,
and two of them change what is known.

### What was measured

| Measurement | Value | Note |
|---|---|---|
| **Download, 360p** | **684,877,097 B in ~1 min** | ≈ **3.5 MB/s** on this machine's connection |
| **Download, 360p muxed** | **844,513,587 B in 175.578 s** | The duration recorded in the transfer log — ≈ **4.8 MB/s** |
| **Download, 1080p (the product default)** | **5,529,989,793 B** (5.52 GB) | The whole four-hour file. **This is the number that exposed defect 5** — the configured 1080p cap was dead, and the download was 12.54 GiB at 1440p60 before the fix |
| **Transcription, 180 s of real Hindi speech** | **432 s** | whisper `small`, `compute_type=int8`, CPU only. ≈ **2.4× real time** |
| **Highlight detection, 180 s** | **342 s** | Real local model (`llama3.1:8b` over Ollama) |
| **Creative planning** | **242 s** | The same model, with the schema repair retry |
| **Reframe** | **20 s** | MediaPipe face tracking over the segment |
| **Export** | **90 s** | Two real 1080×1920 exports, with burnt captions |
| **The whole segment pipeline** | **1,136 s** (19 min) | For 180 s of source. **≈ 6.3× real time** |

### The number that decides what was and was not run

**Transcription measured at ~432 s per 180 s of speech.** The full four-hour recording is
**14,410 s**, so the transcription alone would have taken roughly **9.6 hours** on this four-core
laptop; the highlight stage, which costs **342 s per 180 s** of speech, would have added about
**7.6 hours** of its own; and the whole segment pipeline — **1,136 s per 180 s** — would have taken
roughly **25 hours**.

> **Correction, found while documenting M5.3 (2026-11-22).** This paragraph originally read
> *"roughly **16 hours** of transcription alone"*. That figure does **not** reproduce from the
> rates measured in the table above: 14,410 s ÷ 180 s × 432 s is **9.6 hours**, not 16. **17.2
> hours** is the transcription **plus** the highlight stage, and the **whole** pipeline is **≈25
> hours** — which is the figure that matches the measured segment rate of 1,136 s per 180 s. The
> number was therefore most likely the transcription-and-highlight total, mislabelled as
> transcription alone. **The conclusion does not change — the four-hour pipeline was still not
> run, and it was still impractical — but the arithmetic is now right, and it makes the reason
> stronger rather than weaker.**

That is why the **ingest path** was exercised on the **complete** file (twice) and the **pipeline**
was exercised on **real segments cut from that same downloaded file**. It is a measured constraint,
not a shortcut, and it is recorded as **NOT APPLICABLE** in the evidence table with the arithmetic
attached.

### What it changes in this report

- **P7 is now partly answered.** Transcription time on real media was **not** measured against a
  pre-upgrade baseline — that half still stands, because there is no M0 counterpart to compare it
  with. But the absolute figure is now known: **432 s per 180 s** on CPU, and **1,136 s** for a
  180 s segment end to end.
- **P6 is now partly answered.** yt-dlp's **download** time was measured twice (**175.578 s** for
  844 MB, ≈ 3.5–4.8 MB/s). Its *import* time — the metadata and manifest fetches — was not
  measured separately, so P6 stays open.
- **P4 is still open.** Peak memory, CPU and GPU during a real render were not sampled. The M5.2
  run was long and real, but it was not instrumented for resources.

### The suite, at M5.2

| | M0 | M5 | M5.1 | M5.2 |
|---|---|---|---|---|
| Mandatory suite (CI selection 1) | 672 passed in 193.77 s | **1,263 passed, 61 deselected in 270.59 s** | **1,270 passed, 69 deselected in 249.81 s** | **1,285 passed, 69 deselected** |
| Render suite (CI selection 2) | (not separated) | **37 passed, 1,287 deselected in 232.47 s** | **45 passed, 1,294 deselected in 299.24 s** | **45 passed, 1,309 deselected** |
| Whole suite, one invocation | 672 passed in 193.77 s | **1,300 passed in 709.11 s** | **1,315 passed in 534.88 s** | **1,330 passed in 499.52 s** |

**The M5.2 whole-suite number is the fastest of the three** — **499.52 s** for 1,330 tests — but
that is **machine load, not a speed-up**: the run was made with the two application instances
still running, and the wall clock of a shared four-core machine moves by tens of seconds for
reasons that have nothing to do with the code. The honest reading is **unchanged per test**, and
no claim of improvement is made.

### The Linux leg, re-run at M5.2

The Linux leg was reproduced from the **exact committed tree** (`git archive` of `a907805`), on
**ffmpeg 7.0.2** — the version that exposed defect 3 — with the `ass` filter confirmed present
before the renders ran:

| Selection | Result |
|---|---|
| Unit selection, Linux | **1,285 passed**, 69 deselected, 48.05 s |
| ffmpeg-sensitive selection, Linux | **212 passed**, 193.04 s — the ducking matrix's real renders included |

The Windows numbers for the same selections are identical. **A fix that only renders on the
developer's machine is not a fix**, and this is the leg that proves the opposite.

---

## 8. The M5.3 amendment — a complete source, measured

**Run 2026-11-21, documented 2026-11-22.** M5.3 pointed the application at a **real ten-minute
YouTube video** and ran it through **every stage, end to end**. That is the first run in this
project whose timing figures cover a **whole source**, and two of them change what is known.

### What was measured

| Measurement | Value | Note |
|---|---|---|
| **Download** | **140,602,318 B in 64.55 s** | ≈ **2.18 MB/s** on this machine's connection. Format **399+140** (1920×1080 AV01 + AAC @ 129.482 kbps) |
| **Transcription, 619 s of real Hindi speech** | **1,346 s** | whisper `small`, `compute_type=int8`, CPU only. ≈ **2.17× real time** |
| **Highlight detection** | **425.1 s** (job 1) · **656.8 s** (job 2) | **Two sequential windows** per job — `WINDOW_S = 480 s`, `OVERLAP_S = 60 s` — and a local model runs them **one at a time** (`LOCAL_CONCURRENCY = 1`). Job 1: 174.8 s + 250.3 s. Job 2: 152.5 s + 504.3 s |
| **Creative planning** | **98.2 s** (job 1) · **245.3 s** (job 2) | The same model. Job 1: **one** call, validated first try. Job 2: **two** calls — the plan and its schema-repair retry, 148.7 s + 96.6 s — and **neither validated** |
| **The export, re-rendered** | **176.3 s** for job 2's three clips | 1080×1920, burnt captions, `.srt` sidecars. Output: 31.30 s, 40.27 s and 33.37 s. Its ffmpeg time alone was **140.3 s over 3 runs** |
| **The tail — reframe, captions, export, diagnostics** | **1,274 s** (job 1) | The interval from the end of the creative plan to the job's `finished_at`. The **export's own ffmpeg time** is recorded separately: **82.5 s over 3 runs** for job 1's single clip, **140.3 s over 3 runs** for job 2's three. The split **inside** this tail — the MediaPipe face tracking, the caption pass, the ten diagnostics — was **not instrumented**, so it is given as the interval it is rather than dressed up as per-stage figures. The **first-use** `face_landmarker.task` download (**3.6 MB**) falls in this tail too — the transfer log puts it after the creative-planning call and before job 2's first highlight call |
| **The complete pipeline — job 1** | **3,746 s (62.4 min)** for 619 s of source | ≈ **6.05× real time**, measured as the job's own `started_at → finished_at`. Job 2's wall clock is **not** a pipeline measurement — it was interrupted and resumed twice — and it was **slower at the model stages** anyway (656.8 s of highlight detection against job 1's 425.1 s), because the local model is stochastic |

> **The earlier "≈ 40 min / 3.9× real time" figure is withdrawn.** It was computed from a highlight
> timing that counted **one** window per job, when the stage makes **two**. The corrected total is
> the job's own wall clock, and it is **62.4 minutes**. A number that was wrong because its input
> was wrong is not a number to keep with a footnote attached.

### The second job's creative plan fell back to the defaults

This is the one figure in the table above that would otherwise be misleading, so it is stated on
its own rather than buried in a footnote.

**The two jobs are not equivalent, and their creative plans came out differently.**

| | Job 1 — `1075820ea45841fe` | Job 2 — `f4648116d6ba49e4` |
|---|---|---|
| Highlight stage | 2 calls, **425.1 s** | 2 calls, **656.8 s** |
| Creative-planning calls | **1** — 98.2 s | **2** — 148.7 s + 96.6 s = **245.3 s** |
| Did the plan validate? | **Yes, first try** | **No** — neither the plan nor its schema-repair retry |
| The stored plan | `source='ai'`, `problems=[]` | `source='fallback'`, `problems=['the creative-planning budget was spent']` |
| The budget counters | `plan_used=1, repair_used=0` | `plan_used=1, repair_used=1` |
| What the plan chose | `caption_strategy='clean_lower'`, `ducking_db=-12.0` | `caption_strategy=''`, `ducking_db=0.0`, `reason=''` — the deterministic defaults |

**Why the second job's stored plan says "the budget was spent".** The planning budget is
**one plan call and one repair retry per job**, and job 2 spent both: the model answered, the
answer did not match the schema, the repair answer did not match it either, and the plan fell
back. The later **defect-12 resume** then asked for a plan again — and by then the budget was
already spent, so the plan written at **18:02:38** is the fallback, and the database records the
reason rather than pretending the model chose the defaults.

**What this does and does not mean.** It does **not** mean job 2's clips are uninteresting or
unmodeled. The clips' **titles, hooks, reasons and scores are the highlight stage's** — they came
from the model's own candidates in the first place (*"Hook is not strong, but payoff is a
specific and concrete statement."*). What fell back was the **creative plan's** layer: the
layout, crop, caption strategy, music and ducking choices, which took the deterministic defaults.

That distinction is the point, and it is the reason the numbers are recorded per stage rather
than as one "model time" figure. The model's own output — the clips — was real in both jobs; the
model's *plan* was real in one and a fallback in the other.

### What it changes in this report

- **P7 is now partly answered, again.** The transcription figure is now measured on **two**
  different real sources: **432 s per 180 s** at M5.2 (2.4× real time) and **1,346 s per 619 s**
  here (2.17× real time). The two agree closely — which is what makes the **9.6-hour**
  transcription figure for the four-hour recording a measurement rather than a guess. The missing
  half is unchanged: there is still no **M0 counterpart** to compare against, because the
  pre-upgrade pipeline had no equivalent path.
- **The whole-pipeline rate is now measured on a complete source, and it corroborates M5.2's.**
  M5.2 measured the segment pipeline at **1,136 s per 180 s** — **≈6.3× real time**. M5.3 measured
  the whole pipeline on a **complete** source at **3,746 s per 619 s** — **≈6.05× real time**. Two
  different sources, two different measurements, and they land within **4%** of each other. That is
  the corroboration the four-hour arithmetic rests on, and it is stronger than the transcription
  rate alone: it is the **whole** pipeline that scales, and the whole pipeline is what was not run.
- **P6 is now partly answered.** yt-dlp's **download** time was measured on a second real source:
  **64.55 s** for 140.6 MB (≈ 2.18 MB/s). Its *import* time — the metadata and manifest fetches —
  was still not measured separately, so P6 stays open.
- **P4 is still open.** Peak memory, CPU and GPU during a real render were not sampled. The M5.3
  run was long and real, but it was not instrumented for resources.

### The suite, at M5.3

| | M0 | M5 | M5.1 | M5.2 | **M5.3** |
|---|---|---|---|---|---|
| Mandatory suite (CI selection 1) | 672 passed in 193.77 s | **1,263 passed, 61 deselected in 270.59 s** | **1,270 passed, 69 deselected in 249.81 s** | **1,285 passed, 69 deselected** | **1,351 passed, 70 deselected in 230.28 s** |
| Render suite (CI selection 2) | (not separated) | **37 passed, 1,287 deselected in 232.47 s** | **45 passed, 1,294 deselected in 299.24 s** | **45 passed, 1,309 deselected** | **46 passed, 1,375 deselected in 231.92 s** |
| Whole suite, one invocation | 672 passed in 193.77 s | **1,300 passed in 709.11 s** | **1,315 passed in 534.88 s** | **1,330 passed in 499.52 s** | **1,397 passed in 454.05 s** |

**No claim of a speed-up is made.** The whole-suite wall clock moved from **499.52 s** to
**454.05 s** while the suite grew by **67 tests**, and the per-test figure moved from **0.375 s**
to **0.325 s**. Both of those are **machine load, not a speed-up**: this is a shared four-core
laptop, and the wall clock of a shared machine moves by tens of seconds for reasons that have
nothing to do with the code. The honest reading is **unchanged per test**.

### One performance note that belongs here

The M5.3 export fix does **not** change how long a render takes, and it is worth saying so rather
than letting the numbers imply otherwise. The webcam crop and scale are now applied **once**,
after the segment concat, instead of once per segment — so the *filter graph* is **0.33×** of its
former size — but ffmpeg was doing the same total amount of per-frame work either way. What the
fix buys is that the render **completes at all** on Windows, and that the command line fits.

### The Linux leg, re-run at M5.3

The Linux leg was reproduced from the **exact committed tree** (`git archive` of the M5.3 commit),
on **ffmpeg 7.0.2** — the version that exposed defect 3 — with the `ass` filter confirmed present
before the renders ran. The selection now carries the M5.3 guards explicitly: the filter-graph
structure tests, the ffmpeg command-line tests, the caption-lifetime tests and the emphasis
render.

The first run of this leg **failed** — and the failure was a **real product defect**, not a
harness problem. The export's video graph consumed a filter output once per crop segment; ffmpeg 9
tolerates that and ffmpeg 7 refuses it with *"Invalid stream specifier"*. The developer's machine
agreed with the developer's ffmpeg, so it rendered there and nowhere else. That is **defect 13**,
and it is why the leg exists.

After the fix, from the committed tree (`2b5935d`, by `git archive` — what is tested is what is
committed):

| | Result |
|---|---|
| The toolchain | **Python 3.12.16**, **ffmpeg 7.0.2** (static build), `ass` filter confirmed present, the Windows ffmpeg explicitly kept **off** PATH |
| ffmpeg-sensitive selection | **267 passed**, 0 failed, 104.89 s |
| Unit selection (`-m "not slow and not golden and not e2e"`) | **1,351 passed**, 70 deselected, 48.45 s |
| `ruff check .` | *All checks passed* |
| `ruff format --check .` | exit 0 |

The venv lives **outside** the tree, exactly as CI has it. A venv inside the tree puts the venv's
own `activate_this.py` in front of ruff, and it is neither lint-clean nor format-clean — a harness
artefact, not a finding.

