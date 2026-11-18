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

