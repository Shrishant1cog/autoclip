# AutoClip — Installation and Upgrade (M5)

**Written:** 2026-11-20, for the M0→M5 upgrade on `feature/upgrade-u0-u10`.

This covers three things: installing AutoClip from scratch, upgrading an existing install to this
build, and — the part that actually matters — what the upgrade changes about how AutoClip behaves,
so nobody discovers it by surprise.

---

## 1. Requirements

| | |
|---|---|
| **Python** | 3.11 or 3.12 — **not 3.13.** MediaPipe publishes no 3.13 wheels and the reframe stage needs it. |
| **ffmpeg** | A *full* build with `libass` and `libx264`. Both `ffmpeg` and `ffprobe` on PATH. |
| **Node** | 20+ (CI uses 22), to build the UI. Not needed at runtime. |
| **GPU** | Optional. NVIDIA or Apple Silicon speeds up transcription several-fold; CPU works, just slower. |
| **Disk** | ~2 GB for the Python environment and the ML bundles, plus whatever you keep. |

### Installing ffmpeg correctly

Captions are burned in with **libass**, and on two platforms the obvious package does not include
it. It installs cleanly, then fails to burn a single caption.

**macOS** — Homebrew split the formula; the plain one is a reduced build:

```bash
brew install ffmpeg-full
```

**Windows** — install the *full* build, not `Gyan.FFmpeg.Essentials`:

```bash
winget install Gyan.FFmpeg
```

**Linux** — the distro package is fine:

```bash
sudo apt install ffmpeg
```

CI checks for the `ass` **filter** rather than grepping the version banner for "libass", because
not every build prints its configure line — and the filter is what the export stage actually calls.

---

## 2. Installing from scratch

### 2.1 The Docker path — the guaranteed one

```bash
docker compose -f docker/compose.yaml up --build
```

```bash
docker compose -f docker/compose.yaml --profile gpu up --build
```

The port is bound to loopback on purpose: AutoClip has no authentication, so it must not be
reachable from the network by default.

### 2.2 The source path

```bash
git clone https://github.com/Shrishant1cog/autoclip.git
cd autoclip
```

```bash
uv venv --python 3.11 && uv pip install -e ".[dev]"
```

```bash
cd frontend && npm install && npm run build && cd ..
```

```bash
autoclip doctor
```

```bash
autoclip serve
```

That opens `http://localhost:8000`. If you don't use [uv](https://docs.astral.sh/uv/), a plain
`python -m venv .venv` and `pip install -e ".[dev]"` works the same way.

On Windows there is also a launcher that does the whole sequence for you —
`start-autoclip.bat` in the repository root. It starts Ollama if it isn't already answering, checks
that the virtualenv and the frontend build are there, starts the server, and opens the browser once
it is healthy.

### 2.3 Optional extras

```bash
uv pip install -e ".[gpu]"          # CUDA runtime libraries for NVIDIA GPUs
uv pip install -e ".[diarization]"  # speaker diarization via WhisperX
```

Neither is required. CI installs both with `--dry-run` on every run, so an unsatisfiable extra
cannot ship without being noticed.

---

## 3. Upgrading an existing install

### 3.1 The procedure

```bash
cd autoclip
git pull
uv pip install -e ".[dev]"
cd frontend && npm install && npm run build && cd ..
autoclip doctor
```

Then start AutoClip as usual. **The database migrates itself.** `db.init()` runs on every startup
and applies any outstanding migration before the API accepts a request, so there is no separate
upgrade command and no downtime window to plan around.

### 3.2 What the migration does

The schema is at **v27**. An install that was on v14 will apply thirteen migrations in order:

| Migration | What it adds |
|---|---|
| v15 | `egress_consents`, `egress_log` — the consent decisions and the readable transfer log |
| v16 | `music_folders`, `music_tracks`, `music_licenses` — the music library |
| v17 | `source_layouts` — the saved webcam layout choice, per source |
| v18 | `job_ai_budget` — the AI call counters, which persist across job retries |
| v19 | `creative_plans` — the structured creative plan |
| v20 | `music_preferences` — the per-scope music preferences, plus the three clip columns that record which music each clip ended up with |
| v21 | `clips.diagnostics_json` — the objective quality measurements (a column, not a table: there is one report per clip) |
| v22 | The two per-account OAuth columns on `youtube_accounts` |
| v23 | The publishing-policy columns on `youtube_channels` and `youtube_uploads` |
| v24 | `youtube_quota` — the day's upload-cost ledger — plus the six resumable-upload columns |
| v25 | The three reconciliation columns on `youtube_uploads`, and a rebuild of that table to widen its status check |
| v26 | `routing_decisions` — the recorded routing decisions |
| v27 | `instagram_accounts` and `instagram_uploads` — two tables of their own, on purpose |

**Migrations are append-only, ordered, and transactional one at a time.** `migrate()` refuses to
open a database that is *newer* than the build, so running an old AutoClip against a new database
fails loudly instead of corrupting it.

### 3.3 Before you upgrade: back up the database

AutoClip never destroys user data during an upgrade — every migration is additive or a
rebuild-plus-copy. But "never destroys" is a claim about the code, and a copy of
`autoclip.db` costs nothing:

```bash
# macOS / Linux
cp ~/.autoclip/autoclip.db ~/.autoclip/autoclip.db.backup-$(date +%Y%m%d)

# Windows (PowerShell)
Copy-Item "$env:USERPROFILE\.autoclip\autoclip.db" "$env:USERPROFILE\.autoclip\autoclip.db.backup"
```

> **Known gap.** AutoClip does **not** take this backup itself before migrating. That is recorded
> in the known-limitations list as an open item, not as a fixed one.

### 3.4 What the upgrade changes about behaviour

This is the section to read before upgrading a production install.

| Change | What you will notice | What to do |
|---|---|---|
| **The audience declaration is now mandatory for publishing.** `madeForKids` is a tri-state — *undecided* / *false* / *true*. A channel that existed before the upgrade has no value, so it is *undecided*, and **an upload to it is refused**. | An upload fails with "the audience has not been decided for this channel". | Open the channel's settings and choose *yes* or *no*. A per-upload override also works. This is deliberate: the declaration is a legal statement about children, and AutoClip will not make it for you. |
| **New channels and new uploads default to `private`.** Stored privacy values are never rewritten. | Nothing, unless you create a channel or upload row now. | If you want a different default, change it on the channel. |
| **External processing now asks first.** Transcription to ElevenLabs, voiceover, AI highlight detection, the creative planner and AI music selection all require a recorded consent for the destination class. | The first external call raises *"external processing is blocked"* and the job falls back to local processing. | *Settings → External processing* → grant the operation. Loopback (a local Ollama) never needs a decision. |
| **A refused consent is an answer, not a failure.** | A job completes with local processing instead of failing. | Nothing — this is the intended behaviour. |
| **The music library is new.** It indexes the files you point it at and never copies, moves or deletes them. | *Settings → Music library.* | Point it at a folder. Every track starts with an **unknown** licence, and an unknown licence **blocks the export** until you say what it is. |
| **A music licence cannot be self-verified.** | The licence state list offers *unknown*, *you confirmed*, *incompatible* and *expired* — there is no *verified*. | *You confirmed* is an attestation, and the UI says so. |
| **The webcam layout is new and optional.** | *Settings → Layout* (and a per-source choice on the review screen). | Nothing. With no webcam found, the output is gameplay-only, which is what AutoClip did before. |
| **The clip score is now labelled a suggestion.** | Wherever a 0–100 score appears, it is called a *suggestion*. | Nothing — it was always the model's judgement, and now it says so. |
| **Instagram publishing is new.** | *Settings → Instagram.* | Optional. It needs your own Meta app, and it needs the account to be a professional account. |
| **The export changed.** The audio is now 128 kbps, and the MP4 carries no edit list. | The exported file is slightly smaller. | Nothing. Both changes were required to meet Instagram's documented Reel rules, and both were verified by measuring the rendered file. |
| **Re-exporting a clip now uses the music you chose.** | A clip exported from the review screen now carries the track you picked for it, and the bed ducks under the speech. | Nothing. Before this, a re-export silently used the *global* export setting and ignored your per-clip choice — the choice was on the screen and in the database, and the file did not have it. |
| **A blocked music licence now says so.** | Exporting a clip whose track has an unknown, incompatible or expired licence returns *"that track's licence is …"* with the reason, instead of a render error. | Set the track's licence in *Settings → Music library*. The reason is the licensing rule's own wording, not a paraphrase. |

Nothing is deleted by any of this. Existing jobs, clips, exports, uploads, channels and settings
are all still there; the new fields start empty.

### 3.5 After the upgrade

```bash
autoclip doctor
```

`doctor` reports the Python version, the ffmpeg build and whether it can burn captions, the
encoder, the GPU, the keyring backend, and the schema version. It is the same check CI runs, and
it is the fastest way to tell whether the install is sound.

---

## 4. Where your data lives

Everything is under one directory — `~/.autoclip` on macOS/Linux,
`%USERPROFILE%\.autoclip` on Windows. Override it with the `AUTOCLIP_HOME` environment variable.

```
~/.autoclip/
├── autoclip.db        SQLite: jobs, clips, exports, uploads, channels, workflows
├── config.json        settings (never secrets, unless the keyring is unavailable)
├── media/{source_id}/ files you uploaded
├── raw/{source_id}/   complete YouTube downloads
├── work/{job_id}/     per-job scratch: audio, transcript, crop paths
├── exports/{job_id}/  rendered MP4s
└── music/             background music beds
```

**Secrets never go in `config.json`** unless the OS keyring is unavailable, and AutoClip says so
in the UI and in `doctor` when that happens.

---

## 5. Reproducible builds

| Tool | Pin | Where |
|---|---|---|
| `ruff` | `==0.17.5` | `pyproject.toml` — CI installs `.[dev]`, so the pin is the one honoured |
| Node | `22` | `.github/workflows/ci.yml` |
| Python | `3.11`, `3.12` | CI matrix |
| ffmpeg | Debian's (CI), the Gyan full build (Windows), `ffmpeg-full` (macOS) | CI installs the full build on every platform and checks for the `ass` filter |

The formatter was unpinned for the whole life of the project up to M0, which is how 38 files
shipped unformatted and the format gate failed on a clean checkout. It is pinned now, because a
gate that can change without a commit is not a gate.

---

## 6. If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `Database schema version 27 is newer than this AutoClip build supports (26)` | An old AutoClip is running against a migrated database. | Upgrade AutoClip. The database is fine; the binary is behind. |
| Captions do not appear, or ffmpeg says *"No such filter: ass"* | The ffmpeg build has no libass. | `doctor` prints the right command for your platform. On macOS: `brew install ffmpeg-full`. On Windows: the Gyan **full** build. |
| *"external processing is blocked"* | No consent decision for that operation and destination class. | *Settings → External processing*. Or set the transcription engine to *Local Whisper only*. |
| An upload refuses with *"the audience has not been decided"* | The channel's `madeForKids` is undecided — the state every pre-upgrade channel is in. | Choose *yes* or *no* on the channel, or set it per upload. |
| An export refuses with a music licence error | The track's licence is **unknown**, **incompatible** or **expired**. | Set the track's licence in *Settings → Music library*. *Verified* is deliberately not offered. |
| *"Transcription fails with Library cublas64_12.dll is not found"* | The CUDA runtime libraries are not installed. | `uv pip install -e ".[gpu]"`. |
| YouTube downloads fail with a bot check | As of 2026 YouTube blocks most anonymous downloads. | *Settings → Ingest → cookies from browser*, and **close that browser** first — it locks its cookie database while running. Uploading a file always works. |
| The server died and a job says "running" | It was interrupted. | AutoClip requeues interrupted work on startup and records the restart; `/api/restarts` shows what was recovered. |
