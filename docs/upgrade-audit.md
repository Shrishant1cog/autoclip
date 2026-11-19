# AutoClip — Upgrade Audit (M0)

**Audit date:** 2026-11-19
**Branch:** `feature/upgrade-u0-u10`, created from `feature/autonomous-platform-v2` @ `bf76811`
**Method:** every claim below was checked against the working tree, not against the README. Where a
claim depends on something I could not execute, it is marked **Unverified** and says why.

Reference hardware for all measurements: Intel Core i5-8279U (4 cores / 8 threads), 7.8 GB RAM,
Intel Iris Plus 655 (no CUDA), Windows 10/11, Python 3.11.16, FFmpeg 9.0.2, Node 24.21.0.

---

## 1. Existing architecture

| Layer | Reality | Evidence |
|---|---|---|
| Backend | FastAPI app assembled in `backend/autoclip/app.py`; 18 routers under `backend/autoclip/api/` | `api/*.py`, each declaring `APIRouter(prefix=...)`; 108 route decorators in total |
| Frontend | React 18.3.1 + TypeScript 5.7 + Vite 6, React Router 6, Tailwind 4 | `frontend/package.json` |
| Database | Raw `sqlite3`, no ORM. `db/__init__.py:connect()`; migrations in `db/schema.py` driven by `PRAGMA user_version` | `schema.py:575` `MIGRATIONS`, `:592` `SCHEMA_VERSION = len(MIGRATIONS)` |
| Schema version | 14 (14 migrations: `_migration_v1` … `_migration_v14`) | `schema.py` |
| Pipeline | Six stages: `prepare, transcribe, highlights, reframe, captions, export`, file-based artifacts under `work/{job_id}/` | `pipeline/runner.py`, `pipeline/__init__.py:Stage` |
| Jobs | Single asyncio worker polling SQLite, SSE progress via `sse-starlette` | `jobs/queue.py:JobQueue._worker`, `api/jobs.py` |
| Providers | 16 preset providers, 4 adapters (openai-compatible, anthropic, gemini, ollama) | `providers/presets.py`, `providers/{openai,anthropic,gemini,ollama}_provider.py` |
| Secrets | OS keyring via `keyring`; `config.get_secret`/`set_secret` | `config.py:KEYED_PROVIDERS`, `:324-333` |
| Publishing | YouTube Data API v3 resumable upload; multi-account tables | `youtube/uploader.py`, `youtube/uploads.py`, `youtube/accounts.py` |
| Workflow | Engine + store + API + hand-written canvas | `workflow/engine.py`, `api/workflows.py`, `pages/Workflows.tsx` |

**Backend size:** 97 Python modules (`backend/autoclip/**/*.py`).
**Frontend size:** 13 routed pages (`pages/`), 7 components (`components/`), 1 hook module
(`useJobStream.ts`). Routes are declared in `main.tsx:29-43`.

### Repository structure (top level)

```
backend/autoclip/{api,chat,db,jobs,learning,notifications,pipeline,providers,routing,speech,trends,workflow,youtube}
frontend/src/{pages,components,api.ts,App.tsx,main.tsx}
tests/                     36 test modules
scripts/                   make_e2e_media.py, verify_music_mix.py, bench_baseline.py
.github/workflows/ci.yml   backend matrix + frontend + docker
docs/                      ARCHITECTURE.md, CONTRIBUTING.md (+ this upgrade set)
```

---

## 2. Implemented features (verified working)

These have both a code path and at least one passing automated test.

| Feature | Evidence |
|---|---|
| Six-stage resumable pipeline with per-stage artifacts | `pipeline/runner.py`; `tests/test_runner_fallback.py`, `tests/test_pipeline_e2e.py` (24, media-gated) |
| Job queue with restart recovery | `jobs/queue.py:_requeue_interrupted`; `tests/test_restart_recovery.py` (26 tests) |
| Job state machine + transitions | `tests/test_job_state_transitions.py` (12) |
| SSE progress stream | `api/jobs.py`; `tests/test_api.py` |
| Transcript model, word timestamps, caption rendering | `pipeline/transcript.py`, `pipeline/captions.py`; `tests/test_captions.py` (27) |
| Face-driven reframe (MediaPipe FaceLandmarker + speaker tracking) | `pipeline/reframe/*`; `tests/test_reframe.py` (39) |
| Clip boundary selection | `pipeline/boundaries.py`; `tests/test_boundaries.py` (23) |
| Export render + clip validation gate | `pipeline/export.py`, `pipeline/validate.py`; `tests/test_export_render.py` (13), `tests/test_validation.py` (11) |
| Provider abstraction, key pools, presets, local Ollama fallback | `providers/*`; `tests/test_providers.py` (26), `tests/test_runner_fallback.py` (10) |
| ElevenLabs STT + local faster-whisper STT | `speech/*`; `tests/test_speech.py` (16) |
| Multi-channel routing rules | `routing/classifier.py`; `tests/test_routing.py` (13) |
| Multi-account YouTube tables + fan-out upload queue | `youtube/uploads.py:enqueue_export_all`; `tests/test_multi_channel.py` (10) |
| Upload duplicate detection | `youtube/duplicates.py`; `tests/test_youtube_duplicates.py` (12) |
| Batches | `jobs/batches.py`, `jobs/batch_runner.py`; `tests/test_batches.py` (12) |
| Music bed mixing with sidechain ducking | `pipeline/export.py:build_mixed_audio_filtergraph`; `tests/test_music.py` (11) |
| Notifications | `notifications/events.py`; `tests/test_notifications.py` (15) |
| Resource monitor + cleanup | `resources.py`; `tests/test_resources.py` (42) |
| Assistant over project context | `chat/*`; `tests/test_chat.py` (21) |
| Workflow engine + persistence | `workflow/*`; `tests/test_workflow.py` (19) |
| Trends research | `trends/research.py`; `tests/test_trends.py` (16) |
| Learning aggregates + `improve.txt` | `learning/*`; `tests/test_learning.py` (9) |

---

## 3. Partially implemented

| Feature | What exists | What is missing | Evidence |
|---|---|---|---|
| Workflow execution | Engine, store, API, UI | API passes `{"runner": None}`, so every `stage.*` node raises; execution happens inside the request handler, not the queue (D1) | `api/workflows.py:~140`, `workflow/engine.py:_stage_node` |
| Node library | 8 node types (6 `stage.*`, `util.condition`, `util.log`) | No trigger/filter/merge/split/delay/loop/publish/analytics nodes | `workflow/engine.py` registry |
| `util.condition` | Truthy-string test (`"true"/"1"/"yes"/"on"`) | Not an expression evaluator; no branching semantics | `workflow/engine.py:_cond_handler` |
| Auto Upload | Global switch + per-channel switch + fan-out gate | Precedence is only enforced inside the fan-out; no single resolver; no emergency stop (D7) | `config.py:192`, `routing/classifier.py:322`, `youtube/uploads.py` |
| Multi-account YouTube | Per-account keyring entries, account/channel tables, API | `Channels.tsx` calls the *legacy global* connect, so all "accounts" share one token (D14) | `pages/Channels.tsx:52`, `youtube/oauth.py:_Pending`, `youtube/accounts.py:claim_legacy_token` |
| Music | Upload-to-`~/.autoclip/music/`, list, delete, one track setting, sidechain ducking | No folder selection, no scan, no preview, no metadata, no licensing, no per-clip AI selection | `pipeline/music.py`, `api/music.py` |
| Speech-aware ducking | ffmpeg `sidechaincompress` keyed on the clip's own audio | No shared speech timeline; no VAD; no interval merging; no envelope preview | `pipeline/export.py:184-239` |
| Webcam layout | Face sampling at fixed 5 fps; face-following crop path | No webcam-region detection, no streamer preset, no 40/60 composition, no dwell rule | `pipeline/reframe/faces.py:DEFAULT_SAMPLE_FPS`, `reframe/croppath.py` |
| Learning | Internal outcome aggregates + user-editable `improve.txt` | No analytics data, no evidence/confidence, no experiments, no rollback, no auto-writer | `learning/analytics.py`, `learning/improve.py` |
| Upload resume | Creates resumable session, sends one streaming PUT | Session URI not persisted (D11) | `youtube/uploader.py:81-111` |
| Rights | A docstring precondition only | No stored confirmation, no UI, no gate | `pipeline/ingest.py:136-138` (D13) |
| Notification delivery | Polling every 5 s | No push channel (D6) | `components/NotificationBell.tsx:57` |

---

## 4. Missing features

Verified absent from the tree (searched by symbol and by concept):

- Upload reconciliation after ambiguous failures; persisted resumable-session URI.
- Provider circuit breakers (no open/half-open/closed state anywhere).
- Per-call provider cost/usage records (only key health exists).
- Learning experiments, learning versions, rollback.
- A unified effective-settings resolver and a persisted emergency stop.
- A shared side-effect gate.
- Node-level Skip semantics and ON/OFF persisted per node definition.
- Stored per-source rights confirmation.
- YouTube Analytics collection (and the `yt-analytics.readonly` scope).
- Job pause/resume/retry and concurrency lanes (D10).
- Any Instagram integration at all (no module, no route, no setting, no credential entry).
- Frontend test tooling (D9).
- Music BPM/energy/loudness analysis; music licensing states.
- Webcam-region detection; layout dwell control; manual layout override UI.
- Structured creative plan + AI call budget enforcement.
- Objective quality diagnostics beyond the existing clip validation gate.

---

## 5. Unverified (cannot be established from this machine)

| Item | Why unverified |
|---|---|
| Live ElevenLabs calls | No authorised test credential supplied |
| Live hosted-LLM calls | No authorised test credential supplied |
| Live YouTube publishing | No OAuth client, no test channel, no consent to publish |
| Live Instagram publishing | No Meta app, no professional account, no app review |
| Behaviour of YouTube API under an unaudited project | Needs a real project and a real upload |
| Original requirements document and the seven visual references | Not present anywhere on this machine (see `docs/original/MANIFEST.md`) |
| Real-media pipeline acceptance (Lane C) | 24 e2e tests collect but require `AUTOCLIP_E2E_MEDIA`; source videos exist (see §15) but running the full 3.5 GB job is deferred to the M5 acceptance pass |
| FreeLLMAPI hosted behaviour | Contract verified from the official repository docs; live probe impossible without a key |

---

## 6. Security issues

Full detail in `docs/SECURITY-AUDIT.md`. Summary of findings by severity:

| # | Severity | Issue | Location |
|---|---|---|---|
| S1 | High | No external-transfer consent layer: with `transcription.engine="auto"` and an ElevenLabs key present, extracted **audio leaves the machine** with no per-run consent (§7) | `speech/base.py:resolve_engine` |
| S2 | High | yt-dlp receives a user-supplied URL with no post-redirect or DNS re-validation; yt-dlp makes its own secondary requests | `pipeline/ingest.py` |
| S3 | Medium | FFmpeg invoked without `-protocol_whitelist`; default protocol set is permissive | `pipeline/ffmpeg.py` |
| S4 | Medium | Provider `base_url` is user-configurable and never classified (loopback/private/public) before use | `config.py`, `providers/*` |
| S5 | Medium | MediaPipe model is downloaded from `storage.googleapis.com` on first use - an undocumented outbound request | `models.py:37` (`ensure` at `:64`), called from `reframe/faces.py:113` |
| S6 | Low | Legacy global OAuth token remains valid alongside per-account tokens | `youtube/oauth.py`, `accounts.py:claim_legacy_token` |
| S7 | Low | `ruff` unpinned (`>=0.7`) means the format gate can change under CI | `pyproject.toml:85` |

Positive findings: CORS is restricted; keyring is used for all secrets; no secret is returned by any API route (keys are reported by label only); SQLite is accessed with parameterised statements throughout.

---

## 7. External data transfers

The complete egress inventory is in `docs/EGRESS-INVENTORY.md`. The audited destination set,
extracted from the source rather than from documentation:

```
Google OAuth / identity
  accounts.google.com/o/oauth2/v2/auth
  oauth2.googleapis.com/token
  oauth2.googleapis.com/revoke
YouTube Data API
  www.googleapis.com/youtube/v3/{channels,videos}
  www.googleapis.com/upload/youtube/v3/{videos,thumbnails/set}
ElevenLabs
  api.elevenlabs.io/v1/speech-to-text
  api.elevenlabs.io/v1/text-to-speech/
  api.elevenlabs.io/v1/user/subscription
LLM providers (16 presets)
  api.openai.com/v1, api.anthropic.com, generativelanguage.googleapis.com,
  openrouter.ai/api/v1, api.groq.com/openai/v1, api.cerebras.ai/v1,
  api.deepseek.com/v1, api.mistral.ai/v1, api.together.xyz/v1,
  router.huggingface.co/v1, integrate.api.nvidia.com/v1,
  plus user-supplied base URLs (freellmapi, lmstudio, llamacpp, vllm)
Local
  localhost:11434 (ollama), localhost:1234/v1 (lmstudio), localhost:8001/v1 (vllm),
  localhost:8080/v1 (llamacpp)
Model download
  storage.googleapis.com/mediapipe-models/face_landmarker/
YouTube trending chart
  www.googleapis.com/youtube/v3/videos (chart=mostPopular, trends research)
Media
  yt-dlp against user-supplied URLs (arbitrary third-party hosts and CDNs)
```

**Correcting the inherited claim.** The previous documentation stated that media always remains
local. That is false as written. `speech/base.py:resolve_engine` resolves `transcription.engine`:

- `"local"` → local faster-whisper only. **No external transfer.**
- `"elevenlabs"` → ElevenLabs Scribe only, no fallback. **Audio always leaves the machine.**
- `"auto"` (the default) → ElevenLabs Scribe **if an ElevenLabs key is configured**, else local
  Whisper. When a key exists, **the extracted audio file is uploaded**.

Fallback behaviour, stated exactly as implemented (`pipeline/runner.py:366-404`):

- If the resolved engine raises `SpeechError` and the setting is `auto`, the runner falls back to
  local Whisper and records a user-visible notice. This happens **after** the failed external call.
- If the setting is pinned (`elevenlabs` or `local`), the error surfaces; there is no fallback.
- `SpeechCancelled` never triggers fallback — a cancelled job must not start a second transcription.
- The LLM path has a separate fallback: on auth/transient failure the runner health-checks Ollama
  and, if reachable, switches to the local model (`runner.py:_ollama_fallback:507-544`).

So: **audio and transcript text can leave the machine today, without a consent step.** Fixing that
is M0.5.

---

## 8. Provider inventory

16 presets in `providers/presets.py`:

`anthropic, openai, gemini, openrouter, groq, cerebras, deepseek, mistral, together, freellmapi,
huggingface, nvidia, lmstudio, llamacpp, vllm, ollama`

Adapters: `openai` (used by every OpenAI-compatible preset), `anthropic`, `gemini`, `ollama`.
Capability metadata exists as a coarse tuple (`("text", "json")`, `("text","json","vision")` etc.)
on each preset and is consumed by `resolver.py`. It is **not** a per-model matrix: there is no
per-model context length, tool support or modality declaration.

`freellmapi` is deliberately configured with `default_base_url=None` (`presets.py:124-132`),
i.e. user-supplied. The official contract was verified from the upstream repository
(`docs/en/api/01-rest-api.md`): OpenAI-compatible, default `http://localhost:3001/v1`, unified key
as `Authorization: Bearer <key>`, `model: "auto"` or `auto:<profile>`. Recorded in
`docs/EXTERNAL-CONSTRAINTS.md`.

---

## 9. API inventory

18 routers, 108 routes. Grouped (counted from the `@router.<method>` decorators, not from memory):

| Router | Routes | Notes |
|---|---|---|
| `ai_providers` | 8 | key CRUD by label, health, ad-hoc task |
| `batches` | 9 | create/add/launch/pause/cancel/retry-failed |
| `chat` | 3 | starters, context, ask |
| `clips` | 11 | list/get/words/crop-path, edit, captions, export, validate, download, media, styles |
| `jobs` | 7 | create/list/get/events/cancel/retry/clips + stream |
| `learning` | 7 | summary, score bands, channels, feedback, channel note |
| `music` | 3 | list/upload/delete |
| `notifications` | 6 | list, unread count, read, read-all, delete, clear |
| `recovery` | 1 | |
| `resources` | 2 | snapshot, cleanup |
| `restarts` | 1 | |
| `routing` | 9 | categories, rules CRUD+toggle, classify, target |
| `settings` | 8 | settings, secrets, provider status, speech status, system, models |
| `sources` | 4 | list/get, YouTube add, upload |
| `trends` | 3 | current, refresh, context |
| `workflows` | 9 | nodes, CRUD, runs, validate, run |
| `youtube` | 8 | status, connect, callback, disconnect, auto-upload, privacy, uploads, retry |
| `youtube_accounts` | 9 | accounts/channels CRUD, channel routing |

**Gaps relevant to this upgrade:** no consent/egress route, no music-licensing route, no
webcam-layout route, no creative-plan route, no Instagram route, no emergency-stop route,
no job pause/resume route (only cancel/retry).

---

## 10. Database inventory

Schema v14, 19 live tables:

```
app_restarts        batches            batch_items        clips            clip_edits
content_classifications                exports            google_accounts  job_resources
jobs                notifications      routing_rules      sources          transcripts
workflow_node_runs  workflow_runs      workflows          youtube_channels youtube_uploads
```

(`clips_new`, `youtube_uploads_v3`, `youtube_uploads_v9` are table-rebuild scratch names created
inside migrations, not live tables.)

Migration discipline is sound: appended only, `MIGRATIONS` is an ordered list, `migrate()` refuses a
database newer than the build (`schema.py:599-603`). **Missing:** no backup before migration, no
interrupted-migration test, and no table for rights confirmation, consent decisions, music metadata,
music licensing, upload attempts/idempotency, quota reservations, provider usage, or learning
versions.

---

## 11. Pipeline and queue behaviour

**Pipeline.** `PipelineRunner` runs `prepare → transcribe → highlights → reframe → captions →
export`. Each stage writes artifacts into `work/{job_id}/`, so a retry skips completed stages. Stage
implementation is delegated to `pipeline/<stage>.py`; the runner owns ordering, progress emission
(`_emit`), notices (`_set_notice`) and cancellation checks (`_check_cancelled`).

**Queue.** `jobs/queue.py:JobQueue` holds one asyncio task (`_worker` → `_run_one`) that pulls
`store.next_queued_job()`. It supports `cancel` and `forget_cancel` only. There is no pause, no
resume, no retry by the queue itself (retry is an API-triggered job reset), no concurrency limit
other than 1, and no lane concept. Restart recovery requeues jobs left `running`
(`_requeue_interrupted`).

Consequence for this upgrade: M1/M2/M3 all add media work, and C10-style blocking isolation is not
possible on a single worker. The queue must gain lanes and per-job controls before the new stages
are trusted not to serialise the whole product.

**Known pipeline gap:** audio extraction writes `audio.wav` into the job workspace and, under
`auto` with a key, that file is posted to ElevenLabs. Nothing in the pipeline records that transfer.

---

## 12. Frontend/backend integration

Verified by route-by-route reading of `frontend/src/main.tsx` and `api.ts`:

- 13 routes render `Ingest, Clips, Assistant, Recovery, Trends, Workflows, Providers, Channels,
  Routing, Batches, JobProgress, Review, Settings`.
- Every page calls the typed client in `api.ts`; there is no mock data layer in production code.
- Progress is driven by `useJobStream.ts` over SSE; the header's YouTube switch polls every 20 s and
  the notification bell every 5 s (D6).
- `Channels.tsx` mixes the multi-account *display* with the legacy *connect* call — the single
  integration defect that makes multi-account publishing non-functional (D14).

`frontend/package.json` has `dev/build/preview/typecheck` only: no `test`, no `lint` (D9). There is
no test runner, so no frontend behaviour is currently protected by a test.

---

## 13. CI and test status (baseline, as found)

`.github/workflows/ci.yml` defines three jobs:

1. **backend** — matrix `ubuntu 3.11`, `ubuntu 3.12`, `macos 3.12`, `windows 3.12`.
   Steps: ruff check, `ruff format --check`, mypy (`continue-on-error: true`), unit tests
   (`-m "not slow and not golden and not e2e"`), render tests (`-m "slow and not golden and not e2e"`).
2. **frontend** — `npm ci`, `npm run build`.
3. **docker** — build image, smoke-test `GET /api/health`.

Recorded on 2026-11-19 before any functional change (see `docs/baseline-ci-evidence.md`):

| Gate | Result |
|---|---|
| Local unit suite, excluding e2e | **672 passed**, 193.77 s |
| e2e collection | 24 tests collected (require `AUTOCLIP_E2E_MEDIA`) |
| `ruff check .` | clean |
| `ruff format --check .` | **FAILED — 38 of 147 files unformatted** (D15) |
| mypy | 14 errors in 10 files (tolerated by `continue-on-error`) |
| Frontend `tsc -b && vite build` | not run in this environment at audit time; CI reports it green |
| Docker build + health smoke | not run in this environment at audit time; CI reports it green |

**D15 matters.** CI pins no ruff version, so the format gate is evaluated against whatever ruff CI
installs. The shipped tree did not satisfy the current formatter. Every CI run on a feature branch
would have failed the format step before reaching the tests — which is consistent with the reported
"backend unit tests: not executed" baseline.

**Two additional defects found during the audit (beyond the specification's D1–D13):**

- **D14 — per-account OAuth is unreachable from the UI.** `Channels.tsx:52` calls
  `api.youtubeConnect()` (the legacy global flow). `_Pending` in `oauth.py` carries no account id,
  and `complete_auth` writes the legacy global token. Only `accounts.claim_legacy_token` can
  populate a per-account keyring entry. Therefore a second account cannot be connected
  independently, and "multiple accounts" currently means "one token displayed twice".
- **D15 — the formatter gate is broken on a clean checkout** (above).

---

## 14. Performance baseline

Measured with `scripts/bench_baseline.py`, machine-readable results in
`docs/BENCHMARK-BASELINE.json`, narrative in `docs/performance-baseline.md`.

| Measurement | Median |
|---|---|
| Cold import of `autoclip.app` | 755 ms |
| Cold import of `autoclip.pipeline.runner` | 110 ms |
| Open existing DB + read `user_version` | 2.7 ms |
| `store.list_jobs()` (default limit) | 1.4 ms |
| Fresh DB, all 14 migrations | 239 ms |
| Build ducking filtergraph string | 0.02 ms |
| Encode 5 s 1080×1920 H.264 (veryfast, CRF 23) | 1,518 ms → 3.69 MB |
| Full unit suite (672 tests) | 193.77 s |

No prior baseline existed in the repository, so these are the reference numbers every later
"improved" claim must be compared against.

---

## 15. Real media available for Lane C

`materials/input/ytdownloadedvideos/` contains four real sources with `.info.json` metadata:

| id | size |
|---|---|
| `2fcd7282d8234d75` | 3.58 GB |
| `59ec00754fa34edf` | 1.53 GB |
| `b8da366d2564444d` | 1.02 GB (per directory listing) |
| `d204a54281a04a1a` | 772 MB |

These are YouTube-sourced third-party videos. Two consequences:

1. They are usable for owner-operated Lane C technical acceptance (clipping, ducking, layout).
2. They are **not** usable for publishing acceptance: rights are not confirmed for their creators,
   and the application will (after M1/M0.5) refuse to publish a source without a stored rights
   confirmation. Lane C publishing must use the owner's own footage and own channel.

They are untracked and must stay untracked (`git ls-files` confirms no media is tracked).

---

## 16. Known technical debt

| # | Debt | Impact |
|---|---|---|
| T1 | mypy has 14 errors in 10 files (e.g. `pipeline/runner.py:699`, `cli.py:231`) and CI ignores them | types drift; new code can hide real bugs |
| T2 | `ruff` unpinned at `>=0.7` (`pyproject.toml:85`) | the format gate can change under CI (D15) |
| T3 | Single asyncio worker | one job at a time; a blocked upload delays rendering (D10) |
| T4 | Workflow runs inside the HTTP handler | a long workflow blocks the event loop (D1) |
| T5 | Provider capability metadata is per-preset, not per-model | a model can be selected for a task it cannot do |
| T6 | No cost/usage record per provider call | spend is invisible |
| T7 | `improve.txt` is read on every detection call and has exactly one writer: the user | learning cannot act on evidence |
| T8 | Legacy global OAuth path is still live | credential confusion between accounts (D14/S6) |
| T9 | MediaPipe model downloaded on demand with no consent or cache policy | surprise egress, offline failure |
| T10 | Frontend has no tests | regressions reach the user |
| T11 | `docs/ARCHITECTURE.md` predates Phases 6–17 in places | documentation drift |

---

## 17. Upgrade dependencies

**Approved new dependencies (Part 1.3 of the governing spec, plus the superseded U0–U10 approval):** `@xyflow/react` and frontend
test tooling (Vitest, Testing Library, Playwright). Everything else must be justified.

Dependencies this upgrade will add, with justification:

| Dependency | Why | Where |
|---|---|---|
| `Pillow` / `numpy` (already transitive via MediaPipe/OpenCV) | music envelope + webcam layout composition | no new install expected; verified before adding |
| `librosa` **or** ffmpeg-based DSP | BPM/energy/loudness analysis without a heavy new dependency | **prefer ffmpeg + numpy**; decide in M1 and record here |
| `mutagen` | read audio tags/format/duration for the music library | small, pure-python |

No web framework, no ORM, no queue system, no cloud SDK will be added.

**Removed from scope by the specification:** n8n, visual workflow canvas, chatbot-for-workflows,
YouTube Analytics, learning loops, trending research, TikTok, other platforms, browser automation.
Note that several of these **already exist** in the repository (workflow canvas, assistant, trends,
internal learning). They are not deleted, and they are not extended. This tension is recorded in §18
and in the coverage matrix.

---

## 18. Conflicts between the governing specification and the shipped product

The specification (Part 1.3) declares out of scope: a visual workflow canvas, a conversational
chatbot, YouTube Analytics, analytics-driven learning/`improve.txt`, trending research. All five
exist in the repository, built in Phases 7–17 under a previous authorisation.

Resolution applied (and recorded here because the specification requires conflicts to be recorded):

1. **Nothing is deleted.** "Preserve useful working functionality" (1.1) outranks "do not add these
   features". Removing shipped, tested screens would destroy user value and break existing tests.
2. **Nothing out of scope is extended.** No new canvas work, no new assistant capability, no
   analytics collection, no trending research, no new learning loop. Where an in-scope milestone
   would have touched them (e.g. adding analytics to the learning page), it does not.
3. The earlier U0–U10 specification required these as deliverables. That requirement is
   **superseded**; the matrix marks those rows `NOT APPLICABLE — superseded by M0–M5 spec`.

This is the only substantive conflict between the two specifications. The second, smaller one is the
branch name, retained as `feature/upgrade-u0-u10` for continuity.

---

## 19. Recommended implementation sequence

```text
M0    audit + baseline + formatting/SECURITY commits        ← this milestone
M0.5  consent, egress gateway, endpoint classification, SSRF enforcement
M1    music library → local analysis → licensing → shared speech timeline → ducking
M2    webcam detection → tracking → layouts (needs M1 timeline)
M3    video understanding → plans → AI budget → diagnostics (needs M1/M2 signals)
M4a   YouTube: OAuth correctness, audience declaration, resumable/reconciliation
M4b   Instagram: eligibility, OAuth, resumable upload, isolation
M5    regression, security, performance, acceptance, release package
```

Ordering constraints that are not negotiable:

- The shared speech timeline (M1) must precede webcam layout coordination (M2 §6.5) and creative
  planning (M3), or a second detector gets built.
- The egress gateway (M0.5) must precede M1's AI music-selection call and M3's planning calls, or
  those calls ship ungoverned.
- Rights confirmation and licensing (M1 + M0.5) must precede any publish path change in M4a.
- Queue lanes (introduced with M1's workload) must precede M4a's reconciliation, so a blocked upload
  cannot stall music analysis.

---

## 20. Evidence index

| Claim class | Where the evidence lives |
|---|---|
| Test counts | §13; `docs/baseline-ci-evidence.md` |
| Timings | `docs/BENCHMARK-BASELINE.json` |
| Egress | `docs/EGRESS-INVENTORY.md` |
| Security | `docs/SECURITY-AUDIT.md` |
| External facts | `docs/EXTERNAL-CONSTRAINTS.md` |
| Milestone state | `docs/UPGRADE-LEDGER.md` |
| Feature status | `docs/feature-coverage-matrix.md` |
