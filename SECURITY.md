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

A central consent layer now governs these transfers. See
[External-processing consent](#external-processing-consent) below and
`docs/EGRESS-INVENTORY.md` for the full, code-verified list of outbound
destinations.

## External-processing consent

Every outbound request that carries your content passes through one gateway
(`backend/autoclip/security/egress.py`). The gateway classifies the
destination, checks your stored decision, and records what happened. Nothing
is sent that has not been through it.

**What you control.** *Settings → External processing* lists each operation —
external transcription, AI highlight detection, external voiceover, source
downloads, model downloads, publishing, the trending chart — with a plain
description of what leaves the machine and why it is needed. Each operation has
its own switch for public services and for private-network destinations. The
same screen lists recent transfers: what was sent, where it went, and whether
it worked. Credentials never appear there, and neither does the content itself.

**How a decision is made.**

| Destination | Behaviour |
|---|---|
| Loopback (`127.0.0.1`, `::1`, `localhost`) | Always allowed, and always logged. A tunnel or reverse proxy on localhost can forward traffic elsewhere, so treat local services with the same care as public ones. |
| Private network | Never allowed implicitly. It needs an explicit decision from you. |
| Public network | Allowed only with a decision — either one you made, or one recorded because you configured that destination yourself. A decision you withdraw always wins, even for a configured destination. |

A decision is keyed by *operation and destination class*, not by hostname. If
you change a provider's `base_url` from a public host to one on your own
network, the public decision stops matching and the transfer is refused until
you allow the private class. The same rule applies when DNS resolves
differently later.

**No silent substitution.** If a provider is refused, AutoClip does not try a
different external provider with the same content. It may fall back to a
local model, because nothing leaves the machine that way, and it tells you
what it did.

## URL and subprocess policy

- **Redirects are checked on every hop.** A public URL that redirects to a
  private address is refused at the redirect, not at the first request.
- **DNS is resolved twice.** The address is checked before the request and
  again immediately before the connection, so a name that changes its answer
  between the two is caught.
- **IPv4 and IPv6 are both classified**, including loopback, link-local and
  cloud metadata addresses (`169.254.169.254`), which are refused outright.
- **yt-dlp** runs with proxies disabled and its network surface constrained;
  the URL you supply is classified before the download starts.
- **FFmpeg** runs with `-protocol_whitelist file,pipe`, so it can read local
  files and pipes and nothing else — no `http`, `https`, `tcp` or `rtmp`.
- **Credentials are masked completely** in logs and error messages. A secret
  that appears in a log line is compromised, so a partial mask is not enough.

The policy lives in `backend/autoclip/security/urlpolicy.py` and is covered by
`tests/test_url_policy.py` (26 cases) and `tests/test_egress.py` (18 cases).

## Running it safely

AutoClip **has no authentication**. It binds to `127.0.0.1` by default, and it should stay that way.

Serving it on `0.0.0.0`, or publishing the Docker port beyond loopback, exposes an unauthenticated API that can read any file path the process can reach and execute ffmpeg against it. If you genuinely need remote access, put it behind a reverse proxy that terminates TLS and handles authentication.

## Scope

In scope: anything that lets a third party read your media, exfiltrate your API keys, or execute code through a crafted input file, URL, or API request.

Out of scope: the consequences of deliberately binding to a public interface, and anything requiring an attacker who already has local access to your user account.

## Supported versions

AutoClip is pre-1.0. Fixes land on `main`; there are no backported release branches yet.
