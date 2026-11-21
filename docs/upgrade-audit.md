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
| S7 | Low | ~~`ruff` unpinned (`>=0.7`) means the format gate can change under CI~~ — **CLOSED at M5**, pinned at `0.17.5` | `pyproject.toml:89` |

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

**Since this audit (M0):** the gaps above are closed — the consent and egress routes
(`privacy`, 3), the music routes (`music`, 19, covering the library, the licences, the
preferences and the formats), the webcam-layout routes (`layout`, 6), the creative-plan and
budget routes (`jobs`, 9) and the Instagram routes (`instagram`, 15) now exist. The count is
**21 routers and 162 routes**, counted from the decorators rather than from memory. Two gaps
remain open: there is no emergency-stop route, and a job can still only be cancelled or
retried, not paused and resumed.

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

**Since this audit (M0):** thirteen migrations have closed part of that list — v15 added
`egress_consents` and `egress_log`, v16 added `music_folders`, `music_tracks` and
`music_licenses`, v17 added `source_layouts`, v18 added `job_ai_budget`, v19 added
`creative_plans`, and v20 added `music_preferences` (plus the three clip columns that record
which music each clip ended up with). v21 added the `clips.diagnostics_json` column — no new
table, because there is exactly one report per clip and it is read with the clip. v22 added the
two per-account OAuth columns, v23 the publishing-policy columns on the channel and the upload,
v24 the `youtube_quota` ledger plus the six resumable-upload columns, v25 the three
reconciliation columns, and v26 the `routing_decisions` table. v27 added `instagram_accounts` and
`instagram_uploads` — two tables of their own, on purpose, because the spec requires the
platforms to be independent and a shared table would make one platform's failure land in the
other's rows. The schema is now at **v27 with 32 live tables** (measured against a migrated
database, not counted by hand). The gaps that remain — backup before migration, an
interrupted-migration test, provider usage and learning versions — are still open and are carried
in the ledger.

---

## 11. Pipeline and queue behaviour

**Pipeline.** `PipelineRunner` runs `prepare → transcribe → highlights → creative → reframe → captions →
export`. Each stage writes artifacts into `work/{job_id}/`, so a retry skips completed stages. Stage
implementation is delegated to `pipeline/<stage>.py`; the runner owns ordering, progress emission
(`_emit`), notices (`_set_notice`) and cancellation checks (`_check_cancelled`). The `creative` stage
was added in M3, between the highlights and the reframe, and it runs on the shared M1 timeline and the
shared shot list rather than on a second detector.

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

**Since the baseline (through M5.1).** The table above is the *M0 baseline* and is deliberately left
as it was measured. The current state is recorded per milestone in `docs/UPGRADE-LEDGER.md`; at
the end of M5.1 it is:

| Gate | At M0 (baseline) | At M5 (release) | At M5.1 |
|---|---|---|---|
| Unit selection — `-m "not slow and not golden and not e2e"` | 672 passed | **1,263 passed**, 61 deselected | **1,270 passed**, 69 deselected |
| Render selection — `-m "slow and not golden and not e2e"` | (included above) | **37 passed**, 1,287 deselected | **45 passed**, 1,294 deselected |
| **Total in the two CI selections** | **672** | **1,300** | **1,315** |
| Local full suite (Windows, excluding the e2e collection) | — | **1,300 passed** | **1,315 passed**, 534.88 s |
| `xfail` markers | 26 (the SSRF suite) | **0** | **0** |
| `ruff check .` | clean | **clean** | **clean** |
| `ruff format --check .` | **FAILED** — 38 of 147 files unformatted | **clean** — 226 files already formatted | **clean** — 227 files already formatted |
| `ruff` version | unpinned (`>=0.7`) | **pinned at `0.17.5`** (`pyproject.toml:89`) — committed as `4cf309b`, which closes **D15** and **T2** | unchanged |
| mypy | 14 errors in 10 files | **10 errors in 8 files** (tolerated by `continue-on-error`) | **10 errors in 8 files** — unchanged |
| Frontend `tsc -b && vite build` | not run locally at audit time | **green**, run locally and in CI | unchanged — no frontend file was touched |
| Docker build + health smoke | not run locally at audit time | **not run locally** — Docker is not installed on this machine; the CI `docker` job builds the image and smoke-tests `GET /api/health` | unchanged |

**The M5.1 column, against the M5 column.** M5.1 added **one test file** and **15 tests**: the
eight-case ducking matrix (`tests/test_ducking_matrix.py`, 8 tests), four unit tests for the
tri-state `ducking_intervals()` helper, two API-boundary contract tests and one filter-graph test.
**+7 in the unit selection and +8 in the render selection**, because the matrix is eight real
renders.

**The Linux leg was reproduced on the M5.1 tree too**, before the commit was pushed — WSL,
ffmpeg 7.0.2, Python 3.12.16, the same Python as the Ubuntu py3.12 leg. The counts are
**identical** on both platforms: 1,270 in the unit selection and 45 in the render selection, with
`ruff check` and `ruff format --check` clean on both.

**The ruff pin is the point of this row.** The baseline's format failure was not a style
preference: with no version pinned, the gate was evaluated against whatever ruff CI happened to
install, and the shipped tree did not satisfy it. Pinning the version makes the gate a
**property of the repository** rather than of the day it ran.

### 13.1 The CI runs on this branch, and what each failure was

The branch's CI history is part of the release evidence, because **both of its failures were real
defects** rather than flakes — one in the product, one in the CI itself. Each is recorded with its
cause and its fix.

| Run | Commit | Result | What happened | Cause | Fix |
|---|---|---|---|---|---|
| 4–17 | the M0–M4b commits | **success** | green | — | — |
| 18 | `5fc04cc` | **cancelled** | superseded by the next push | — | — |
| **19** | `4cf309b` | **failure** | the Ubuntu legs failed in **Unit tests**; Windows and macOS passed the same tests | **A test wrote to the owner's real OS keyring.** `tests/test_instagram.py::test_the_unified_setup_does_not_refuse_a_local_file` called `accounts_store.store_token(...)` without the keyring fixture. On Linux there is no OS keyring backend, so the token was never stored and the assertion that depended on it could not hold. The test passed on Windows and macOS **because those machines have a real keyring to write to** — the failure was a symptom, not the defect | `94c6d9c` — an **autouse** `isolated_keyring` fixture in `tests/conftest.py`, so no test in the suite can reach the owner's credential store |
| **20** | `94c6d9c` | **failure** | the Ubuntu **py3.12** leg failed at step 7, *"Verify ffmpeg can burn subtitles"*. Ubuntu py3.11, macOS, Windows and Docker all passed | **The check itself was wrong.** It piped the ffmpeg filter list into `grep -q`. `grep -q` exits at the first match, the producer then gets **SIGPIPE**, and GitHub runs bash steps with `set -o pipefail`, which turns that broken pipe into a failed step. The Ubuntu runner's ffmpeg 8 has a filter list large enough to fill the pipe, so CI reported that an ffmpeg **with** the `ass` filter did not have one — the job log shows `printf: Broken pipe` and then the `ass` filter listed on the very next line | the check now matches the list with bash's own pattern matching and never pipes. **The check was corrected, not removed**: a build genuinely without the `ass` filter still fails it |
| 21 | `64d253d` | **cancelled** | superseded by run 22 | — | — |
| 22, 23, 24, 25 | `cbcbe1c`, `ab9052e`, `2931059`, `822143e` | **success** | green on all six jobs — the four backend legs, the frontend build, and the Docker image with its health smoke test | — | — |

**Both failures were reproduced before they were fixed.** Run 19 was reproduced on a Linux
environment with no keyring backend, and run 20 was reproduced with a 320 KB filter list — the
old body fails it, the new body passes it, and a build without the `ass` filter still fails the
new body. A failure that is only fixed in CI is a failure that comes back.

**Every run on this branch since those two failures was green.**

### 13.2 Four product defects, found by running the application

The full-suite gates were green while the application was broken. These four defects were found
by **running the application and its gates**, not by reading the code, and each is now guarded by
a test that fails without the fix.

| # | Defect | Found by | Guard |
|---|---|---|---|
| 1 | The API export path ignored the user's music preference and passed no speech intervals, so the re-exported clip had neither the chosen track nor any ducking | clicking *Export this clip* on a clip with a track chosen | 7 regression tests in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix** |
| 2 | The timeline-driven ducking filtergraph was malformed — an output label in the middle of the bed's chain — and ffmpeg refused the whole graph | the export failing, with ffmpeg's own stderr in the response | 3 real-render tests in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix** |
| 3 | The sidechain fallback consumed one filter output twice, which **ffmpeg 9 accepts and ffmpeg 7 refuses** | the Linux CI leg, reproduced locally on ffmpeg 7.0.2 | the same 3 render tests, plus a **structural** check in `tests/test_music.py` that no filter output is consumed twice and no filter follows an output label — version-independent, so it catches the defect on any ffmpeg |
| 4 | **An empty speech timeline was indistinguishable from no timeline at all**, so a clip with no talking fell back to keying the ducking on the audio and the music was pulled down by whatever else the source contained | the **no-speech** case of the eight-case ducking matrix, at M5.1 | `tests/test_ducking_matrix.py::test_no_speech_means_no_ducking` — **fails without the fix**, at a measured ratio of 0.915 against a flat render — plus 4 unit tests for `ducking_intervals()` and 2 for the API boundary |

**Defect 3 is the one that would have shipped.** It rendered on the machine the code was written
on and would have failed on the CI runners and on every user with an ffmpeg older than 9. It was
caught by reproducing the Linux leg locally rather than assuming the two platforms agreed.

**Defect 4 was found by closing a matrix row, not by a report.** The eight-case ducking matrix
(MUS-31) was the last closeable PARTIAL row; writing it as eight **real renders** rather than
filter-level string checks is what exposed the conflation. The impact was small — **≤ 0.9 dB** on
a source carrying its own loud music — but the contract was violated at the API boundary, and the
webcam layout already treated an empty timeline as "no emphasis" without falling back. The fix
keeps the three answers apart: no timeline (`None`), a timeline that found no speech in this clip
(`[]`), and the speech itself.

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
| T2 | ~~`ruff` unpinned at `>=0.7`~~ — **CLOSED at M5**, pinned at `0.17.5` (`pyproject.toml:89`, commit `4cf309b`) | the format gate can no longer change under CI (D15) |
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
| Instagram API facts | `docs/INSTAGRAM-API-EVALUATION.md` |
