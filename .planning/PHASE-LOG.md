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

