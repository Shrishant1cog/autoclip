"""Settings persistence and secret storage.

Non-secret settings live in ``<root>/config.json`` as plain JSON so users can
hand-edit them. Secrets (LLM API keys, the HuggingFace token) are kept out of
that file and stored in the OS keyring — Credential Manager on Windows, Keychain
on macOS, Secret Service on Linux.

If no keyring backend is available (headless Linux, some Docker images), we fall
back to writing secrets into ``config.json`` with restrictive permissions and
set :attr:`Settings.insecure_secret_storage` so the UI and ``autoclip doctor``
can warn about it. Silently downgrading security without telling the user is the
thing we're trying to avoid.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

from . import paths

log = logging.getLogger(__name__)

KEYRING_SERVICE = "autoclip"

#: Keyring service used before the rename. Read from as a fallback so keys
#: stored under the old name aren't silently lost; writes always use the new one.
LEGACY_KEYRING_SERVICE = "clipforge"

ProviderName = Literal["anthropic", "openai", "gemini", "ollama"]

#: Providers that authenticate with an API key. Ollama runs locally and needs none.
#: ElevenLabs is keyed too (speech STT/TTS) even though it is not an LLM highlight
#: provider — the Settings API uses this list for its secret endpoints.
KEYED_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "gemini", "elevenlabs")

#: Extra secrets that aren't tied to a provider.
HF_TOKEN_KEY = "huggingface_token"

#: ElevenLabs API key. Read through the same keyring as the provider keys, plus
#: the aliases the ElevenLabs CLI itself writes (keyring entry and .env file).
ELEVENLABS_API_KEY = "elevenlabs"

#: YouTube OAuth client secret and the long-lived refresh token.
YOUTUBE_CLIENT_SECRET_KEY = "youtube_client_secret"
YOUTUBE_REFRESH_TOKEN_KEY = "youtube_refresh_token"


class ProviderSettings(BaseModel):
    """Per-provider configuration. The API key itself is never stored here."""

    model: str = ""
    #: Only meaningful for the OpenAI-compatible provider. Pointing this at
    #: OpenRouter, Groq, DeepSeek, or a local LM Studio server is the supported
    #: way to use any other vendor.
    base_url: str | None = None


class WhisperSettings(BaseModel):
    #: tiny | base | small | medium | large-v3 — or a local path.
    model: str = "small"
    #: Force a CTranslate2 compute type. Empty means "let hardware detection pick".
    compute_type: str = ""
    #: ISO 639-1 code, or empty for auto-detection.
    language: str = ""
    #: Run WhisperX diarization to label words by speaker. Needs the
    #: ``diarization`` extra and a HuggingFace token.
    diarization: bool = False


class TranscriptionSettings(BaseModel):
    """Which speech-to-text engine runs, and how.

    ``auto`` prefers the external engine (ElevenLabs Scribe) and falls back to
    local faster-whisper on any failure — auth, rate limit, outage, timeout, or
    an unusable result. ``elevenlabs`` and ``local`` pin the engine and disable
    fallback between them.
    """

    engine: Literal["auto", "elevenlabs", "local"] = "auto"
    #: Scribe model id. ``scribe_v2`` is the stable general model.
    elevenlabs_model: str = "scribe_v2"
    #: Ask Scribe for speaker labels (replaces the local WhisperX path when the
    #: external engine runs). Free of extra charge, included in the call.
    diarize: bool = True
    #: Clip narration. ``off`` keeps today's behaviour exactly; ``muxed``
    #: synthesizes a voiceover per clip and mixes it over the original audio.
    voiceover: Literal["off", "muxed"] = "off"
    #: ElevenLabs voice for narration. Empty = the CLI default (Rachel).
    voice_id: str = ""


class ClipSettings(BaseModel):
    min_duration_s: float = 20.0
    max_duration_s: float = 90.0
    max_clips: int = 10


class IngestSettings(BaseModel):
    #: yt-dlp format selector. Default caps at 1080p to keep downloads sane.
    ytdlp_format: str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]"
    #: Browser to pull YouTube cookies from ("chrome", "firefox", "edge", ...).
    #: As of 2026 most anonymous YouTube downloads hit a bot check that only
    #: browser cookies reliably clear, so this is a first-class setting.
    cookies_from_browser: str = ""
    #: Offer YouTube's own auto-captions as a fast path, skipping Whisper.
    prefer_youtube_captions: bool = False
    #: Where complete downloads are kept. Empty means ``<root>/raw/<source_id>``.
    #: Every link gets its own subdirectory, so downloads never collide.
    download_dir: str = ""


class ExportSettings(BaseModel):
    ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    caption_style: str = "bold_pop"
    #: Integrated loudness target in LUFS. -14 is the de-facto platform standard.
    loudness_lufs: float = -14.0
    #: Use h264_nvenc when the hardware supports it. Falls back to libx264.
    prefer_hardware_encoder: bool = True
    crf: int = 18
    #: Also write a .srt sidecar next to each exported clip.
    write_srt: bool = False
    #: Background music (Phase 8): file name inside ~/.autoclip/music/, or an
    #: absolute path. Empty = no bed. Looped to the clip duration when shorter.
    music_track: str = ""
    #: Music bed level relative to speech before ducking (0.0 - 1.0).
    music_volume: float = 0.15
    #: Duck the bed while speech is present (ffmpeg sidechaincompress).
    music_ducking: bool = True
    #: How far the bed drops when speech is detected, in dB (negative).
    ducking_amount_db: float = -12.0
    #: How quickly the bed ducks when speech starts, in milliseconds. A slow
    #: attack sounds musical; a fast one sounds like a fader move.
    ducking_attack_ms: int = 120
    #: How quickly the bed comes back up when speech stops, in milliseconds.
    ducking_release_ms: int = 350
    #: How the webcam and the gameplay sit together (M2).
    #:
    #: ``auto`` lets the planner decide from what it detects. ``above`` puts
    #: the webcam in a strip over the gameplay, ``corner`` overlays it in a
    #: corner, and ``gameplay_only`` never shows a webcam. A manual choice
    #: made for one source beats this setting for that source.
    layout: Literal["auto", "above", "corner", "gameplay_only"] = "auto"
    #: The webcam's share of the output height in the stacked layout. 0.40 is
    #: the preset — about forty per cent webcam, sixty per cent gameplay. It
    #: is a preference, not a rule.
    webcam_height_frac: float = Field(default=0.40, gt=0.0, le=0.85)
    #: Which corner the webcam sits in when the layout is ``corner``.
    webcam_position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-right"
    #: The webcam's share of the output width in the corner layout.
    webcam_corner_frac: float = Field(default=0.38, gt=0.0, le=1.0)


class ResourceSettings(BaseModel):
    """Bounds on what AutoClip is allowed to consume (Phase 16).

    Every field here has a default that preserves today's behaviour, so an
    existing install changes nothing until the user opts in. The defaults are
    chosen to be safe on a modest machine rather than fast on a large one:
    an autonomous install runs unattended for weeks, so the risk is filling a
    disk or saturating a CPU, not a render taking ten minutes longer.
    """

    #: ffmpeg worker threads per process. 0 leaves ffmpeg's own default, which
    #: is the core count — that oversubscribes badly when more than one ffmpeg
    #: is running at a time.
    ffmpeg_threads: int = Field(default=0, ge=0)
    #: How many ffmpeg processes may run at once across the whole app.
    #: At least one: with zero, nothing would ever render.
    max_parallel_ffmpeg: int = Field(default=2, ge=1)
    #: Days to keep a finished job's scratch directory (audio, transcript, crop
    #: paths). 0 keeps them forever. Failed jobs keep theirs regardless: it is
    #: what makes "run it again" resume instead of re-transcribe.
    work_retention_days: int = Field(default=7, ge=0)
    #: Days to keep a *published* clip's rendered file. 0 keeps everything.
    #: Only published exports are ever reclaimed — an unpublished clip is the
    #: user's own work and is never deleted automatically.
    export_retention_days: int = Field(default=0, ge=0)
    #: Days to keep a downloaded YouTube video. 0 keeps them forever.
    #: Uploaded files are never touched: they cannot be re-downloaded.
    raw_retention_days: int = Field(default=0, ge=0)
    #: Run the cleanup pass when the server starts.
    cleanup_on_start: bool = True
    #: Maximum tokens the model may return for one detection call. The
    #: providers' own defaults vary; one number here makes the cap explicit.
    max_output_tokens: int = Field(default=4096, ge=1)
    #: Maximum detection calls per job (one call per transcript window).
    #: 0 is unlimited. When the cap bites, the job says so rather than
    #: quietly analysing less of the video than it claims to.
    max_llm_calls_per_job: int = Field(default=0, ge=0)


class YouTubeSettings(BaseModel):
    """Upload destination and automation policy.

    The OAuth client secret and refresh token are secrets, stored in the OS
    keyring; only non-sensitive identifiers live here.
    """

    #: OAuth client id from a Google Cloud "Desktop app" credential.
    client_id: str = ""
    #: Must exactly match a redirect URI registered on the OAuth client.
    redirect_uri: str = "http://localhost:8000/api/youtube/callback"
    #: Upload automatically whenever a clip finishes exporting.
    auto_upload: bool = False
    privacy: Literal["private", "unlisted", "public"] = "public"
    #: YouTube category id. 24 = Entertainment, 20 = Gaming.
    category_id: str = "24"
    #: Filled by the OAuth callback so the header can name the channel
    #: without a network round trip on every page load.
    channel_id: str = ""
    channel_title: str = ""
    channel_url: str = ""
    connected_at: str = ""


class Settings(BaseModel):
    """Top-level persisted settings."""

    active_provider: ProviderName = "anthropic"
    providers: dict[str, ProviderSettings] = Field(
        default_factory=lambda: {
            "anthropic": ProviderSettings(model="claude-sonnet-5"),
            "openai": ProviderSettings(model="gpt-4o"),
            "gemini": ProviderSettings(model="gemini-3.5-flash"),
            "ollama": ProviderSettings(model="", base_url="http://localhost:11434"),
        }
    )
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    clips: ClipSettings = Field(default_factory=ClipSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    resources: ResourceSettings = Field(default_factory=ResourceSettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)

    #: Set when secrets had to be written to config.json because no keyring
    #: backend was usable. Surfaced as a warning in the UI and in `doctor`.
    insecure_secret_storage: bool = False
    #: Plaintext secret fallback. Empty whenever the keyring is working.
    #: A private attribute so it never round-trips through the public schema —
    #: `save()` writes it back explicitly.
    _fallback_secrets: dict[str, str] = PrivateAttr(default_factory=dict)

    model_config = {"extra": "ignore"}

    def provider(self, name: str | None = None) -> ProviderSettings:
        """Return settings for ``name``, defaulting to the active provider."""
        key = name or self.active_provider
        return self.providers.setdefault(key, ProviderSettings())


def load() -> Settings:
    """Read settings from disk, falling back to defaults on a missing or bad file."""
    path = paths.config_path()
    if not path.exists():
        return Settings()
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s (%s); falling back to defaults.", path, exc)
        return Settings()

    fallback = raw.pop("_fallback_secrets", {}) or {}
    settings = Settings.model_validate(raw)
    settings._fallback_secrets = fallback
    return settings


def save(settings: Settings) -> None:
    """Write settings to disk atomically, with owner-only permissions."""
    paths.ensure_layout()
    path = paths.config_path()

    payload = settings.model_dump(mode="json")
    if settings._fallback_secrets:
        payload["_fallback_secrets"] = settings._fallback_secrets

    # Write to a sibling temp file then replace, so an interrupted write can
    # never leave a truncated config behind.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _restrict_permissions(tmp)
    os.replace(tmp, path)


def _restrict_permissions(path: Path) -> None:
    """Best-effort chmod 600. A no-op where the platform doesn't support it."""
    with contextlib.suppress(OSError):  # platform dependent
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------


def _keyring():
    """Return a usable keyring module, or None if no backend works.

    Importing ``keyring`` succeeds even with no backend; the failure only shows
    up on first use, so we probe explicitly.
    """
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
    except ImportError:  # pragma: no cover - keyring is a hard dependency
        return None

    try:
        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
    except Exception:  # pragma: no cover - backend probing can raise anything
        return None
    return keyring


def get_secret(key: str, settings: Settings | None = None) -> str | None:
    """Return a stored secret, or None if unset.

    ``key`` is a provider name for API keys, or :data:`HF_TOKEN_KEY`.
    """
    env_override = os.environ.get(f"AUTOCLIP_{key.upper()}_KEY")
    if env_override:
        return env_override

    kr = _keyring()
    if kr is not None:
        for service in (KEYRING_SERVICE, LEGACY_KEYRING_SERVICE):
            try:
                value = kr.get_password(service, key)
                if value:
                    return value
            except Exception as exc:  # pragma: no cover - backend dependent
                log.warning("Keyring read failed for %s: %s", key, exc)

        # The ElevenLabs CLI stores the key under its own service name when you
        # run `elevenlabs auth login`; read that rather than asking for a
        # second copy of the same key.
        if key == ELEVENLABS_API_KEY:
            try:
                value = kr.get_password("elevenlabs", "OAuth")
                if value:
                    return value
            except Exception as exc:  # pragma: no cover - backend dependent
                log.debug("ElevenLabs CLI keyring read failed: %s", exc)

    settings = settings if settings is not None else load()
    return settings._fallback_secrets.get(key) or None


def set_secret(key: str, value: str, settings: Settings | None = None) -> bool:
    """Store a secret. Returns True if it went to the keyring, False if to disk.

    A False return is not an error — it means the caller should surface the
    insecure-storage warning to the user.
    """
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, key, value)
            return True
        except Exception as exc:  # pragma: no cover - backend dependent
            log.warning("Keyring write failed for %s: %s", key, exc)

    settings = settings if settings is not None else load()
    settings._fallback_secrets[key] = value
    settings.insecure_secret_storage = True
    save(settings)
    return False


def delete_secret(key: str, settings: Settings | None = None) -> None:
    """Remove a secret from both the keyring and the plaintext fallback."""
    kr = _keyring()
    if kr is not None:
        # Backends raise when the entry is absent; deleting a missing secret is
        # not an error from the caller's point of view. Both services are cleared
        # so a delete can't leave a pre-rename copy behind to resurface.
        for service in (KEYRING_SERVICE, LEGACY_KEYRING_SERVICE):
            with contextlib.suppress(Exception):
                kr.delete_password(service, key)

    settings = settings if settings is not None else load()
    if settings._fallback_secrets.pop(key, None) is not None:
        settings.insecure_secret_storage = bool(settings._fallback_secrets)
        save(settings)
