# Changelog

Notable changes. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [semantic versioning](https://semver.org/) once 0.1.0 ships.

## Unreleased

Everything so far. The first tagged release waits on the reframe acceptance bar
being validated against a fixed golden video set — see
[the README](README.md#what-has-and-hasnt-been-verified).

### Added

- **Pipeline** — ingest (YouTube via yt-dlp, or file upload), audio preparation,
  transcription with word-level timings, LLM highlight detection, speaker-tracked
  reframing, ASS caption generation, and export at 9:16 / 1:1 / 16:9.
- **Sixteen LLM providers** behind one interface — Anthropic, OpenAI-compatible
  (any `base_url`, covering OpenRouter, Groq, DeepSeek, LM Studio), Google
  Gemini, and Ollama, plus eleven more presets. Each provider carries a pool of
  keys: rotation picks the healthiest, auth failures disable a key, rate limits
  impose a self-recovering cooldown, and capability-aware fallback chains move
  to the next provider on a transient failure. Malformed responses are retried
  once with the validation error attached.
- **Reframing** with shot detection, MediaPipe face tracking, active-speaker
  selection from mouth movement correlated against diarization, and a
  One Euro Filter with dead zone and velocity clamp. Shots are framed as TRACK,
  WIDE, or GENERAL; subjects too far apart to crop get a fitted frame over a
  blurred fill rather than someone being cut out.
- **Four caption styles** with bundled OFL fonts, so nothing is fetched at runtime.
- **Web UI** — thirteen screens: ingest, live job progress over SSE, clip review
  with word-snapping trim handles and caption editing, export, a provider and
  key-pool manager, Google accounts and YouTube channels, content routing,
  batch queues, a visual workflow builder, a project-aware assistant, trend
  research, a recovery centre, and settings.
- **Workflow engine** — versioned graphs over a node registry (six pipeline
  stages plus conditional and log nodes), with validation, per-node run history,
  and a native n8n-inspired canvas to build them.
- **Multi-account and multi-channel publishing** — several Google accounts, each
  with its own channels, each channel with its own privacy, category, title
  suffix and auto-publish policy.
- **Content classification and routing** — a clip is classified into one of ten
  categories and routed to the channels you assign that category to.
- **Batch queues** — queue many sources, watch them run, pause, cancel, retry the
  failures.
- **Resource accounting and reclamation** — disk, token and ffmpeg-time totals
  per job and overall, bounded by retention settings, with a cleanup pass that
  never touches unpublished work.
- **Notification centre and recovery centre** — one inbox for what happened, and
  a screen that explains what failed and what will fix it.
- **Restart recovery** — interrupted work is resumed on startup and the restart
  is recorded with the real counts and the exact job ids involved.
- **Resumable stages.** Artifacts live on disk per job, so a retry restarts at the
  stage that failed.
- **`autoclip doctor`** — probes ffmpeg features, GPU acceleration, compute-type
  support, and provider reachability, and explains what to do about each.
- **End-to-end test** against real media, covering every stage with only the
  language model's answer scripted.
- **YouTube publishing.** AutoClip can publish exported clips to a connected
  channel: a title, description and tags generated from the clip's own
  subtitles, a custom thumbnail drawn locally with ffmpeg and rendered *after*
  the title is known so the picture and the video always say the same thing, and
  a duplicate guard that skips a clip already published rather than uploading it
  twice. Credentials live in the OS keyring, never in the config file.
- **ElevenLabs speech services.** With a key in Settings → Keys, transcription
  runs on Scribe (a 4-hour video takes minutes instead of hours, ~$0.20/hour);
  the `auto` engine prefers it and falls back to local Whisper on any failure.
  The word list Scribe returns is mapped onto AutoClip's transcript — non-word
  entries dropped, speaker labels normalised, segments synthesised — so clip
  boundaries and captions are unchanged. Optional voiceover narrates clips over
  a ducked original track; off by default.
- **Highlight fallback covers transient outages.** A provider 503, rate limit,
  or timeout used to fail the whole job because only credential errors
  triggered the local fallback. Transient failures now degrade to a
  health-checked Ollama fallback, and transcription got the same
  external-first treatment.

### Notable fixes during development

Each of these was found by running the thing, not by reading it:

- **Compute-type selection asked the wrong question.** Inferring from CUDA compute
  capability chose `int8_float16` on a GTX 1060, which advertises fp16 to CUDA and
  then can't use it. Selection now queries CTranslate2 for what it actually
  supports.
- **CUDA libraries were installed and unloadable.** pip places them where the OS
  loader doesn't look, so the model loaded and died at first inference. AutoClip
  registers the directories itself.
- **`h264_nvenc` being listed is not proof it works.** A build can require a newer
  NVENC API than the driver provides. Encoder selection now runs a one-frame probe.
- **Filtergraph paths need two levels of escaping**, and quoting interacts badly
  with apostrophes. Renders now use bare relative names with ffmpeg's working
  directory set, removing the problem instead of out-escaping it.
- **The wheel shipped with no UI.** hatchling honours `.gitignore`, and the built
  frontend is gitignored; declared via `artifacts`.
- **Retry could never clear a job's error message**, because the update helper
  skipped `None` values.
- **Progress ran backwards** at every stage boundary, double-counting each
  completed stage.
- **Progress could still tick backwards** mid-stage, when a stage reported a
  lower fraction than the one before it. The bar is now clamped to its
  high-water mark, so it only ever moves forward.
- **A 9:16 preview rendered nearly square.** A max-height clamp shortened the box
  without narrowing it, silently violating the declared aspect ratio.
- **The preview showed different framing from the export**, centre-cropping while
  the renderer tracked the speaker.
