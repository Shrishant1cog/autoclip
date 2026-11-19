# Security

## Reporting a vulnerability

Please **don't** open a public issue for a security problem. Use GitHub's
[private vulnerability reporting](https://github.com/Shrishant1cog/autoclip/security/advisories/new)
instead, and I'll respond as quickly as I can.

## What AutoClip does with your data

Worth stating plainly, because "local-first" is easy to claim and easy to get wrong:

- **Your media can leave your machine, and you should know exactly when.** Three paths:
  1. **Speech-to-text.** With `transcription.engine` set to `"elevenlabs"`, the extracted audio is
     uploaded to ElevenLabs. With the default `"auto"`, it is uploaded **whenever an ElevenLabs API
     key is configured**, and local Whisper is used only when no key exists. Pinning
     `transcription.engine = "local"` keeps audio on the machine and disables the external engine
     entirely.
  2. **Highlight detection and the assistant.** Only the *transcript text* and your `improve.txt`
     standing instructions are sent to the configured LLM provider — never video or audio. Choosing
     Ollama sends nothing off the machine.
  3. **Publishing.** When you upload, the rendered clip and its metadata go to the YouTube API.
     Nothing is published unless you have connected an account and either enabled Auto Upload or
     published manually.
- **Model files are downloaded on first use.** Face detection fetches a MediaPipe model from
  `storage.googleapis.com`, and transcription fetches Whisper weights from Hugging Face. These are
  model downloads, not your content, and they happen once per machine.
- **Downloading a source URL lets yt-dlp choose where to connect.** The URL you provide, and the
  CDN/manifest hosts yt-dlp follows from it, are contacted. Don't feed AutoClip a URL you wouldn't
  open yourself.
- **API keys live in your OS keyring** (Credential Manager, Keychain, Secret Service), not in `config.json`. If no keyring backend exists, AutoClip falls back to a file **and tells you so** in the UI and in `autoclip doctor`. It will not silently downgrade.
- **No telemetry, no analytics, no phone-home.** There is no code that contacts a server AutoClip's authors control.
- **Everything is under `~/.autoclip/`** — media, transcripts, exports, database, settings. Delete that directory and nothing remains.

A central consent layer for these transfers is being built; until it lands, the settings above are
the control you have. See `docs/EGRESS-INVENTORY.md` for the full, code-verified list of outbound
destinations.

## Running it safely

AutoClip **has no authentication**. It binds to `127.0.0.1` by default, and it should stay that way.

Serving it on `0.0.0.0`, or publishing the Docker port beyond loopback, exposes an unauthenticated API that can read any file path the process can reach and execute ffmpeg against it. If you genuinely need remote access, put it behind a reverse proxy that terminates TLS and handles authentication.

## Scope

In scope: anything that lets a third party read your media, exfiltrate your API keys, or execute code through a crafted input file, URL, or API request.

Out of scope: the consequences of deliberately binding to a public interface, and anything requiring an attacker who already has local access to your user account.

## Supported versions

AutoClip is pre-1.0. Fixes land on `main`; there are no backported release branches yet.
