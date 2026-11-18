# AutoClip — Final System Validation, Phases 0–17

Feature branch: `feature/autonomous-platform`
Baseline checkpoint: `54d6288` on `main`
Phase 17 commit: *(see the phase log — this report is written before the final push)*

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

Fifteen phases, fifteen commits, each one pushed before the next began.

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

The suite grew from **362 passing** at the Phase 1 baseline to **658 passing**
at the end of Phase 17 — 296 new tests, no test deleted or weakened.

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

---

## 3. The real database, at the end

Schema version **12**, foreign-key check clean, 296 rows of real work:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `sources` | 8 | `workflows` | 6 |
| `jobs` | 11 | `workflow_runs` | 4 |
| `clips` | 32 | `workflow_node_runs` | 8 |
| `exports` | 52 | `batches` | 1 |
| `youtube_uploads` | 52 | `notifications` | 36 |
| `google_accounts` | 1 | `youtube_channels` | 1 |
| `job_resources` | 3 | `app_restarts` | 3 |

Job outcomes: **5 done, 2 failed, 3 cancelled, 1 running**.
Clip outcomes: **32 exported** — every clip that was found made it to a render.
Upload outcomes: **32 published, 20 skipped as duplicates**.

The three failures are honest failures with honest messages — a 56-second test
video that genuinely contains no self-contained highlight. The twenty skipped
uploads are the duplicate guard working: the same clip re-exported was
recognised and not published twice.

---

## 4. The migrations, and why they were safe

Twelve migrations, every one of them additive and every one of them verified
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
resumed. Two of the three restarts in the history are restarts that had real
work to recover, and the third — the clean start — says "nothing was in
flight", which is the honest answer for a normal boot.

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

**Additive migrations only.** Twelve of them, each verified against a copy of
the real database with row counts compared and a foreign-key check run.

---

## 9. The defects the live runs found — the real return on the work

Thirteen phases found something the tests had not. This is the number worth
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

Eighteen phases. Fifteen feature commits, each pushed before the next began.
The suite went from 362 to 658 tests, and every phase passed the same six
gates. The real database holds 32 published clips, 52 exports, 52 upload
rows, 6 workflows, 36 notifications and a clean foreign-key check at schema
version 12.

The platform is local-first, multi-provider, multi-key, multi-account and
multi-channel, with a native visual workflow builder, real resource
accounting, honest failure reporting, and a restart that is recorded and
shown rather than silently swallowed.

Twenty-two defects were found by running the thing against real data, and
every one of them is fixed with a regression test. The three failures in the
job history are honest failures with honest messages — a 56-second test video
that genuinely contains no self-contained highlight. The twenty skipped
uploads are the duplicate guard working.

Two items remain, both outside the code and both named in §10: the YouTube
quota increase (a manual Google account action) and one duplicate video to
delete from the user's channel (the stored token lacks the delete scope, and
widening it is the user's decision to make).
