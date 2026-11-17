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

