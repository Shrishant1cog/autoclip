# Original requirements matrix

**Status of this document: INCOMPLETE — blocked on missing source material.**

The governing specification (§3) requires a matrix built from the *original* requirements document
and *seven* visual workflow references. Neither the document nor the references exist on this
machine (see `docs/original/MANIFEST.md`, which records the full search and enumerates the 8 missing
items).

Therefore:

- **No row may be marked `Verified against original source`**, because no original source was found.
- Every requirement below is taken from the **consolidated M0–M5 specification** and is marked
  `Verified against consolidated prompt only`.
- The eight missing items are carried as explicit `Blocked — source missing` rows so they cannot be
  forgotten.
- This file is **not complete** and must not be reported as complete.

---

## 1. Missing source material

| # | Item | Status |
|---|---|---|
| ORIG-01 | Original product requirements document | **Blocked — source missing** |
| ORIG-02 | Visual workflow reference 1 of 7 | **Blocked — source missing** |
| ORIG-03 | Visual workflow reference 2 of 7 | **Blocked — source missing** |
| ORIG-04 | Visual workflow reference 3 of 7 | **Blocked — source missing** |
| ORIG-05 | Visual workflow reference 4 of 7 | **Blocked — source missing** |
| ORIG-06 | Visual workflow reference 5 of 7 | **Blocked — source missing** |
| ORIG-07 | Visual workflow reference 6 of 7 | **Blocked — source missing** |
| ORIG-08 | Visual workflow reference 7 of 7 | **Blocked — source missing** |

Nothing has been reconstructed from assumption. Where the consolidated specification describes a
requirement, it is listed in §2 under its own ID and is delivered by a milestone; that is the most
this matrix can honestly claim.

---

## 2. Requirements from the consolidated M0–M5 specification

Columns follow specification §3.2 exactly. "Backend location" and "Frontend location" name the
**intended** location where delivery will land; `—` means none exists yet.

### 2.1 Product area 1 — Music intelligence and ducking

| Req | Requirement | Existing implementation | Missing functionality | Required modification | Frontend location | Backend location | DB support | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| R-M1 | Select a local music folder | fixed `~/.autoclip/music/` | folder picker + persistence | add setting + scanner root | Settings | `pipeline/music.py` | new column/table | — | Verified against consolidated prompt only |
| R-M2 | Scan music files | none | scan service | new module | Settings | `pipeline/music_scan.py` (new) | `music_tracks` | — | Verified against consolidated prompt only |
| R-M3 | Track metadata analysis (BPM/energy/mood/rhythm/duration/loudness) | none | all of it | new analyser | Settings | `pipeline/music_analysis.py` (new) | `music_tracks` | — | Verified against consolidated prompt only |
| R-M4 | AI music selection from metadata | none | selection + validation | new service | Review | `pipeline/music_select.py` (new) | `music_selections` | — | Verified against consolidated prompt only |
| R-M5 | Music licensing states + export block | none | states, evidence, gate | new domain + export gate | Settings, Review | `music/licensing.py` (new), `pipeline/export.py` | new table | — | Verified against consolidated prompt only |
| R-M6 | Shared speech timeline | ffmpeg sidechain only | VAD, merging, shared object | new module consumed by ducking + layout | — | `pipeline/speech_timeline.py` (new) | artifact only | — | Verified against consolidated prompt only |
| R-M7 | 349 ms merges / 350 ms does not | none | exact boundary logic | ms-domain merging | — | `pipeline/speech_timeline.py` | — | — | Verified against consolidated prompt only |
| R-M8 | Duck only added music, smooth, no fragmentation | sidechain compressor | interval-driven gain, original audio untouched | replace signal keying with timeline | Review | `pipeline/export.py` | — | — | Verified against consolidated prompt only |
| R-M9 | Volume-envelope preview | none | preview UI | new component | Review | `api/music.py` | — | — | Verified against consolidated prompt only |

### 2.2 Product area 2 — Webcam detection and layouts

| Req | Requirement | Existing implementation | Missing functionality | Required modification | Frontend location | Backend location | DB support | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| R-W1 | Webcam region detection | face landmarks | region + confidence | new detector | Review | `reframe/webcam.py` (new) | per-clip artifact | — | Verified against consolidated prompt only |
| R-W2 | Adaptive scene sampling | fixed 5 fps | density from scene rate | modify sampler | — | `reframe/faces.py`, `reframe/scenes.py` | — | — | Verified against consolidated prompt only |
| R-W3 | Tracking with uncertainty/occlusion | smoothing | confidence + fallback | extend tracker | — | `reframe/tracker.py` | — | — | Verified against consolidated prompt only |
| R-W4 | ~40/60 vertical preset | generic 9:16 | preset + composition | new layout module | Review | `pipeline/layout.py` (new) | `clip_layouts` | — | Verified against consolidated prompt only |
| R-W5 | Layout dwell ≥1.5 s | none | dwell control | new rule | — | `pipeline/layout.py` | — | — | Verified against consolidated prompt only |
| R-W6 | Manual override wins | none | override API + UI | new | Review | `api/clips.py` | `clip_layouts` | — | Verified against consolidated prompt only |
| R-W7 | Use the M1 timeline | none | coordination | consume shared timeline | — | `pipeline/layout.py` | — | — | Verified against consolidated prompt only |

### 2.3 Product area 3 — Creative intelligence

| Req | Requirement | Existing implementation | Missing functionality | Required modification | Frontend location | Backend location | DB support | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| R-C1 | Multi-signal video understanding | transcript → LLM | visual/action signals | extend highlights | — | `pipeline/highlights.py` | — | — | Verified against consolidated prompt only |
| R-C2 | Context-aware boundaries | word + silence | scene/sentence context | extend boundaries | Review | `pipeline/boundaries.py` | — | — | Verified against consolidated prompt only |
| R-C3 | Structured creative plan | none | plan model + validation | new module | Review | `pipeline/plan.py` (new) | `creative_plans` | — | Verified against consolidated prompt only |
| R-C4 | AI budget 1 + 1 repair + ≤1/clip | none | counter + refusal | new | Review | `pipeline/plan.py` | `ai_call_budget` | — | Verified against consolidated prompt only |
| R-C5 | Objective quality diagnostics | partial validation gate | the measurable set | extend validate | Review | `pipeline/validate.py` | — | — | Verified against consolidated prompt only |
| R-C6 | No invented quality/virality score | absent | must stay absent | guardrail | — | — | — | — | Verified against consolidated prompt only |

### 2.4 Product area 4 — YouTube and Instagram hardening

| Req | Requirement | Existing implementation | Missing functionality | Required modification | Frontend location | Backend location | DB support | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| R-Y1 | Account-scoped OAuth | tables + legacy flow | working per-account connect | fix `Channels.tsx` + state mapping | Channels | `youtube/oauth.py` | existing | — | Verified against consolidated prompt only |
| R-Y2 | `madeForKids` never guessed | hardcoded False | stored value + block | change uploader | Channels, Review | `youtube/uploader.py` | `youtube_channels` | — | Verified against consolidated prompt only |
| R-Y3 | Resumable upload with persisted session | one PUT | persist + resume | rewrite uploader | — | `youtube/uploader.py` | `youtube_uploads` | — | Verified against consolidated prompt only |
| R-Y4 | Idempotency + duplicate prevention | hash dedupe | attempt record + key | extend | — | `youtube/uploads.py` | new table | — | Verified against consolidated prompt only |
| R-Y5 | Ambiguous-result reconciliation | none | reconcile + `unresolved` | new module | Recovery | `youtube/reconcile.py` (new) | new states | — | Verified against consolidated prompt only |
| R-Y6 | Quota accounting per project | none | reservations + reset | new | Settings | `youtube/quota.py` (new) | new table | — | Verified against consolidated prompt only |
| R-Y7 | Routing explanation | partial | six stored fields | extend classifier | Routing, Review | `routing/classifier.py` | `content_classifications` | — | Verified against consolidated prompt only |
| R-I1 | Official Instagram API integration | none | everything | new, disabled until eligible | Settings | `instagram/` (new) | new tables | — | Verified against consolidated prompt only |
| R-I2 | Platform isolation | n/a | independent pipelines | new | — | `instagram/`, `youtube/` | — | — | Verified against consolidated prompt only |
| R-I3 | No browser automation / scraping | absent | must stay absent | guardrail | — | — | — | — | Verified against consolidated prompt only |

### 2.5 Governance, privacy and reliability

| Req | Requirement | Existing implementation | Missing functionality | Required modification | Frontend location | Backend location | DB support | Test evidence | Status |
|---|---|---|---|---|---|---|---|---|---|
| R-G1 | Consent for every external transfer | none | consent records + UI | new | Settings | `security/egress.py` (new) | new tables | — | Verified against consolidated prompt only |
| R-G2 | One egress gateway, retrofitting existing calls | none | gateway | new + retrofit E1–E13 | Settings | `security/egress.py` | transfer log | — | Verified against consolidated prompt only |
| R-G3 | Endpoint classification (loopback/private/public) | none | classifier | new | Settings | `security/urlpolicy.py` (new) | — | 26 xfail registered | Verified against consolidated prompt only |
| R-G4 | SSRF enforcement across redirects/DNS/IPv4/IPv6/proxy | none | enforcement | new | — | `security/urlpolicy.py` | — | 26 xfail registered | Verified against consolidated prompt only |
| R-G5 | yt-dlp + FFmpeg network restriction | none | hardening args | modify ingest/ffmpeg | — | `pipeline/ingest.py`, `pipeline/ffmpeg.py` | — | — | Verified against consolidated prompt only |
| R-G6 | Rights confirmation once per source | docstring only | storage + gate | new | Ingest | `sources` service | new table | — | Verified against consolidated prompt only |
| R-G7 | Queue lanes, pause/resume/retry | single worker | lanes + controls | extend queue | Jobs | `jobs/queue.py` | `jobs` | — | Verified against consolidated prompt only |
| R-G8 | Real-time progress from backend state | SSE exists | nothing new required for existing stages | extend per stage | JobProgress | `jobs/events.py` | — | — | Verified against consolidated prompt only |
| R-G9 | DB migrations preserve data, backup first | append-only migrations | backup + interrupted test | add | — | `db/schema.py` | — | — | Verified against consolidated prompt only |
| R-G10 | Known limitations documented | `SECURITY.md` only | release limitations | add in M5 | — | — | — | — | Verified against consolidated prompt only |

---

## 3. Summary (counted, not estimated)

| Status | Count |
|---|---|
| Verified against original source | **0** |
| Verified against consolidated prompt only | 42 |
| Partial | 0 |
| Blocked — source missing | 8 |

The matrix **cannot be marked complete**. Completing it requires the eight missing files. Every
requirement the consolidated specification states is at least tracked here; none is claimed verified.
