# Autonomous Platform Upgrade — Audit & Phase Log

Feature branch: `feature/autonomous-platform`
Baseline (Phase 0 checkpoint): commit `54d6288` on `main`, pushed to `origin/main` before any change.

## Phase 0 — GitHub checkpoint (COMPLETE)

| Item | Value |
|---|---|
| Original commit hash | `54d6288f29268d5fa2ca98ab2dc7890212b13df2` |
| Checkpoint commit hash | `54d6288` (working tree was clean; nothing to checkpoint) |
| Feature branch | `feature/autonomous-platform` (pushed, tracking `origin`) |
| Remote sync | `main` == `origin/main` == branch point; no divergence |
| Working-tree changes preserved | None existed at checkpoint time |
| Sensitive-file audit | No `.env`, `*.db`, media, or credential files tracked (verified via `git ls-files`) |
| Blockers | None |

## Phase 1 — Complete project audit (COMPLETE)

### Baseline test results (pre-change)

- `pytest tests` (excluding `test_pipeline_e2e.py`, which requires `AUTOCLIP_E2E_MEDIA`): **362 passed**, 0 failed.
- Full suite including e2e (run 2026-11-17 with media cut via `scripts/make_e2e_media.py`): **368 passed, 0 skipped**.
- `ruff check backend tests scripts`: clean.
- `npm run typecheck` (frontend): clean.

### Feature inventory

| Feature | Existing status | Required action |
|---|---|---|
| Ingest (YouTube via yt-dlp, file upload) | Functional | Preserve |
| Audio extraction (16 kHz mono PCM WAV) | Functional | Preserve |
| Transcription (faster-whisper local) | Functional | Preserve |
| Transcription (ElevenLabs Scribe, external-first w/ local fallback) | Functional (new, this branch's parent) | Preserve |
| Diarization (WhisperX optional; Scribe `diarize`) | Functional | Preserve |
| LLM highlight detection (Anthropic/OpenAI/Gemini/Ollama) | Functional | Improve (Phase: provider manager) |
| Highlight transient-failure fallback w/ health check | Functional (new) | Preserve |
| Speaker-tracked reframing (MediaPipe + PySceneDetect + One Euro) | Functional | Preserve |
| Caption generation (4 styles, ASS/SRT, libass burn-in) | Functional | Improve (caption correction stage) |
| Export (9:16/1:1/16:9, NVENC probe, loudnorm) | Functional | Preserve |
| Thumbnails (ffmpeg-drawn, title-aware re-render) | Functional | Preserve |
| YouTube OAuth (single account/channel) | Functional | Improve (Phase: multi-account) |
| Auto-upload queue + duplicate guard | Functional | Improve (Phase: multi-channel routing) |
| Metadata generation (model ladder w/ timeouts) | Functional | Preserve |
| Settings/secret management (OS keyring) | Functional | Improve (Phase: multi-key manager) |
| ElevenLabs TTS voiceover (mux, off by default) | Functional | Preserve |
| Job queue, SSE progress, resumable stages | Functional | Extend (workflow engine wraps, not replaces) |
| Batch processing (multi-link paste) | Partial | Implement batch manager |
| Multi Google accounts / channels | Missing | Implement |
| Channel routing / classification | Missing | Implement |
| Analytics + learning engine | Missing | Implement |
| Trending research | Missing | Implement |
| Chatbot | Missing | Implement |
| Workflow builder UI | Missing | Implement |
| Notification centre | Missing | Implement (reuse SSE broker) |
| Unified error records | Partial (job.error only) | Implement |

### Architecture notes (verified, not assumed)

- Backend: FastAPI + SQLite (`backend/autoclip/`), pipeline stages in `pipeline/` with a
  `Stage` enum and resumable artifacts in `~/.autoclip/work/{job_id}/`.
- Providers: `providers/` registry — `PROVIDERS` dict + `build_provider()`; secrets via
  `config.get_secret` (env → keyring → plaintext fallback).
- Speech: `speech/` package — `resolve_engine()` external-first resolution, `SpeechEngine` protocol.
- YouTube: `youtube/` — `oauth.py`, `uploader.py`, `uploads.py`, `queue.py`; single-channel
  assumption baked into `config.YouTubeSettings`.
- Frontend: React 18 + Vite + Tailwind 4 (`frontend/src/`), builds into `backend/autoclip/static/`.
- DB: raw sqlite3 migrations in `db/` (currently v3); no ORM.
- Events: `jobs/events.py` SSE broker — reuse for notifications.

### Phase 0/1 gates

- [x] Checkpoint pushed before code changes
- [x] Feature branch pushed unchanged
- [x] Baseline tests green
- [x] Inventory recorded

## Implementation phases (running log)

Each phase: implement → test → typecheck/build → commit → push. Log updated per phase.

### Phase 3 — Universal AI provider manager (COMPLETE)

- `providers/keypool.py`: multi-key pools per provider — OS keyring entries `<provider>#<label>`
  (first key keeps the legacy bare name), pool metadata in `~/.autoclip/key_pools.json`
  (non-secret). Rotation picks fewest-failures/least-recently-used; auth failures disable a
  key, rate-limits impose a 60s self-recovering cooldown; success resets health.
- `providers/presets.py`: 16 provider presets as data (openai, gemini, anthropic, openrouter,
  groq, cerebras, deepseek, mistral, together, freellmapi, huggingface, nvidia, lmstudio,
  llamacpp, vllm, ollama). OpenAI-compatible vendors share the `openai` adapter; locals need
  no key and sort last in fallback chains; `freellmapi` has deliberately no hardcoded URL.
  Capability registry maps tasks (clip_analysis→json, metadata→text, …).
- `providers/resolver.py`: capability-aware fallback chains, `run_with_fallback`
  (never fabricates — raises `AllProvidersFailedError`), `available_providers` summary.
- `api/ai_providers.py`: `/api/ai/providers`, `/keys` (add/remove/enable), `/presets`,
  `/health`, `/tasks` (task execution over the chain). Wired into `api/__init__.py`.
- Tests: 16 new (`tests/test_ai_providers.py`); suite **396 passed**; ruff + tsc + build clean.
- Live-verified: `/api/ai/providers` returns 16 presets with pool health; legacy single keys
  surface as `primary` automatically; presets endpoint enumerates all 16.

### Phase 4 — Multi Google-account / multi YouTube-channel manager (COMPLETE)

- Migration v5: `google_accounts` + `youtube_channels` (per-channel profile: privacy,
  category, auto_upload, default flag; unique (account, channel) pair; first channel is
  default). Append-only, idempotent.
- `youtube/accounts.py`: account/channel CRUD, per-account keyring refresh tokens
  (`youtube_refresh#<id>`), legacy single-account import (`ensure_legacy_migrated`) that
  runs at startup and claims the legacy token without deleting it.
- `api/youtube_accounts.py`: `/api/youtube/accounts` CRUD + channels + routing endpoints.
  Original single-account endpoints untouched.
- Tests: 13 new (`tests/test_youtube_accounts.py`); suite **409 passed**; ruff + tsc + build
  clean. Live-verified: real `clipsorial` connection auto-migrated as default account/channel,
  token claimed, routing endpoint returns effective upload policy.

### Phase 5 — Intelligent classification & user-defined routing (COMPLETE)

- Migration v6: `content_classifications` (clip → category/confidence/provider/reason,
  latest wins) + `routing_rules` (keyword → target channel, priority-ordered, enable flag).
- `routing/classifier.py`: classification over the provider fallback chain (never raises;
  failures leave the clip unclassified), rules CRUD, `resolve_target_channel` (first enabled
  matching rule wins, else the default channel — preserving pre-routing behaviour).
- Upload path integration: `process_upload` resolves the channel profile and uses its
  privacy/category; routing failures never block publishing.
- `api/routing.py`: categories, rules CRUD + toggle, per-clip classify/target endpoints.
- Tests: 13 new (`tests/test_routing.py`); suite **422 passed**; ruff + tsc + build clean.
- Live-verified over HTTP: categories listed, rule created/toggled/deleted against the real
  clipsorial channel row.

### Phase 6 — Persistent batch queues (COMPLETE)

- Migration v7: `batches` + `batch_items` (ordered, per-item status/error/job link,
  FK cascade from sources; startup recovery resets 'processing' items to 'pending').
- `jobs/batches.py`: CRUD + progress counters; `jobs/batch_runner.py`: event-driven
  runner advancing running batches one item at a time through the existing job queue —
  launch/pause/cancel/retry-failed; failures mark their item and continue.
- Wired into app lifespan (start/stop). `api/batches.py`: full batch lifecycle API.
- Tests: 12 new (`tests/test_batches.py`); suite **434 passed**; ruff + tsc + build clean.
- Live-verified over HTTP: batch create → add real source → detail (item pending with
  source title) → delete. Defect fixed: module-vs-singleton import in app + API.

### Phase 17 — The complete frontend, and a restart you can see (COMPLETE)

Two things were missing at the end of Phase 16: most of the backend had no
screen, and the one automatic behaviour nobody could see was the restart.

**Four pages that were already in the backend but had no frontend.**

The provider manager (Phase 3), the multi-account/multi-channel store
(Phase 10), the routing rules (Phase 5) and the batch queue (Phase 6) had
working endpoints the whole time. The client methods existed for the batch
queue and nothing called them. Now each has a screen:

- **Providers** (`/providers`) — all 16 presets, hosted and local, with the
  state of each key pool: how many keys are usable, which one is cooling
  down, what error it actually hit, and whether the provider is active. Keys
  can be added, removed, disabled and re-enabled; the value never leaves the
  server (the endpoint returns the label and the health, not the secret).
- **Channels** (`/channels`) — every Google account with its token status,
  and every channel under it with its own publishing policy: privacy, YouTube
  category, title suffix, whether it publishes automatically, and whether it
  is the default. A channel with automatic publishing off is never published
  to by a fan-out, so this switch is load-bearing, not decoration.
- **Routing** (`/routing`) — the ten categories the classifier assigns, and
  the rules that map a category to a channel. Rules can be created, edited,
  toggled and deleted. A rule whose target channel does not exist is refused
  by the server (404), not stored as one that can never fire.
- **Batches** (`/batches`) — the full lifecycle: create, add videos, run,
  pause, cancel, retry the failed ones, delete. Each item carries its own
  status and its own real error. The page polls only while a batch is
  actually running — a batch that is merely queued does nothing until it is
  launched, so polling it would be traffic for a page that never changes.

**Restart recovery, made visible.**

AutoClip resumes interrupted work on startup. That behaviour existed before
this phase and was correct, but it was invisible: the job simply carried on,
and there was no way to learn that a restart had interrupted it (or that it
had to begin a stage again because the interruption landed mid-stage).

- Migration **v12** adds `jobs.last_resumed_at`, `youtube_uploads.last_resumed_at`
  and an `app_restarts` table. Verified on a WAL-safe copy of the real
  database: v11 → v12 preserved all 8 sources / 8 jobs / 32 clips / 52 exports
  / 52 uploads / 6 workflows / 1 batch / 32 notifications / 1 account /
  1 channel / 1 job-resource row, foreign-key check clean, re-running is a
  no-op, and the two new columns default to NULL on every existing row.
- The three recovery paths now report what they recovered instead of
  returning a bare count: the job queue returns the ids it requeued, the
  upload queue returns the ids it put back to pending, and the batch runner
  returns the item ids it reset. Each marks the row it recovered.
- The app's lifespan collects those, writes one `app_restarts` row with the
  real counts, and leaves a notification in the inbox. A restart with nothing
  in flight is the normal case and is recorded but not announced.
- `GET /api/restarts` exposes the history; the **Recovery** page now lists
  every restart with what it recovered.

**Verified live, by actually killing the server mid-job.**

A real job (`84cf122f2d9d4f05`) was started on the 56-second local test
video and the server processes were killed while it was in the *transcribe*
stage. The row was left exactly as a crash leaves it — `status = running`,
`last_resumed_at = null`. The server was restarted, and:

- `/api/restarts` reported `jobs_resumed: 1`, `total_resumed: 1`, and the
  exact job id `84cf122f2d9d4f05` — the real row, not an estimate;
- the job carried on (it resumed at *transcribe* and ran to the next stage);
- `jobs.last_resumed_at` was stamped with the restart time;
- the inbox gained "AutoClip restarted — Resumed 1 job that was interrupted."

The earlier restart (before the crash) is also in the history, showing
"nothing was in flight" — the honest answer for a clean start.

**A second, unplanned proof.** Later in the phase the server process died on
its own — no fatal error in its log, no OS-level event, the process simply
gone — while job `2e27f97823df42c8` was transcribing a 68-minute interview.
The next start reported `jobs_resumed: 1` for that job id and the job
resumed. Two of the three restarts in the history are restarts that had real
work to recover; the third — the clean start — says "nothing was in flight".

**Three real defects found and fixed while verifying.**

1. *The schema tests hardcoded the version number.* `test_the_schema_migrates_to_v11`
   asserted `version == 11`, so adding a migration broke a test that had
   nothing to do with migrations — and a version literal has to be edited by
   every later phase, which is exactly how such a test stops meaning
   anything. Both tests now compare against `schema.SCHEMA_VERSION`.
2. *The restart notification disagreed with itself.* "Resumed 1 job that
   were interrupted" — the verb did not agree with the count. The wording
   now agrees, and a test pins both the singular and the plural.
3. *The navigation was squeezed to 150px.* Eleven links do not fit beside the
   logo on a narrow window. The first fix made the nav scroll but left it
   shrinking to whatever space was left (`flex-1` with `min-w-0`) — eight
   links off-screen. Measured: the links need 766px, and beside the logo and
   the status controls they need ~1252px to sit inline, which fits at 1536px
   but not at 1024px. The breakpoint moved from `lg` to `2xl`, and below it
   the nav takes a full-width row of its own and scrolls horizontally.
   Verified at a 613px viewport: the nav is on its own row, the first eight
   links are visible, and scrolling reaches Channels, Routing and Settings.

**Test isolation defect found while writing the API tests.** The new
frontend-API tests read the *real* OS keyring through the legacy
single-account fallback, so a test asserting "this account has no refresh
token" failed on the developer's machine because the developer's YouTube
token was there. The fixture now replaces the keyring, which is what the
suite's own charter (`nothing in the test suite may touch the user's real
~/.autoclip directory or their real OS keyring`) requires.

- Tests: 26 new (`tests/test_restart_recovery.py`) + 29 new
  (`tests/test_frontend_api.py`); suite **658 passed**; ruff + tsc + build
  clean.
- Final system validation report for phases 0–17 written to
  `.planning/VALIDATION-REPORT.md`.

### Phase 17 audit — the job state transitions (COMPLETE)

The last thing the upgrade owed was an audit of the job state machine
itself: every row in `jobs` had to agree with every other row about what
happened to that job. Reading the real database found seven ways it did not.

**How the audit started.** Job `e4a714b3c4c04794` had been *failed* at
16:52:33 and was *cancelled* at 17:28:02 — and its `finished_at` still said
16:52:33. The access log showed what had happened in between: a `POST
/api/jobs/{id}/retry` followed by a `POST /api/jobs/{id}/cancel`, both from
the JobProgress page. The job had failed, been retried, waited behind
another job in the queue, and then been cancelled while it was still
waiting.

**Seven defects, each fixed with a regression test.**

1. *A retry left the previous attempt's finish time behind.*
   `api/jobs.py::retry_job` reset the status, the error and the progress,
   but not `finished_at` — so a queued job claimed it had finished before
   the retry even started. The retry now clears `finished_at` and
   `started_at`: both belonged to the attempt that ended.

2. *Cancelling a queued job never stamped a finish time.* The queue
   cancelled a waiting job with a bare `status="cancelled"`, so the row
   had no finish time at all — indistinguishable from a job still in
   flight. Two rows in the real database had exactly that. The queue now
   stamps `finished_at`.

3. *The cancel request outlived the cancellation.* This was the serious
   one. `JobQueue._cancel_requested` is discarded when a runner finishes —
   but a job cancelled while it was still **queued** never had a runner, so
   its flag stayed set forever. Retrying that job put it back in the
   queue, where the worker cancelled it the instant it started: **a retried
   job could never run.** The queue now has `forget_cancel()`, and the
   retry endpoint calls it — a retry is an explicit instruction to run the
   job again.

4. *A job whose source had gone missing was marked failed without a finish
   time.* The queue's own failure path (`Source not found.`) now stamps one.

5. *A cancelled transcription was reported as a failed job.* This one
   surfaced live: cancelling job `2e27f97823df42c8` mid-transcription left
   it `failed` with the error `Transcription cancelled.` The speech layer
   raised its cancellation as an ordinary engine error, so the runner
   treated it as a failure — and, worse, **fell back to the local Whisper
   engine**, which would have started a second full transcription of a job
   the user had asked to stop. The speech layer now has its own
   `SpeechCancelled` type, and the runner checks it *before* the fallback:
   a cancellation is never a reason to try another engine.

6. *`GET /api/ai/health` answered 500 instead of the provider statuses.*
   The endpoint returned a list of `ProviderStatusOut` models while
   declaring `list[dict]`, so FastAPI rejected the response it had just
   built. The endpoint now declares the model it actually returns.

7. *A server-side response bug was classified as an auth failure.* The
   error classifier reads markers out of the message, and the message
   quoted the provider's own status detail — including `"Incorrect API key
   provided"` and a `401`. So a bug in this app was reported as
   **"check your API key"**, sending the user to fix something that was
   never broken. A `ResponseValidationError` is now classified as
   `internal`/500, before the marker matching — the app's own response
   bug is never the caller's fault.

**Two repair migrations.** Both append-only, both verified against a
WAL-safe copy of the real database (the `.db`, `-wal` and `-shm` together,
after a checkpoint — a copy without the write-ahead log under-counts, and a
migration check that under-counts is worse than none).

- **v13** repairs the rows the old code wrote wrong: a terminal job whose
  `finished_at` was missing or older than its own last write now carries
  that write's time, and a queued or running job never carries a finish
  time. Verified: 218 rows before and after, foreign-key check clean, a
  re-run is a no-op, and exactly the three broken rows changed.
- **v14** repairs the one row the cancellation bug produced: a job whose
  error is exactly `Transcription cancelled.` was a job the user stopped,
  not a job that failed. The error text is the fingerprint — only the
  cancellation path produces it. Verified the same way: 222 rows before and
  after, one row changed, a re-run is a no-op.

**Proved live, against the running app.**

- The queued-cancel path: a job cancelled while it was waiting behind
  another job came back `cancelled` with `finished_at` stamped.
- The retry path: retrying that same job came back `queued` with
  `finished_at` and `started_at` both null, and the queue's cancel flag
  cleared.
- The recovery path: the restart after the second silent death resumed the
  interrupted job and reported `jobs_resumed: 1` for its exact id — the
  third restart in the history with real work to recover.
- The cancellation path: cancelling job `2e27f97823df42c8` mid-transcription
  used to mark it failed; the repaired row now reads `cancelled`, and the
  run that proved it was the first to use the fixed code. Job
  `3ce7a92e38c44e3e` was then cancelled mid-transcription on purpose, and
  came back `cancelled` with `error: None` — the old code produced
  `failed` and "Transcription cancelled.".
- The health path: `GET /api/ai/health` answered **401 with an empty body**
  before the fix. It now answers **200** with the real provider statuses —
  Gemini available, and the rejected OpenAI key reported honestly as a
  detail rather than crashing the endpoint.

**The final green run, end to end.** Job `8c6a0771907c4495` — a 68-minute
interview, Whisper *small*, three clips of 20–60 s, the Gemini provider —
finished in 2 minutes 37 seconds: 3 clips with real titles and scores
(92 / 91 / 91), 3 exports that `ffprobe` confirms are h264 1080×1920
(true 9:16) at 45.2 s / 53.0 s / 24.7 s, and 3 videos published and
confirmed through YouTube's own oEmbed lookup (`m8GFe59Gejw`,
`i_cis9lIUyc`, `vpIg0wnPQE8`). Ten real LLM calls, 102,262 input tokens,
2,195 output tokens; 3 ffmpeg runs and 89.0 seconds of encoding. Gemini
answered three highlight requests with `503 — high demand`; the provider
layer retried and the stage succeeded, with nothing fabricated.

The transcription was not recomputed: the audio and transcript from the
earlier run of the same source with the same model were already in the work
directory, and the pipeline reuses them by design. That is the resume path,
not a way around it.

**The environment, honestly.** The 68-minute interview with Whisper
**medium** killed the server twice — the process disappeared with no fatal
error in its log and no OS-level event, on a machine with 0.6 GB of 7.8 GB
free. Whisper **small** completes the same source with the machine healthy.
The final verification run therefore used the model that is known to finish
on this hardware. The failure was the environment's, not the pipeline's — but
the pipeline's response to it (restart recovery) was itself correct, and is
now recorded three times over.

- Tests: 14 new (`tests/test_job_state_transitions.py`, plus one each in
  `tests/test_frontend_api.py` and `tests/test_errors.py`); suite **672
  passed**; ruff + tsc + build clean.

### Phase 16 — Resource optimisation: measure, bound, reclaim, expose (COMPLETE)

- **Measure.** `resources.py` owns the accounting. `disk_usage()` walks the
  four storage areas (`raw`, `media`, `work`, `exports`) plus the database and
  reports real bytes and file counts — no estimates. `Usage` accumulates what
  one job actually consumed, gathered where the work happens: the token counts
  are **what the provider reported** (`AnthropicProvider`, `OpenAIProvider`,
  `GeminiProvider`, `OllamaProvider` each record their own usage — a provider
  that reports nothing leaves the counter at zero rather than guessing),
  and the ffmpeg seconds are the wall clock around the real process.
  Migration **v11** adds `job_resources` (llm calls/tokens, ffmpeg runs and
  seconds, export bytes, windows skipped), written by the runner on success,
  on failure *and* on cancellation — the work spent up to a failure is still
  work spent. Verified on a copy of the real database: v10 → v11 preserved all
  8 sources / 8 jobs / 32 clips / 31 exports / 31 uploads / 6 workflows /
  1 batch / 6 notifications / 1 account / 1 channel, foreign-key check clean,
  re-running is a no-op.
- **Bound.** A new `ResourceSettings` section (every default preserves current
  behaviour): `max_parallel_ffmpeg` (2), `ffmpeg_threads` (0 = automatic),
  `max_output_tokens` (4096), `max_llm_calls_per_job` (0 = unlimited),
  and three retention windows. `ConcurrencyGate` is a resizable counting gate
  — a semaphore cannot be resized, and the limit is a setting the user can
  change while the app runs — and **every** ffmpeg/ffprobe invocation takes a
  slot, so a thumbnail pass cannot start on top of an export. A detection
  budget that bites says so: the skipped windows are counted and reported
  (`usage.windows_skipped`), because analysing less of the video than the job
  claims to would be a quiet lie.
- **Reclaim.** `cleanup()` removes only what the settings allow: scratch
  directories of *finished* jobs past retention, files of *already-published*
  clips past retention (the export row survives — it is the record the
  duplicate check reads), downloaded YouTube videos past retention, and files
  no row points at any more. Never removed: an unpublished clip, an uploaded
  source file (it cannot be downloaded again), a failed job's scratch (that is
  what lets "run it again" resume instead of re-transcribing), or anything a
  queued/running job owns. Startup runs a cleanup pass (failure logged, never
  fatal).
- **Expose.** `GET /api/resources` (disk, limits, measured totals, per-job
  usage) and `POST /api/resources/cleanup`; CLI `autoclip resources` and
  `autoclip cleanup [--dry-run]`; Settings → **Resources** in the frontend
  (disk per area, measured use, editable limits, "Clean up now").
- **Four real defects found and fixed by this phase's live run:**
  1. *The orphan sweep would have deleted every clip thumbnail.* A thumbnail
     is the export path with a `.jpg` suffix — an artifact of the export, not
     a row — so the orphan check removed it along with the row it belonged to.
     Exports now own their `.jpg`/`.srt` siblings, and a published clip's
     thumbnail is reclaimed with the video.
  2. *A source's sidecar files were treated as orphans.* yt-dlp writes
     `source.info.json` and friends beside the video. Ownership is now derived
     from the row's own path (the directory holding the file) rather than a
     reconstructed `media/{source_id}` layout.
  3. *Cleanup could race a running job.* The export stage writes the file
     *before* the database row that describes it, so a cleanup running at that
     moment would see an unreferenced file and delete a clip the job was about
     to publish. A live job's directory is now untouchable.
  4. *The token counter double-counted every concurrent window.* Detection
     runs several transcript windows in parallel against one provider, and the
     usage was read from the provider's "last call" slot — a race between
     them. The regression test reproduces it exactly: 8 real calls were
     recorded as 16. Providers now keep a running total as well, and the
     detection stage attributes the *difference* of that total, so every
     token is charged to exactly one call.
- Verified live against the real project:
  - the user's long-running job (`798a3104e2a4494a`) finished under the new
    code and recorded **17 ffmpeg runs / 690.3 s / 399 MB exported** — real
    measurements, not estimates;
  - `GET /api/resources` reports the real 4.1 GB on disk (media 2.4 GB, work
    722.3 MB, exports 1.0 GB, database 320 KB);
  - the startup cleanup reclaimed the one genuine orphan and left **all six**
    work directories (including the cancelled and running ones) and every
    referenced export untouched;
  - the Settings → Resources section was exercised in the browser: disk and
    measured-use figures render, "Clean up now" posts and reports "Nothing to
    reclaim" (correct — everything is referenced and within retention), and a
    limit edited in the UI round-tripped to `config.json` and back through
    `GET /api/settings`; no console errors;
  - `autoclip resources` and `autoclip cleanup --dry-run` both work from the
    command line.
- Tests: 49 new (`tests/test_resources.py`, `tests/test_cli_resources.py`);
  suite **603 passed** (up from 554); ruff + tsc + build clean.

### Phase 15 — Unified error handling and the recovery centre (COMPLETE)

- `errors.py`: one taxonomy for the whole app. Stable codes — `auth`,
  `quota`, `rate_limit`, `provider`, `network`, `timeout`, `not_found`,
  `validation`, `config`, `media`, `conflict`, `internal` — each with a
  default status, a hint that says the fix, and a **retryability decision
  that is a property of the cause, not of the mood**: a rate limit or a
  dropped connection is worth retrying; a rejected credential is not, and
  telling the user to "try again" there would be a lie.
  - The real message is always preserved. An unrecognised exception becomes
    `internal` with its own text — never a guessed cause. An exception that
    carries an explicit `code` wins over the marker heuristics.
- `app.py`: `_install_error_handlers()` gives **every** API failure the same
  JSON body — `{detail, code, hint, retryable}` — for `HTTPException`,
  `RequestValidationError` and unhandled exceptions alike. Structured
  `detail` objects (the ingest endpoints' `{message, hint}`) are flattened
  into that shape, so the client has one contract rather than two.
- `recovery.py` + `api/recovery.py`: `GET /api/recovery` — one list of
  everything that failed: failed jobs, failed uploads, and clips whose render
  did not survive validation. Each item carries the real error, its
  classification, and the action that would fix it, pointing at the endpoint
  that already owns that work (retry a job, retry an upload, re-render a
  clip). The list is read-only — nothing starts work behind the user's back.
- Frontend: `ApiError` carries `code` and `retryable`; `ErrorNote` shows the
  code and offers **Try again** when the server says a retry is worth
  attempting; a new `ErrorBoundary` catches a render crash and offers a way
  out instead of a blank page; a new **Recovery** page (`/recovery`, in the
  top nav) lists the failures with their fix.
- **Three real defects found and fixed by this phase's live run:**
  1. *The crash boundary never ran.* React Router catches route render
     errors before an outer React boundary sees them, so the app showed
     React Router's bare "Unexpected Application Error!" page. The router
     now has its own `errorElement` (`RouteError`), and the outer
     `ErrorBoundary` catches crashes outside the route tree — both showing
     the same friendly screen with a way back. Verified live by crashing a
     screen on purpose and confirming the recovery screen appeared.
  2. *The recovery action ignored the cause.* A failed upload whose file
     was gone was offered "Try publishing again", which would fail in
     exactly the same way. The action now follows the cause: a transient
     failure (rate limit, network, timeout) offers a retry; a missing file
     offers **Render it again**; a rejected credential is not offered as a
     retry at all, because the user has to fix something first.
  3. *A recovered failure stayed in the list forever.* Re-rendering a clip
     creates a new export and a new upload, but the original failed row
     remained as history — and the recovery list kept asking for a fix that
     had already been applied. A failure whose clip has been rendered again
     since it failed is now recognised as superseded and drops off the list.
- Verified live against the real project:
  - a 404, a 422 validation error and a 415 unsupported upload all returned
    the unified body with the right code and a real hint;
  - a **genuine unhandled crash** — a transcript file corrupted on disk so
    `json.loads` raised — returned a classified 500 with the real message and
    no stack trace, and the file was restored afterwards;
  - the recovery centre classified real seeded failures correctly
    ("quota exceeded" → `quota`, "429 Too Many Requests" → `rate_limit`,
    "the file has been moved or deleted" → `not_found`) and offered the
    right action for each;
  - the **upload retry action** was exercised end-to-end: `failed` →
    `pending` → the worker picked it up → it failed again with a real,
    honest error → a notification with the real title was left behind;
  - the **job retry action** was exercised end-to-end in an isolated
    instance: `failed` → `queued` → the worker ran it → it failed again
    with a real error → it was back in the recovery list with "Run it
    again";
  - the **"Render it again" action** was exercised from the browser: the
    clip was re-rendered (a real 34 MB file), a new upload was queued and
    correctly **skipped as a duplicate** (that clip is already published),
    and the superseded failure then dropped off the recovery list.
- Suite **554 passed**, ruff/tsc/build clean.

### Phase 14 — The notification centre (COMPLETE)

- **Migration v10** adds a `notifications` table: kind, severity
  (info/success/warning/error), title, body, an in-app `link`, the `entity_id`
  it refers to, a read flag and a timestamp. Verified on a copy of the real
  database: v9 → v10 preserves all 8 sources / 8 jobs / 15 clips / 21 exports
  / 21 uploads / 6 workflows / 1 batch, with a clean foreign-key check, and
  re-running the migration is a no-op.
- `notifications/events.py`: the one place that knows how to describe an
  event — job done, job failed, clip exported, clip failed validation, upload
  published, upload failed, upload skipped, batch finished. Every value is
  the real one (the clip's own title, the upload's own error string, the
  number of clips actually found). Every helper is wrapped so a failed insert
  can never break the work it describes.
- Wired into the real event points: the pipeline runner (job done/failed),
  the export endpoint (render passed/failed validation), the upload queue
  (published/failed/skipped) and the batch runner (batch finished).
- `api/notifications.py`: `GET /api/notifications`, `/unread-count`,
  `POST /{id}/read`, `POST /read-all`, `DELETE /{id}`, `POST /clear`. The
  inbox is pruned to the newest 500 rows.
- Frontend: a **notification bell** in the masthead with an unread badge, a
  panel with severity dots, relative timestamps and per-row links, plus
  "Mark all read" and "Clear read". Polled every 5 s — a local-first app has
  no push channel.
- **Two real bugs found and fixed by this phase's live run:**
  1. *Duplicate detection compared the wrong key.* It compared the internal
     `channel_row_id`, so the legacy row (`''`) and its imported channel
     profile looked like different destinations — even though both point at
     the same YouTube channel (`UChaj0U8h_RTMizn00n7EbRA`). A re-export of an
     already-published clip therefore published a second copy. The comparison
     now resolves each row to its **YouTube channel id**
     (`duplicates.destination_channel_id`), so the two rows are correctly
     recognised as one destination. Re-verified live: the re-export is now
     **skipped** instead of published.
  2. *Upload notifications said "Untitled clip".* The worker notified from a
     snapshot taken before metadata generation wrote the title, and a skipped
     upload never generates metadata at all. The title now falls back
     upload row → clip row → "Untitled clip".
- Verified live end-to-end: a real 52 s export produced a real
  `clip_exported` notification naming the clip, the upload worker published
  for real (`youtu.be/OoA4bvUJbAg`) and the `upload_done` notification carried
  the channel and video id; the next export was correctly skipped as a
  duplicate; the bell, badge, panel, "Mark all read" and click-through
  navigation were all confirmed in the browser with no console errors. The
  verification artefacts were then removed from the real database and the
  exported file.
- Suite **528 passed**, ruff/tsc/build clean.

### Phase 13 — The project-aware assistant (COMPLETE)

- `chat/context.py`: a read-only snapshot of **real** project state — the
  library summary, current settings, recent jobs, recent clips (with their
  score, hook, the reason the model gave and the upload outcome), failures
  (failed jobs and failed uploads with their real error strings), YouTube
  channels, routing rules, the `improve.txt` standing instructions, the trend
  cache, and an optional focus on one clip or one job. Every fact traces back
  to a row or a file.
- `chat/agent.py`: the answer loop. The snapshot is the *entirety* of what the
  model is told, and the system prompt says so explicitly. The provider
  fallback chain is the standard resolver, so the configured provider leads
  and a healthy local model is the terminal fallback. A JSON-shaped answer is
  retried once as prose, since a chat reply is not a schema.
- **No fabrication, enforced at two levels.** The prompt forbids inventing
  counts, titles, errors or URLs; and when every provider fails, the endpoint
  returns HTTP 502 with an actionable message instead of a canned reply that
  would look like an answer.
- `api/chat.py`: `POST /api/chat`, `GET /api/chat/context` (the exact
  snapshot, for inspection), `GET /api/chat/starters`.
- Frontend: a new **Assistant** page (`/assistant`, in the top nav) — a
  message thread, starter questions, the provider that answered, and a
  "Show what the assistant can see" panel that renders the literal brief sent
  with the question. `components/Markdown.tsx` renders the model's prose
  (emphasis, lists, code spans) as React elements — never HTML strings.
- Verified live against the real project with Google Gemini: asked what has
  been produced (answered 15 clips, correctly named the top clip "Recreating
  the Hunger Games in real life" at score 92), what is failing (correctly
  reported zero failures and distinguished the one running job), and how many
  views the published videos got — the assistant answered *"The project data
  does not record view counts"*, which is the correct honest reply. The UI
  thread, the context panel and the Markdown rendering were verified in the
  browser with no console errors. Suite **512 passed**, ruff/tsc/build clean.

### Phase 12 — Trending research (COMPLETE)

- `trends/research.py`: real trend signal from YouTube itself — the Data API's
  `videos.list?chart=mostPopular` (1 quota unit per call) for the channel's
  category and region, cached for 6 hours. The list is parsed into
  `TrendingVideo` records (title, channel, views, tags, URL).
- AI analysis over the provider fallback chain reads the real titles into
  themes / working formats / saturated angles for the user's niche. A provider
  failure is **not** fatal: the raw chart is still returned with `error` set.
  Themes are never invented.
- `providers/base.py`: the cached trend digest is appended to the highlight
  detection system prompt as a "What is trending right now" block — read
  network-free, so detection never blocks on a fetch. A broken trend cache
  cannot break detection (guarded read).
- `api/trends.py`: `GET /api/trends/current` (cached read, fetches when empty),
  `POST /api/trends/refresh` (force re-fetch + re-analysis), and
  `GET /api/trends/context` (the exact prompt block, for verification).
- Frontend: a new **Trends** page (`/trends`, in the top nav) — niche input,
  category and region pickers, Refresh, the analyst's themes with fit badges,
  working formats, saturated angles, and the real chart with view counts.
- Verified live against the real YouTube Data API: 50 trending videos fetched
  for category 24 / US, analysed by Google Gemini into 3–4 themes + formats +
  avoid list; `from_cache` flips to true on the second call and false after a
  forced refresh; `/api/trends/context` contains the "What is trending right
  now" header; the UI shows the real chart with no console errors, and typing a
  niche visibly re-steers the analysis. Suite **491 passed**, ruff/tsc/build
  clean.

### Phase 11 — Analytics and the learning engine (COMPLETE)

- `learning/analytics.py`: honest outcome aggregates — pipeline summary
  (clips/exported/invalid/discarded/uploads/sources plus the most common
  validation failures), score-band outcomes (keep/export/upload/trim rates per
  85-100 / 70-84 / 50-69 / 0-49 band, the calibration evidence), and per-channel
  upload outcomes.
- `learning/improve.py`: `~/.autoclip/improve.txt` — the user's standing
  instructions, created with a commented template, comments stripped, capped at
  4,000 characters. Injected into the highlight-detection system prompt on every
  call (`providers/base.py`). Per-channel notes live in
  `~/.autoclip/channels/<UC_id>.md` and steer upload titles.
- `api/learning.py`: `GET /api/learning/{summary,score-bands,channels,feedback}`,
  `PUT /api/learning/feedback` (blank content restores the template),
  `GET/PUT /api/learning/channel-note/{channel_id}`.
- Frontend Settings → Learning: counters, the score-band calibration table, the
  per-channel upload table, and the standing-instructions editor (save writes
  the file; the active-character count shows what actually reaches the model).
- No fabricated performance data: until the YouTube quota increase lands,
  learning is driven by the user's own keep/discard/trim decisions and
  validation outcomes.
- Verified live: real library shows 15 clips / 15 published, score bands 9/4/0/2,
  per-channel 15 published + 6 skipped; UI save round-tripped to
  `improve.txt` ("31 chars active"); the feedback is confirmed present in the
  detection prompt. Suite **475 passed**, ruff/tsc/build clean.

### Phase 10 — Multi-channel publishing fan-out (COMPLETE)

- Migration **v9**: `youtube_uploads` rebuilt with `channel_row_id` (unique per
  export+channel, legacy rows map to `''`), `youtube_channels.title_suffix`,
  `routing_rules.extra_channel_ids_json`. Verified on a copy of the real DB
  (15 clips / 21 exports / 21 uploads preserved, FK check clean).
- `uploads.enqueue_export_all`: one row per target channel from
  `routing.resolve_target_channels` (primary + extras, channels with
  `auto_upload` off are dropped, legacy single row when no profiles).
  Per-channel privacy is captured at enqueue; `retry_upload` keeps a channel
  row's own privacy instead of the global default.
- `process_upload` publishes to the row's channel (`account_id`, privacy,
  category) and appends `title_suffix`; account-scoped OAuth tokens
  (`oauth.access_token(settings, account_id=...)`) cached per Google account;
  `uploader.upload_video` / `set_thumbnail` accept `account_id`.
- Duplicate detection (`conflict_for`, same-clip / identical-file / same-title)
  is now scoped per destination channel, so a legitimate fan-out is not flagged.
- APIs expose channel `title_suffix` and rule `extra_channel_ids`; `ExportOut`
  gained `uploads: list[UploadOut]` (`upload` kept for compatibility); the
  clips library renders one upload badge per channel.
- Verified live on a copy of the real DB: rule + extra channel produced two
  pending rows with per-channel privacy, re-enqueue idempotent, duplicate
  scoping correct. Suite **466 passed**, ruff/tsc/build clean.

### Phase 9 — Clip validation gate (COMPLETE)

- `pipeline/validate.py`: bounds checks (positive/min/max duration, word range,
  inside the source) and media checks (file exists, size floor, ffprobe, video
  stream, audio stream, exact resolution, duration tolerance, peak-level silence
  test via the new `ffmpeg.volumedetect`).
- Migration **v8** rebuilds `clips` to allow the `invalid` status and adds
  `validation_json`; verified against a copy of the real 15-clip database
  (rows preserved, `PRAGMA foreign_key_check` clean).
- Runner and the manual export endpoint validate every render, persist the
  report, mark failures `invalid`, and skip auto-publish. `enqueue_export` also
  refuses an invalid clip, so an old queued row cannot slip through.
- `POST /api/clips/{id}/validate` re-runs checks on the newest export; the
  library shows `validated` / `failed checks` (with details on hover) plus
  `re-check`.
- Verified live: export → 8 checks all pass (1080×1920, 21.2 s vs 21.12 s,
  peak −1.5 dBFS); sim/re-check endpoint returns ok; UI shows `validated`.
  Suite **457 passed**, ruff/tsc/build clean.

### Phase 8 — Background music with speech-aware ducking (COMPLETE)

- `config.py`: export settings `music_track`, `music_volume`, `music_ducking`,
  `ducking_amount_db` (additive defaults: no track, 0.15, ducking on, -12 dB).
- `pipeline/music.py`: track library in `~/.autoclip/music`; resolves bare names or
  absolute paths; a missing track logs loudly and degrades to a plain export.
- `pipeline/export.py`: `build_mixed_audio_filtergraph` mixes a looped, trimmed bed
  under loudness-normalised speech with `sidechaincompress` keyed on the speech
  (attack 120 ms, release 600 ms) and `amix … normalize=0` so speech level is
  preserved. Sources with no audio skip the bed instead of failing.
- `api/music.py`: `GET/POST /api/music/tracks`, `DELETE /api/music/tracks/{name}`.
- Frontend Settings → Export → Background music: track picker, volume, ducking
  toggle, ducking depth, upload and remove.
- Verified: real ffmpeg render (looping 2.5 s bed under a 5 s clip), and a real
  app export measured with `bandpass=f=330` — music-only energy up +1.6 dB in the
  bed band while overall loudness stayed flat (found and fixed `amix` default
  normalisation attenuating speech ~6 dB). Suite **446 passed**, ruff/tsc/build clean.

### Phase 7 — Visual workflow builder UI (COMPLETE)

- `frontend/src/pages/Workflows.tsx`: n8n-inspired builder — infinite pan/zoom canvas
  (SVG bezier edges + HTML node cards in world coordinates), node palette (all 8 types),
  drag to move, output→input linking with live preview, per-node ON/OFF toggle,
  config inspector, delete, workflow list with version display, Run button, and
  per-workflow run history panel.
- `api.ts`: typed Workflow/Batch client surfaces (nodes, CRUD, run, runs, batches).
- Backend fix found by live UI testing: `/api/workflows/runs` was shadowed by
  `/{workflow_id}` (route ordering) — moved above and added a regression test.
- Verified live in the browser: create "UI builder smoke" via palette click → save →
  run (succeeded) → history; node disable → save v3 → run shows `skipped/node disabled`;
  re-enable → v5 saved. Suite **435 passed**; tsc + build clean.

### Phase 2 — Workflow engine foundation (COMPLETE — commit `b07e759`)

- Migration v4: `workflows` (versioned, active flag), `workflow_runs`, `workflow_node_runs`.
- `workflow/engine.py`: `NodeSpec` registry (6 pipeline stages + `util.condition` + `util.log`),
  graph validation (types/dupes/edges/cycles), topological execution, retry policy,
  disabled-node passthrough, cancellation, start/finish hooks.
- `workflow/store.py`: CRUD with versioning (old versions retained), run + node history.
- `api/workflows.py`: `/api/workflows` CRUD + validate + run + runs/{id}; `/nodes` registry.
- Tests: 18 new (`tests/test_workflow.py`); suite 380 passed; ruff + tsc + build clean.
- Live-verified: registry lists 8 node types, workflow create → run → history over HTTP.
- Defects found & fixed during the phase (each has a regression test): eager runner binding
  (made lazy), spec-vs-factory registry resolution, double-resolution bug, disabled-node
  data passthrough, `api.engine` name collision.
- Known limitation (deliberate): pipeline-stage nodes require a runner binding which the
  HTTP run endpoint does not yet construct; stage execution through workflows lands with
  the batch/execution phase (the engine, history, and validation paths are complete).

