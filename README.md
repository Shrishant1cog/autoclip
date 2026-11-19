# AutoClip

**Open-source, local-first AI video clipper.** Long video in → ranked, caption-burned, speaker-tracked 9:16 clips out — and, if you connect one, straight onto YouTube.

[![CI](https://github.com/Shrishant1cog/autoclip/actions/workflows/ci.yml/badge.svg)](https://github.com/Shrishant1cog/autoclip/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)

Paste a YouTube link or drop a file. AutoClip transcribes it, asks a language model where the moments worth clipping are, reframes them to vertical while tracking whoever is speaking, burns in animated captions, validates the render, and publishes it.

No AutoClip account, no sign-up, no watermarks, no subscription. Your source video never goes to an AI provider — only the transcript *text* does. The one exception is YouTube publishing, which is opt-in: AutoClip talks to YouTube using *your* Google account, and only when you connect it.

---

## Why this exists

Existing open-source clippers stop at "works on my machine" — no UI, janky reframing, ugly captions. AutoClip ships the whole loop: ingest → clips → review → export, and then the parts that make it usable unattended: many providers, many keys, many accounts and channels, a visual workflow builder, real resource accounting, and a restart you can see.

Three ways to run it:

- **Fully local** — Whisper + Ollama. Nothing leaves your machine, no API costs.
- **Bring your own key** — 16 providers, with multi-key pools and automatic fallback between them.
- **External speech** — an ElevenLabs key (Settings → Keys) switches transcription to Scribe: a 4-hour video transcribes in minutes instead of hours. The `auto` engine prefers it and falls back to local Whisper on any failure. Optional ElevenLabs voiceover can narrate clips.

Only transcript *text* is ever sent to a text provider — never video or audio. Audio is sent to ElevenLabs only when its transcription (or voiceover) is enabled; with `engine: local` and voiceover off, nothing is sent at all.

## Status

Working end to end: ingest, transcription, highlight detection across 16 providers with fallback chains, speaker-tracked reframing, four caption styles, export at three aspect ratios, duplicate-safe YouTube publishing, and thirteen screens in the UI.

Verified against real footage and a real channel — see [what "verified" means](#what-has-and-hasnt-been-verified) and [`.planning/VALIDATION-REPORT.md`](.planning/VALIDATION-REPORT.md).

Pre-1.0 (`0.1.0.dev0`). The reframe quality bar hasn't been validated against a fixed golden set yet, which is the gate for tagging v0.1.0.

## Requirements

| | |
|---|---|
| **Python** | 3.11 or 3.12 — **not 3.13.** MediaPipe publishes no 3.13 wheels and the reframe stage needs it. |
| **ffmpeg** | A *full* build with `libass` and `libx264`. Both `ffmpeg` and `ffprobe` on PATH. See below — the default package is the wrong one on macOS and Windows. |
| **Node** | 20+ (CI uses 22), to build the UI. Not needed at runtime. |
| **GPU** | Optional. NVIDIA or Apple Silicon speeds up transcription several-fold; CPU works, just slower. |

`autoclip doctor` checks all of this and tells you exactly what to fix. Run it before anything else.

### Installing ffmpeg correctly

Captions are burned in with **libass**, and on two platforms the obvious package doesn't include it. It installs cleanly, then fails to burn a single caption.

**macOS** — Homebrew split the formula; the plain one is a reduced build:

```bash
brew install ffmpeg-full
```

If you already installed the plain one: `brew unlink ffmpeg && brew link --force --overwrite ffmpeg-full`.

**Windows** — install the *full* build, not `Gyan.FFmpeg.Essentials`:

```bash
winget install Gyan.FFmpeg
```

**Linux** — the distro package is fine:

```bash
sudo apt install ffmpeg
```

CI checks for the `ass` **filter** rather than grepping the version banner for "libass", because not every build prints its configure line — and the filter is what the export stage actually calls.

## Quickstart

```bash
git clone https://github.com/Shrishant1cog/autoclip.git
```

```bash
cd autoclip && uv venv --python 3.11 && uv pip install -e ".[dev]"
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

That opens `http://localhost:8000`. If you don't use [uv](https://docs.astral.sh/uv/), a plain `python -m venv .venv` and `pip install -e ".[dev]"` works the same way.

On Windows there is also a launcher that does the whole sequence for you —
`start-autoclip.bat` in the repository root. It starts Ollama if it isn't
already answering, checks that the virtualenv and the frontend build are
there, starts the server, and opens the browser once it is healthy.

### Add a provider

Clip selection needs a language model. Either paste a key in **Settings → Keys**, or:

```bash
autoclip config set-secret anthropic
```

The value is prompted for, never taken as an argument — it stays out of your shell history and out of the process list.

Keys go into your OS keyring — Credential Manager, Keychain, or Secret Service — never into a config file. If no keyring backend exists, AutoClip falls back to a file **and says so**, in the UI and in `doctor`.

For a fully local setup, install [Ollama](https://ollama.com) and pull a model instead:

```bash
ollama pull llama3.1:8b
```

Clip quality tracks model quality closely. A 7B model returns valid JSON full of mediocre picks; a frontier model is noticeably better at spotting a real hook. That's the honest trade for running offline.

### Optional extras

```bash
uv pip install -e ".[gpu]"
```

CUDA runtime libraries for NVIDIA GPUs. Install these if `doctor` reports that CTranslate2 can't see your GPU — pip puts them somewhere the OS loader doesn't search, and AutoClip registers the location itself. On macOS this deliberately installs nothing: there's no CUDA there, and Apple Silicon takes the CPU path.

```bash
uv pip install -e ".[diarization]"
```

Speaker diarization via WhisperX — what lets the reframe stage cut to whoever is talking in a multi-person video. Pulls PyTorch (large), and needs a HuggingFace token plus acceptance of the gated pyannote model licences.

### Docker

The guaranteed path — ffmpeg, Python version, and fonts all pinned:

```bash
docker compose -f docker/compose.yaml up --build
```

```bash
docker compose -f docker/compose.yaml --profile gpu up --build
```

The port is bound to loopback on purpose: AutoClip has no authentication, so it must not be reachable from the network by default.

## Using it

Everything the UI does is also on the CLI:

| command | does |
|---|---|
| `autoclip doctor` | check this machine and explain what's missing |
| `autoclip serve` | start the web app |
| `autoclip init` | create the data directory and initialise the database |
| `autoclip clip <url\|file>` | run the whole pipeline and export |
| `autoclip jobs` | list recent jobs |
| `autoclip duplicates` | skip repeat YouTube uploads (`--dry-run` to only report) |
| `autoclip providers` | check which providers are reachable |
| `autoclip styles` | list caption presets |
| `autoclip resources` | show what AutoClip is using: disk, tokens, ffmpeg time |
| `autoclip cleanup` | reclaim disk space according to the retention settings |
| `autoclip fetch-models` | download the ML bundles the reframe stage needs |
| `autoclip update-ytdlp` | update yt-dlp after a YouTube change |
| `autoclip config show` | print settings (secrets are never displayed) |
| `autoclip config path` | print the path to `config.json` |
| `autoclip config set-secret <name>` | store an API key or token |
| `autoclip config delete-secret <name>` | remove a stored secret |
| `autoclip version` | print the version |

`autoclip clip` takes overrides for the things you'd otherwise change in Settings: `--provider`, `--whisper-model`, `--max-clips`, `--style`, `--ratio`, `--diarize`, `--centre-crop`.

### The thirteen screens

| screen | what it is for |
|---|---|
| **Ingest** | Add a source — a YouTube link or a local file — and watch the job run. |
| **Clips** | The clip library: every clip, its render, its publish state, and a re-validate action. |
| **Review** | Trim handles, caption-style edits, the crop path, and re-export. |
| **Job progress** | Live stage-by-stage progress over SSE, with cancel and retry. |
| **Providers** | All 16 presets, hosted and local, with each key pool's real health. |
| **Channels** | Every Google account, every channel under it, each channel's publishing policy. |
| **Routing** | The ten content categories the classifier assigns, and the rules that send each one to a channel. |
| **Batches** | Queue many sources at once, pause, cancel, retry the failures. |
| **Workflows** | The visual workflow builder — pan/zoom canvas, node palette, live wiring, run history. |
| **Assistant** | A chat that sees your clips, jobs, failures, channels and settings — and nothing else. |
| **Trends** | Real YouTube signal, not a generated trend line. |
| **Recovery** | What failed, why, and what will fix it. |
| **Settings** | Providers, keys, transcription, export, resources, YouTube. |

### Duplicate upload protection

AutoClip never publishes the same clip twice. Every upload is checked against
the others before it reaches YouTube:

- the worker checks each upload against the other rows for the same clip, so a
  re-export, a second "Export again", or a retried job is skipped automatically;
- `autoclip duplicates` (or `python scripts/detect_duplicate_uploads.py`) finds
  the wider set — byte-identical exported files and, with `--by-title`, repeated
  titles — and **skips** them by default. Use `--dry-run` to only report.

Skipped uploads stay visible in the clip library with the badge
`skipped (duplicate)`; nothing is deleted and nothing is published.

### Caption styles

| style | look |
|---|---|
| `bold_pop` | chunky white, heavy outline, spoken word grows and turns yellow |
| `karaoke_fill` | words fill with colour exactly as they're spoken |
| `clean_lower` | minimal lower third, no animation |
| `boxed` | high-contrast text on a solid block |

Caption fonts (Anton, Inter) are bundled under the SIL Open Font License, so nothing is fetched at runtime.

## How it works

```
ingest → prepare → transcribe → highlights → reframe → captions → export
```

Each stage writes artifacts to `~/.autoclip/work/{job_id}/`, so a retry resumes at the stage that failed rather than starting over. Two decisions carry most of the design:

**Highlight detection returns word indices, not timestamps.** Models are unreliable at arithmetic and completely reliable at copying a number they can see. Timing is looked up from measured word timings afterwards.

**Crop paths never interpolate across a cut.** Shots are detected first and framed independently. Panning through an edit is the most obvious sign of an auto-reframed video.

[ARCHITECTURE.md](docs/ARCHITECTURE.md) covers the rest, including why several odd-looking choices exist.

### Where your data lives

Everything is under one directory — `~/.autoclip` on macOS/Linux,
`%USERPROFILE%\.autoclip` on Windows. Override it with the `AUTOCLIP_HOME`
environment variable.

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

### Configuration

Settings live in `config.json` and are editable from **Settings** in the UI or
by hand. The sections are `active_provider`, `providers`, `whisper`,
`transcription`, `clips`, `ingest`, `export`, `resources` and `youtube`.

```bash
autoclip config show    # print the whole thing as JSON, secrets excluded
```

The `resources` section is worth knowing about, because it is what keeps an
unattended install from filling a disk:

| setting | default | what it bounds |
|---|---|---|
| `ffmpeg_threads` | `0` (ffmpeg's own default) | threads per ffmpeg process |
| `max_parallel_ffmpeg` | `2` | ffmpeg processes running at once, app-wide |
| `work_retention_days` | `7` | how long a finished job's scratch directory is kept |
| `export_retention_days` | `0` (forever) | how long a *published* clip's file is kept |
| `raw_retention_days` | `0` (forever) | how long a downloaded video is kept |
| `cleanup_on_start` | `true` | run the cleanup pass when the server starts |
| `max_output_tokens` | `4096` | tokens the model may return for one detection call |
| `max_llm_calls_per_job` | `0` (unlimited) | detection calls per job |

Only *published* exports are ever reclaimed. An unpublished clip is your own
work and is never deleted automatically.

### Publishing to YouTube

Open the **Channels** screen and press *Connect a Google account*. AutoClip requests exactly
two scopes — `youtube.upload` and `youtube.readonly` — and stores the refresh
token in your OS keyring. It will not silently widen a token's permissions.

Each channel has its own publishing policy: privacy, YouTube category, title
suffix, whether it publishes automatically, and whether it is the default. A
channel with automatic publishing **off** is never published to by a fan-out.

## Troubleshooting

Everything here is a real failure hit during development, not hypothetical.

**`autoclip doctor` says Python is wrong.** You're on 3.13. MediaPipe has no wheels for it. `uv venv --python 3.11`.

**Transcription fails with "Library cublas64_12.dll is not found".** The CUDA runtime libraries aren't installed. `uv pip install -e ".[gpu]"`. AutoClip registers their location itself — pip installs them somewhere the OS loader doesn't search, which is why the error is so unhelpful.

**"Requested int8_float16 compute type, but the target device does not support..."** Clear `whisper.compute_type` in `~/.autoclip/config.json` and let AutoClip choose. It queries the backend for what's actually supported rather than guessing from your GPU model.

**Captions don't appear in exports, or ffmpeg says "No such filter: ass".** Your ffmpeg has no libass. `doctor` reports this and prints the right command for your platform. On macOS that means `brew install ffmpeg-full`, not `brew install ffmpeg`; on Windows the full Gyan build, not "essentials".

**YouTube downloads fail with a bot check.** As of 2026, YouTube blocks most anonymous downloads and proof-of-origin tokens no longer clear it. Set **Settings → Ingest → cookies from browser** to a browser you're signed into, and **close that browser** first — it locks its cookie database while running. Uploading a file always works and needs none of this.

**Exports are slower than expected.** Check `doctor` for GPU encoding. A build can list `h264_nvenc` and still be unusable if your driver is older than the NVENC API it was compiled against; AutoClip probes this and falls back to CPU encoding, which is identical quality and just slower.

**No sound in the review player.** Click **Test audio** under the player. It measures the actual signal leaving the video element and tells you whether the problem is in AutoClip or between your browser and your speakers.

**A job says "failed" with an error you don't recognise.** The **Recovery** screen explains what went wrong and what will fix it. Every API failure carries the same JSON shape — `{detail, code, hint, retryable}` — with a stable code the UI branches on.

**The server died and a job says "running".** It was interrupted. AutoClip requeues interrupted work on startup and records the restart; `/api/restarts` shows what was recovered and which jobs, by id.

## What has and hasn't been verified

**Has been:** the full pipeline on real talking-head footage, asserted end to end — 1080×1920 h264/yuv420p output, AAC at −14 LUFS, crop segments tiling each clip without gaps, captions burned in, framing correctly following a cut to a second speaker. Run it yourself:

```bash
AUTOCLIP_E2E_MEDIA=/path/to/clip.mp4 pytest -m e2e
```

Those 24 tests are skipped without that variable — the gate is deliberate, because synthetic colour bars pass where real footage fails. `scripts/make_e2e_media.py` cuts a suitable three-minute segment out of a video already in your media library and runs the suite against it, so the skip count can be driven to zero with one command:

```bash
python scripts/make_e2e_media.py --run
```

**Has also been:** the whole autonomous platform, run against the real database,
the real ffmpeg, the real Gemini key and a real YouTube channel. 672 unit and
integration tests, 14 migrations verified against a WAL-safe copy of the real
database, and a final end-to-end job that produced three clips, three
`ffprobe`-confirmed 1080×1920 MP4s and three published videos, each confirmed
through YouTube's own API. The numbers and the method are in
[`.planning/VALIDATION-REPORT.md`](.planning/VALIDATION-REPORT.md).

**Hasn't been:** the reframe acceptance bar — no visible jitter, no cut-off faces, speaker on screen ≥95% of speaking time — against a fixed three-video golden set. The mechanics have unit coverage, but "looks right on footage I picked" isn't the bar. This is the gate for v0.1.0.

Also unverified: whether the clip *picks* are good. That's a judgement call about your material and your model, and no test settles it.

## Non-goals

Deliberate, not oversights:

- **No direct posting** to TikTok/Instagram. Their APIs are approval-gated; AutoClip exports files for those. YouTube is the exception: AutoClip can publish to a channel you connect, with duplicate protection enabled by default.
- **No cloud version, no AutoClip account, no telemetry.**
- **No timeline editor** beyond trim handles and caption edits.
- **No DRM circumvention**, ever.

## Contributing

Prompts and caption styles are the highest-leverage places to start, and neither needs deep knowledge of the codebase — `backend/autoclip/prompts/highlight_v1.txt` is plain text and affects output quality more than most code changes. See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Legal

AutoClip bundles [yt-dlp](https://github.com/yt-dlp/yt-dlp). **Only download content you own or have the rights to process.** AutoClip contains no workarounds for DRM or paywalled content and never will.

## License

MIT — see [LICENSE](LICENSE). Bundled caption fonts (Anton, Inter) are under the SIL Open Font License.
