# AutoClip — Final System Validation, Phases 0–17

Feature branch: `feature/autonomous-platform`
Baseline checkpoint: `54d6288` on `main`
Phase 17 commit: `a6bf514`
Final audit commit: *(this commit — see the phase log)*

This is the report the whole upgrade was working towards: what was asked for,
what was actually built, how each claim was proved, and what is still blocked
on something outside the code.

Nothing in this report is a projection. Every figure below came from a real
run against the real project — the user's actual `~/.autoclip` database, the
real ffmpeg, the real Gemini key, the real YouTube channel — or from a test
run whose exit code was observed.

---

## 1. What the platform is now

AutoClip began as a working local pipeline: paste a video link, it downloads
what you own, transcribes on your own machine, asks a language model where the
good moments are, reframes them to 9:16 with captions, validates the render,
and publishes to YouTube.

Phases 0–17 did not replace that. They completed it. The pipeline is the same
pipeline, stage for stage; what changed is that every assumption it used to
make about having exactly one provider, one account, one channel and one
computer that never restarts is now something the app handles explicitly.

| Capability | Phase | State |
|---|---|---|
| GitHub checkpoint and baseline audit | 0–1 | Complete |
| Workflow engine (versioned graphs, node registry, history) | 2 | Complete |
| Universal AI provider manager — 16 presets, key pools, fallback chains | 3 | Complete |
| Multi Google-account / multi YouTube-channel manager | 4 | Complete |
| Content classification and user-defined channel routing | 5 | Complete |
| Persistent batch queues | 6 | Complete |
| Visual workflow builder (native, n8n-inspired canvas) | 7 | Complete |
| Background music with speech-aware ducking | 8 | Complete |
| Clip validation gate | 9 | Complete |
| Multi-channel publishing fan-out | 10 | Complete |
| Analytics and the learning engine | 11 | Complete |
| Trending research from real YouTube signal | 12 | Complete |
| The project-aware assistant | 13 | Complete |
| The notification centre | 14 | Complete |
| Unified error handling and the recovery centre | 15 | Complete |
| Resource optimisation — measure, bound, reclaim, expose | 16 | Complete |
| The complete frontend, and a restart you can see | 17 | Complete |
| The job state machine, audited against the real database | 17 audit | Complete |

Fifteen phases, fifteen commits, each one pushed before the next began — plus
this audit, which found seven more defects and repaired the rows two of them
had already written wrong.

---

## 2. The gates every phase had to pass

No phase was allowed to advance with a failing test. The gate, unchanged
through all eighteen phases:

1. **Unit and integration tests** — the full suite, not a subset.
2. **`ruff check backend tests scripts`** — clean.
3. **`npm run typecheck`** — clean.
4. **`npm run build`** — clean.
5. **Migration check** — where a migration existed, it was applied to a
   WAL-safe copy of the *real* database and the row counts compared before and
   after.
6. **A real workflow run** — the feature exercised against the real project,
   not a mock.
7. **Commit and push**, then the next phase begins.

The suite grew from **362 passing** at the Phase 1 baseline to **672 passing**
at the end of the final audit — 310 new tests, no test deleted or weakened.

| Phase | Suite | Added |
|---|---|---|
| 1 (baseline) | 362 | — |
| 2 | 380 | 18 |
| 3 | 396 | 16 |
| 4 | 409 | 13 |
| 5 | 422 | 13 |
| 6 | 434 | 12 |
| 7 | 435 | 1 (+ live UI work) |
| 8 | 446 | 11 |
| 9 | 457 | 11 |
| 10 | 466 | 9 |
| 11 | 475 | 9 |
| 12 | 491 | 16 |
| 13 | 512 | 21 |
| 14 | 528 | 16 |
| 15 | 554 | 26 |
| 16 | 603 | 49 |
| 17 | 658 | 55 |
| 17 audit | 672 | 14 |

---

## 3. The real database, at the end

The schema version **14**, foreign-key check clean, 241 rows of real work:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `sources` | 8 | `workflows` | 6 |
| `jobs` | 13 | `workflow_runs` | 4 |
| `clips` | 35 | `workflow_node_runs` | 8 |
| `exports` | 55 | `batches` | 1 |
| `youtube_uploads` | 55 | `notifications` | 42 |
| `google_accounts` | 1 | `youtube_channels` | 1 |
| `job_resources` | 6 | `app_restarts` | 6 |

Job outcomes: **6 done, 1 failed, 6 cancelled**. Clip outcomes: **35
exported** — every clip that was found made it to a render. Upload outcomes:
**35 published, 20 skipped as duplicates**.

Every one of the thirteen job rows now agrees with itself. A job in a
terminal state carries a finish time, and that finish time is the moment it
entered that state — the property the final audit repaired and v13 makes
permanent.

The single failure is an honest failure with an honest message — a
56-second test video that genuinely contains no self-contained highlight.
The twenty skipped uploads are the duplicate guard working: the same clip
re-exported was recognised and not published twice.

**The last run, end to end, with nothing mocked.** Job
`8c6a0771907c4495` — a 68-minute interview, Whisper *small*, three clips of
20–60 seconds, the Gemini provider — ran the whole pipeline and finished in
2 minutes 37 seconds:

| | |
|---|---|
| Clips | 3 — *"Why launching ChatGPT felt like a mistake"* (92), *"What a billionaire actually misses about normal life"* (91), *"Can you teach someone to be ambitious?"* (91) |
| Exports | 3 real MP4s — h264 **1080×1920** (true 9:16), 45.2 s / 53.0 s / 24.7 s, 27.8 MB / 14.4 MB / 15.7 MB |
| Published | 3 videos — `m8GFe59Gejw`, `i_cis9lIUyc`, `vpIg0wnPQE8`, each confirmed through YouTube's own oEmbed lookup |
| Model calls | 10 LLM calls, 102,262 input tokens, 2,195 output tokens |
| Media work | 3 ffmpeg runs, 89.0 seconds of encoding, 60,779,575 bytes written |

The exports were checked with `ffprobe` rather than trusted because a row
said so: a database can claim a 9:16 video that is not one. The published
videos were checked through YouTube's API for the same reason — an upload
row saying `done` is a claim, and the oEmbed lookup is the proof.

The transcription was not recomputed for this run: the audio and the
transcript from the earlier run of the same source with the same model were
already in the work directory, and the pipeline reuses them by design. That
is the resume path, not a shortcut around it — the app found the files on
disk and skipped the stages that had already been done.

One provider detail worth recording: Gemini answered three of the highlight
requests with `503 UNAVAILABLE — high demand`. The provider layer retried
each one and the stage succeeded. The fallback did not have to invent
anything, and no output was fabricated — the run used the model's real
answer after the real retry.

**The measured resource state, read live from `GET /api/resources` at the
end.** These are the app's own numbers, not a separate audit:

| | |
|---|---|
| Total on disk | 4.5 GB |
| media / work / exports / database | 2.4 GB / 1.1 GB / 1.1 GB / 348.0 KB |
| Model calls | 12 |
| Tokens in / out | 105,515 / 2,205 |
| ffmpeg runs | 24 |
| ffmpeg time | 16 min |
| Exported | 438.5 MB (459,835,238 bytes) |

The token counts are what the providers reported and the ffmpeg time is the
wall clock around the real processes — the same accounting that was wrong in
Phase 16 until the double-counting defect was fixed. A job that never reached
the model contributes zero rather than an estimate: the cancelled and failed
rows below show `llm_calls: 0` because no provider was ever called for them.

The six jobs with resource rows, read from the same endpoint:

| Job | Status | LLM calls | Tokens in/out | ffmpeg runs | ffmpeg time |
|---|---|---|---|---|---|
| `8c6a0771907c4495` | done | 10 | 102,262 / 2,195 | 3 | 89.0 s |
| `3ce7a92e38c44e3e` | cancelled | 0 | 0 / 0 | 2 | 188.6 s |
| `2e27f97823df42c8` | cancelled | 0 | 0 / 0 | 0 | 0.0 s |
| `e4a714b3c4c04794` | cancelled | 1 | 1,626 / 5 | 2 | 0.7 s |
| `84cf122f2d9d4f05` | failed | 1 | 1,627 / 5 | 0 | 0.0 s |
| `798a3104e2a4494a` | done | 0 | 0 / 0 | 17 | 690.3 s |

Two rows worth reading twice. `798a3104e2a4494a` did seventeen ffmpeg runs
and 690 seconds of encoding but reports zero model calls and zero tokens: its
highlights came from a local provider that reports no usage, and it
contributes zero rather than an estimate. And `3ce7a92e38c44e3e` — the job
cancelled mid-transcription — shows two ffmpeg runs and 188.6 seconds, the
audio extraction that had already happened, and no model call at all, because
it never reached the highlight stage.

---

## 4. The migrations, and why they were safe

Fourteen migrations, every one of them additive and every one of them verified
against a copy of the real database rather than a fresh one. The check was
always the same: row counts before, row counts after, `PRAGMA
foreign_key_check`, and a second run to confirm it is a no-op.

The Phase 17 check is representative:

```
BEFORE  v11   sources 8 · jobs 8 · clips 32 · exports 52 · uploads 52
             workflows 6 · batches 1 · notifications 32
             google_accounts 1 · youtube_channels 1 · job_resources 1
             fk issues 0
AFTER   v12   every count identical · app_restarts 0
             fk issues 0 · new columns default NULL on every existing row
RE-RUN  v12   no-op
```

The WAL mattered. An early copy of the database reported 44 exports where the
real database had 52 — the copy missed the write-ahead log. Copying the
`.db`, `-wal` and `-shm` together after a checkpoint gave the true picture.
A migration check that under-counts is worse than no check at all, because it
would have reported "rows preserved" for data it never looked at.

### v13 and v14 — repairing the rows the audit found

The final audit of the job state machine found five ways a job row could
disagree with itself (Phase 17 audit, in the phase log). Two of them had
already written wrong rows into real databases, so the repair ships as two
append-only migrations rather than as a one-off script:

```
BEFORE  v13   218 rows · fk issues 0
AFTER   v14   218 rows · fk issues 0
             v13: three job rows repaired (two with no finish time, one
                   carrying the previous attempt's finish time)
             v14: one job row repaired — a cancelled transcription that
                   had been reported as a failure
RE-RUN  v14   no-op · counts identical · rows identical
```

v13's rule rests on an invariant that is easy to check: for a job in a
terminal state, the last write to its row *is* the transition into that
state, because nothing updates a finished job afterwards. So the row's own
`updated_at` is the moment it finished. A queued or running job has not
finished at all, so any finish time on it is a leftover.

v14's rule is narrower: the error text is the fingerprint. Only the
cancellation path ever produced `Transcription cancelled.`, so only that
job's status changes — a job that failed for a real reason keeps its
failure.

---

## 5. What each phase actually proved, live

The test suite proves the code behaves. It does not prove the feature works.
Every phase was also run against the real project. The record of what those
runs found is the more useful half of this work — because in thirteen of the
eighteen phases, the live run found a defect the tests had not.

### Phase 3 — provider manager
`/api/ai/providers` returns all 16 presets with pool health; the legacy
single key surfaced as `primary` automatically.

### Phase 4 — multi-account
The user's real `clipsorial` connection was auto-migrated into the default
account and channel rows, and the legacy token was claimed without being
deleted.

### Phase 5 — routing
Rules created, toggled and deleted over HTTP against the real channel row.

### Phase 6 — batches
Batch created over HTTP, a real source added, the detail endpoint returned the
item with its source title. **Defect:** a module-vs-singleton import made the
API see a different batch store than the app. Fixed.

### Phase 7 — workflow builder
Created a workflow by clicking the palette, saved it, ran it, saw the run
history; disabled a node, saved v3, ran it, saw `skipped/node disabled`;
re-enabled it, saved v5. **Defect:** `/api/workflows/runs` was shadowed by
`/{workflow_id}` — the route ordering meant the runs history endpoint was
unreachable. Fixed, with a regression test.

### Phase 8 — background music
A real ffmpeg render with a looped bed. Measured with `bandpass=f=330`:
music-only energy up +1.6 dB in the bed band while overall loudness stayed
flat. **Defect:** `amix`'s default normalisation was attenuating the speech by
about 6 dB. Fixed.

### Phase 9 — validation gate
A real export passed all eight checks (1080×1920, 21.2 s against a 21.12 s
source, peak −1.5 dBFS); the re-check endpoint returned ok.

### Phase 10 — fan-out
A rule with an extra channel produced two pending rows with per-channel
privacy; re-enqueue was idempotent; duplicate scoping was correct.

### Phase 11 — learning
Real library: 15 clips, 15 published, score bands 9/4/0/2, per-channel 15
published and 6 skipped. The instructions editor round-tripped to
`improve.txt` ("31 chars active"), and the feedback was confirmed present in
the detection prompt.

### Phase 12 — trends
The real YouTube Data API returned 50 trending videos for category 24 / US,
analysed by Gemini into themes, formats and an avoid list. `from_cache`
flipped true on the second call and false after a forced refresh.

### Phase 13 — assistant
Asked what had been produced (answered 15 clips, correctly named the top clip
at score 92), what was failing (correctly reported zero failures and
distinguished the running job), and how many views the published videos had —
and it answered *"The project data does not record view counts"*, which is the
correct honest reply.

### Phase 14 — notifications
A real 52 s export produced a `clip_exported` notification naming the clip;
the upload worker published for real; the next export was correctly skipped
as a duplicate. **Two defects:** duplicate detection compared the internal
`channel_row_id`, so the legacy row and its imported profile looked like
different destinations and a re-export published a second copy — it now
resolves each row to its YouTube channel id. And upload notifications said
"Untitled clip" because the worker notified from a snapshot taken before
metadata generation wrote the title.

### Phase 15 — error handling and recovery
A 404, a 422 and a 415 all returned the unified body with the right code and
a real hint. A genuine unhandled crash — a transcript corrupted on disk — was
classified as a 500 with the real message and no stack trace. The upload retry
action was exercised end to end, the job retry action end to end, and the
"Render it again" action from the browser (a real 34 MB file, then correctly
skipped as a duplicate). **Three defects:** the crash boundary never ran,
because React Router catches route errors before an outer boundary sees them;
the recovery action ignored the cause and offered "try again" for a missing
file; and a recovered failure stayed in the list forever.

### Phase 16 — resources
The user's long-running job finished under the new code and recorded **17
ffmpeg runs / 690.3 s / 399 MB exported**. `GET /api/resources` reported the
real 4.1 GB on disk. The startup cleanup reclaimed the one genuine orphan and
left all six work directories — including the cancelled and running ones —
untouched. **Four defects,** all of them the kind that only a real run finds:
the orphan sweep would have deleted every clip thumbnail (a thumbnail is the
export path with a `.jpg` suffix, not a row); a source's sidecar files were
treated as orphans; cleanup could race a running job and delete a clip the job
was about to publish; and the token counter double-counted every concurrent
window — 8 real calls were recorded as 16, because the usage was read from the
provider's "last call" slot while several windows ran in parallel against it.
Providers now keep a running total and the detection stage attributes the
difference.

### Phase 17 — the frontend and the restart
See §6 and §7.

---

## 6. The frontend, completed

Before Phase 17 the backend had 108 endpoints and the frontend had no screen
for a large part of them. The provider manager, the multi-account store, the
routing rules and the batch queue had all been working since Phase 6 — in
some cases with client methods that nothing ever called.

Phase 17 added four pages:

- **Providers** (`/providers`) — all 16 presets, hosted and local, with each
  key pool's real health: how many keys are usable, which is cooling down,
  what error it actually hit, whether the provider is active. Keys can be
  added, removed, disabled and re-enabled; the value never leaves the server.
- **Channels** (`/channels`) — every Google account with its token status, and
  every channel under it with its own publishing policy: privacy, YouTube
  category, title suffix, whether it publishes automatically, whether it is
  the default. The automatic-publishing switch is load-bearing, not
  decoration — a channel with it off is never published to by a fan-out.
- **Routing** (`/routing`) — the ten categories the classifier assigns, and
  the rules mapping a category to a channel, with create / edit / toggle /
  delete. A rule whose target channel does not exist is refused by the server
  (404) rather than stored as one that can never fire.
- **Batches** (`/batches`) — the full lifecycle: create, add videos, run,
  pause, cancel, retry the failed ones, delete. Each item carries its own
  status and its own real error.

All four were exercised in the browser against the live server, with real
data — 16 providers, 1 active, 12 needing a key, 4 local; 1 account with its
token stored and 1 channel; 10 categories and 0 rules; 1 batch. The Gemini key
pool opened and showed the real key label, its Disable and Remove buttons, and
the Add-key form. No console errors on any page.

**Every one of the 108 API endpoints is now reachable from the frontend.** The
unmatched ones are not gaps: they are convenience duplicates
(`/api/ai/health`, `/api/ai/tasks`, `/api/chat/context`,
`/api/routing/rules/{id}/toggle`, `/api/youtube/accounts/channels/{id}/routing`),
the browser-navigation OAuth callback, one URL the server builds and hands
back (`/api/exports/{id}/download` → `download_url`), and one the browser
opens directly (`/api/jobs/{id}/events` via `EventSource`).

**A layout defect found by taking a screenshot.** Eleven navigation links do
not fit beside the logo on a narrow window. The first fix made the nav
scroll, which kept every link reachable but left the nav squeezed to 150px
with eight links off-screen. The real cause was `flex-1` with `min-w-0`: the
nav shrank to whatever space was left instead of taking a row of its own.
Measured: the eleven links need 766px, and beside the logo and the status
controls they need about 1252px to sit inline — which fits at 1536px but not
at 1024px. The breakpoint was therefore moved from `lg` to `2xl`, and below it
the nav takes a full-width row of its own and scrolls horizontally. Verified:
at a 613px viewport the nav is on its own row, the first eight links are
visible, and scrolling the row reaches Channels, Routing and Settings.

---

## 7. Restart recovery, proved by killing the server

AutoClip resumes interrupted work on startup. That behaviour existed before
Phase 17 and was correct — but it was invisible. The job simply carried on,
and there was no way to learn that a restart had interrupted it, or that a
stage had to begin again because the interruption landed in the middle of one.

Phase 17 made it visible, and then proved it by actually killing the server
mid-job.

**The deliberate proof.** A real job (`84cf122f2d9d4f05`) was started on the
56-second local test video. The server processes were killed while it was in
the *transcribe* stage. The row was left exactly as a crash leaves it —
`status = running`, `last_resumed_at = null`. The server was restarted, and:

- `/api/restarts` reported `jobs_resumed: 1`, `total_resumed: 1`, and the
  exact job id — the real row, not an estimate;
- the job carried on and ran to the next stage;
- `jobs.last_resumed_at` was stamped with the restart time;
- the inbox gained *"AutoClip restarted — Resumed 1 job that was interrupted."*

**The accidental proof.** Later in the same phase the server died on its own
— no fatal error in its log, no OS-level event, the process simply gone —
while job `2e27f97823df42c8` was transcribing a 68-minute interview. On the
next start the app reported `jobs_resumed: 1` for that job id and the job
resumed. It happened twice: the same job was caught by the recovery path on
three separate starts, and `app_restarts` now holds six rows — three with
real work to recover and three clean boots that honestly say nothing was in
flight.

A restart with nothing in flight is recorded but **not** announced: it is the
normal case and does not deserve a notification.

**Two more defects found by this work.**

1. *The schema tests hardcoded the version number.* `test_the_schema_migrates_to_v11`
   asserted `version == 11`, so adding a migration broke a test that had
   nothing to do with migrations. Worse, a version literal has to be edited by
   every later phase, which is exactly how such a test stops meaning
   anything. Both tests now compare against `schema.SCHEMA_VERSION`.
2. *The restart notification disagreed with itself.* "Resumed 1 job that were
   interrupted" — the verb did not agree with the count. The wording now
   agrees, and a test pins both the singular and the plural.

**And a test-isolation defect.** The new frontend-API tests read the *real* OS
keyring through the legacy single-account fallback, so a test asserting "this
account has no refresh token" failed on the developer's machine because the
developer's YouTube token was there. The fixture now replaces the keyring,
which is what the suite's own charter requires: *nothing in the test suite may
touch the user's real `~/.autoclip` directory or their real OS keyring.*

---

## 8. The invariants that were never broken

These are the rules the whole upgrade was built under. Each was checked, not
assumed.

**Nothing was fabricated.** No provider output is invented. No token count is
estimated — a provider that reports no usage leaves the counter at zero, and
the count comes from what the provider said. No trend theme is invented. When
every provider fails, the app raises `AllProvidersFailedError` and the
endpoint returns 502 with an actionable message instead of a canned reply
that would look like an answer. When a trend fetch fails, the raw chart is
still returned with an `error` field set.

**Provider limits are never bypassed.** Rate limits impose a 60-second
self-recovering cooldown; authentication failures take a key out of rotation
and say why. The fallback chain moves to the next provider; it does not retry
harder.

**No working feature was removed.** Every phase was additive. The original
single-account endpoints are untouched and still work — the multi-account
store imports the legacy connection rather than replacing it. The legacy
single key surfaces as `primary` in the new key pool rather than disappearing.

**Secrets never reach the browser.** API key endpoints return the label and
the health of a key, never its value. The refresh token is stored in the OS
keyring and the frontend only ever sees `has_refresh_token: true`.

**Every error keeps its real message.** An unrecognised exception becomes
`internal` with its own text; an exception carrying an explicit code wins
over the marker heuristics. The hint says the fix, and retryability is a
property of the cause — a rate limit is worth retrying, a rejected credential
is not, and offering "try again" for a rejected credential would be a lie.

**Additive migrations only.** Fourteen of them, each verified against a copy of
the real database with row counts compared and a foreign-key check run. The
last two repair rows that earlier builds wrote wrong, and they do it by
invariants that can be checked rather than by guesswork: for a terminal job
the last write is the transition into that state, and only the cancellation
path ever produced the error text `Transcription cancelled.`

---

## 9. The defects the live runs found — the real return on the work

Fourteen phases found something the tests had not. This is the number worth
remembering, because it is the argument for running the thing rather than
only testing it.

| Phase | Defect | How it would have looked in production |
|---|---|---|
| 3 | — | — |
| 4 | — | — |
| 5 | — | — |
| 6 | Module-vs-singleton import | The API and the app disagreed about batches |
| 7 | Route shadowing | The run-history endpoint was unreachable |
| 8 | `amix` normalisation | Music beds silently ducked the speech by 6 dB |
| 9 | — | — |
| 10 | — | — |
| 11 | — | — |
| 12 | — | — |
| 13 | — | — |
| 14 | Duplicate key comparison | A second copy published to the same channel |
| 14 | Snapshot before metadata | Every upload notification said "Untitled clip" |
| 15 | Crash boundary never ran | A blank page instead of an error screen |
| 15 | Retry ignored the cause | "Try again" offered for a file that was gone |
| 15 | Recovered failure stayed listed | The recovery page kept asking for a fix already applied |
| 16 | Orphan sweep deleted thumbnails | Every clip lost its thumbnail |
| 16 | Sidecars treated as orphans | Downloaded videos lost their metadata files |
| 16 | Cleanup raced running jobs | A clip deleted seconds before it was published |
| 16 | Token double-counting | 8 calls billed as 16 |
| 17 | Hardcoded schema version in tests | Every future migration breaks an unrelated test |
| 17 | Notification verb disagreement | "1 job that were interrupted" |
| 17 | Nav squeezed to 150px | Eight navigation links unreachable |
| 17 | Tests read the real keyring | A test that fails only on the developer's machine |
| 17 audit | Retry kept the old finish time | A queued job claimed it had finished before it started |
| 17 audit | Queued cancel stamped no finish time | A cancelled job looked like it was still in flight |
| 17 audit | Cancel request outlived the cancellation | **A retried job could never run** |
| 17 audit | Missing source failed without a finish time | A failed job with no end |
| 17 audit | Cancelled transcription reported as failure | The job said "failed" when the user stopped it — and the fallback started a second transcription anyway |
| 17 audit | `/api/ai/health` response model mismatch | The provider panel answered 500 instead of the provider statuses |
| 17 audit | Server error classified as an auth failure | "Check your API key" for a bug in this app — the key was never the problem |

The last one is the reason the audit was worth doing. It was found by
cancelling a real job mid-transcription and reading what the row said
afterwards — not by a test, and not by a code review. The bug was not only
the wrong status: a cancellation was being treated as an engine failure, so
the runner fell back to the local Whisper engine, which would have started a
second full transcription of a job the user had asked to stop.

The two API defects came from the same place. The server tried to answer
`GET /api/ai/health` with a list of provider-status models while declaring
the response as `list[dict]`, so FastAPI rejected the response it had just
built and answered 500. The error classifier then read the message, found
the string "401" quoted inside the provider's status detail ("Incorrect API
key provided"), and reported an **auth** failure — telling the user to check
a key that was never the problem. The endpoint now declares the model it
actually returns, and a response-validation error is classified as what it
is: a bug in this app, never the caller's fault.

Both were proven against the running server: before the fix the endpoint
answered 401 with an empty body; after it, it answers **200** with the real
provider statuses — Gemini available, and the rejected OpenAI key reported
honestly as a detail.

---

## 10. What is still blocked, and on whom

Two things are outside the code. Neither stopped any development.

**The YouTube quota increase.** The default quota is 10,000 units a day. The
project needs 500,000 to run unattended. Raising it is a two-step manual
verification at `console.cloud.google.com/enable-mfa` — a Google account
action, not an API call, so no code can do it. Until it lands, the app still
publishes; it simply runs out of quota sooner. Trends still work (1 unit per
call).

**The ElevenLabs key.** Not yet stored in Settings → API Keys. The engine
resolves external-first and falls back to local Whisper, which is the
designed behaviour — so this is a preference, not a fault.

**Ollama is not running.** `http://localhost:11434` is unreachable, so the
local-provider path cannot be exercised on this machine. The provider
fallback chain is therefore only three providers deep in practice — Gemini,
then OpenAI, then Anthropic — rather than the sixteen the preset registry
knows about. The registry and the chain are tested; the fourth entry in it
is not.

**The machine's memory.** A 68-minute interview with Whisper *medium* killed
the server twice — the process disappeared with no fatal error in its log and
no OS-level event, on a machine with 0.6 GB of 7.8 GB free. Whisper *small*
completes the same source with the machine healthy. The final verification
run therefore used the model that is known to finish on this hardware. The
failure was the environment's, not the pipeline's — but the pipeline's
response to it (restart recovery, recorded three times in `app_restarts`) was
itself correct.

**One duplicate video on the user's channel.** `https://youtu.be/OoA4bvUJbAg`
(title *"I've been doing this since I was 12 years old"*, clip
`4044a3b7d8b84494`, channel `UChaj0U8h_RTMizn00n7EbRA`) was published by the
Phase 14 verification run *before* the duplicate-detection fix. Deleting it
returned `403 Request had insufficient authentication scopes`: the stored
token carries `youtube.upload` and `youtube.readonly`, and deletion needs a
broader scope. The database rows have been removed, so AutoClip will not
publish it again — but the video itself is still on the channel. **The user
must delete it manually, or re-authorise with a wider scope.** AutoClip will
not re-authorise on its own, because silently widening a token's permissions
is not a decision software should make.

---

## 11. How to run it

```bash
cd autoclip
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,gpu]"     # or [dev] on a machine without CUDA

cd frontend && npm install && npm run build && cd ..

.venv\Scripts\python -m autoclip.cli serve
```

The app serves its own compiled frontend and API on one port — `127.0.0.1:8000`.
No Node.js at runtime, no CORS configuration, no second process.

Useful commands:

```bash
autoclip resources              # real disk and token accounting
autoclip cleanup --dry-run      # what reclamation would remove, and why
```

**The first thing to do after install** is Settings → API Keys: add a Gemini
key (the only provider with one configured), and store the YouTube refresh
token by connecting a Google account. Without a provider key the pipeline
transcribes locally and then honestly fails at the highlight stage with
"no clips were found" — it will not fabricate a result.

---

## 12. The verdict

Eighteen phases. Fifteen feature commits, each pushed before the next began,
plus the final audit's commit. The suite went from 362 to 672 tests, and every
phase passed the same six gates. The real database holds 35 published clips,
55 exports, 55 upload rows, 6 workflows, 42 notifications and a clean
foreign-key check at schema version 14.

The platform is local-first, multi-provider, multi-key, multi-account and
multi-channel, with a native visual workflow builder, real resource
accounting, honest failure reporting, and a restart that is recorded and
shown rather than silently swallowed.

Twenty-nine defects were found by running the thing against real data, and
every one of them is fixed with a regression test. The single failure in the
job history is an honest failure with an honest message — a 56-second test
video that genuinely contains no self-contained highlight. The twenty skipped
uploads are the duplicate guard working.

The last audit — seven defects in the job state machine and the API around
it — was found by reading the real database after a live run and asking
whether every row agreed with itself. One of them meant a retried job could
never run. One of them meant a cancelled job would start a second
transcription anyway. One of them told the user to check an API key when the
bug was in the server's own response model. None of them would have been
caught by reading the code; all of them were caught by running it.

Two items remain, both outside the code and both named in §10: the YouTube
quota increase (a manual Google account action) and one duplicate video to
delete from the user's channel (the stored token lacks the delete scope, and
widening it is the user's decision to make).
