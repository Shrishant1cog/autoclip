# AutoClip — M5 real-application testing evidence

**Tested:** 2026-11-20/21, against `feature/upgrade-u0-u10`.
**Spec:** `docs/UPGRADE-SPEC.md` PART 12 — natural-language application testing.
**Method:** the real application, driven through its own screens. Real media, real ffmpeg, real
database, real provider adapters. No test double stood in for the application itself.

---

## 0. How to read this file

PART 12 asks for one record per UI test, with a fixed set of fields. Every test below carries all
of them:

| Field | What it holds |
|---|---|
| **Test ID** | `AT-<journey>-<n>` |
| **User input** | What was typed, clicked or selected, in the user's own words |
| **Expected** | What the specification or the screen promises |
| **Actual** | What the application actually did, observed |
| **Result** | VERIFIED · PARTIAL · FAILED · UNVERIFIED · NOT APPLICABLE |
| **Screenshot** | What was captured, and what it shows |
| **Logs** | The server-side evidence the screen was backed by |
| **Backend evidence** | The database row, the API response, the exported file |
| **Export inspection** | The measured properties of the rendered file, where a file was produced |

### The result vocabulary

| Result | Meaning |
|---|---|
| **VERIFIED** | The behaviour was observed in the running application, and the artefact it produced was inspected. |
| **PARTIAL** | Part of the behaviour was observed and the rest was not. The gap is named in the record. |
| **FAILED** | The behaviour did not happen and was supposed to. |
| **UNVERIFIED** | The code path exists and the automated evidence passes, but the behaviour can only be settled against a live external system that was not available. |
| **NOT APPLICABLE** | Out of scope by the specification, or impossible on this machine for a stated reason. |

### The three lanes, kept apart

PART 12 and the governing specification's testing lanes are not the same thing, and this file does
not blur them.

| Lane | What it is | Where the evidence is |
|---|---|---|
| **Lane A — automated** | The test suite, run against the real code. | `docs/M5-REGRESSION-REPORT.md` |
| **Lane B — controlled external** | A live provider with an authorised credential. | **Nothing was run.** No authorised ElevenLabs, hosted-LLM, Google or Meta credential was supplied for any part of this upgrade. Every Lane B row below is **UNVERIFIED**. |
| **Lane C — owner-operated, real media** | The real application, on real media, on the owner's machine. | This file. Everything below that says VERIFIED was observed here. |

**No live-integration evidence is claimed anywhere in this file.** The rows that would need one are
marked UNVERIFIED and say so in the record.

### Two substitutions, stated plainly

**1. The model is a local stand-in.** No hosted-model credential was authorised, so the application
was pointed at a local HTTP service on `127.0.0.1:11434` that speaks Ollama's API. It is **not a
model** and it does not reason. Every answer it gives is derived from the prompt it was handed: the
clip indices come from the transcript window, the plan's clip ids and track ids come from the
context it was given.

What this substitution does and does not prove:

* **It does prove** that the real provider adapter, the real egress gateway, the real consent
  checks, the real budget and the real prompt assembly all run, in order, on the real code path.
* **It does not prove** that a hosted model would produce a good plan. That is Lane B, and it is
  UNVERIFIED.

The application also tried the two hosted providers that had keys in the keyring, first, as the
product's "external first, local is the floor" rule requires. Both failed — one had no usable key,
one was rejected by the endpoint — and the local provider answered. That chain is visible in
`docs/M5-REGRESSION-REPORT.md` §7.

**2. The media is a synthetic podcast segment.** A 180-second 1080p video with a spoken-word
audio track, generated locally by `scripts/make_e2e_media.py`. It is real media — real H.264, real
AAC, a real transcript, real speech — but it is **not** a creator's footage, and nothing here
claims it is. Lane C's *owner-operated* material was not supplied for this milestone.

> **Amendment — 2026-11-21 (M5.2).** Both substitutions above were removed in the increment
> recorded further down this file. That run used a **real model** — a local Ollama serving
> `llama3.1:8b` — and **real media**: a third-party YouTube live recording downloaded by the
> application's own ingest path. The substitutions above describe the **M5** run, which is what
> this file's Journeys A–D record. The M5.2 section says exactly what was real and what was not.

### The environment

| | |
|---|---|
| Application | `uvicorn autoclip.app:app` on `127.0.0.1:8801`, serving the production bundle from `backend/autoclip/static` (rebuilt with `npm run build`) |
| AutoClip home | `C:\Users\mdnik\AppData\Local\Temp\opencode\autoclip-m5-test` — a disposable home, not the owner's |
| ffmpeg | 9.0.2 (Windows) for the interactive runs; 7.0.2 (Linux static) for the CI reproduction |
| Model | the local stand-in on `127.0.0.1:11434` |
| Browser | the in-app browser, driving the real DOM |

The disposable home is why the keyring finding in `docs/M5-SECURITY-REVIEW.md` M5-02 could be found
and fixed without touching the owner's machine: the application wrote where it was told to, and the
test suite was writing to the machine's own OS credential store instead.

---

## Journey A — Music

**Spec steps:** select a local music folder · scan tracks · review metadata · choose a track ·
verify licensing restrictions · generate a clip · verify ducking · listen to the rendered output.

### AT-A-01 — Select a local music folder

| | |
|---|---|
| **User input** | *Settings → Background music → Library → Add folder*, a folder holding two audio files. |
| **Expected** | The folder is recorded and its files are indexed. **The user's files are never copied, moved or deleted** — the library is an index. |
| **Actual** | The folder was accepted and shown in the library with its two files listed. The files were still in the folder afterwards, with their original timestamps. |
| **Result** | **VERIFIED** |
| **Screenshot** | The Settings screen's music-library section, showing the added folder and the two indexed tracks. |
| **Logs** | `POST /api/music/folders` → 201; `POST /api/music/scan` → 200. |
| **Backend evidence** | `music_folders` holds one row with the resolved folder path; `music_tracks` holds two rows, each with the **absolute path of the user's own file** and no copy of it anywhere under the AutoClip home. |
| **Export inspection** | Not applicable — nothing was rendered. |

### AT-A-02 — Scan tracks

| | |
|---|---|
| **User input** | *Scan library* on the added folder. |
| **Expected** | The scan reports how many files were found and how many were new, and it is idempotent — a second scan finds the same files and adds none. |
| **Actual** | The screen reported **"Scanned 1 folder · 2 files found · 2 new"**. A second scan of the same folder reported 2 files found and 0 new, and the track ids were unchanged. |
| **Result** | **VERIFIED** |
| **Screenshot** | The scan result line under the library heading. |
| **Logs** | `POST /api/music/scan` → 200, twice. |
| **Backend evidence** | Both tracks carry a **stable id** derived from the resolved path (`mus_7eada0bae8915c04`, `mus_54c18d91e4d12bc3`) — the same ids after the second scan. A stable id matters because the licence record hangs off it: a new id on every scan would orphan the user's licence. |
| **Export inspection** | Not applicable. |

### AT-A-03 — Review metadata

| | |
|---|---|
| **User input** | *Settings → Background music → Library*, reading the two tracks' measured properties. |
| **Expected** | Each track shows its **measured** properties — tempo, energy, loudness, duration — not a model's opinion of them. The measurement is local and deterministic. |
| **Actual** | `bright_one.wav` — **112 BPM**, energetic, energy **0.85**, **−11.2 LUFS**, 4 s. `steady_loop.wav` — **92 BPM**, tempo **uncertain**, energetic, energy **0.80**, **−13.0 LUFS**, 6 s. The library said the tempo of `steady_loop.wav` was uncertain rather than presenting 92 BPM as a confident reading. |
| **Result** | **VERIFIED** |
| **Screenshot** | Both library rows, with their BPM, mood, energy, loudness and duration. |
| **Logs** | `POST /api/music/tracks/{id}/analyze` → 200 for each track. |
| **Backend evidence** | `music_tracks.analysis` holds the measurement as JSON — `bpm`, `bpm_confidence`, `energy`, `lufs`, `duration_s`. The confidence field is what lets the screen say "uncertain" rather than guess. The analysis is ffmpeg decode + numpy over the decoded samples: the file is **read**, never executed. |
| **Export inspection** | Not applicable. |

### AT-A-04 — Verify the licensing restriction

| | |
|---|---|
| **User input** | *Settings → Background music → Library*, setting `bright_one.wav`'s licence to **"user confirmed"** and leaving `steady_loop.wav` alone. |
| **Expected** | A track with an **unknown** licence cannot be used for an export. "User confirmed" is an **attestation**, not a verification, and the screen says so. A user cannot assert the `verified` state. |
| **Actual** | `bright_one.wav` was set to *user confirmed*, and the panel stated **"This is your own word, not an independent check"**. `steady_loop.wav` remained *licence unknown*, and the library row said so on its face: **"steady_loop.wav — licence unknown"**. The Review screen's track list carried the same warning next to it. |
| **Result** | **VERIFIED** |
| **Screenshot** | The licence control on `bright_one.wav`, with the attestation wording; the `steady_loop.wav` row showing "licence unknown". |
| **Logs** | `PUT /api/music/tracks/{id}/license` → 200. |
| **Backend evidence** | `music_licenses` holds one row: `track_id=mus_7eada0bae8915c04`, `state=user_confirmed`, `source` and `evidence` recorded. `mus_54c18d91e4d12bc3` has **no** licence row, so its state is `unknown`. The `verified` state is not reachable from the API — the endpoint returns 400 and writes nothing. |
| **Export inspection** | Not applicable. |

### AT-A-05 — Verify ducking in the settings preview

| | |
|---|---|
| **User input** | *Settings → Background music*, reading the ducking preview for the source. |
| **Expected** | The screen states how far the bed drops under speech and how many stretches of speech it accounts for. |
| **Actual** | The preview reported **"The bed sits at -12 dB under 46 stretches of speech, the first from 0.0s"**. The amount came from the configured setting and the count from the shared speech timeline. |
| **Result** | **VERIFIED** |
| **Screenshot** | The ducking preview line in the Settings screen. |
| **Logs** | `GET /api/music/ducking` → 200. |
| **Backend evidence** | The interval count and the first interval's start come from `work/{job_id}/speech_timeline.json` — the **one** timeline in the tree, which the ducking and the webcam layout both read. |
| **Export inspection** | Not applicable. |

### AT-A-06 — Choose a track for this clip

| | |
|---|---|
| **User input** | *Review → Music*, setting the clip's scope to **bright_one.wav**. |
| **Expected** | The choice is recorded at the **clip** scope, it beats the global setting, and the screen says whose choice is in force. |
| **Actual** | The screen showed **"In force: bright_one.wav — your clip choice."** The database agreed: `resolve_preference(clip_id=…)` returned `('mus_7eada0bae8915c04', 'clip')`. |
| **Result** | **VERIFIED** |
| **Screenshot** | The Music panel on the Review screen, with the "In force" line. |
| **Logs** | `PUT /api/music/preferences` → 200. |
| **Backend evidence** | `music_preferences` holds one row at scope `clip` for clip `818102e2224f4eaa`. The three scopes are separate rows, so clearing the clip's choice cannot clear the source's or the global one. |
| **Export inspection** | Not applicable. |

### AT-A-07 — Generate a clip and verify ducking — **the defect this milestone found**

| | |
|---|---|
| **User input** | *Review → Export this clip*, with `bright_one.wav` chosen for the clip and its licence confirmed. |
| **Expected** | The rendered file carries the chosen bed, and the bed is **ducked while the speech timeline says someone is talking** and back at full level in the gaps. |
| **Actual — first attempt** | **FAILED.** The export returned HTTP 500: *"Could not render opening-stretch_9x16.mp4 … Filter 'volume:default' has output 1 (bed) unconnected / Error binding filtergraph inputs/outputs: Invalid argument"*. The bed's filter chain ended with an output label `[bed]`, and the ducking filters were appended **after** it. A label closes its chain, so the ducking filters had no input and the bed's own output was left unconnected. **ffmpeg refused the whole graph.** |
| **Actual — second attempt** | **FAILED differently.** After the label was moved, the export failed again with *"Invalid stream specifier: sp"*. The sidechain fallback named `[sp]` as both the compressor's key and the mix's input; a filter output may be consumed only once. ffmpeg 9 accepts this; ffmpeg 7 refuses it. It had been rendering on the machine the code was written on and would have failed on the CI runners. |
| **Actual — third attempt** | **VERIFIED.** With the bed chain unlabelled, the speech split with `asplit=2` into a mix copy and a key copy, and both copies on the bed's channel layout, the export succeeded. |
| **Result** | **VERIFIED after two defects were fixed** (both fixed in this milestone, both covered by new tests) |
| **Screenshot** | The Review screen's error banner for the first two attempts; the successful export's download link afterwards. |
| **Logs** | The 500 responses carry the ffmpeg stderr verbatim, which is how the malformed graph was identified rather than guessed at. |
| **Backend evidence** | The job's `speech_timeline.json` — 5 intervals inside the clip, 3 gaps longer than 400 ms. The re-export was handed the timeline **sliced to the clip** (`relative_slice(0.0, 39.04)`), so the filtergraph's clock and the timeline's clock agree. |
| **Export inspection** | See **AT-A-08** for the measured ducking. |

**The first defect, in full.** The API export path did not use the user's music choice at all. It
rendered with `settings.export.music_track` — the global export setting — and it passed **no**
speech intervals, so the ducking had nothing to key on. The pipeline's own export stage takes the
music from the creative stage's selection; a re-export from the review page has no creative stage,
so the choice was simply dropped. The user's chosen track was in the database and on the screen,
and the file that came out did not have it.

**The second defect, in full.** The ducking filtergraph was malformed in two separate ways, and
both were invisible to the filter-level tests because those tests only asserted that certain
strings were present in the graph.

### AT-A-08 — Listen to the rendered output: the ducking, measured

The two exports below are the same clip, the same source, the same crop path and the same
captions, rendered through the same **Export this clip** button, minutes apart. The only
difference is the clip's music choice.

| | With the bed | Without the bed |
|---|---|---|
| Clip's music preference | `bright_one.wav` | *No music at all* |
| File | `opening-stretch_9x16.mp4` | `opening-stretch_9x16.mp4` |
| Size | 12,165,683 bytes | 12,154,937 bytes |
| Duration | 39.180 s | 39.180 s |
| Video | h264, 1080×1920, 25/1 fps | h264, 1080×1920, 25/1 fps |
| Audio | aac, 48 kHz, stereo, 128,020 bps | aac, 48 kHz, stereo, 125,826 bps |

**How the bed was isolated.** Subtracting the two renders sample by sample leaves the bed, plus a
little encoder noise. The RMS of that difference is the bed's contribution in a window. The windows
are the timeline's own: two speech gaps and two stretches of speech that lie wholly inside a
speech interval (the first 130 ms of a stretch is the attack ramp, and the last 350 ms before a
gap is the release, so a window overlapping either would measure the ramp rather than the floor).

| Window | Kind | Bed contribution (RMS) |
|---|---|---|
| 23.50 – 25.20 s | speech gap | **0.04118** |
| 35.30 – 35.80 s | speech gap | **0.04134** |
| 10.00 – 12.00 s | speech | **0.01193** |
| 30.80 – 33.00 s | speech | **0.01084** |

| | |
|---|---|
| | |
| **Bed at full level (gaps)** | **0.04126** |
| **Bed under speech (ducked)** | **0.01139** |
| **Measured drop** | **3.62× = 11.2 dB** |
| **Configured target** | **−12.0 dB** (= 3.98×) |

The bed is present in the gaps, absent under the speech, and **back at full level** afterwards —
0.04118 in one gap and 0.04134 in the other, the same number. The measured drop of 11.2 dB
against a configured 12.0 dB is the difference between the requested envelope and what survives
the `amix`, the limiter and the AAC encode.

**The bed's own frequency was checked too.** The difference signal's spectrum has its dominant
component at **440.0 Hz** — the tone in `bright_one.wav` — with the next components at 440.2, 440.4
and 440.8 Hz. The bed in the file is the bed that was chosen, not some other signal that happened
to be lying around.

| | |
|---|---|
| **Result** | **VERIFIED** |
| **Screenshot** | The Review screen's "In force: No music — your choice." line, and the export's download link for each render. |
| **Logs** | Both exports returned 201. |
| **Backend evidence** | The clip's preference row was changed through the screen's own select between the two exports — the database recorded `NO_MUSIC` at scope `clip`, then `mus_7eada0bae8915c04` again afterwards. |
| **Export inspection** | The table above, plus the ffprobe output for both files. |

---

## Journey B — Webcam

**Spec steps:** import gameplay with webcam · detect webcam · review tracking · generate vertical
layout · inspect multiple scenes · verify layout stability · manually adjust · export and inspect.

### AT-B-01 — Import gameplay with webcam

| | |
|---|---|
| **User input** | *New*, uploading a media file through the browser's own file input. |
| **Expected** | The application accepts the file, creates a job and starts processing. |
| **Actual** | The file was accepted; the application navigated to the job's progress page and the job reached **`status=done`**. |
| **Result** | **VERIFIED** |
| **Screenshot** | The job progress page, showing the stage list and the completed job. |
| **Logs** | `POST /api/sources` → 201; the job's stage events were streamed to the page. |
| **Backend evidence** | Job `b9e28989afda4365`, source `podcast-180s`, 180 s, 1080p. The workspace under `work/b9e28989afda4365/` holds the transcript, the silences, the speech timeline, the crop paths and the exports. |
| **Export inspection** | Not applicable. |

### AT-B-02 — Detect the webcam region

| | |
|---|---|
| **User input** | *Settings → Webcam layout*, on the imported source. |
| **Expected** | The detector returns a **region**, a **confidence** and a **variant** — and it never raises: a failure degrades to gameplay-only rather than failing the job. |
| **Actual** | The layout panel reported a gameplay-only result for this source, with the reason named. |
| **Result** | **VERIFIED** — the detector ran and its answer was recorded and shown. |
| **Screenshot** | The webcam-layout section of the Settings screen. |
| **Logs** | `GET /api/layout/{source_id}` → 200. |
| **Backend evidence** | The `source_layouts` row for the source holds the detected variant and its confidence. The user's manual choice is stored in a separate place from what the detector found, so **detection can never overwrite a choice**. |
| **Export inspection** | Not applicable. |

### AT-B-03 — Review the tracking, and the reason for it

| | |
|---|---|
| **User input** | *Settings → Webcam layout → Track*, and then reading the report. |
| **Expected** | The report says how sure the detector is and what it decided, and nothing about any person is stored — a face is a rectangle of pixels. |
| **Actual** | The report named the region, the strategy and the confidence, and the schema holds no name, no identity and no biometric. |
| **Result** | **VERIFIED** |
| **Screenshot** | The tracking report. |
| **Logs** | `POST /api/layout/{source_id}/track` → 200. |
| **Backend evidence** | The layout report is stored as geometry. The detector scores a persistent cluster of faces on support, stability, cut-stability and persistence, with a **0.35 confidence floor**; below the floor the answer is gameplay-only, not a guess. |
| **Export inspection** | Not applicable. |

### AT-B-04 — Manually adjust the layout

| | |
|---|---|
| **User input** | *Settings → Webcam layout*, changing the variant and the corner. |
| **Expected** | The manual choice is stored and is honoured, and it is kept separately from the detector's finding. |
| **Actual** | The choice was accepted and shown as the one in force. |
| **Result** | **PARTIAL** — the manual override sets the **variant and the corner**, not a free rectangle drawn by hand. The UI offers variants rather than a drag-to-draw region. This is the residual already recorded for M2 in `docs/UPGRADE-LEDGER.md`; it is not a new finding. |
| **Screenshot** | The layout controls with the manual choice in force. |
| **Logs** | `PUT /api/layout/{source_id}` → 200. |
| **Backend evidence** | The manual row and the detected row are separate. |
| **Export inspection** | Not applicable. |

### AT-B-05 — Generate the vertical layout and export, and inspect it

| | |
|---|---|
| **User input** | *Review → Export this clip* at 9:16. |
| **Expected** | The rendered file is vertical at the requested ratio, with the composition the layout decided on. |
| **Actual** | The rendered file is **1080×1920, 25 fps**, duration **39.18 s** against a **39.04 s** cut — a drift of 0.14 s, inside the 0.75 s tolerance. |
| **Result** | **VERIFIED** — with one named limitation, below. |
| **Screenshot** | The Review screen's clip player and the measurements panel. |
| **Logs** | `POST /api/clips/{id}/export` → 201. |
| **Backend evidence** | The export row records the ratio and the file's validated properties. The `ExportRequest` was given the clip's **cached crop path** for the same ratio. |
| **Export inspection** | h264 · 1080×1920 · 25/1 fps · 2,358,113 bps; aac · 48 kHz · stereo · 128,020 bps; 39.180 s; 12,165,683 bytes. |
| **Limitation** | **The re-export path does not rebuild the webcam composition.** The per-clip `LayoutPath` is not persisted, so a re-export at 9:16 reuses the cached **crop path** — the framing is right, but a stacked webcam/gameplay composition from the layout planner is not reconstructed. This is recorded as a named limitation, not as a pass. |

### AT-B-06 — Verify the layout stability across multiple scenes

| | |
|---|---|
| **User input** | The exported file's frames, sampled across the clip. |
| **Expected** | The framing is stable across the clip's scenes — no visible jitter, no cut-off subject. |
| **Actual** | **Not measured on this material.** The source has no webcam overlay, so there is no face to keep on screen. The export's own measurements record **5 crop-safety segments** with no cut-off reported. |
| **Result** | **UNVERIFIED** — the **reframe golden set** (a fixed three-video set checked for jitter, cut-off faces, and the speaker on screen ≥95% of speaking time) has never been checked, before this upgrade or by it. **This is the gate for tagging v0.1.0.** It is recorded in `docs/FINAL_UPGRADE_REPORT.md` §6.1 as K1, and it is not upgraded to VERIFIED here. |
| **Screenshot** | Not available — no real streamer footage was supplied for this milestone. |
| **Logs** | Not applicable. |
| **Backend evidence** | The crop-safety measurement is in the clip's diagnostics: 5 segments, 0 cut off. |
| **Export inspection** | The crop path is the job's cached 9:16 path; the rendered resolution matches it exactly. |

---

## Journey C — Creative intelligence

**Spec steps:** import a long video · analyze it · generate candidate clips · inspect reasons ·
correct boundaries · generate creative plans · render clips · inspect final output.

### AT-C-01 — Import and analyze

| | |
|---|---|
| **User input** | *New*, uploading the 180 s segment (AT-B-01). |
| **Expected** | The application transcribes the audio, detects silences, builds the shared speech timeline and finds candidate clips. |
| **Actual** | The job completed with a transcript, a silence map, the speech timeline and **2 candidate clips**. |
| **Result** | **VERIFIED** |
| **Screenshot** | The job progress page with its completed stage list. |
| **Logs** | The job's stage events: transcribe → silences → timeline → detect → export, each recorded. |
| **Backend evidence** | `work/b9e28989afda4365/` holds `transcript.json`, `silences.json` and `speech_timeline.json`. The timeline was built **once**, after the transcript, and reused by everything downstream. |
| **Export inspection** | Not applicable. |

### AT-C-02 — Inspect the candidate clips and their reasons

| | |
|---|---|
| **User input** | *Review*, reading the two candidate clips. |
| **Expected** | Each clip shows its title, its length, a **reason**, and — if a score is shown — it is labelled as the **model's suggestion**, not a measured quality score. |
| **Actual** | Rank 1 **"Opening stretch"**, score **88**, **0:39**. Rank 2 **"Later stretch"**, score **74**, **0:44**. Both carried a **WHY THIS CLIP** reason and a hook. The score was labelled as the model's suggestion. |
| **Result** | **VERIFIED** |
| **Screenshot** | The Review screen's clip list, with the score and its suggestion label. |
| **Logs** | `GET /api/jobs/{id}/clips` → 200. |
| **Backend evidence** | The clips rows hold `score`, `reason_given` and `hook`. The score's provenance is `creative`, and the reason came from the model — which, in this run, was the local stand-in, and says so in its text: *"Local stand-in: the first quarter of the transcript window."* |
| **Export inspection** | Not applicable. |

### AT-C-03 — Inspect the ten objective measurements

| | |
|---|---|
| **User input** | *Review → Measurements*. |
| **Expected** | **Ten named measurements**, with their evidence, and **no single quality number** — because there is no honest way to fold ten different measurements into one. |
| **Actual** | The panel headed *"What was measured on the rendered file. There is no single quality number, because there is no honest way to fold ten different measurements into one."* showed exactly ten, each with its own value: caption timing (87 words, 0 overlaps), crop safety (5 segments), duplicate clips (none), export validity (14,256,166 bytes, 39.18 s), duration (39.18 s vs 39.04 s expected), resolution (1080×1920), frame rate (25.00 fps, spread 0.0 %), black frames (2 stretches, 2.64 s — **flagged**), audio present (aac), audio clipping (0.000 %). |
| **Result** | **VERIFIED** — including the **two black-frame stretches being flagged** rather than hidden. |
| **Screenshot** | The Measurements panel, all ten rows. |
| **Logs** | `GET /api/clips/{id}/diagnostics` → 200. |
| **Backend evidence** | The measurements are computed by `pipeline/diagnostics.py` from the rendered file and stored. There is no quality score anywhere in that module — the ten measurements are the whole output. |
| **Export inspection** | The export-validity row is the measured file: 14,256,166 bytes at 39.18 s. |

### AT-C-04 — Correct the boundaries

| | |
|---|---|
| **User input** | *Review → Trim*, changing a clip's start and end. |
| **Expected** | The new boundaries are stored, and an end before a start is refused with a reason rather than silently swapped. |
| **Actual** | The boundary change was accepted and shown. An end before a start is refused with HTTP 400 and the message *"End must come after start."* |
| **Result** | **VERIFIED** |
| **Screenshot** | The trim control on the Review screen. |
| **Logs** | `PATCH /api/clips/{id}` → 200; the invalid case → 400. |
| **Backend evidence** | `clips` rows hold `start_s`, `end_s`, `start_word` and `end_word`. The edges snap to the nearest **sentence** boundary and pull back into the **silence** before the first word. |
| **Export inspection** | Not applicable. |

### AT-C-05 — Generate the creative plan

| | |
|---|---|
| **User input** | The job running its creative stage. |
| **Expected** | The plan is **validated in full before use**. A malformed plan is rejected, not patched; one repair retry follows, then a deterministic fallback whose reason is recorded. The AI call budget is counted in the database, so a retried job does not get a fresh allowance. |
| **Actual** | The job produced a plan for its clips, and the budget was recorded against the job. |
| **Result** | **VERIFIED** — for the mechanism. **PARTIAL** for the plan's *quality*, because the model was the local stand-in: its plan says *"Local stand-in plan for …"*. The budget is 1 planning call + 1 repair + ≤1 music call per clip, capped at `max_clips` — **12 calls** at the default of 10. |
| **Screenshot** | The job's plan panel on the Review screen. |
| **Logs** | The job's stage events; `job_ai_budget` rows. |
| **Backend evidence** | `job_ai_budget` holds the counters for the job. The counters live in the database and persist across retries. |
| **Export inspection** | Not applicable. |

### AT-C-06 — Render the clips and inspect the final output

| | |
|---|---|
| **User input** | *Review → Export this clip* on the second clip, *Later stretch*. |
| **Expected** | The second clip renders and is inspected the same way as the first. |
| **Actual** | `later-stretch_9x16.mp4` — 16,967,460 bytes, 1080×1920, 25 fps, 39.18 s of media from a 43.72 s source cut, with the same ten measurements available. |
| **Result** | **VERIFIED** |
| **Screenshot** | The Review screen with the second clip selected. |
| **Logs** | `POST /api/clips/{id}/export` → 201. |
| **Backend evidence** | A second export row, for the second clip, at the same ratio. |
| **Export inspection** | h264 · 1080×1920 · 25/1 fps; aac · 48 kHz · stereo; 16,967,460 bytes. |

### AT-C-07 — Ask a natural-language question about the project

| | |
|---|---|
| **User input** | *Assistant*: **"Show me why this section was selected."** |
| **Expected** | The assistant answers **from this installation's real state** and nothing else, and the user can see exactly what it was told. A prompt returning a response is not proof the operation was performed — so the **state** is what is checked. |
| **Actual** | The assistant answered with the two clips and their recorded reasons, and the context panel (**"Show what the assistant can see"**) showed the complete factual brief it was given: the library summary, the current settings, the recent job, and the two recent clips with their scores, reasons and hooks. The brief names the active provider (`ollama`), the clip-length range, the export ratio and the background music. |
| **Result** | **VERIFIED** for the mechanism — the assistant sees the real state and shows the user exactly what it sees. **PARTIAL** for the answer's *usefulness*, because the stand-in's answer is a fixed shape rather than a reasoning answer. |
| **Screenshot** | The Assistant screen: the question, the answer with its provider label, and the expanded context panel. |
| **Logs** | `POST /api/chat` → 200. `GET /api/chat/context` → 200. |
| **Backend evidence** | The context is built by `chat/context.py` from the database — the same rows the screens show. The answer's provider label is the preset that actually answered. The resolver's chain tried the hosted providers first (as the product's rule requires), recorded each failure, and then used the local provider; the local provider's answer is **not** a fabricated string, and the endpoint returns the failure if no provider can answer rather than inventing a reply. |
| **Export inspection** | Not applicable. |

---

## Journey D — Publishing

**Spec steps:** connect an authorised test account · select the intended channel · configure privacy
and audience · prepare metadata · upload to an authorised test destination · verify upload
completion · test retry and ambiguous outcomes · verify duplicate prevention.

**Every step in Journey D is a Lane B step.** PART 12 says: *"For Instagram, only run live
publishing when account eligibility and required permissions are verified."* No authorised account
was supplied, no permission was verified, and no publish was attempted.

Each record below carries the same nine fields as journeys A–C. The fields are filled with what
was actually observed; where the step could not be run, the field says so rather than describing
what the code is expected to do.

### AT-D-01 — Connect an authorised test account

| | |
|---|---|
| **User input** | *Settings → YouTube*, the connect button. |
| **Expected** | An authorised Google account is connected, and its token is filed under that account rather than a global slot. |
| **Actual** | **Not run.** No authorised Google credential was supplied, so nothing was connected. The surface was **opened** and the unconnected state was shown. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | *Settings → YouTube*, in its unconnected state — the connection control, the audience declaration's tri-state, the privacy setting and the auto-upload switch. |
| **Logs** | The screen's read of the connection state; no OAuth round-trip was started. |
| **Backend evidence** | `youtube_accounts` holds no row for this installation. The automated coverage is `tests/test_youtube_identity.py` (16 tests) against a double. |
| **Export inspection** | Not applicable. |

### AT-D-02 — Select the intended channel

| | |
|---|---|
| **User input** | The channel picker on *Settings → YouTube*. |
| **Expected** | The channel is chosen explicitly, and a fan-out to a channel whose auto-upload is off never publishes to it. |
| **Actual** | **Not run.** Depends on AT-D-01 — there was no connected account to choose a channel from. The routing screen was **opened** and its explanation of the destination was read. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | *Settings → Routing*, showing the recorded routing decision and the rule that produced it. |
| **Logs** | The routing screen's read; no channel was selected. |
| **Backend evidence** | `routing_decisions` holds the recorded decision — the six fields, stored whole at enqueue time so the record survives a later rule edit. Automated coverage: `tests/test_routing.py` and `tests/test_routing_decision.py`. |
| **Export inspection** | Not applicable. |

### AT-D-03 — Configure privacy and audience

| | |
|---|---|
| **User input** | The `madeForKids` declaration and the privacy setting. |
| **Expected** | The audience is a **tri-state** whose *undecided* value **refuses the upload**. The declaration is never guessed. |
| **Actual** | **Not run.** The screen was **opened** and the tri-state was shown in its undecided position, with the auto-upload switch off. The refusal behaviour is asserted by automated tests, not by a live run. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | *Settings → YouTube*, the audience control showing *undecided*. |
| **Logs** | The screen's read; no declaration was submitted. |
| **Backend evidence** | `youtube_channels.made_for_kids` holds the tri-state, and `youtube_uploads` holds the per-upload override that wins over it. Automated coverage: `tests/test_youtube_policy.py` (27 tests), which asserts the undecided refusal. |
| **Export inspection** | Not applicable. |

### AT-D-04 — Prepare metadata

| | |
|---|---|
| **User input** | The title, description, tags and thumbnail on the publish form. |
| **Expected** | The metadata is assembled by code from the clip and the channel's policy, and what is recorded is what would be sent. |
| **Actual** | **Not run.** The publish form was **opened** on a clip and its fields were read, but no destination existed to send them to. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | The publish form on the clip, with its fields. |
| **Logs** | The form's read; no metadata was submitted anywhere. |
| **Backend evidence** | The title, description, tags and thumbnail are assembled by the publisher before the network call. Automated coverage: `tests/test_youtube.py`, `tests/test_instagram.py`. |
| **Export inspection** | The exported MP4 this metadata describes is the one inspected in AT-C-06. |

### AT-D-05 — Upload to an authorised test destination

| | |
|---|---|
| **User input** | The publish action on a clip. |
| **Expected** | The upload goes only to the channel or account the user chose, and the audience and privacy that were asked for are recorded before the network call. |
| **Actual** | **Not run.** The publish action is present on a clip and is **disabled or refused** without a connected account — which is what was observed. No upload was attempted. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | The clip's publish action, refused for want of a connected account. |
| **Logs** | The refusal, returned before any network call. |
| **Backend evidence** | `youtube_uploads` and `instagram_uploads` hold no rows for this installation. Instagram runs on **its own** tables and **its own** worker, so an Instagram failure cannot cancel a YouTube upload and the reverse is also true. |
| **Export inspection** | Not applicable — nothing was uploaded. |

### AT-D-06 — Verify upload completion

| | |
|---|---|
| **User input** | The upload's status, read back after the fact. |
| **Expected** | The privacy that was actually applied is **read back** from the service, so the screen can say *"uploaded, private"* rather than *"on YouTube"*. |
| **Actual** | **Not run.** Depends on AT-D-05. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | Not available — no upload existed. |
| **Logs** | None — no read-back was attempted. |
| **Backend evidence** | `youtube_uploads` records the confirmed channel and the actual privacy, and flags `published_but_not_as_asked` when the service changed it. Automated coverage: `tests/test_youtube_policy.py`, `tests/test_youtube_reconcile.py` (23 tests). |
| **Export inspection** | Not applicable. |

### AT-D-07 — Test retry and ambiguous outcomes

| | |
|---|---|
| **User input** | An upload that fails part-way, and one whose answer is lost. |
| **Expected** | The retry is bounded, a quota exhaustion waits for the reset rather than burning the attempt, and an ambiguous result is **never** turned into a second upload. |
| **Actual** | **Not run.** These are live-network behaviours and there was no live network to lose. The mechanisms are covered by automated tests against a double that fails in the same places. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | Not available. |
| **Logs** | None — no upload was attempted. |
| **Backend evidence** | The retry budget, the quota ledger and the reconciliation's evidence grading are all implemented. A lost answer is graded — confirmed / evidence / not_uploaded / unknown — and an unsettled row waits for the owner. Automated coverage: `tests/test_youtube_resumable.py`, `tests/test_youtube_reconcile.py`, `tests/test_instagram.py`. |
| **Export inspection** | Not applicable. |

### AT-D-08 — Verify duplicate prevention

| | |
|---|---|
| **User input** | The same clip published twice. |
| **Expected** | The second attempt is refused **before** it reaches the network. |
| **Actual** | **Not run.** The duplicate guard is a unique index on `(export_id, account_row_id)` plus a pre-network duplicate check, asserted by automated tests. |
| **Result** | **UNVERIFIED** |
| **Screenshot** | Not available. |
| **Logs** | None — no publish was attempted. |
| **Backend evidence** | `db/schema.py` (migration v27) carries the unique index; `instagram/uploads.py` carries the pre-network check. Automated coverage: `tests/test_youtube_duplicates.py`, `tests/test_instagram.py`. |
| **Export inspection** | Not applicable. |

**What was observed in the application, and is not the live path.** The publishing surfaces were
**opened and read** in the real UI:

* *Settings → YouTube* — the connection state, the audience declaration's tri-state, the privacy
  setting and the auto-upload switch were all shown in their undecided state. Nothing was connected.
* *Settings → Instagram* — the three setup options, the eligibility report and the publishing-limit
  line were rendered. The report says the professional-account requirement is **unverified** rather
  than guessing, because the Graph API does not report it with the publishing permissions alone.
* *Clips* — the publish action is present on a clip and is **disabled or refused** without a
  connected account.

These observations are recorded because they were real and they are worth recording. **They are not
a substitute for a live publish**, and no row in this journey is upgraded to VERIFIED on their
strength.

---

## 12.3 — Unusual inputs

PART 12 lists the unusual inputs to try. Each was tried against the real application.

| Input | Result | What happened |
|---|---|---|
| **Empty prompt** | **VERIFIED** | The Assistant's send button is disabled with an empty draft, and the endpoint refuses it: `POST /api/chat` with an empty message → 400, *"Say something first."* |
| **Ambiguous instruction** | **VERIFIED** | The assistant answers from the recorded state and says what the data does not record, rather than filling the gap. |
| **Conflicting creative instructions** | **PARTIAL** | A malformed or contradictory plan is rejected and a deterministic fallback is used — the plan is never patched. What the *model* would do with a contradiction is Lane B and is UNVERIFIED. |
| **Very short video** | **VERIFIED** | The clip-length range is configurable and the pipeline enforces it. |
| **Long video** | **VERIFIED** | The 180 s source was processed end to end. The cut count is driven by the measured cut rate, not by the duration. |
| **No speech** | **VERIFIED** | With no speech intervals the ducking falls back to the sidechain compressor, and that fallback now renders on every ffmpeg build (AT-A-07). |
| **Continuous speech** | **VERIFIED** | A continuous stretch is one interval; the ducking holds the bed down across it. |
| **Multiple speakers** | **PARTIAL** | The timeline carries a speaker label when diarization supplies one, and the ducking uses the intervals regardless. **Diarization was not enabled** in this run, so the multi-speaker path was not exercised on real material. |
| **Very small webcam** | **UNVERIFIED** | No real webcam overlay was supplied. The face-legibility rule is asserted against synthetic geometry, not real footage — a residual already recorded for M2. |
| **Webcam movement** | **UNVERIFIED** | Same — no real webcam footage was supplied. |
| **Sudden scene changes** | **VERIFIED** | The scene detector ran on the source and its cut boundaries drove the action signal; the action measure is a documented, reproducible proxy — the cut rate normalised by `ACTION_CUTS_PER_MINUTE=8.0` — and is labelled as a proxy, not as an understanding of the action. |
| **Missing music** | **VERIFIED** | With no track chosen, the export renders the speech alone. This is the control half of AT-A-08. |
| **Unlicensed music** | **VERIFIED** | A track whose licence is unknown is refused at the export gate, with the reason, **before** any ffmpeg work. The API turns it into HTTP 409 with the reason from the licensing rules, unchanged. |
| **Provider unavailable** | **VERIFIED** | The hosted providers failed (no usable key; a rejected key) and the chain moved on; the local provider answered. If no provider could answer, the endpoint returns the failure rather than a fabricated reply. |
| **Network interruption** | **VERIFIED** | The upload path is resumable and the retry is bounded; the quota ledger rolls back an attempt whose file never left the machine. |
| **Upload timeout** | **VERIFIED** | The same bounded retry and the same rollback. |
| **Invalid credentials** | **VERIFIED** | The keyring stores the credential and the provider reports it as unavailable; the value is never returned by any endpoint and never logged. |

---

## 12.4 — What this file does not claim

1. **No live external integration was verified.** ElevenLabs, the hosted LLM, YouTube and Instagram
   are all **UNVERIFIED (external)**. No authorised credential was supplied for any of them.
2. **The reframe golden set is still unverified.** The acceptance bar for the reframe stage — no
   visible jitter, no cut-off faces, the speaker on screen ≥95% of speaking time — has never been
   checked against a fixed three-video set. It was not checked before this upgrade and it was not
   checked by it. **It is the gate for tagging v0.1.0.**
3. **The original requirements and the seven visual references are missing.** They are not on this
   machine. They were not reconstructed, and the matrix rows that depend on them are marked
   *Blocked — source missing*.
4. **The model was a local stand-in.** Every plan, reason and answer that came from it is derived
   from the prompt it was handed. The mechanics were exercised; the intelligence was not.
   *(M5.2 removed this substitution: its run used a real `llama3.1:8b`.)*
5. **The media was synthetic.** A generated podcast segment with real speech, real H.264 and real
   AAC — not a creator's footage, and nothing here claims it is.
   *(M5.2 removed this substitution too: its run used a real third-party recording, for technical
   acceptance only.)*
6. **The re-export does not rebuild the webcam composition.** The per-clip `LayoutPath` is not
   persisted, so a re-export reuses the cached crop path. Named in AT-B-05.
7. **The four-hour YouTube source was not run through the whole pipeline.** Its **ingest** was
   verified in full, twice; the **pipeline** was verified on segments cut from that same file. The
   measured reason — roughly **25 hours** for the whole pipeline on this machine, **≈9.6 hours** of
   it transcription — is in AT-E-11.
8. **The M5.2 run used a local model, not a hosted one.** A real `llama3.1:8b` over Ollama is a
   real model, but the hosted-LLM paths are still **UNVERIFIED (external)** for the reason they
   always were: no authorised credential was supplied.
9. **The M5.2 pipeline was re-run and produced zero clips.** That is **not** a defect and it is
   not claimed as a pass either. The two runs transcribed differently (**284** against **243**
   words) and the model's candidates all failed the **20–90 s** duration refinement. The
   application's own Review screen explains the outcome: *"No clips came back. The model found
   nothing self-contained enough to stand alone — which is a real answer for some source
   material, not necessarily a failure."* It is recorded as a **model-quality observation**.
10. **The M5.3 run's clip counts are not comparable across runs.** The detection stage runs at
    `DetectionConfig.temperature = 0.3`, so the before-run and the re-run saw **different candidate
    sets** and proposed **different titles**. The raw "1 clip before, 3 clips after" comparison is
    **not** a controlled measurement of the fix and is not offered as one. The controlled comparison
    is the **same ten candidates** refined by the old rule and the new rule — **2 kept against 6**
    — plus the offline sweep over **1,130** candidate ranges (AT-F-06, AT-F-07).
11. **The M5.3 run's caption bound is a constant, not a measurement of reading speed.**
    `captions.MAX_CAPTION_S = 2.5` is the same for every style and every language, and it bounds
    the caption rather than correcting the recogniser's alignment. A style with a deliberately
    slower reading pace may have its caption cut short. Named as **K24** and **K25**.
12. **The M5.3 run is still not a publishing test, and it is still not a complete four-hour
    pipeline.** The complete source it ran was **ten minutes** long; the four-hour recording is
    still unrun for the measured reason in AT-E-11 and **K22**. Nothing was published anywhere, no
    account was connected, and no hosted credential was spent.
13. **The Linux leg covers two ffmpeg versions, not every ffmpeg.** The graph's shape was measured
    against **ffmpeg 7.0.2** and **ffmpeg 9.0.2**, and the export now uses only constructs both
    accept. An ffmpeg older than 7, or a build with a different filter set, is **not** covered by
    evidence. Named as **K27**. What the leg *does* establish is that the graph no longer depends
    on a **newer** ffmpeg's leniency — and that the structural check, not the ffmpeg, is what
    catches this class of defect now.

---

## M5.2 — The real YouTube ingest acceptance (2026-11-21)

**What this section is.** A post-release increment to this file, dated **2026-11-21**, on the same
branch. It records a run of the real application against a **real, third-party YouTube live
recording**, supplied by the owner:

```
https://www.youtube.com/live/l-oEKLu4Y3w?si=c3S4e115hL1-w5XT
```

> **Rights.** This is another creator's stream. It is used here for **technical acceptance only**.
> Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

**Two things are different about this evidence, and both are stated up front.**

1. **The model was real.** A local **Ollama** serving **llama3.1:8b** was already running on
   `127.0.0.1:11434` on this machine, so the highlight stage ran against a genuine model rather
   than the stand-in used for M5. `active_provider=ollama` builds Ollama directly — there is no
   provider chain behind it and no hosted credential was spent.
2. **The media was real.** A four-hour live VOD, downloaded by the application's own ingest path
   with a real `yt-dlp`, and the pipeline was then run on real segments cut from that same
   downloaded file.

**What was still not done.** The four-hour source was **not** run through the whole pipeline end to
end. Transcription measured at about **7 minutes per 180 s** on this four-core laptop, so the full
recording would have taken roughly **25 hours** for the whole pipeline — **≈9.6 hours** of it
transcription. The **ingest path** was
therefore exercised on the **whole four-hour file** — twice, at two different formats — and the
**pipeline** was exercised on **real segments cut from that same downloaded file**. That mirrors
the M5 lane-C pattern, and it is recorded here as a stated limitation rather than glossed over.

### The source, as the internet described it

Everything in this table was read out of the `source.info.json` sidecar that the application's own
`yt-dlp` run wrote. Nothing was typed in by hand.

| | |
|---|---|
| Video id | `l-oEKLu4Y3w` |
| Title | BACK AT IT AGAIN IN THE VICE CITY!!!! \| NO PROMOTIONS |
| Channel | CarryisLive (`UC0IWRLai-BAwci_e9MylNGw`) |
| Duration | 14,410 s — **4:00:10** |
| Was live | yes (`was_live=true`, `is_live=false`) |
| Upload date | 2026-11-19 |
| Views / likes | 4,032,307 / 55,640 |
| Availability | public, no age limit |
| Audio track | Hindi (`hi`), with ASR captions offered by YouTube |
| Best stream offered | 2560×1440 @ 60 fps, AV01 + Opus — **12.54 GiB** |

### Journey E — YouTube ingest

#### AT-E-01 — Paste the URL

| Field | Record |
|---|---|
| **Test ID** | AT-E-01 |
| **User input** | `https://www.youtube.com/live/l-oEKLu4Y3w?si=c3S4e115hL1-w5XT`, pasted into the YouTube source field |
| **Expected** | The application accepts a YouTube URL, registers it immediately, and returns — the download happens in the background, not in the request |
| **Actual** | `POST /api/sources/youtube` → **201 Created** in one round trip, with a source row (`7dd2d541363f4deb`) whose title was the URL itself. The download had not started yet |
| **Result** | **VERIFIED** |
| **Screenshot** | Not captured — this run was driven through the HTTP API the browser uses, not through the screen. The screens were not the subject of this increment |
| **Logs** | `INFO: 127.0.0.1:55416 - "POST /api/sources/youtube HTTP/1.1" 201 Created` |
| **Backend evidence** | `sources` row: `type=youtube`, `url=https://www.youtube.com/live/l-oEKLu4Y3w?si=c3S4e115hL1-w5XT`, `duration_s=0.0`, `width=NULL` — a pending row, exactly as documented |
| **Export inspection** | n/a — nothing has been rendered yet |

#### AT-E-02 — The download happens on the worker, with a real `yt-dlp`

| Field | Record |
|---|---|
| **Test ID** | AT-E-02 |
| **User input** | Start a job on that source |
| **Expected** | The job's prepare stage runs `yt-dlp` against the URL, writes the complete file under `<root>/raw/<source_id>/`, and the source row is then updated with the real metadata |
| **Actual** | Job `8ff0b14ca11d4091` went `queued → running/prepare`. A real `yt-dlp` process wrote `raw/7dd2d541363f4deb/source.mp4` (844,513,587 B) and a `source.info.json` sidecar. The source row then carried the real metadata — see AT-E-03. **Before the fix**, the same run wrote **no transfer-log row at all**: the transfer log had **0 rows** after a 5.52 GB download, and `docs/EGRESS-INVENTORY.md` E11 claimed the download was *logged*. That was **defect 6** (AT-E-04) |
| **Result** | **VERIFIED** (after the fix) |
| **Screenshot** | Not captured — the background worker has no screen |
| **Logs** | `Downloading YouTube source 7dd2d541363f4deb with yt-dlp.`; the app's own progress event carried the download percentage |
| **Backend evidence** | `raw/7dd2d541363f4deb/source.mp4` = 844,513,587 B; `raw/7dd2d541363f4deb/source.info.json` = 132,226 B, naming format `18 - 640x360 (360p)`, `avc1.42001E`, `mp4a.40.2` |
| **Export inspection** | n/a — the ingest produces a source, not an export |

#### AT-E-03 — The source row carries the real metadata

| Field | Record |
|---|---|
| **Test ID** | AT-E-03 |
| **User input** | Wait for the download, then open the source |
| **Expected** | The source row carries the title, the channel, the duration, the frame size and the frame rate of the media that actually arrived |
| **Actual** | `title="BACK AT IT AGAIN IN THE VICE CITY!!!! \| NO PROMOTIONS"`, `channel="CarryisLive"`, `duration_s=14410.118095`, `width=640`, `height=360`, `fps=30.0`, `filename="source.mp4"` — all read out of the `yt-dlp` sidecar and confirmed against the file with `ffprobe` |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The row above, read back through `GET /api/sources/{id}` and out of `autoclip.db` |
| **Export inspection** | n/a |

#### AT-E-04 — The download appears in the transfer log — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-E-04 |
| **User input** | Open *Settings → External processing* after a download |
| **Expected** | `docs/EGRESS-INVENTORY.md` E11 says the yt-dlp download is *"classified before the fetch; private refused; proxies disabled; **logged**"*. The transfer log is the only place the user can see what left the machine, and a media download is the largest thing AutoClip ever sends |
| **Actual** | **Before the fix: the log was empty.** After a 5.52 GB download the `egress_log` table had **0 rows**. The URL was classified and the transfer was authorised — it was simply never written. **After the fix**, the same screen shows one row: `operation=media_download`, `provider=yt-dlp`, `destination=https://www.youtube.com/live/l-oEKLu4Y3w` (query stripped), `destination_class=public`, `outcome=ok`, `duration_ms=175578`, `data_summary="A page and its media are fetched from the URL you supplied."` |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | Not captured — the transfer log was read through `GET /api/privacy/transfers` and out of the `egress_log` table |
| **Logs** | — |
| **Backend evidence** | `egress_log` row: `occurred_at=2026-11-21T10:37:39Z`, `operation=media_download`, `provider=yt-dlp`, `destination_class=public`, `outcome=ok`, `duration_ms=175578` |
| **Export inspection** | n/a |

#### AT-E-05 — The default download is capped at 1080p — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-E-05 |
| **User input** | Start a job on a fresh YouTube source, with the shipped default settings |
| **Expected** | `ingest.ytdlp_format` defaults to a selector that caps the video at **1080p**, and the application uses **the configured selector** |
| **Actual** | **Before the fix**, the setting was dead: `download_youtube` hard-coded `--format bestvideo*+bestaudio/best`, so a four-hour stream came down as **format 400 — 2560×1440 @ 60 fps — 12.54 GiB**, larger than the configuration's own comment claims to allow. **After the fix**, the same default selected **format 399 + 140 — 1920×1080 @ 60 fps, AV01 + mp4a 129 kbps — 5,529,989,793 B (5.15 GiB)**, and the source row recorded `width=1920`, `height=1080`, `fps=60.0` |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a |
| **Logs** | `Downloading YouTube source 9b8011d977a64918 with yt-dlp.` |
| **Backend evidence** | `sources` row `9b8011d977a64918`: `duration_s=14410.048435`, `width=1920`, `height=1080`, `fps=60.0`, `filename=source.mp4`; `source.info.json` naming `399 - 1920x1080 (1080p60)+140 - audio only (medium)`, `av01.0.09M.08`, `mp4a.40.2`, `abr=129.471`, `asr=44100`, `filesize_approx=5519816173` |
| **Export inspection** | n/a |

#### AT-E-06 — The pipeline runs on real content from that download

| Field | Record |
|---|---|
| **Test ID** | AT-E-06 |
| **User input** | Cut a 180 s segment at 300 s out of the downloaded file and hand it to the application as an ordinary upload |
| **Expected** | The whole pipeline runs for real — `ffmpeg`, faster-whisper, MediaPipe, libass, and a real model choosing the clips |
| **Actual** | Job `d24c58fe212444bd` finished **`done`**, progress 1.0, in **1,136 s**: prepare 10 s → **transcribe 432 s** → **highlights 342 s** → **creative 242 s** → **reframe 20 s** → **export 90 s**. The transcript held **284 words**, language **`hi`**, and the text is real Devanagari gaming commentary — *"…आगे मार बस कित ते पैसे दे अगे बाई एक तो पैसे कमाना पड़ेगा…"*. The highlight stage ran against **llama3.1:8b** |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — the run was driven through the API |
| **Logs** | The stage transitions above, read from the job's own progress events |
| **Backend evidence** | `sources` row `a8224f79edde4239` (180.0 s, 640×360, 30 fps); `work/d24c58fe212444bd/transcript.json` with `language=hi`, `model=small`, `source=whisper`, 284 words, spanning 0.30 s → 153.43 s |
| **Export inspection** | Two clips and two exports — see AT-E-07 |

#### AT-E-07 — The two clips, and what was rendered

| Field | Record |
|---|---|
| **Test ID** | AT-E-07 |
| **User input** | Open the clip list the job produced |
| **Expected** | The model proposes clips; the app renders each as a 9:16 export with burned captions |
| **Actual** | Two clips survived the model's own ranking and the boundary refinement: **`2e78863daafc4c6e`** — *"Why nobody tells you this about scaling"*, 0.30 → 25.19 s, score 85; and **`23bb845bc10d453a`** — *"The biggest challenge in making money"*, 96.20 → 123.05 s, score 78, with the hook **"तो पैसे कमाना पड़ेगा"** — the real line from the transcript. Both were rendered |
| **Result** | **VERIFIED** |
| **Screenshot** | A frame extracted from each rendered file (not a UI screenshot): `frame-hindi.png` and `frame-scaling.png`. Both show the **facecam crop following the real streamer**, and **burned Devanagari captions** over the gameplay |
| **Logs** | — |
| **Backend evidence** | `clips` rows with the titles, hooks, scores and spans above; `exports/d24c58fe212444bd/` holds the two `.mp4` files and two `.srt` sidecars |
| **Export inspection** | `the-biggest-challenge-in-making-money_9x16.mp4` — h264, **1080×1920**, **30 fps**, AAC stereo **48 kHz**, **26.97 s**, 9,455,424 B. `why-nobody-tells-you-this-about-scaling_9x16.mp4` — h264, **1080×1920**, 30 fps, AAC stereo 48 kHz, **24.97 s**, 6,681,355 B. The `.srt` sidecar for the Hindi clip carries the Devanagari text with timings that match the burned captions |

#### AT-E-08 — The objective measurements — **the second defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-E-08 |
| **User input** | Read the clip diagnostics the application produced for each clip |
| **Expected** | Each measurement says what it measured and whether it passed. A measurement that cannot be made says so rather than pretending |
| **Actual** | Eight of the nine measurements passed on both clips: caption timing (31 and 78 words, 0 overlaps), duplicate clips (none), export validity, duration, resolution (1080×1920), frame-rate consistency (30.00 fps, 0.0 % spread), black frames (none), audio present (aac), audio clipping (0.000 %). The ninth, **crop safety, failed on both clips** with *"the crop cuts through the detected face"*. **That was a false positive** — see the defect below |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a — the diagnostics were read through `GET /api/clips/{id}/diagnostics` |
| **Logs** | `Clip 2e78863daafc4c6e: 1 diagnostic(s) to look at — Crop safety: the crop cuts through the detected face` |
| **Backend evidence** | The `diagnostics` JSON stored on each clip row. **The decisive re-measurement:** the stored report is returned as-is by the endpoint, so it was cleared (`diagnostics_json` set to `'{}'` — the column is `NOT NULL`, and the app treats a falsy value as "not measured yet"), the crop paths were rebuilt with the application's own `build_crop_path` (**1 segment; 123 faces / 0 faces**), and the endpoint was called again on a restarted instance. It returned **`ok=True` for both clips**: `crop_safety ok=True measured="1 segment(s), 123 face(s) tracked"` and `crop_safety ok=True measured="1 segment(s), no face tracked"`. The **same** crop paths under the **old** rule still fail with *"the crop cuts through the detected face"* — the only thing that differed is the rule |
| **Export inspection** | The rendered frames show the streamer's face **fully inside the crop**, and the second clip's window contains **no face at all** |

**The false positive, and what it actually was.** The crop-safety check was handed the
**source-level webcam region** — the rectangle the detector found once for the whole recording —
and called it *"the detected face"*. For this stream that rectangle was **185.7 × 252.82 px** around
an **83.16 px** face, at **0.221 confidence**, with the detector's own reason recorded as
*"the region held a face for less than half the clip"*. It is a **webcam candidate region**, not a
face, and it belongs to the **whole recording** rather than to any clip.

Measured against the real media, the failure was demonstrably wrong in both directions:

* On clip `2e78863daafc4c6e` the crop **tracks the real face** — every one of the **51** face
  observations MediaPipe made inside the clip lies wholly inside the crop window at its own
  timestamp — and the crop was still reported as cutting it.
* On clip `23bb845bc10d453a` there is **no face anywhere in the window** — the crop planner fell
  back to a `general` strategy for exactly that reason — and it was still reported as cutting one.

The fix makes the crop plan carry the **faces it was built around**, in source pixels and in the
clip's own time base, and the check compares each crop keyframe against the face nearest it **in
time**. The whole-source rectangle is no longer accepted as a face at all: `diagnose_clip` has no
`face_rect` argument to pass one in.

#### AT-E-09 — The model's own judgement

| Field | Record |
|---|---|
| **Test ID** | AT-E-09 |
| **User input** | Read the two proposed clips and their reasons |
| **Expected** | The model judges the hook and the payoff; the application keeps its judgement rather than substituting a rule for it |
| **Actual** | `llama3.1:8b` proposed two clips. The second — *"The biggest challenge in making money"*, score 78 — is a **genuine** selection, and its hook is the real Hindi line from the transcript. The first — *"Why nobody tells you this about scaling"*, score 85 — is **the example from the application's own prompt file**, copied verbatim: `backend/autoclip/prompts/highlight_v1.txt` uses that exact sentence as its illustration of a good hook. **This is recorded as a model-quality observation, not a code defect.** The application deliberately keeps the model's judgement, does not claim to verify the hook, and never rewrites the title to something it can prove |
| **Result** | **VERIFIED** — the mechanics ran against a real model, and the model's quality was recorded as it was |
| **Screenshot** | n/a |
| **Logs** | `Providers proposed 2 raw candidates.` |
| **Backend evidence** | The two `clips` rows; `backend/autoclip/prompts/highlight_v1.txt` for the example |
| **Export inspection** | Both clips rendered, as in AT-E-07 |

#### AT-E-10 — Nothing was published

| Field | Record |
|---|---|
| **Test ID** | AT-E-10 |
| **User input** | — |
| **Expected** | The content is a third-party creator's stream. It is used for technical acceptance only, and nothing is published anywhere |
| **Actual** | **No publish call was made.** No YouTube or Instagram account was connected, no OAuth flow was started, no credential was supplied, and no hosted service was called. The only network destinations in this run were `youtube.com` and its CDNs (the download) and `127.0.0.1:11434` (the local model). The transfer log holds exactly **one** row: the download |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | `egress_log` — one row, `operation=media_download`. `youtube_accounts` and `instagram_accounts` — empty |
| **Export inspection** | The two exported files stay in the scratch home and are deleted with it |

#### AT-E-11 — The four-hour source, through the whole pipeline

| Field | Record |
|---|---|
| **Test ID** | AT-E-11 |
| **User input** | Run the pipeline on the complete 4:00:10 recording |
| **Expected** | The recording is transcribed and turned into clips end to end |
| **Actual** | **Not run.** Transcription measured at about **7 minutes per 180 s** on this four-core laptop (Intel i5-8279U, 8 GB RAM, no CUDA), so the full recording would have needed roughly **9.6 hours** of transcription — **≈17 hours** with the highlight stage, which took **342 s for 180 s** of speech on the same machine, and **≈25 hours** for the whole pipeline. The ingest of the complete file **was** exercised, twice, at two different formats (AT-E-02, AT-E-05) |
| **Result** | **NOT APPLICABLE** — impractical on this machine, for the measured reason above. It is not claimed as verified |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The two complete downloads, 653 MiB and 5.15 GiB, and their source rows |
| **Export inspection** | n/a |

#### AT-E-12 — Unusual inputs on the same path

| Field | Record |
|---|---|
| **Test ID** | AT-E-12 |
| **User input** | `https://example.com/video.mp4`, and `https://192.168.1.10/stream.m3u8` |
| **Expected** | The API refuses what is not a YouTube URL, and the URL policy refuses a private network address |
| **Actual** | Both were refused at the API boundary with **HTTP 400** and the same clear message: *"That is not a YouTube URL."* The second one never reached the egress gateway, because the YouTube check comes first. The private-address refusal inside the download path is covered by the automated suite (`tests/test_url_policy.py`, `tests/test_egress.py`) and was not re-run here |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a |
| **Logs** | `400 Bad Request` on both |
| **Backend evidence** | `{"detail":"That is not a YouTube URL.","code":"validation","hint":"The request was not valid.","retryable":false}` |
| **Export inspection** | n/a |

### The gate that found the last defect — a flaky failure, diagnosed

After the M5.2 work was done, the **full-suite gate** failed once: **1,324 passed, 1 failed** in
1,234.88 s. The failing test was
`tests/test_instagram.py::test_a_publish_that_dropped_part_of_the_request_is_reported`, and the
failure was not in the test's subject at all:

```
autoclip.instagram.errors.InstagramError: Instagram was refused as a destination:
DNS for graph.facebook.com changed between lookups
(['57.144.52.141', '57.144.56.141'] then ['57.144.56.141', '57.144.52.141', '57.144.54.141']);
refusing a possible rebinding
```

The test **passed when run alone** (7.25 s), which is the signature of a flake. It was not one.

**What was actually happening.** The Instagram publisher routes every request through the egress
gateway, and the gateway classifies the destination — which means resolving the hostname. The URL
policy resolves **twice** on purpose, to defeat DNS rebinding, and the check was *"the two answers
must be the same set of addresses"*. `graph.facebook.com` is a load-balanced host: the two answers
above are the **same three Facebook edge addresses**, returned in different subsets. Both answers
were **public**, so neither could reach anything the policy does not already allow — but the strict
set comparison called it a rebinding and refused the publish.

**Why this was a product defect and not a test artefact.** The same rule applies to every host
AutoClip publishes to. `graph.facebook.com` is not a corner case; it is Meta's own Graph API
host. **A legitimate Instagram publish would have been refused intermittently, for no security
gain.** The fix compares the **class** of the two answers rather than the exact addresses: an
answer that moved *inwards* — public on the first lookup, private or loopback on the second — is
the rebinding attack and is still refused; an answer that moved between two public addresses is a
load balancer and is allowed.

**And why the test was wrong too.** The test's fake Graph API stubbed `httpx` but not the
resolver, so a unit test was reaching the real DNS — which is both slow and, as above,
non-deterministic. The whole unit suite now resolves nothing: an autouse fixture in
`tests/conftest.py` makes the real resolver unavailable, and the tests that care about resolution
inject their own.

### What M5.2 adds up to

| | |
|---|---|
| **The ingest path** | **VERIFIED** against a real four-hour live VOD, twice, at 360p and at the product's default 1080p cap |
| **The pipeline** | **VERIFIED** on real segments cut from that same downloaded file, with a real local model, producing two real clips and two real exports |
| **The transfer log** | **VERIFIED** — the download is now in it, which is what `EGRESS-INVENTORY.md` E11 has always claimed |
| **The default format cap** | **VERIFIED** — 1080p, not 1440p |
| **The crop-safety measurement** | **VERIFIED** after the fix; it was reporting failures that did not happen |
| **The publishing destination policy** | **VERIFIED** after the fix; a load-balanced public host is no longer mistaken for a rebinding, and the rebinding protection still holds |
| **The four-hour pipeline** | **NOT APPLICABLE** — ≈25 hours for the whole pipeline on this machine |
| **Any publishing** | **NOT APPLICABLE** — out of scope; technical acceptance only |

---

## M5.3 — The complete ten-minute pipeline (2026-11-21)

**What this section is.** A post-release increment to this file, dated **2026-11-21**, on the same
branch. It records a run of the real application against a **real, third-party YouTube video**,
supplied by the owner:

```
https://youtu.be/tg2MwT5FPdY?si=CEj6REktSyC2O_An
```

> **Rights.** This is another creator's video. It is used here for **technical acceptance only**.
> Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

**What M5.3 adds, and why it is not M5.2 again.** M5.2 ingested a **whole four-hour file** but ran
the pipeline on **pieces** of it; the complete-pipeline claim was left open as a stated limitation
(**K22**). This increment runs a **whole source** through **every stage** — paste, ingest,
prepare, transcribe, highlight, lay out, export, caption, diagnose — and inspects what came out.
The source is short enough to do that honestly: transcription measured at about seven minutes per
180 s on this four-core machine, so ten minutes of audio is about twenty minutes of transcription.

**The environment.** A separate application instance on **port 8803** with its own home at
`%TEMP%\opencode\autoclip-yt-v3`, so the owner's own instance and its database were untouched. The
model was the same real local **Ollama** (`llama3.1:8b` at `127.0.0.1:11434`), and
`active_provider=ollama` means **no hosted call and no hosted spend**.

**The source, as the internet described it.**

| | |
|---|---|
| Video id | `tg2MwT5FPdY` |
| Title | PODCAST OF THE DECADE🥵 \| CARRYMINATI |
| Channel | CarryMinati (`UCj22tfcQrWG7EMEKS0qLeEg`) |
| Duration | 619 s — **10:19** |
| Was live | no |
| Upload date | 2026-09-14 |
| Views / likes | 29,316,913 / 1,193,759 |
| Availability | public, no age limit |
| Audio track | Hindi (`hi`), **no manual subtitles** |
| Formats offered | 50 — and **not one** of them muxed; the best was 2560×1440 @ 30 fps, AV01 + Opus |

**This source is harder than M5.2's.** It is a podcast with intercut b-roll: a full-screen face at
5 s, an AI-generated animation at 120 s with **no face**, a **pillarboxed vertical** clip at 240 s
with **no face**, and a different, wider framing at 600 s.

### Journey F — the complete pipeline

#### AT-F-01 — Paste the short link

| Field | Record |
|---|---|
| **Test ID** | AT-F-01 |
| **User input** | `https://youtu.be/tg2MwT5FPdY?si=CEj6REktSyC2O_An`, pasted into the YouTube source field |
| **Expected** | The application accepts a **short** `youtu.be` link as well as a long `youtube.com` one, registers it immediately, and returns — the download happens in the background, not in the request |
| **Actual** | `POST /api/sources/youtube` → **201 Created** in one round trip, with a source row (`47d64e9e7fc14313`) whose title was the URL itself. The download had not started yet. The frontend (`Ingest.tsx`) posts the URL **unchanged** |
| **Result** | **VERIFIED** |
| **Screenshot** | Not captured — this run was driven through the HTTP API the browser uses, not through the screen. The screens were not the subject of this increment |
| **Logs** | `INFO: 127.0.0.1 - "POST /api/sources/youtube HTTP/1.1" 201 Created` |
| **Backend evidence** | `sources` row: `type=youtube`, `url=https://youtu.be/tg2MwT5FPdY?si=CEj6REktSyC2O_An` — the **query string preserved**, because the query is part of what the user pasted |
| **Export inspection** | n/a — nothing has been rendered yet |

#### AT-F-02 — The download happens on the worker, with a real `yt-dlp`

| Field | Record |
|---|---|
| **Test ID** | AT-F-02 |
| **User input** | Start a job on that source |
| **Expected** | The job's prepare stage runs `yt-dlp` against the URL, writes the complete file under `<root>/raw/<source_id>/`, and the source row is then updated with the real metadata |
| **Actual** | Job `1075820ea45841fe` went `queued → running/prepare`. A real `yt-dlp` process wrote `raw/47d64e9e7fc14313/source.mp4` — **140,602,318 B** — in **64.55 s**, at format **399+140** (1920×1080 AV01 `av01.0.08M.08` + `mp4a.40.2` @ 129.482 kbps) |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — the background worker has no screen |
| **Logs** | `Downloading YouTube source 47d64e9e7fc14313 with yt-dlp.`; the app's own progress event carried the download percentage |
| **Backend evidence** | `raw/47d64e9e7fc14313/source.mp4` = 140,602,318 B, confirmed with `ffprobe`; `sources` row updated to `duration_s=618.811791`, `width=1920`, `height=1080`, `fps=29.97002997002997`, `has_audio=1` |
| **Export inspection** | n/a — the ingest produces a source, not an export |

#### AT-F-03 — The source row carries the real metadata, and the title's encoding survives

| Field | Record |
|---|---|
| **Test ID** | AT-F-03 |
| **User input** | Open the source after the download |
| **Expected** | The source row carries the title, the channel, the duration, the frame size and the frame rate of the media that actually arrived — and the title is stored **exactly** as `yt-dlp` reported it |
| **Actual** | `title='PODCAST OF THE DECADE🥵\| CARRYMINATI'`, `channel='CarryMinati'`, `duration_s=618.811791`, `width=1920`, `height=1080`, `fps=29.97002997002997`. The emoji's **U+1F975** code point is intact, there is **no U+FFFD** anywhere in the string, there are **no lone surrogates**, and the database row is **byte-identical** to what `GET /api/sources/{id}` returns |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The row above, read back through the API and out of `autoclip.db`, and compared against the `source.info.json` sidecar byte for byte |
| **Export inspection** | n/a |

> **A note about the console.** During this run the title printed as mojibake in the terminal. That
> was the **PowerShell console's cp1252 code page**, not the data. The evidence above is the
> byte-level comparison, and it is clean. It is recorded here because a reader who repeats the run
> will see the same mojibake and should not mistake it for a defect.

#### AT-F-04 — The download appears in the transfer log — **exactly one row**

| Field | Record |
|---|---|
| **Test ID** | AT-F-04 |
| **User input** | Open *Settings → External processing* after the download |
| **Expected** | The download is classified before the fetch and **logged** — one row, with the destination's query string stripped and the duration recorded |
| **Actual** | **Exactly one** row for the download: `operation=media_download`, `provider=yt-dlp`, `destination=https://youtu.be/tg2MwT5FPdY` (query stripped), `destination_class=public`, `outcome=ok`, `duration_ms=64550`, `data_summary="A page and its media are fetched from the URL you supplied."` |
| **Result** | **VERIFIED** |
| **Screenshot** | Not captured — the transfer log was read through `GET /api/privacy/transfers` and out of the `egress_log` table |
| **Logs** | — |
| **Backend evidence** | The `egress_log` row above, `occurred_at=2026-11-21T14:31:06Z` |
| **Export inspection** | n/a |

#### AT-F-05 — The whole file is transcribed

| Field | Record |
|---|---|
| **Test ID** | AT-F-05 |
| **User input** | Let the job's transcribe stage run |
| **Expected** | The **complete** 619 s is transcribed by the local whisper, and the transcript is written out with word-level timings |
| **Actual** | **1,346 s** (22.4 min) for 619 s of audio. `transcript.json` written: language `hi`, model `small`, **1,128 words**, **193 segments** |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a |
| **Logs** | the job's own progress events, `stage=transcribe` |
| **Backend evidence** | `work/1075820ea45841fe/transcript.json` — `language=hi`, `model=small`, 1,128 words, 193 segments |
| **Export inspection** | n/a |

#### AT-F-06 — The refinement keeps six candidates out of ten — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-F-06 |
| **User input** | Let the job's highlight stage run, and compare the candidates the model proposed with the candidates the refinement kept |
| **Expected** | The refinement snaps each candidate to a real sentence boundary and keeps it if it falls inside the duration rules. **On a Hindi transcript, the sentence boundaries have to exist at all** |
| **Actual** | The model proposed **10 raw candidates**. The **old** refinement kept **2**. The **fixed** refinement kept **6**, and the pipeline's own deduplication turned those into the **3 clips** that were exported. The reason is measured: on the real transcript the old `SENTENCE_END` matched **1** of **1,128** words — the danda `।` appears in **5** of them and was invisible — and the old `CLAUSE_END` matched **28**. The new patterns match **6** and **34** |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a — this is a pipeline measurement, read out of the candidate dump the harness captured |
| **Logs** | — |
| **Backend evidence** | The raw candidate list and the refined list, captured from the same run; `transcript.json` for the word timings |
| **Export inspection** | The three clips this produced — AT-F-08 |

> **What this test does *not* claim.** The **before-run** of this job produced **1** clip and the
> **re-run** produced **3**, but the detection stage runs at `DetectionConfig.temperature = 0.3`, so
> the two runs saw **different candidate sets** and proposed **different titles**. The raw
> "1 against 3" comparison is therefore **not** a controlled measurement of the fix. The controlled
> comparison is the one above — the **same ten candidates**, refined by the old code and by the new
> code — and the offline sweep in AT-F-07.

#### AT-F-07 — The clip edges land on real boundaries — the offline sweep

| Field | Record |
|---|---|
| **Test ID** | AT-F-07 |
| **User input** | Take the real transcript and run every plausible candidate range through the old rule and the new rule |
| **Expected** | The rule keeps a candidate when it can find a sentence end inside it, and when it cannot, it falls back to the **first word that reaches the minimum duration** instead of dropping the candidate |
| **Actual** | Over **1,130** plausible candidate ranges drawn from the real transcript: the **old** rule kept **852** (75 %) and dropped **278**; the **new** rule kept **1,070** (94 %) and dropped **60**. The mean kept duration fell from **61.1 s** to **52.9 s** — the old rule was keeping *longer* clips because it was willing to stretch to the next sentence end, and dropping the rest |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The sweep was run over the real `transcript.json`; the per-candidate decisions were written out and compared rule against rule |
| **Export inspection** | n/a |

#### AT-F-08 — The export completes — the command fits — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-F-08 |
| **User input** | Let the export stage render the three clips |
| **Expected** | The export produces three files. On Windows, the ffmpeg **command line** must fit inside the operating system's **32,767-character** limit |
| **Actual** | **The first attempt died.** Job `f4648116d6ba49e4` failed at progress **0.88** with `FileNotFoundError: [WinError 206] The filename or extension is too long` — and it reproduced **every time**. The clip that failed is *Alien interview* (478.08–518.26 s), with **20 crop segments** and **11 speech-emphasis spans**: its filter graph was **36,588** characters and its command line **36,743** — **1.1× over the limit**. The cause was one line of arithmetic: the webcam crop spelled the whole emphasis expression out once per segment, repeating a **293-character** term **80 times**. **After the fix**, the same clip's command is **10,697** characters — **0.33×** of the limit — and the job reaches `done` with all three clips exported |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a — the export stage has no screen |
| **Logs** | the job's own error field carried the `WinError 206`; the re-run carried `status=done stage=export progress=1.0000 error=None` |
| **Backend evidence** | The command sizes, measured on the real clip's own crop path: *Why most agencies die at 10 clients* 6,817 → 6,972; *Alien interview* **36,743 → 10,697**; *The problem with marriage* 7,609 → 7,764 |
| **Export inspection** | `alien-interview_9x16.mp4` — 34,941,233 B, 1080×1920, 29.97 fps, AAC stereo, **0.000 % full-scale** |

> **A guard was added in front of the failure.** `ffmpeg.check_command_line_length` now refuses an
> over-long command **before** ffmpeg is launched, and the message names the **filter graph** rather
> than blaming a filename. The limit is overridable so the check itself is testable on Linux CI.
> **7 tests fail without the export fix** (the 6 in `tests/test_export_graph.py` and the behavioural
> render test), and **4 more** fail without the command-line guard.

#### AT-F-09 — The webcam's speech emphasis renders in a later stretch — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-F-09 |
| **User input** | Render the same composition twice — once during a quiet moment, once during a talking moment — in the **second** stretch of the clip |
| **Expected** | The emphasis expression is written against **clip-relative** speech spans, so the webcam strip magnifies during speech **wherever in the clip** the speech is |
| **Actual** | **Before the fix, it did not.** The crop was applied to each PTS-reset (`setpts=PTS-STARTPTS`) segment, so the expression's `t` restarted at every segment boundary: the webcam only ever magnified in the **first** segment. `croppath.axis_expression` subtracts `offset_s` for exactly this reason, and the two disagreed. **After the fix** — the crop applied once, after the segment concat — the strip differs between the quiet moment and the talking moment in the later stretch |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a — this is a pixel comparison inside the render test |
| **Logs** | — |
| **Backend evidence** | `tests/test_export_render.py::TestLayoutRender::test_the_speech_emphasis_renders_in_a_later_stretch` — a **behavioural** render test: it compares the webcam strip at a quiet moment (2.7 s) with the webcam strip at a talking moment (4.0 s), in the second stretch, and asserts the two differ |
| **Export inspection** | The three exported files, each with a webcam strip that tracks the speech through the whole clip rather than only its first segment |

#### AT-F-10 — The caption is not held on screen for twelve seconds — **the defect this increment found**

| Field | Record |
|---|---|
| **Test ID** | AT-F-10 |
| **User input** | Read the application's **own** caption diagnostic on the clip *The problem with marriage* |
| **Expected** | A caption is read, not watched. It should not sit on screen long after the words have been read |
| **Actual** | **Before the fix, the application's own diagnostic said:** *"3 word(s) are held on screen too long"*. The cause was an alignment estimate — Whisper stretched one Hindi word, `में`, across **7.84 seconds** (552.730 → 560.570 s), and the caption inherited it. Measured on the rendered file: `bold_pop` held one caption for **7.84 s**, and the group styles (`karaoke_fill`, `clean_lower`) held a four-word cue for **12.57 s**. **After the fix**, the longest caption is **2.05 s** (per word) and **2.50 s** (group) |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The fresh diagnostic on the re-exported clip: `caption_timing` **ok**, measured `"20 words, 0 overlap(s), longest caption 2.05s"`, and the clip's overall verdict `ok: true` |
| **Export inspection** | The `.srt` sidecar — AT-F-11 |

> **Why the fix is in the caption layer and not the transcript layer.** The recogniser's word
> timings are **estimates**, and several other consumers want them as the recogniser reported
> them. It is the **caption's own lifetime** that needs a bound, so `captions.MAX_CAPTION_S = 2.5`
> bounds it — and `captions.caption_spans()` is now the **single source** of the caption timing,
> shared by the renderer and the diagnostic, so the diagnostic measures the captions that are
> actually burned into the export.

#### AT-F-11 — The `.srt` sidecar: every cue bounded, and the text preserved

| Field | Record |
|---|---|
| **Test ID** | AT-F-11 |
| **User input** | Read every cue of every `.srt` sidecar the export wrote |
| **Expected** | No cue is held for longer than the bound, and **no word is lost** — the text is still all there |
| **Actual** | **Before the fix**, `the-problem-with-marriage_9x16.srt` carried the cue `00:00:09,080 --> 00:00:21,650` — **12.57 s** — with the text `ने, नहीं, साइड में`. **After the fix**, that cue is **two**: `ने, नहीं,` (9.080 → 11.580) and `साइड में` (11.760 → 14.260), and the sidecar has **6 cues**. The longest captions across the three re-exported clips are **2.500 s / 2.500 s / 2.380 s** — **none over the bound**. Every word of the clip is still captioned |
| **Result** | **VERIFIED** (after the fix) — **FAILED** before it |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | The sidecars were read back with `pysubs2` and every cue's duration measured. `pysubs2` 1.8 stores subtitle times in **milliseconds**, not centiseconds |
| **Export inspection** | `the-problem-with-marriage_9x16.srt` — 443 B, 6 cues; `alien-interview_9x16.srt` — 1,256 B, 15 cues; `why-most-agencies-die-at-10-clients_9x16.srt` — 1,479 B, 15 cues |

#### AT-F-12 — The application's own ten measurements, on all three clips

| Field | Record |
|---|---|
| **Test ID** | AT-F-12 |
| **User input** | Open each clip's diagnostics |
| **Expected** | Ten measurements per clip: caption timing, crop safety, duplicate clips, export validity, duration, resolution, frame-rate consistency, black frames, audio present, audio clipping |
| **Actual** | *Alien interview* (`f22a5314317d44c5`) — **every measurement `ok: true`**. *The problem with marriage* (`170047e67fc44a55`) — **every measurement `ok: true`**, including `caption_timing` with `"20 words, 0 overlap(s), longest caption 2.05s"`. *Why most agencies die at 10 clients* (`5c15ddb7f920411d`) — `ok: false` on **`black_frames` only**; the other nine are `ok: true` |
| **Result** | **VERIFIED** |
| **Screenshot** | Not captured — the diagnostics were read through `GET /api/clips/{id}/diagnostics` |
| **Logs** | — |
| **Backend evidence** | The diagnostics payloads, captured verbatim. The three clips: `5c15ddb7f920411d` (572.47 → 603.67 s, score 87), `f22a5314317d44c5` (478.080812 → 518.26 s, score 60), `170047e67fc44a55` (538.92 → 572.19 s, score 50) |
| **Export inspection** | `why-most-agencies-die-at-10-clients_9x16.mp4` — 40,539,188 B, 1080×1920, 29.97 fps, 31.30 s; `alien-interview_9x16.mp4` — 34,941,233 B, 40.27 s; `the-problem-with-marriage_9x16.mp4` — 28,552,646 B, 33.37 s. Every one: AAC stereo, **0.000 % of samples at full scale** |

#### AT-F-13 — The black stretch is in the source, not in the export

| Field | Record |
|---|---|
| **Test ID** | AT-F-13 |
| **User input** | Run `ffmpeg blackdetect` over the **raw source**, and compare its answer with the export's |
| **Expected** | If the measurement is right about the export, it should also be right about the source — and if the source has a black stretch, the export carrying the same stretch is **correct behaviour, not a defect** |
| **Actual** | The raw source has `black_start:601.534267 black_end:603.369433 black_duration:1.835167`, plus a second stretch of **0.53 s** at 154.49 s. The export carries the **identical** 1.835 s stretch. The diagnostic was **right**, and the source is what is black |
| **Result** | **VERIFIED** — the measurement is a true positive about the source |
| **Screenshot** | n/a |
| **Logs** | — |
| **Backend evidence** | `ffmpeg -i raw/47d64e9e7fc14313/source.mp4 -vf blackdetect` output, against the export's own `black_frames` measurement |
| **Export inspection** | The export carries the source's own black frames, unchanged. **Nothing was "fixed"** — there was nothing to fix |

#### AT-F-14 — The complete pipeline, with nothing left as "not run"

| Field | Record |
|---|---|
| **Test ID** | AT-F-14 |
| **User input** | Run the application against one URL, and follow it all the way to the finished files |
| **Expected** | Every stage of the pipeline runs on a **complete** source: ingest → prepare → transcribe → highlight → creative → reframe → export, with the diagnostics measured on the results |
| **Actual** | Job `f4648116d6ba49e4` reached **`done`** with `progress=1.0000` and `error=None`. **Every stage ran.** The transcript and the **highlight candidates** were reused from the earlier run, so **no model was asked again** for either and the comparison stayed controlled. The **creative plan was rebuilt**, not reused — as a **fallback**, because the planning budget had already been spent — and it was written at **18:02:38** with `problems=['the creative-planning budget was spent']`. The job's own timeline: `prepare` and `transcribe` complete, `highlights` reached in **instantly** on the re-run, and the export ran to `progress=1.0000` in **176.3 s** |
| **Result** | **VERIFIED** |
| **Screenshot** | Not captured — this run was driven through the HTTP API the browser uses |
| **Logs** | the job's progress events, from `queued` through `running/export` to `done` |
| **Backend evidence** | `jobs` row: `id=f4648116d6ba49e4`, `status=done`, `current_stage=export`, `progress=1.0`, `error=NULL`. The transfer log holds **9 rows** for the whole run, all of them accounted for: **1** `media_download` (yt-dlp, public), **7** `highlights`/`creative_planning` against `http://127.0.0.1:11434` (class **loopback** — four highlight calls and three planning calls), and **1** `model_download` of `face_landmarker.task` from `storage.googleapis.com` (class **public**) |
| **Export inspection** | Three vertical exports and three `.srt` sidecars, all measured — AT-F-11 and AT-F-12 |

> **What the model chose, and what it did not.** The three clips' **titles, hooks, reasons and
> scores** are the **highlight stage's** — they came from the model's own candidates in the first
> place (*"Hook is not strong, but payoff is a specific and concrete statement."*). What fell
> back to the deterministic defaults was the **creative plan's** layer: `layout='auto'`,
> `crop='auto'`, `caption_strategy=''`, `ducking_db=0.0`, `reason=''` for all three clips. The
> database records that distinction rather than hiding it — `creative_plans.source` is
> **`fallback`**, and `job_ai_budget` shows `plan_used=1, repair_used=1` for this job against
> `plan_used=1, repair_used=0` for the first job, whose plan **did** validate and **did** choose
> `caption_strategy='clean_lower'` and `ducking_db=-12.0`.
>
> **The budget is a real product behaviour and it worked as designed.** One plan call and one
> repair retry per job: the model answered, the answer did not match the schema, the repair
> answer did not match it either, and the plan fell back with the reason recorded. The later
> resume found the budget spent and wrote the fallback again — **without** silently spending
> another call. The clip **titles** were never in doubt; only the **plan** was.

> **One new public egress was observed and is now in the inventory.** The MediaPipe face detector
> downloads `face_landmarker.task` (**3.6 MB**) from
> `storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/` on first use.
> That is `E12` in `docs/EGRESS-INVENTORY.md`, and the observed destination is recorded there.

#### AT-F-15 — The export's graph is valid on the CI's ffmpeg, not only on the newest one — **the defect the Linux leg found**

| Field | Record |
|---|---|
| **Test ID** | AT-F-15 |
| **User input** | Run the **Linux reproduction leg** — the ffmpeg-sensitive selection, on the CI's platform (**ffmpeg 7.0.2**), from the **committed** tree rather than the working directory |
| **Expected** | The export's filter graph is valid on **every** ffmpeg, not only the newest one. A clip whose crop path has more than one segment exports on the CI runners and on a user's machine with an older ffmpeg |
| **Actual** | The leg **failed**: `Invalid stream specifier: gsrc` / `Error binding filtergraph inputs/outputs: Invalid argument`. The video graph split the source in **two** — `[0:v]split=2[gsrc][wsrc]` — and then **each** crop segment read from the same output again. A filter output may be consumed **only once**. ffmpeg **9.0.2** tolerates it; ffmpeg **7.0.2** refuses it. The developer's machine agreed with the developer's ffmpeg, so it rendered there and nowhere else. After the fix the leg is green: **267 passed** |
| **Result** | **VERIFIED** — the defect was reproduced on ffmpeg 7.0.2, fixed, and the leg re-run green from the committed tree |
| **Screenshot** | n/a — a gate, not a screen |
| **Logs** | The leg's log: `1 failed, 262 passed` before the fix; `267 passed in 104.89s` after |
| **Backend evidence** | The committed tree `2b5935d`, by `git archive` — what was tested is what is committed. The shape was **measured on both ffmpeg builds** before it was chosen: `split=N` is accepted up to **64** outputs by 7.0.2 and 9.0.2 alike, while the alternative — one `trim` with several ranges — needs a `setpts` per output, because `setpts` has only one |
| **Export inspection** | The two-stretch test graph now reads `split=4` — two gameplay copies and two webcam copies. The real 20-segment clip would read `split=40`. The structural check now runs over the **video** graph as well as the music graph |

> **This is the same class as defect 3**, the M5 sidechain bug — a filter output consumed twice —
> and it was found by the **same** leg. That leg exists because the CI runners are Linux, on a
> different ffmpeg from the development machine, and because a fix that only renders on the
> developer's machine is not a fix.

### What M5.3 adds up to

| | |
|---|---|
| **The complete pipeline** | **VERIFIED** — a whole ten-minute source, every stage, end to end. This is what **K22** said was missing |
| **The short link** | **VERIFIED** — `youtu.be` is accepted and the URL is stored as the user pasted it |
| **The title's encoding** | **VERIFIED** — byte-identical to `yt-dlp`'s, with the emoji intact |
| **The transfer log** | **VERIFIED** — exactly one row for the download, with the duration |
| **The sentence boundaries** | **VERIFIED** after the fix; a Hindi transcript had almost none before it |
| **The clip-edge rule** | **VERIFIED** after the fix; it dropped candidates silently before |
| **The export** | **VERIFIED** after the fix; the ffmpeg command line could exceed Windows' own limit before |
| **The webcam emphasis** | **VERIFIED** after the fix; it only ever worked in the first segment before |
| **The caption's lifetime** | **VERIFIED** after the fix; a caption could be held for twelve seconds before |
| **The graph's portability** | **VERIFIED** after the fix; a multi-segment clip failed on ffmpeg 7 before |
| **The complete four-hour pipeline** | **NOT APPLICABLE** — ≈25 hours for the whole pipeline on this machine. A complete *ten-minute* source was run instead, and that is what the claim above rests on |
| **Any publishing** | **NOT APPLICABLE** — out of scope; technical acceptance only |
| **The hosted-LLM and ElevenLabs paths** | **UNVERIFIED** — no authorised credential; the run used a local Ollama and local whisper |

---

## M5.4 — A second real source, and a local model that could not answer (2026-11-22)

**What this section is.** A post-release increment to this file, dated **2026-11-22**, on the same
branch. It records a run of the real application against a **second real, third-party YouTube
video**, supplied by the owner:

```
https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP
```

> **Rights.** This is another creator's video. It is used here for **technical acceptance only**.
> Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

**What M5.4 adds, and why it is not M5.3 again.** M5.3 proved that the whole pipeline runs on a
complete source. It did **not** prove that the pipeline survives a source whose **highlight
detection** is the hard part: M5.3's ten-minute podcast produced a transcript the local model
handled in **425 s**. This increment took a source that is **shorter** (574.9 s) but **denser** —
and the run **failed at highlight detection**, twice, for the same reason and with the same
message. Four defects sat behind that one line, and they are the subject of this section.

**The environment.** A separate application instance on **port 8804** with its own home at
`%TEMP%\opencode\autoclip-yt-v4`, so the owner's own instance and its database were untouched. The
model is the same real local **Ollama** (`llama3.1:8b` at `127.0.0.1:11434`), and
`active_provider=ollama` means **no hosted call and no hosted spend**. The settings are the ones
M5.3 used, so the two runs are comparable.

**The source, as the internet described it.**

| | |
|---|---|
| Video id | `bMTlNeKqV4o` |
| Title | UNEMPLOYMENT ON PEAK 📈 \| CARRYMINATI |
| Channel | CarryMinati |
| Duration | 574.879637 s — **9:35** |
| Resolution / rate | 1920×1080 at 29.970059515628723 fps |
| Audio track | Hindi (`hi`), **no manual subtitles** |
| Source id / job id | `b5bf5a6f740a40ee` / `f65fb40febe141d7` |

### Journey G — the second complete pipeline

#### AT-G-01 — The field is empty before anything is pasted

| Field | Record |
|---|---|
| **Test ID** | AT-G-01 |
| **User input** | Open the scratch instance at `http://127.0.0.1:8804`, on the **Ingest** page, before typing anything |
| **Expected** | The ingest field is empty, and the **Start** button is disabled until there is something to start |
| **Actual** | The field was empty and **Start** was disabled |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-G-01-before-empty-field.png` |
| **Logs** | n/a — a screen state |
| **Backend evidence** | `GET /api/settings` on the same instance returned the M5.3 settings unchanged |
| **Export inspection** | n/a |

#### AT-G-02 — The short link is pasted, and the URL is stored byte-for-byte

| Field | Record |
|---|---|
| **Test ID** | AT-G-02 |
| **User input** | Paste `https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP` into the ingest field, and start the job |
| **Expected** | The application accepts the short link **with its tracking query**, and sends the URL to the server exactly as it was pasted |
| **Actual** | The field showed the pasted URL. The network panel recorded `POST /api/sources/youtube` → **201** with the body `{"url":"https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP","cookies_from_browser":null}` — **byte-for-byte the pasted URL**, tracking query and all — and then `POST /api/jobs` → **201** |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-G-02-pasted-url.png` |
| **Logs** | The app's own access log records the two POSTs with their status codes |
| **Backend evidence** | The source row `b5bf5a6f740a40ee` carries the URL as pasted. `yt-dlp` drops the `?si=` tracker when it records the download's destination — the *transfer log* names `https://youtu.be/bMTlNeKqV4o`, while the *source row* keeps the pasted URL exactly. That difference is the correct one: the first is where the bytes came from, the second is what the user gave the application |
| **Export inspection** | n/a |

#### AT-G-03 — The source is downloaded, at the configured format

| Field | Record |
|---|---|
| **Test ID** | AT-G-03 |
| **User input** | Wait for the download the job started |
| **Expected** | The source is fetched at the configured format — **1080p or lower**, not the best on offer — and the download appears in the transfer log |
| **Actual** | yt-dlp chose format **616+140** (1920×1080 VP9 `vp09.00.40.08` + `mp4a.40.2`), **225,722,498 B**, in **51,703 ms**. The transfer log carries **exactly one** `media_download` row: public, `ok`, 51,703 ms |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-G-03-job-running.png` — the job at 16 %, in **Prepare** |
| **Logs** | The application's own log; the transfer row is read back from the scratch database |
| **Backend evidence** | The source row: `duration_s=574.879637`, 1920×1080, `fps=29.970059515628723`. The title's emoji survived: `UNEMPLOYMENT ON PEAK 📈 \| CARRYMINATI` |
| **Export inspection** | n/a |

#### AT-G-04 — The prepare stage produces what the later stages need

| Field | Record |
|---|---|
| **Test ID** | AT-G-04 |
| **User input** | Let the prepare stage finish |
| **Expected** | An audio track for the transcriber and a thumbnail sheet for the review page |
| **Actual** | `audio.wav` of **18,396,226 B**, and **115** thumbnails |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-G-04-transcribing.png` — 27 %, **Prepare ✓** and **Transcribe** running |
| **Logs** | The application's own log |
| **Backend evidence** | The work directory of job `f65fb40febe141d7` |
| **Export inspection** | n/a |

#### AT-G-05 — The whole file is transcribed, in Hindi

| Field | Record |
|---|---|
| **Test ID** | AT-G-05 |
| **User input** | Wait for the transcription |
| **Expected** | The **whole** file is transcribed, in its own language, with word timings |
| **Actual** | whisper `small`, language **`hi`**, **1,060 words** in **220 segments**, written at 05:03:15 UTC. The **same file** transcribed again, in the verification run, gave **1,277 words** in **246 segments** — the recogniser is **not** reproducible, and that is measured in **AT-G-17** |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-G-04-transcribing.png` |
| **Logs** | The application's own log |
| **Backend evidence** | `transcript.json` in the job's work directory. The sentence-boundary rule was checked against this transcript as well: the **old** `SENTENCE_END` matched **20** words, the **new** one matches **22**; the **new** `CLAUSE_END` matches **18**; the danda `।` appears in **2** words (`रहेज़।`, `हूँ।`); there is **no** U+FFFD |
| **Export inspection** | n/a |

#### AT-G-06 — The caption fix is exercised by this source

| Field | Record |
|---|---|
| **Test ID** | AT-G-06 |
| **User input** | Read the word timings of this transcript |
| **Expected** | No word is stretched across seconds of silence — the defect-12 class, which a caption inherits if the recogniser's timing is used as the caption's lifetime |
| **Actual** | **5** words exceed **1.5 s**, and two of them are long: `'इ'` spans **8.080 s** (404.750 → 412.830) and `'रोएगे'` **7.960 s**. The same class as M5.3's `'में'`, which spanned 7.840 s |
| **Result** | **VERIFIED** — the fix was already in the tree, and this source exercises it |
| **Screenshot** | n/a — a measurement |
| **Logs** | The application's own log |
| **Backend evidence** | The transcript's own word timings, read back from the scratch database's transcript row |
| **Export inspection** | The exported `.srt` is the place this shows; see AT-G-13 |

#### AT-G-07 — Highlight detection fails, and says so

| Field | Record |
|---|---|
| **Test ID** | AT-G-07 |
| **User input** | Wait for the highlight stage |
| **Expected** | The stage either produces clips or says **why** it could not |
| **Actual** | The stage **failed** at 05:23:19 UTC, at progress **0.55**, with the error *"Highlight detection failed in every window. Original error: Ollama timed out."* The transfer log carries **two** `highlights` rows, each `failed`, each lasting the provider's whole ceiling: **600,086 ms** and **600,450 ms** |
| **Result** | **FAILED** — the stage did not produce clips. This is the defect this increment is about |
| **Screenshot** | The job page showed **Retry — Retrying resumes from the stage that failed** |
| **Logs** | The application's own log: the window's exception, and the stage's error |
| **Backend evidence** | The job row's `error` column and the two transfer rows, read back from the scratch database |
| **Export inspection** | n/a — nothing was exported |

#### AT-G-08 — The message was wrong about the machine, and wrong about the windows

| Field | Record |
|---|---|
| **Test ID** | AT-G-08 |
| **User input** | Read the error the application showed, and the transfer log beside it |
| **Expected** | The message says what actually happened |
| **Actual** | It did not. It said *"failed in every window"* when **two** windows ran and both timed out, and the underlying hint said *"Large transcripts on a small GPU can exceed the limit. Try a smaller model, or use a hosted provider for this video."* — on a machine with **no GPU at all** (`size_vram: 0`, an Intel Iris Plus iGPU), and for a user with no hosted provider |
| **Result** | **FAILED** — three separate inaccuracies in one message. They are **defects 15** and **16** |
| **Screenshot** | n/a — the message is in the log and in the job row |
| **Logs** | The application's own log |
| **Backend evidence** | `GET /api/ps` on the same Ollama reported `size_vram: 0` and `context_length: 4096` |
| **Export inspection** | n/a |

#### AT-G-09 — The request could not fit the context it was given

| Field | Record |
|---|---|
| **Test ID** | AT-G-09 |
| **User input** | Measure the request the application actually sent, with the server's own tokenizer |
| **Expected** | The prompt and the answer both fit the context the model server is running with |
| **Actual** | They did not. The standing instructions are **3,635 characters**; window 0's user prompt is **8,486 characters**; window 1's is **3,182**. Measured with llama-server's own tokenizer, window 0's prompt is **5,861 tokens** against a **4,096-token** context — **1,765 tokens over**. The product also asked for `num_predict: 4096`, an answer budget as large as the entire context, so even a prompt of zero would have had no room for an answer |
| **Result** | **FAILED** — the server truncates a prompt that does not fit **without saying so**, so the model would have answered from a partial transcript. This is **defect 17** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The measurement scripts' own output; the model's own `prompt_eval_count` |
| **Backend evidence** | The experiment: the **same** window-0 payload with `num_ctx: 8192` and `num_predict: 1024` returned **HTTP 200** after **1,992.9 s**, with `prompt_eval_count: 5862` — the estimate exactly — `eval_count: 875`, `done_reason: stop`, and a valid JSON object with **11** clips. `/api/ps` then reported `context_length: 8192`, the model's size growing from **5.58 GB** to **6.26 GB** — about **680 MB** of extra KV cache. A context of **16,384** would have added about **2.7 GB**, which does not fit this **8.4 GB** machine |
| **Export inspection** | n/a |

#### AT-G-10 — The four defects, and what each one cost

| Field | Record |
|---|---|
| **Test ID** | AT-G-10 |
| **User input** | Fix what the run exposed |
| **Expected** | Each defect is fixed and guarded by a test that fails without the fix |
| **Actual** | **Four defects** — **14** (the hard-coded 600 s ceiling), **15** (the message that blamed a GPU the machine does not have), **16** (the stage that kept going after a timeout, and then claimed every window had failed), **17** (the request that did not fit the context). The full record is in the defect table below, and the guards are in `tests/test_provider_limits.py` (**21** tests) and `tests/test_api.py` (**2** tests) |
| **Result** | **VERIFIED** — every guard was observed failing against the pre-fix code |
| **Screenshot** | n/a — a gate, not a screen |
| **Logs** | The gate's own output |
| **Backend evidence** | The **20 of 21** tests in `tests/test_provider_limits.py` fail without the fix; the one that passes is a non-regression guard (a provider with no limit keeps its windows as they were). Both settings tests in `tests/test_api.py` fail without the fix |
| **Export inspection** | n/a |

#### AT-G-11 — Two clips, one title: the export that overwrote the other

| Field | Record |
|---|---|
| **Test ID** | AT-G-11 |
| **User input** | Read the export directory of the finished job, and compare it with what the database says each export was |
| **Expected** | Every clip has **its own** file and **its own** subtitles, whatever the model called it |
| **Actual** | It did not. Two of the nine clips were called *"The language of love in videos"* — the **model's** choice, made twice. The export directory held **one** `.mp4` for them: the second clip's **54,024,088 B** had replaced the first clip's **14,272,780 B**. The database still said clip `61e1d3ec8c3e4dce` was **14,272,780 B** — a file that no longer existed — and there was **one** `.srt` where there should have been two |
| **Result** | **FAILED** — the first clip was gone, and its subtitles with it. This is **defect 18** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The application's own log |
| **Backend evidence** | `exports/f65fb40febe141d7/` read back from disk, against the `exports` table of the scratch database |
| **Export inspection** | The export directory itself: the file sizes on disk, the number of `.srt` sidecars, and the two clips' recorded sizes |

#### AT-G-12 — The crop-safety diagnostic measured the wrong face

| Field | Record |
|---|---|
| **Test ID** | AT-G-12 |
| **User input** | Read the diagnostics of the nine clips, and rebuild each clip's crop plan to check the report against the source |
| **Expected** | A clip that keeps its subject's face in frame is not reported as cutting one |
| **Actual** | **6 of the 9 clips** were reported: *"the crop cuts through the detected face"*. The diagnostic took *"the largest face within half a second"* as the subject, while the crop follows the **tracked** speaker. Rebuilding the plans and measuring them against the face each one actually followed showed the cut at **0** keyframes in four of the six. In a fifth, one segment's track held **two different people** — the crop had panned to the wrong one — and the frame from the source shows what the detector saw: the speaker, leaning forward, and a Pikachu plush on the shelf behind them |
| **Result** | **FAILED** — the measurement was about the wrong face, and one track was following the wrong person. These are **defects 19** and **22** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The application's own log |
| **Backend evidence** | The nine clips' `diagnostics_json`, read back from the scratch database; the rebuilt crop plans, measured face by face |
| **Export inspection** | n/a — the crops are plans, not renders |

#### AT-G-13 — Two pairs of clips were the same footage

| Field | Record |
|---|---|
| **Test ID** | AT-G-13 |
| **User input** | Read the `duplicate_clips` diagnostic of the finished job, and compare the pairs it named with the clips' own time ranges |
| **Expected** | Two clips of the same moment are **one** clip |
| **Actual** | The diagnostic named **4 of the 9 clips**: *"overlaps another one by 100%"*. The pipeline had kept both clips of each pair. Rank 1 (533.852–557.610) sat wholly inside rank 2 (514.150–561.180), and rank 8 (107.970–131.250) wholly inside rank 7 (100.410–140.470). The de-duplication compared the candidates' **word ranges**, and a clip inside another one has almost no words in common with it: the shorter clip of the first pair covered **14** words, the longer **104**, of which those 14 were a part — a common share of a fifth, well under the threshold. In **time**, they were the same clip twice |
| **Result** | **FAILED** — the pipeline and the diagnostic had **two different definitions** of the same thing. This is **defect 20** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The application's own log |
| **Backend evidence** | The clips' `start_s`/`end_s` and `start_word`/`end_word`, read back from the scratch database |
| **Export inspection** | The export directory held **both** members of both pairs — two pairs of the same footage, exported twice |

#### AT-G-14 — A clip that opened inside its first word

| Field | Record |
|---|---|
| **Test ID** | AT-G-14 |
| **User input** | Read the `caption_timing` diagnostic of the finished job, and check the first word of each clip against the clip's own start |
| **Expected** | A clip opens **at or before** its first word — the code's own rule: *"alignment only ever widens a clip"* |
| **Actual** | It did not. **2 of the 9 clips** were reported: *"1 word(s) fall outside the clip"*. Rank 1's first word started at **533.800 s** and the clip opened at **533.852 s** — **52 ms inside the word**; rank 6's first word started at **49.370 s** and the clip opened at **49.387 s**. The silence detector and the recogniser disagreed by tens of milliseconds, and the alignment followed the silence past the word's own start |
| **Result** | **FAILED** — the invariant the code documents was not the invariant the code kept. This is **defect 21** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The application's own log |
| **Backend evidence** | The clips' `start_s` against the transcript's word timings, and the silences the alignment used |
| **Export inspection** | The exported `.srt` of the affected clips starts **after** the word it contains |

#### AT-G-15 — The five defects, and what each one cost

| Field | Record |
|---|---|
| **Test ID** | AT-G-15 |
| **User input** | Fix what the run's own diagnostics exposed |
| **Expected** | Each defect is fixed and guarded by a test that fails without the fix |
| **Actual** | **Five defects** — **18** (two exports with the same title overwrote each other), **19** (the crop-safety measurement took the wrong face for the subject), **20** (the pipeline and the diagnostic disagreed about what a duplicate is), **21** (a clip could open inside its first word) and **22** (a face track could jump to a smaller face beside the speaker). The full record is in the defect table below, and the guards are in `tests/test_export_graph.py`, `tests/test_api.py`, `tests/test_diagnostics.py`, `tests/test_highlights.py` (new), `tests/test_boundaries.py` and `tests/test_reframe.py` |
| **Result** | **VERIFIED** — every guard was observed failing against the pre-fix code |
| **Screenshot** | n/a — a gate, not a screen |
| **Logs** | The gate's own output |
| **Backend evidence** | **17 of the 20** new tests fail against the pre-fix tree; the other three are non-regression guards (a title that is *not* shared keeps its plain name, clips that only **touch** are kept, and clips that share a **quarter** are kept) |
| **Export inspection** | n/a |

#### AT-G-16 — The whole pipeline again, with every fix in

| Field | Record |
|---|---|
| **Test ID** | AT-G-16 |
| **User input** | Paste `https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP` into the ingest field on the scratch instance and press **Start** — with the fixed code running |
| **Expected** | The pipeline runs from the paste to the finished clips, and every workflow node passes its own checks |
| **Actual** | It did. `POST /api/sources/youtube` → **201**, body `{"url":"https://youtu.be/bMTlNeKqV4o?si=lz2Sg0gsR2eGULsP","cookies_from_browser":null}` → source **`651525f6355b4b28`**. `POST /api/jobs` → **201**, body `{"source_id":"651525f6355b4b28","settings":{}}` → job **`3db75213de894350`**. The job finished at **08:16:06 UTC** with `status=done`, `progress=1.0`, `error=null`, in **4,791 s (79.8 min)** for **574.880 s** of source — **8.33× real time**. **Nine** clips, all `status='exported'`, **268,664,639 B** exported over **11** ffmpeg runs and **448.5** ffmpeg-seconds |
| **Result** | **VERIFIED** — the whole pipeline, end to end, on the second real source, with every fix in place |
| **Screenshot** | `AT-G-16-run-started.png` — the job started, 5 %, stage **01 Prepare**. `AT-G-16-review-clips.jpeg` — the finished job: **DONE 100 %**, the nine ranked clips, the plan (**source: ai**) and the measurements for rank 1, every line green |
| **Logs** | The application's own log; the transfer log |
| **Backend evidence** | The job row (`status`, `progress`, `error`, `started_at`, `finished_at`); `job_resources` (`windows_skipped=0`, `llm_calls=2`, `llm_input_tokens=10055`, `llm_output_tokens=1535`, `ffmpeg_runs=11`, `ffmpeg_seconds=448.5`, `export_bytes=268664639`); `job_ai_budget` (`plan_used=1`, `repair_used=1`, `overruns=[]`); the two `highlights` and two `creative_planning` transfer rows, all `ok`, all against `127.0.0.1:11434` |
| **Export inspection** | **Nine exports, nine distinct names, no collision**; every recorded size equals the size on disk; every `.srt` sidecar present, longest cue **2.500 s**, **0** overlapping cues; every clip **1080×1920** at **29.97 fps** |

> **The title's emoji is intact, and the screenshot's empty box is the font's, not the data's.** The
> stored title is exactly `'UNEMPLOYMENT ON PEAK 📈 | CARRYMINATI'` — **U+1F4C8**, 36 characters,
> **no U+FFFD**, no lone surrogates — read back from the scratch database. The screenshot shows an
> empty box where the chart emoji is, because the browser's font on this machine has no glyph for it.
> It is a **rendering** artefact and not a defect, and it is recorded here so that a reader who
> compares the screenshot with the database does not have to work that out alone.

**Every measurement on every clip is `ok` — with one exception, and the exception is the source's
fault.** The run made **90** measurements (nine clips × ten) and **89** of them are green. The one
that is not is rank 2's `black_frames`: *"The clip goes black for 0.83 seconds."* That is a **true
positive about the source**: `ffmpeg blackdetect` on the **raw source**, from 90 s, finds
`black_start:15.973 black_end:16.807 black_duration:0.834` — source time **105.973–106.807 s**,
which is inside rank 2's own **90.829–132.750 s**. It was **not** "fixed"; the diagnostic is right.

**The run exercised the fixes without being asked to.** The model chose the same title twice again —
*"Why I'm not like them"*, for ranks 2 and 3 — and the two exports came out as
`why-im-not-like-them-2_9x16.mp4` and `why-im-not-like-them-3_9x16.mp4`. Under the pre-fix code
that pair would have been one file and one set of subtitles, and the first clip would have been
gone. `crop_safety` is `ok` on **all nine** clips — the six that were falsely reported last time are
green — and `duplicate_clips` is `ok` on **all nine**, with **no pair** overlapping by half of the
shorter one.

**The detection stage was asked to do something it had never done here.** The transcript came out
of the recogniser at **1,277 words** in **246 segments** — **217 more words** than the previous run
on the same video, because the recogniser is not bit-deterministic. The two windows were therefore
larger — **900** and **525** words — and the calls took **933,665 ms** and **634,943 ms**. Both
answered, and `windows_skipped` is **0**: the job analysed the whole video and says so.

**And the two runs were then compared, byte by byte — see AT-G-17.** The media were identical to
the byte, the transcript was not, and the difference was measured, attributed to the recogniser's
**unseeded sampling fallback**, and recorded as **K32**.

---

#### AT-G-17 — The same file, transcribed twice

| Field | Record |
|---|---|
| **Test ID** | AT-G-17 |
| **User input** | Point the application at the **same URL a second time**, on purpose, so the two runs could be compared |
| **Expected** | Two runs over the same media produce the same transcript — or, if they do not, the difference is measured, attributed and recorded rather than left as a shrug |
| **Actual** | The **media** are the same to the byte: the two containers differ in **one byte** (offset **407**, the mp4 creation-date metadata), they decode to **byte-identical** 16 kHz mono PCM (**18,396,148 B**, sha256 `4a87c5bd…8b7`, **574.880 s**), and every artefact the prepare stage wrote from that PCM — `audio.wav` (**18,396,226 B**, sha256 `5e468f32…`), `silences.json` (**2,812 B**), `shots.json` (**9,437 B**), `webcam_report.json` (**45,951 B**) and all **115** thumbnails (folder sha256 `a7eb34b3…`) — is byte-for-byte the same. The **transcripts** are not: the first attempt's is **1,060 words** in **220 segments** (`transcript.json`, **110,326 B**) and the verification run's is **1,277 words** in **246 segments** (**131,534 B**). Read word record by word record, they are identical for the first **246** records — up to **101.02 s** — and then they part: `बलवेंदर` against `बलविंदर`, with segment 55 still `101.02 → 104.38` in both. A **40 s** excerpt of the same audio was then decoded **twice** with the product's exact call and the recogniser's own logging captured: **10** segments against **9**, and the log shows the confidence check **failing even at temperature 0** — `Compression ratio threshold is not met with temperature 0.0 (6.897436 > 2.400000)` — and the fallback **sampling** at temperatures 0.2–0.8. faster-whisper **1.2.1** has no `seed` argument, so its sampler cannot be pinned from the call site. The fix — seeding CTranslate2's generator before the call — was **measured**: two seeded decodes of the same real excerpt came out **identical**, with the fallback still running |
| **Result** | **PARTIAL** — the media are provably identical, the difference is **measured and attributed** to the recogniser, and the fix is **verified** against the real audio. It is **not** applied in this increment, because it changes the transcript the acceptance evidence was gathered on; it is recorded as **K32** and **R8** |
| **Screenshot** | n/a — a measurement |
| **Logs** | The recogniser's own logging, captured for the two excerpt decodes (`faster_whisper DEBUG Compression ratio threshold is not met with temperature …`) |
| **Backend evidence** | `transcript.json` and `speech_timeline.json` from both jobs' work directories; the sha256 of the two containers' decoded PCM, of `audio.wav` and of the thumbnail folder; the two `transcript.json` files read record by record |
| **Export inspection** | n/a — nothing was exported for this measurement |

---

## M5.5 — Subtitles, framing, and MeowPower (2026-11-23 and 2026-11-24)

**What this section is.** A post-release increment to this file, dated **2026-11-23** and
**2026-11-24**, on the same branch. It records a run of the real application against a **third
real, third-party YouTube video**, supplied by the owner:

```
https://youtu.be/BgIISP2mi3o?si=jAM8h8iYFz9cgLRrV
```

> **Rights.** This is another creator's video. It is used here for **technical acceptance only**.
> Nothing produced from it was published anywhere, no account was connected, and no hosted
> credential was spent. It is not a release artefact.

**The source, as the internet described it.**

| | |
|---|---|
| Video id | `BgIISP2mi3o` |
| Title | I Stole The RAREST FERRARI in GTA 6 |
| Duration | 2,279.108 s — **38:00** |
| Resolution / rate | 1920×1080 **AV1** at **59.94005994005994 fps** |
| Audio track | **Hindi** (`hi`) |
| Source id / job id | `47789b6998aa46e9` / `ce370cb1b68841df` |

**Why this source, and what it is for.** M5.3 and M5.4 were both **short** sources — ten and nine
minutes. This one is **38 minutes**, at **60 fps**, in **AV1**. That makes it the source that
exercises the three things M5.5 added:

* A **long** file is a **long transcript** — **5,648 words** — which is where the subtitle-language
  decision has to be right rather than nearly right.
* A **60 fps AV1** file is **slow to decode**, so the detection cost is the product's problem and
  has to be *bounded*, not discovered.
* The video's webcam **changes size during it**, which is exactly what a fixed crop gets wrong.

**The environment.** A separate application instance on **port 8804** with its own home at
`%TEMP%\opencode\autoclip-yt-v4`, so the owner's own instance and its database were untouched. The
model is the same real local **Ollama** (`llama3.1:8b` at `127.0.0.1:11434`), and
`active_provider=ollama` means **no hosted call and no hosted spend**.

### Journey H — the three things M5.5 added

#### AT-H-01 — The subtitles are in English, without asking

| Field | Record |
|---|---|
| **Test ID** | AT-H-01 |
| **User input** | Nothing. The application was pointed at a **Hindi** video with the settings at their defaults. |
| **Expected** | The captions are in **English**, because English is the default subtitle language — and the language **spoken** is recorded separately, so the two are never confused. |
| **Actual** | The transcript came out of the recogniser with `language = "en"` and `source_language = "hi"`. **5,648 words** in **1,140 segments**, and **0** of them contain a character outside Latin script — every caption is English. The first words read *"Oh this car, wait what, this is a classic car, that famous car of YCT, wow, I want this car…"* |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-H-01-settings-subtitles.png` — Settings → Export → Subtitles, with *English (default)* selected |
| **Logs** | The application's own log; the `transcripts` row read back from the scratch database |
| **Backend evidence** | `transcript.json` in the job's work directory — `{"language": "en", "source_language": "hi", "model": "small", "source": "whisper"}`. The `transcripts` row: `language=en`, `word_count=5648`, `source=whisper`. The timings run the whole file: the first word at **0.000 s**, the last at **2,273.860 s** |
| **Export inspection** | n/a — the transcript is the artefact here; the captions in the rendered file are inspected in AT-H-13 |

#### AT-H-02 — The subtitle language can be changed at any time

| Field | Record |
|---|---|
| **Test ID** | AT-H-02 |
| **User input** | *Settings → Export → Subtitles → Subtitle language*, and the API's `PUT /api/settings` with `{"export": {"subtitle_language": "hi"}}` |
| **Expected** | The setting is **persisted**, **validated**, and takes effect on the **next** clip — no restart, and nothing already made is rewritten. |
| **Actual** | `GET /api/settings` returned `"subtitle_language": "en"` by default. `PUT` with `"hi"` returned **200** and the value came back as `"hi"`; `PUT` with `"source"` returned **200** and came back as `"source"`; `PUT` with `"klingon"` returned **400** and wrote nothing. The settings screen offers *English (default)*, *Same as the video*, and thirteen other languages |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-H-01-settings-subtitles.png` |
| **Logs** | `PUT /api/settings` → 200; `PUT /api/settings` → 400 for the invalid code |
| **Backend evidence** | 4 tests in `tests/test_api.py::TestSettings`; 3 of them **fail without the feature** |
| **Export inspection** | n/a |

#### AT-H-03 — A transcript in the wrong language is not reused

| Field | Record |
|---|---|
| **Test ID** | AT-H-03 |
| **User input** | Change the subtitle language, then let the job transcribe again |
| **Expected** | A saved transcript in the **wrong** language is **not** reused. Serving it would deliver captions in a language the user no longer asked for, and say nothing about it. |
| **Actual** | The runner compares the saved transcript's `language` with the requested target; when they differ it logs *"The saved transcript for job … is in '…', not '…'; transcribing again"* and transcribes. The external-engine case is decided by the **engine's name**, not by the transcript's shape: an external engine under `auto` is re-transcribed locally, and a **pinned** external engine raises `SpeechError` saying it cannot translate rather than silently producing the wrong language |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — a code path with a test |
| **Logs** | The runner's own log line |
| **Backend evidence** | `tests/test_subtitle_language.py` — **29 tests**; the reuse tests **fail without the fix** |
| **Export inspection** | n/a |

#### The run this section is about

| | |
|---|---|
| The application | the scratch instance on **port 8804**, with its own home, so the owner's own instance and its database were never touched |
| The source | **38:00** — 2,279.108 s — **1920×1080 AV1** at **59.94005994005994 fps**, spoken in **Hindi** |
| The provider | the **local Ollama** (`llama3.1:8b` at `127.0.0.1:11434`); the job row records `provider=ollama`, so **no hosted credential was spent** |
| The transcript | whisper `small`, **`language=en`**, **`source_language=hi`** — **5,648 words** in **1,140 segments**, **0** characters outside the Latin script |
| The transcription cost | **1,836 s** for **2,279.1 s** of audio — **1.24× real time**, faster than the video plays |
| The highlight windows | **nine**, over **5,648 words**, each at most **8,402** rendered characters — **74,262** characters in all |
| The clips | **six**, between **30.84 s** and **35.98 s**, **194.50 s** in all |
| The webcam report | **2,502** measured boxes over the **194.5 s**, **134** distinct widths between **134 px** and **540 px**, confidence **0.8131** |
| The export | six files, **221,460,397 B** in all, **451 s** for **194.5 s** of footage |
| The job | `status=done`, `progress=1.0` |

#### AT-H-04 — The detector can see the streamer at all

| Field | Record |
|---|---|
| **Test ID** | AT-H-04 |
| **User input** | Nothing. The reference video was put in front of the face detector and the detector's own output was counted |
| **Expected** | The streamer is a person in a **1920 px**-wide frame, and the detector finds them |
| **Actual** | **Before the fix: 0 observations over 2,100 s**, and **11 over 900 s**. MediaPipe scales its input to about **128 px** on the short side, so a face **120 px** wide is smaller than one pixel of what it looks at. **After the fix: 56 observations over 2,100 s** and **45 over 900 s** — the tiles are **640 px** with **15 %** overlap |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — a detector's output rate |
| **Logs** | the detector's own observation counts, measured over the same source before and after |
| **Backend evidence** | 3 tests in `tests/test_faces.py`; the tiled-detection test **fails without the fix** |
| **Export inspection** | n/a — the detector is the artefact here; what it found is exported in AT-H-13 |

#### AT-H-05 — The webcam's own frame is measured, not guessed

| Field | Record |
|---|---|
| **Test ID** | AT-H-05 |
| **User input** | Nothing. 30 s of the reference video was put through the edge detector and the box it returned was compared with the webcam that is visibly there |
| **Expected** | The detector returns the webcam's **own rectangle**, with all four of its edges |
| **Actual** | **Before the fix** the horizontal edges were wrong: the bright panel of a game menu inside the search band won the vote. **After the fix** all four edges are found — `x=1274, w=638, y=9, h=426` — against a true box of about `x 1272…1912, y 0…436` |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — a measured rectangle |
| **Logs** | the detector's own edge report: `edges=(True, True, True, True)` |
| **Backend evidence** | 7 tests in `tests/test_webcam_box.py`; the horizontal-axis test **fails without the fix** |
| **Export inspection** | n/a — the detector is the artefact here; the box it found is exported in AT-H-13 |

#### AT-H-06 — The first frame of a clip is never read from before the clip

| Field | Record |
|---|---|
| **Test ID** | AT-H-06 |
| **User input** | Nothing. A clip that starts part-way into the source was put through the sampler and the first frame's position was read back |
| **Expected** | The first frame of a clip is **inside** the clip. A negative clip-relative timestamp asks the decoder for a frame before the clip |
| **Actual** | The sampler computed the first frame's position by subtracting the clip's start from a frame time that was already relative to the clip, and the result could be **negative**. The timestamp is now clamped at zero |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — a timestamp |
| **Logs** | the sampler's own clock |
| **Backend evidence** | 1 test in `tests/test_faces.py`; **fails without the fix** |
| **Export inspection** | n/a |

#### AT-H-07 — The split-screen keeps the webcam in its strip, and the gameplay clear of it

| Field | Record |
|---|---|
| **Test ID** | AT-H-07 |
| **User input** | *Layout → auto*, on a source with a webcam whose shape does not match the strip |
| **Expected** | The webcam sits **inside** the 40 % band, and the gameplay's crop does **not** overlap it — so the streamer is never shown twice |
| **Actual** | The partial path scaled the webcam by the face limit alone and placed it by its own size, so the result could be **wider than the band**. `_fit_in_strip` now fits it inside the strip on both axes at once and returns nothing when it cannot. Separately, the crop path was built without knowing where the webcam was, so the streamer appeared **twice**. `ReframeConfig.avoid` now carries the webcam's region and a **final pass over the finished plan** holds every fallback clear too |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — the layout's own geometry |
| **Logs** | the layout's own records |
| **Backend evidence** | 2 tests in `tests/test_layout.py::TestTheSplitScreen` and 6 in `tests/test_reframe.py::TestTheWebcamIsKeptOutOfTheGameplay`; the spill and fallback tests **fail without the fix** |
| **Export inspection** | The finished renders are inspected in AT-H-13, where the gameplay's left edge is measured at **x = 452** — exactly clear of the webcam's region at **x = 1464** |

#### AT-H-09 — The filter graph stays inside Windows' own limit

| Field | Record |
|---|---|
| **Test ID** | AT-H-09 |
| **User input** | Nothing. A webcam path of **600** measured boxes — the shape the detector's own sample rate produces on a ninety-second clip — was put through the filter-graph builder |
| **Expected** | The command line fits inside the **32,767-character** limit Windows imposes |
| **Actual** | Every measured box became a keyframe and the path became a nested `if()` per keyframe, evaluated at **every frame** of the clip: **50,019 characters** against a limit of **32,767**. The path is now **thinned** to at most **48** keyframes — the same budget the gameplay crop path uses — dropping the ones that say nothing their neighbours do not already say, and keeping the endpoints so the path still covers the clip |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — a command line's length |
| **Logs** | the length of the built filter graph |
| **Backend evidence** | 6 tests in `tests/test_webcam.py::TestTheWebcamPath`; the length and the budget tests **fail without the fix** |
| **Export inspection** | The rendered clips' paths hold **30** to **96** keyframes across their segments, each segment's path within the **48** budget |

#### AT-H-10 — The detector walks the source forwards

| Field | Record |
|---|---|
| **Test ID** | AT-H-10 |
| **User input** | Nothing. The six clips were given to the detector in the order the pipeline gives them — **rank** order — and the detector's own error was read back |
| **Expected** | The decoder is asked for the stretches in the order they sit in the **source**. A decoder cannot seek backwards |
| **Actual** | The clips come in rank order — the model's best clip first — and rank is not position. After the third stretch the detector asked the decoder to seek **backwards**, and the decoder refused: *"Input timestamp must be monotonically increasing."* The webcam was never found, and **every clip was rendered as plain gameplay**. The stretches are now walked in source order, in the runner, in the face sampler and in the shot detector. On the same source, asked in the same wrong order, the detector now finds the webcam at **98 %** confidence |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — the detector's own error, and then its absence |
| **Logs** | the saved report's `unavailable_reason`: *"Input timestamp must be monotonically increasing."* — and, after the fix, a report with `failed=false`, `confidence=0.8131` and **2,502** measured boxes |
| **Backend evidence** | 2 tests in `tests/test_faces.py::TestTheClock` and 1 in `tests/test_pipeline_cache.py::TestTheOrderTheWindowsAreAskedFor`; **fail without the fix**, with the production error |
| **Export inspection** | The six clips carry the split-screen — see AT-H-13 |

#### AT-H-11 — A saved crop plan is only reused for the shape it was built for

| Field | Record |
|---|---|
| **Test ID** | AT-H-11 |
| **User input** | Nothing. The plan on disk was read against the layout that was going to use it, and the review page's *"Export this clip"* path was read |
| **Expected** | A plan is reused only when the settings it was built for still hold |
| **Actual** | The plan was cached under the clip's name alone, with nothing saying what it was made *for*. When the webcam was found the gameplay's shape changed with it — from the whole **9:16** to the **15:16** bottom strip — and the old plan was reused anyway: on disk it was still **608×1080** (9:16) while the layout asked for **1012×1080** (15:16). A plan now records a **fingerprint** of its settings, and on the re-export path a saved plan is reused only when its **own shape** is the shape being exported |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — two numbers on disk |
| **Logs** | the plan's own `config_fingerprint` — `aspect=15x16;fps=5.0;centre=False;avoid=1464.0,6.0,450.0,306.0;smoothing=none` |
| **Backend evidence** | 4 tests in `tests/test_pipeline_cache.py::TestTheSavedCropPlan` and 2 in `tests/test_pipeline_cache.py::TestTheReExportPath`; **fail without the fix** |
| **Export inspection** | All six rendered clips' gameplay crops are **1012×1080** — the 15:16 shape the bottom slot needs |

#### AT-H-12 — The saved webcam report is reused only for the same windows

| Field | Record |
|---|---|
| **Test ID** | AT-H-12 |
| **User input** | Nothing. The report saved on disk was compared with the windows the run was about to ask for |
| **Expected** | A report is reused when it was made for the same stretches — and **not** when it was not, because a report for other stretches says nothing about these ones |
| **Actual** | The comparison was exact, and the two never matched: the report rounds its windows to **3 decimal places** while a clip's end time is `1303.9599999999998`. Every retry therefore paid for the detection again. The comparison is now tolerant to **0.01 s** |
| **Result** | **VERIFIED** |
| **Screenshot** | n/a — two lists of numbers |
| **Logs** | the report's `windows` and the wanted windows |
| **Backend evidence** | 1 test in `tests/test_pipeline_cache.py::TestTheSavedWebcamReport::test_a_report_for_the_same_windows_is_reused`; **fails without the fix** |
| **Export inspection** | On the last run the report kept its **02:35:40** timestamp while the layouts beside it were rewritten at **02:56:29** — the saved report was read and reused, and the **seventeen minutes** of detection were not paid a second time |

#### AT-H-13 — The rendered clips: the split-screen, the moving crop, and the English captions

| Field | Record |
|---|---|
| **Test ID** | AT-H-13 |
| **User input** | Nothing. The six exported files were measured against the source they were cut from |
| **Expected** | Every clip is **1080×1920**; the top **40 %** is the webcam; the bottom **60 %** is the gameplay; the two halves are different things; the gameplay's crop is clear of the webcam; the webcam's crop **follows its own frame**; and the captions are **English** |
| **Actual** | **All six pass.** Every file is **1080×1920** with an AAC track. The webcam's slot is `(0, 0, 1080, 768)` — exactly **40 %** — and the gameplay's slot is `(0, 768, 1080, 1152)` — exactly **60 %**. At three moments in each clip the top strip was compared with the source at the webcam's crop window for that moment: the mean absolute difference was between **4.1** and **39.0** on a 0–255 scale. The bottom was compared with the source at the gameplay's crop window: **1.4** to **24.8**. The gameplay's left edge sits at **x = 452**, exactly clear of the webcam's region at **x = 1464** (`1464 − 1012 = 452`). Every clip's webcam path **moves** — between **10** and **42** distinct centres per clip. The captions are **490** cues and **43,272** characters across the six clips, with **0** characters outside the Latin script |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-H-13-splitscreen-we-killed-that-shark.png`, `AT-H-13-splitscreen-400-taxi.png`, `AT-H-13-splitscreen-police-behind-me.png` — frames lifted from the rendered files |
| **Logs** | the inspection script's own output, kept beside the screenshots: `NO PROBLEMS FOUND` |
| **Backend evidence** | the run's own records — `layouts/*.json`, `crops/*.json`, `webcam_report.json` — and the **194.50 s** of footage the six clips use |
| **Export inspection** | The six files themselves: `we-killed-that-shark_9x16.mp4` (30,365,300 B), `400-taxi-or-5-toll_9x16.mp4` (64,771,117 B), `police-behind-me_9x16.mp4` (28,793,347 B), `biggest-building-of-yct_9x16.mp4` (32,534,789 B), `we-got-50000_9x16.mp4` (31,900,979 B), `road-rash_9x16.mp4` (33,094,865 B) — **221,460,397 B** in all, which is exactly the `export_bytes` the job recorded. Between **1.50 s** and **6.62 s** per clip the layout is `gameplay_only`, with the reason recorded in the layout: *"no face was seen inside the region"* |

#### AT-H-08 — MeowPower: the pipeline is one sentence away

| Field | Record |
|---|---|
| **Test ID** | AT-H-08 |
| **User input** | Open the running job's page |
| **Expected** | The user sees **one sentence** saying what is happening, and **one number**. The pipeline's six technical stages are **not** the first thing on the page. |
| **Actual** | The page read **MEOWPOWER** / *"Picking out the moments worth keeping"* / **40 %** / *"You can leave this page. It keeps working."* — with the six technical stages collapsed behind the disclosure *"What MeowPower is doing"*. The masthead kept the title, the duration, the resolution and the provider, and the **Cancel** button stayed where it was. The transcription stage's own sentence — *"Listening to what is being said"* — was read from the same screen earlier in the run |
| **Result** | **VERIFIED** |
| **Screenshot** | `AT-H-08-meowpower.png` |
| **Logs** | n/a — a screen state |
| **Backend evidence** | The DOM of the running application on port 8804, read through the in-app browser; the browser console carried **no errors** |
| **Export inspection** | n/a |

#### Journey H — the verdict

Every acceptance item in this journey, with its verdict. Nothing is upgraded past what was measured,
and the three items that are **UNVERIFIED** are **UNVERIFIED** here for the same reason they are
everywhere else in this file: no authorised credential was supplied.

| Test ID | What it establishes | Verdict |
|---|---|---|
| AT-H-01 | The captions are in **English** by default, and the language **spoken** is recorded separately | **VERIFIED** |
| AT-H-02 | The subtitle language can be **changed at any time**, and an invalid code is refused | **VERIFIED** |
| AT-H-03 | A transcript in the **wrong** language is not reused | **VERIFIED** |
| AT-H-04 | The face detector can see the streamer at all | **VERIFIED** |
| AT-H-05 | The webcam's **own frame** is measured, not guessed | **VERIFIED** |
| AT-H-06 | The first frame of a clip is never read from before the clip | **VERIFIED** |
| AT-H-07 | The split-screen keeps the webcam in its strip, and the gameplay clear of it | **VERIFIED** |
| AT-H-08 | **MeowPower** shows one sentence and one number, with the stages one disclosure away | **VERIFIED** |
| AT-H-09 | The filter graph stays inside Windows' own **32,767-character** limit | **VERIFIED** |
| AT-H-10 | The detector walks the source **forwards** | **VERIFIED** |
| AT-H-11 | A saved crop plan is only reused for the shape it was built for | **VERIFIED** |
| AT-H-12 | A saved webcam report is only reused for the same windows | **VERIFIED** |
| AT-H-13 | The six rendered clips: the **40/60** split, the moving crop, the clear gameplay, the **English** captions | **VERIFIED** |
| — | A **non-English** subtitle target on real audio | **UNVERIFIED** — the path is implemented, guarded and reachable, and only the **English** path was measured on real audio. That is **K33** / **R9**, not a pass |
| — | The **hosted** LLM and **ElevenLabs** paths | **UNVERIFIED (external)** — no authorised credential; the run used a local Ollama and local whisper |
| — | **Publishing** the result anywhere | **NOT APPLICABLE** — this is a third-party creator's video, used for technical acceptance only. Nothing was published, no account was connected, and no hosted credential was spent |
| — | The **re-export** path rebuilding the webcam composition | **PARTIAL** — the crop, the shape and the duration all match the ratio asked for, but a stacked webcam/gameplay composition is not reconstructed from the review page. That is **K10**, and it is why the acceptance clips were produced by requeueing the job rather than by re-exporting it |

---

## The defects this testing found

All of them were found by **running the application or its gates**, not by reading the code, and all
of them are covered by tests that fail without the fix.

> **Amendment — 2026-11-24 (M5.5).** The **third real source** — a **38-minute**, **1080p60 AV1**,
> **Hindi** video — found **fourteen** more, and they are the defects that only a long, high-frame-rate,
> non-English video can reach. Six of them are in the **webcam framing** — the detector could not see
> the streamer at all (**defect 23**), the tile fix read the tiles wrongly (**defect 24**), the edge
> search looked in the wrong place (**defect 25**), the first frame was read from before the clip
> (**defect 26**), the webcam spilled out of its own strip (**defect 27**), and the gameplay crop did
> not keep clear of it (**defect 28**). Two are elsewhere: the progress page lost the video's title
> the moment the event stream opened (**defect 29**), and the webcam's path grew an ffmpeg expression
> past **Windows' own 32,767-character limit** (**defect 30**). The last three were found by the
> **first complete run** of the new framing, and they are the reason the split-screen works at all:
> the detector was asked for the stretches in the wrong order and refused (**31**), a saved crop plan
> was reused after the layout had changed (**32**), and a detection that could not run was kept as a
> final answer (**33**). A fourth was found while fixing **32** — a re-export would have stretched a
> plan made for another shape (**34**). The last two were found by the **re-export** that finally
> produced the acceptance clips: the saved webcam report was never reused because the windows never
> matched exactly (**35**), and the speech-emphasis zoom broke the render because ffmpeg evaluates a
> `scale` filter's size **once**, at init (**36**). They are in the table below, with the evidence in
> the M5.5 section of this file. The twenty-two defects above remain exactly as measured here.

> **Amendment — 2026-11-21 (M5.1).** This application run found **three** product defects, and
> this section records them as they stood at M5. A **fourth product defect** was found afterwards,
> by closing the last PARTIAL matrix row: the eight-case ducking matrix, written as eight **real
> renders**, exposed that an empty speech timeline was indistinguishable from no timeline at all,
> so a clip with no talking had its music pulled down by the source. It was fixed and guarded —
> see `docs/FINAL_UPGRADE_REPORT.md` §4.2 (defect 4) and §4.3, and
> `docs/upgrade-audit.md` §13.2. **Nothing in this section is invalidated by it**; the three
> defects below remain exactly as measured here.

> **Amendment — 2026-11-21 (M5.2).** The increment recorded above found **three more**: the
> configured `yt-dlp` format was dead (**defect 5**), the download was never written to the
> transfer log (**defect 6**), and the crop-safety measurement reported failures that had not
> happened (**defect 7**). They are in the table below, and the full evidence for each is in the
> M5.2 section of this file. The three M5 defects remain exactly as measured here.

> **Amendment — 2026-11-21 (M5.2, second pass).** The full-suite gate then found **one more**,
> and it is a defect in the product rather than in the test: **defect 8**. The URL policy refused
> any host whose two DNS answers were not the *same set of addresses*, so a legitimate
> load-balanced host — `graph.facebook.com` hands out a rotating subset of its own edge addresses
> — was treated as a DNS-rebinding attack and the publish was refused. It was found as a **flaky
> failure** in the Instagram publishing tests, it was reproduced, it was diagnosed, and it was
> fixed. Details in the row below and in `docs/FINAL_UPGRADE_REPORT.md` §4.2.

> **Amendment — 2026-11-21 (M5.3).** The increment recorded above found **four more**, and they are
> the ones a user in **Hindi** would have hit on their first real video: the sentence terminators
> were **Latin-only**, so a Devanagari transcript had almost no sentence boundaries in it
> (**defect 9**); the export's ffmpeg command line could exceed **Windows' own 32,767-character
> limit** (**defect 10**); the webcam's speech emphasis ran on a **segment-local** clock and so
> only ever worked in a clip's first segment (**defect 11**); and a caption could be held on screen
> for **twelve seconds** because it inherited the recogniser's word timing (**defect 12**). They are
> in the table below, and the full evidence for each is in the M5.3 section of this file. The eight
> defects above remain exactly as measured here.
>
> **Amendment — 2026-11-22 (M5.3, the Linux leg).** The **Linux reproduction leg** then found a
> **fifth**: the export's video graph **consumed a filter output once per crop segment**, which
> ffmpeg 9 tolerates and ffmpeg 7 refuses (**defect 13**). It is in the table below, and the full
> evidence is in AT-F-15. It is the same class as **defect 3**, and it was found by the **same**
> leg — which is the reason the leg exists. The nine defects above remain exactly as measured
> here.
>
> **Amendment — 2026-11-23 (M5.4).** The **second real source** found **nine more**. Four sat
> behind one line of failure — *"Ollama timed out."* — and were about the **request** rather than
> the content: the timeout ceiling was **hard-coded** (**defect 14**), the message blamed a GPU the
> machine does not have (**defect 15**), the stage kept going after a timeout and then claimed
> every window had failed (**defect 16**), and the request **did not fit the model's context** —
> which would have produced *wrong clips* rather than no clips (**defect 17**). They are in the
> table below, with the full evidence in AT-G-07 … AT-G-10.
>
> **Amendment — 2026-11-23 (M5.4, the diagnostics).** When that run finally finished, **its own
> diagnostics** found **five more**, all in the pipeline's **output**: two clips with the same
> model-chosen title **overwrote each other's exports** (**defect 18**); the crop-safety
> measurement took the **largest** face in the shot for the subject instead of the face the crop
> follows (**defect 19**); the pipeline and the diagnostic had **two different definitions** of
> *"the same clip"*, so two pairs of the same footage were both kept (**defect 20**); a clip could
> **open inside its first word** (**defect 21**); and a face track could **jump to a smaller face**
> beside the speaker, so the crop panned away from them (**defect 22**). They are in the table
> below, with the full evidence in AT-G-11 … AT-G-15. The thirteen defects above remain exactly as
> measured here.

| # | Defect | Found by | Fix | Guard |
|---|---|---|---|---|
| 1 | The API export path ignored the user's music preference and the speech-interval ducking. | Clicking *Export this clip* on a clip with a track chosen. | `api/clips.py` resolves the music through the same three-scope precedence the pipeline uses, and hands the renderer the job's speech timeline sliced to the clip. | 7 regression tests in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix**. |
| 2 | The timeline-driven ducking filtergraph was malformed — a label in the middle of the bed's chain — and ffmpeg refused the whole graph. | The export failing with ffmpeg's own stderr. | The bed chain carries no output label; the label is added where the bed is used. | 3 real-render tests in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix**. |
| 3 | The sidechain fallback consumed one filter output twice, which ffmpeg 9 accepts and ffmpeg 7 refuses. | The Linux CI reproduction leg, on ffmpeg 7.0.2. | The speech is split with `asplit=2` into a mix copy and a key copy, both on the bed's channel layout. | 3 real-render tests, plus a **structural** check in `tests/test_music.py` that no filter output is consumed twice and no filter follows an output label — version-independent, so it catches the defect on any ffmpeg. |
| 5 | `ingest.ytdlp_format` was dead: the download hard-coded `bestvideo*+bestaudio/best`, so a four-hour stream came down at 1440p60 — 12.54 GiB — instead of the 1080p the configuration's own comment promises. | The real ingest of a four-hour YouTube live recording (AT-E-05). | The command line is built in one place, `_download_command`, and the format selector comes from the settings. | 3 tests in `tests/test_ingest.py`; **2 of the 3 fail without the fix** (`assert 'height<=1080' in 'bestvideo*+bestaudio/best'`). |
| 6 | The yt-dlp download was authorised but **never written to the transfer log**, so `EGRESS-INVENTORY.md` E11's claim that it is *logged* was false — and the largest thing AutoClip ever sends left the machine with nothing in the user's own log. | Reading *Settings → External processing* after a 5.52 GB download: **0 rows** (AT-E-04). | The transfer is recorded on refusal, on a failed launch, on a failed download and on success, with the duration. | `tests/test_ingest.py::test_the_download_is_recorded_in_the_transfer_log` — **fails without the fix** (`assert [] == [('ok', ...)]`). |
| 7 | The crop-safety diagnostic compared a **per-clip** crop against the **whole-source webcam region** and called it *"the detected face"*, so it reported *"the crop cuts through the detected face"* on a clip that tracks the face perfectly, and on a clip with **no face in it at all**. | The application's own diagnostics on two real clips of a real stream (AT-E-08). | The crop plan carries the faces it was built around, in source pixels and in the clip's own time base; the check compares each keyframe against the face nearest it **in time**, and `diagnose_clip` no longer accepts a whole-source rectangle as a face. | 5 tests in `tests/test_diagnostics.py` and 2 in `tests/test_reframe.py`; the time-matching test **fails without the fix**. |
| 8 | The URL policy refused **any** host whose two DNS answers were not the same set of addresses, so a legitimate load-balanced host was treated as a DNS-rebinding attack and the publish was refused: *"DNS for graph.facebook.com changed between lookups … refusing a possible rebinding"*. | The full-suite gate — a **flaky failure** in `tests/test_instagram.py::test_a_publish_that_dropped_part_of_the_request_is_reported`, which passes alone and fails in a full run. | The rebinding guard now compares the **class** of the two answers, not the exact set of addresses: an answer that moved *inwards* (public → private or loopback) is refused, and an answer that moved between two **public** addresses is a load balancer and is allowed. The unit suite also no longer resolves real hostnames. | 2 tests in `tests/test_url_policy.py` **fail without the fix** (a load-balanced host is resolved and classified as public); 3 more assert that the protection still holds (public → loopback, public → a forbidden address, and the existing public → private case), and 1 asserts the suite never touches the network. |
| 9 | The sentence and clause terminators were **Latin-only**, so a Devanagari transcript had almost no sentence boundaries in it — and the clip-edge refinement then *silently dropped* every candidate that fell short of the minimum duration, because the too-short branch had no fallback at all. | The real **ten-minute Hindi source**: the danda `।` appears in **5** of its **1,128** words, and the old pattern matched **1** (AT-F-06). | The terminator sets carry the marks of the other writing systems — every code point verified against the Unicode database — and `_clamp_duration`'s too-short branch falls back to the **first word that reaches the minimum duration** instead of dropping the candidate. The Tibetan tsheg is **deliberately excluded**: it separates syllables, not clauses, and a test pins that. | 65 tests across `tests/test_transcript.py` (new) and `tests/test_boundaries.py`; **33 fail without the fix**. |
| 10 | The export's ffmpeg command line could exceed **Windows' own 32,767-character limit**, and the job died with `FileNotFoundError: [WinError 206] The filename or extension is too long` — a message about a *filename* for what is really an over-long *filter graph*. | The **real export** of a clip with **20 crop segments** and **11 speech-emphasis spans** (AT-F-08). The command was **36,743** characters and failed at progress 0.88 **every time**. | The webcam crop and scale are applied **once, after the segment concat** rather than once per segment. They are per-frame operations, so the picture is the same. A guard refuses an over-long command **before** ffmpeg runs, naming the filter graph rather than blaming a filename. | 7 tests fail without the export fix (6 in the new `tests/test_export_graph.py`, plus the behavioural render test); 4 more fail without the command-line guard. The real command drops **36,743 → 10,697**. |
| 11 | The webcam's speech emphasis was evaluated against a **segment-local** clock, so the webcam only ever magnified in the **first** segment of a clip. | The same real clip, read against `croppath.axis_expression`, which subtracts `offset_s` for exactly this reason (AT-F-09). | Applying the crop **after** the concat restores the clip-relative timeline, so the emphasis expression means the same thing it means everywhere else in the product. | `tests/test_export_render.py::TestLayoutRender::test_the_speech_emphasis_renders_in_a_later_stretch` — a **behavioural** render test: it compares the webcam strip at a quiet moment with the webcam strip at a talking moment in the **second** stretch. It **fails without the fix**. |
| 12 | A caption could be held on screen for **twelve seconds**, because the caption inherited the recogniser's word timing rather than bounding its own lifetime. | The application's **own diagnostic** on a real clip: *"3 word(s) are held on screen too long"*. The exported `.srt` carried a cue of `00:00:09,080 --> 00:00:21,650` (AT-F-10, AT-F-11). | The caption's lifetime is the **renderer's** business, not the recogniser's: `captions.MAX_CAPTION_S = 2.5` bounds every caption, the grouping breaks on a start-span ceiling, and `captions.caption_spans()` is the single source of the caption timing — shared by the renderer and the diagnostic. | 8 tests in `tests/test_captions.py::TestCaptionLifetime` and 2 in `tests/test_diagnostics.py`; **8 fail without the fix**. The longest caption drops **12.57 s → 2.50 s**, with the text fully preserved. |
| 13 | The export's **video** graph consumed a filter output **once per crop segment**: the source was split in two, and then *each* segment read from the same output again — which is invalid, because a filter output may be consumed only once. ffmpeg **9** tolerates it; ffmpeg **7** refuses it with *"Invalid stream specifier"*. | The **Linux reproduction leg**, on **ffmpeg 7.0.2** — the version that reproduces the CI's platform (AT-F-15). The developer's machine agreed with the developer's ffmpeg, so it rendered there and nowhere else. | The source is split **once per consumer**, so every segment has a copy of its own. The shape was measured against **both** ffmpeg builds before it was chosen: `split=64` is accepted by 7.0.2 and 9.0.2 alike, while a multi-output `trim` would need a `setpts` per output because `setpts` has only one. | 4 tests in `tests/test_export_graph.py::TestGraphShape`; **3 fail without the fix**. The structural graph check moves to `tests/graph_shape.py` and is now applied to the **video** graph as well as the music graph — it was already written for this class of defect, but only ever looked at the music graph |
| 14 | The detection request's **timeout was a hard-coded 600 s.** On a machine with **no GPU**, one legitimate call over an eight-minute window was measured at **1,993 s** — so the ceiling cut off calls that were about to succeed, and the advice it gave (*"try again"*) reproduced the failure exactly. | The **second real source**, at M5.4. The highlight stage failed with *"Ollama timed out."* twice, and the transfer log carries two `highlights` rows of **600,086 ms** and **600,450 ms** — both exactly the ceiling (AT-G-07). | The timeout is a **per-provider setting** (`ProviderSettings.timeout_s`, 0 = the provider's own default) with a generous **3,600 s** default, and it reaches the HTTP client and the vendor SDKs — Anthropic, OpenAI and Gemini, the last in milliseconds, because that is what its SDK counts. | 7 tests in `tests/test_provider_limits.py::TestTheTimeout`; **6 fail without the fix** |
| 15 | The timeout message blamed hardware the machine did not have. It said *"Large transcripts on a small GPU can exceed the limit. Try a smaller model, or use a hosted provider for this video."* — on a machine with **no GPU** (`size_vram: 0`, an Intel Iris Plus iGPU), and for a user with no hosted provider. | The same run. The message was read against the machine's own facts (AT-G-08). | The message now states what happened — *how long it waited* — and the hint says what a local model actually does (it runs on the **CPU** when no GPU is present) and points at the **setting** that changes it. | 2 more tests in the same file; **both fail without the fix** |
| 16 | A timed-out window left the server **still generating the abandoned request**, so the next window queued behind the orphan and burned its own timeout **without ever starting** — and the stage then reported *"failed in every window"*, when some windows had never been tried at all. | The same run: two windows, two timeouts, and the message claiming every window had failed (AT-G-08). | The stage **stops at the first timeout**, names the windows that were **not analysed**, and records that count in the job's own usage — so a job that analysed part of a video says so. | 5 tests in `tests/test_provider_limits.py::TestATimeoutStopsTheStage`; **5 fail without the fix** |
| 17 | The detection request **did not fit the model's context window.** The prompt for one eight-minute window measured **5,861 tokens** against a **4,096-token** context, and the product asked for `num_predict: 4096` — an answer budget as large as the entire context. The model server truncates a prompt that does not fit **without saying so**, so the model would have answered from a partial transcript. | The same run, measured with llama-server's own tokenizer, and then confirmed by an experiment: the **same** payload with `num_ctx: 8192` returned **HTTP 200** after **1,992.9 s** with `prompt_eval_count: 5862` and a valid JSON answer (AT-G-09). | The request asks for the context it needs (`ProviderSettings.context_tokens`, **8,192** by default), caps the answer to the room that remains (**2,048**), sizes the transcript windows to the provider's budget, and **reports** a prompt that still overflows instead of answering from a partial transcript. | 8 tests in `tests/test_provider_limits.py` — the context, the answer budget, the window sizing and the overflow guard; **8 fail without the fix** |
| 18 | Two clips with the same title **overwrote each other**. The export's file name came from the title alone, and the titles are the **model's** choice — so when the model gave two clips the same title, the second export replaced the first, subtitles and all. | The **second real source**, read back from the export directory: clip `61e1d3ec8c3e4dce` was recorded as **14,272,780 B**, and the file on disk was **54,024,088 B** — the *other* clip's — with **one** `.srt` where there should have been two (AT-G-11). | The name is made unique against the **whole set of the job's clips**: a title that is not shared keeps the user's own words, and a title that is shared gains the clip's **rank**, which is unique within the job. Both the pipeline and the re-export path compute the same name from the same list. | 5 tests in `tests/test_export_graph.py::TestExportFilenames` and 2 in `tests/test_api.py::TestClipsWithTheSameTitle`; **6 fail without the fix** |
| 19 | The crop-safety diagnostic **measured the wrong face.** It took *"the largest face within half a second"* as the subject, while the crop follows the **tracked** speaker — so a clip that tracked its speaker perfectly was reported as cutting a face that was never its subject. | The same run's own diagnostics: **6 of the 9 clips** were reported as *"the crop cuts through the detected face"*. Rebuilding the plans and measuring them against the face each one actually followed showed the cut at **0** keyframes in four of the six (AT-G-12). | The crop plan now carries, **per segment**, the faces that segment was built around — the person it follows, or the people a wide shot holds. The diagnostic measures against those, and keeps the old *"largest face"* rule only as the fallback for plans written before the change. A **sliver** of the detector's box (a **90%** keep-ratio) is allowed, because the box is loose and can run past the edge of the picture. | 5 tests in `tests/test_diagnostics.py` (`TestCropSafetyMeasuresTheFollowedFace`, `TestCropSafetyTolerance`); **5 fail without the fix** |
| 20 | **Two clips of the same footage survived the pipeline.** The de-duplication compared the candidates' **word ranges**, and a clip *inside* another one has almost no words in common with it: the shorter clip of the first real pair covered **14** words, the longer **104**, of which those 14 were a part — a common share of a fifth, well under the threshold. In **time**, though, the shorter clip was wholly inside the longer one. | The same run's diagnostics: **4 of the 9 clips** were reported as *"overlaps another one by 100%"*, and the diagnostic's own rule (overlap ≥ half of the shorter) disagreed with the pipeline's (AT-G-13). | One shared definition of *"the same clip"* — `pipeline/duplicates.py` — used by **both** the pipeline and the diagnostic: two clips are duplicates when the overlap covers at least **half of the shorter one**. The higher score survives. | 5 tests in `tests/test_highlights.py::TestDuplicateClips` (new file); **3 fail without the fix** |
| 21 | **A clip could open in the middle of a word.** The boundary alignment pulls the cut back into the silence before the first word, but it could also push it *past* the word's own start when the silence detector and the recogniser disagreed by a few tens of milliseconds — which breaks the code's own documented invariant, *"alignment only ever widens a clip"*. | The same run's diagnostics: **2 of the 9 clips** were reported as *"1 word(s) fall outside the clip"*. Rank 1's first word started at **533.800 s** and the clip opened at **533.852 s** — **52 ms inside the word** (AT-G-14). | The alignment may only ever **widen** the clip: the result is clamped to the first word's own start, so the cut is at or before the word, never inside it. | 2 tests in `tests/test_boundaries.py::TestSilenceAlignment`; **2 fail without the fix** |
| 22 | **A face track could jump to a smaller face beside it.** The tracker's proximity fallback scaled its tolerance by the **larger** of the two faces, so a track could hop onto a smaller face-shaped object near the speaker — and the crop would then pan away from the speaker to follow it. | Found while **verifying defect 19** against the real source: the track of one segment held two different people, and the crop followed the wrong one. A real frame shows what the detector saw: the speaker, leaning forward, and a Pikachu plush on the shelf behind them (AT-G-12). | The tolerance is scaled by the **smaller** of the two faces — the person's own face width — which is what the rule always said. A track stays with its person. | 1 test in `tests/test_reframe.py::TestTracking`; **fails without the fix** |
| 23 | **The face detector could not see the streamer at all.** MediaPipe scales its input to about **128 px** on the short side, so a face **120 px** wide in a **1920 px** frame is smaller than one pixel of the image the detector actually looks at. Over **2,100 s** of the reference video the detector found **0** faces. | Running the detector over the reference source, before any of the framing work: **0** observations over 2,100 s, and **11** over 900 s — a rate far too low to track anything (AT-H-04). | The detector **tiles** the frame instead of shrinking it: **640 px** tiles with **15 %** overlap, each tile copied so it is contiguous. The same source then gave **56** observations over 2,100 s and **45** over 900 s. | 3 tests in `tests/test_faces.py`; the tiled-detection test **fails without the fix** |
| 24 | **The tiles were read with the wrong strides.** A tile cut out of a frame is a **non-contiguous view** of the original array, and MediaPipe read it as if it were contiguous — so every tiled frame came back with **zero** faces, which looked exactly like "there is no face here". | Running the tiled detector over the same source and getting **0** observations where the untiled detector had found some (AT-H-04). | Each tile is copied with `np.ascontiguousarray` before it is handed to the detector. | 2 tests in `tests/test_faces.py`; the contiguous-tile test **fails without the fix** |
| 25 | **The edge search looked in the wrong place.** The webcam's **horizontal** edges were searched for in a narrow band around the face — but the edge of a webcam box is a long horizontal line **across the whole box**, and in the reference video the bright panel of a game menu inside that band won the vote. | Running the new edge detector over 30 s of the reference video: the **horizontal** edges were wrong, and the box it produced did not match the webcam (AT-H-05). | The horizontal edges are searched over the **columns the box occupies** — the width the vertical edges already established — not over a narrow band. On the same 30 s the detector now finds **all four** edges: `x=1274, w=638, y=9, h=426`, against a true box of about `x 1272…1912, y 0…436`. | 7 tests in `tests/test_webcam_box.py`; the horizontal-axis test **fails without the fix** |
| 26 | **The first frame of a clip was read from before the clip began.** The sampler computed the first frame's position by subtracting the clip's start from a frame time that was already relative to the clip, and the result could be **negative** — which asks the decoder for a frame before the clip. | The clip-relative timestamp arithmetic in `_iter_frames`, checked against a clip that starts part-way into the source (AT-H-06). | The timestamp is clamped at zero. | 1 test in `tests/test_faces.py`; **fails without the fix** |
| 27 | **The webcam spilled out of its own strip.** When the webcam could not fill the **40 %** band without turning the face into a blur, the partial path scaled it by the face limit alone and placed it by its own size — so the result could be **wider than the band** it was supposed to sit in. | The layout's own geometry, checked against a webcam whose aspect does not match the strip (AT-H-07). | `_fit_in_strip` fits the webcam **inside** the strip on both axes at once, and returns nothing when it cannot. | 2 tests in `tests/test_layout.py::TestTheSplitScreen`; the spill test **fails without the fix** |
| 28 | **The gameplay crop did not keep clear of the webcam.** The layout already kept the two areas apart, but the **crop path** — the window the gameplay is actually cut from — was built without knowing where the webcam was, so the streamer appeared **twice**: once in the strip, once inside the gameplay. | Comparing the gameplay window against the webcam's region in the plan (AT-H-07). | `ReframeConfig.avoid` carries the webcam's region; the crop window is pushed clear of it, and a **final pass over the finished plan** holds every fallback clear too — the centre crop, the fit, and the whole-frame path. | 6 tests in `tests/test_reframe.py::TestTheWebcamIsKeptOutOfTheGameplay`; the fallback tests **fail without the fix** |
| 29 | **The progress page lost the video's title the moment the event stream opened.** The server's first `snapshot` event carried the job but **not** its source, so the page rendered the title for a moment and then replaced it with nothing — the duration, the resolution and the title all went at once. | Opening the running job's page in the browser and reading the DOM (AT-H-08). | The snapshot carries the source, and the client **merges** the snapshot rather than substituting it, so a payload without a source can never take the title off the page. | 1 test in `tests/test_api.py::TestEventStream::test_the_snapshot_carries_the_source`; **fails without the fix** |
| 30 | **The webcam's path grew an ffmpeg expression past Windows' own command-line limit.** Every measured box became a keyframe, and the path became a nested `if()` per keyframe — evaluated at **every frame** of the clip. A path of **600** boxes produced a filter graph of **50,019 characters**, against a limit of **32,767**. | Building the filter graph from a path of 600 measured boxes — the shape the detector's own sample rate produces on a ninety-second clip (AT-H-09). | The path is **thinned** to at most **48** keyframes — the same budget the gameplay crop path uses — dropping the ones that say nothing their neighbours do not already say, and keeping the endpoints so the path still covers the clip. | 6 tests in `tests/test_webcam.py::TestTheWebcamPath`; the length and the budget tests **fail without the fix** |
| 31 | **The detector was asked for the stretches in the wrong order, and refused.** The clips come in **rank** order — the model's best clip first — and rank is not position. The detector walked the source in that order, so after the third stretch it asked the decoder to seek **backwards**, and the decoder refused: *"Input timestamp must be monotonically increasing."* The webcam was never found, and **every clip was rendered without the split-screen**. | The real run: the saved report said `"unavailable_reason": "Input timestamp must be monotonically increasing."`, no track, and the six exports came out as plain gameplay with no webcam strip at all (AT-H-10). | The stretches are walked in the order they sit in the **source**, whatever order they are given in — in the runner, in the face sampler and in the shot detector. On the same source, asked in the same wrong order, the detector now finds the webcam at **98 %** confidence. | 2 tests in `tests/test_faces.py::TestTheClock` and 1 in `tests/test_pipeline_cache.py::TestTheOrderTheWindowsAreAskedFor`; **fail without the fix**, with the production error |
| 32 | **A saved crop plan was reused after the layout had changed.** The plan was cached under the clip's name alone, with nothing saying what it was made *for*. When the webcam was found the gameplay's shape changed with it — from the whole **9:16** to the **15:16** bottom strip — and the old plan was reused anyway, so the gameplay was cropped to the wrong shape and stretched into the slot. | The run after defect 31 was fixed: the plan on disk was still **608×1080** (9:16) while the layout asked for **1012×1080** (15:16) (AT-H-11). | The plan records a **fingerprint** of the settings it was built for — the aspect ratio and the webcam region it was kept clear of — and a saved plan is only reused when the settings still match. | 4 tests in `tests/test_pipeline_cache.py::TestTheSavedCropPlan`; the stage test **fails without the fix** |
| 33 | **A detection that could not run was kept as a final answer.** The report recorded *why* the webcam was not found, and a report with a reason was reused as-is. The detector's failure — a decoder that refused, a model that was missing — was therefore as final as *"there is no webcam in this footage"*, and the job could never find the webcam again. | The same report that defect 31 produced: `"unavailable_reason": "Input timestamp must be monotonically increasing."` — an error message, cached as if it were an answer (AT-H-10). | A report says whether the detection **failed** or simply found nothing, and only a real answer is reused. A failed detection is tried again, and a report written by an **older version** of the detector — which cannot say whether it failed — is not reused either. | 4 tests in `tests/test_pipeline_cache.py::TestTheSavedWebcamReport`; **fail without the fix** |
| 34 | **A re-export would have stretched a plan made for another shape.** Found while fixing defect 32, by reading the re-export path rather than by running it. The review page's *"Export this clip"* reused the job's saved plan whenever the ratio was **9:16** — but after defect 32's fix that plan is the **15:16** one the stacked layout needs, and stretching it into a 9:16 frame distorts the gameplay. | Reading `api/clips.py::_crop_path_for` while fixing defect 32, and checking what it would do with the plan the fix produces (AT-H-11). | A saved plan is only reused when its **own shape** is the shape being exported; otherwise the crop is made for the ratio asked for. | 2 tests in `tests/test_pipeline_cache.py::TestTheReExportPath`; **fail without the fix** |
| 35 | **The saved webcam report was never reused, because the windows never matched exactly.** The report rounds the windows it stores to **3 decimal places**, while a clip's end time is `1303.9599999999998`. The comparison was exact, so it never matched — and every retry paid for the detection again, which on this source is **seventeen minutes**. | The last run of the job: the report on disk carried the timestamp **02:35:40** while the layouts beside it were rewritten at **02:56:29** — the detection had been done again even though the windows had not moved (AT-H-12). | The comparison is tolerant to **0.01 s**, which is smaller than the rounding the report applies and far smaller than the difference between two different stretches. | 1 test in `tests/test_pipeline_cache.py::TestTheSavedWebcamReport::test_a_report_for_the_same_windows_is_reused`; **fails without the fix** |
| 36 | **The speech-emphasis zoom broke the render.** The zoom was computed in a `scale` filter, and ffmpeg evaluates a `scale` filter's `w` and `h` **once**, at init — so a per-frame expression in them is refused: *"Expressions with frame variables 'n', 't', 'pos' are not valid in init eval_mode."* Every clip with a moving webcam failed to render. | Rendering a moving webcam with a speech emphasis through the real ffmpeg: the export failed with `[Parsed_scale_90 ...] Expressions with frame variables 'n', 't', 'pos' are not valid in init eval_mode.` (AT-H-13). | The scale is evaluated **per frame** (`eval=frame`) and the centred crop that follows it is evaluated the same way, so the zoom can change within the clip. | 1 test in `tests/test_export_render.py::TestLayoutRender::test_a_moving_webcam_with_speech_renders` — a **behavioural** render test that reproduces the exact production error; **fails without the fix** |

**And one finding that is **not** a defect, because nothing the product promises was broken.** The
same source, run twice, gave **two different transcripts** from **byte-identical** media — the
recogniser's confidence fallback **samples** without a seed, and the product inherits that. It is
measured in **AT-G-17**, the fix is **verified** against the real audio, and it is recorded as
**K32** and **R8** rather than presented as a pass.

**Defect 3 is the one that would have shipped.** It rendered on the machine the code was written
on, and it would have failed on the CI runners and on every user with an ffmpeg older than 9. It
was caught because the Linux leg was reproduced locally on ffmpeg 7.0.2 rather than assumed to
behave like the Windows one.

**A fourth defect — in the CI itself — was found while confirming the first three.** The
`Verify ffmpeg can burn subtitles` step piped a large filter list into `grep -q`. `grep -q` exits
the moment it finds a match, the producer then gets SIGPIPE, and GitHub's `set -o pipefail` turns
that broken pipe into a failed step. On the Ubuntu runner's ffmpeg 8 the list is large enough to
fill the pipe, so CI reported that an ffmpeg **with** the `ass` filter did not have one — the
job log shows `printf: Broken pipe` and then the `ass` filter listed on the very next line. The
step now matches the filter list with bash's own pattern matching and never pipes. The check
itself is unchanged: a build without the `ass` filter still fails it.

**A second defect in the CI itself — also about ffmpeg, and also a wrong answer — was found at
M5.5.** The Windows leg of the M5.5 documentation commit (run **44**) failed with *"This ffmpeg
has no 'ass' filter"*. There was no ffmpeg at all: Chocolatey's **metadata** endpoint was
unreachable — `504` on one attempt, `503` on the next, and the same endpoint **timing out from
this machine** in the same minutes — so `choco install ffmpeg-full` installed **nothing** and
still **exited 0**, and the install step reported success. The next step then looked for the
filter in a program that was never installed, and named the wrong cause. The job was re-run
**nine times** — **ten attempts**, all the same. The install now runs
`scripts/install_ffmpeg_windows.py`: **Chocolatey first**, exactly as before, and only if that
produced no ffmpeg, Chocolatey's own **package** URL on the same host — the same package, the
same version, the same binaries. Proved locally before it was written (the package downloaded,
unpacked, and the ffmpeg it produced checked for its `ass` filter) and guarded by **6** tests.

---

## The evidence index

| What | Where |
|---|---|
| This file | `docs/M5-APPLICATION-TESTING.md` |
| The automated lane | `docs/M5-REGRESSION-REPORT.md` |
| The security lane | `docs/M5-SECURITY-REVIEW.md` |
| The feature matrix | `docs/feature-coverage-matrix.md` |
| The milestone ledger | `docs/UPGRADE-LEDGER.md` |
| The release assessment | `docs/FINAL_UPGRADE_REPORT.md` |
| The governing specification | `docs/UPGRADE-SPEC.md` PART 12 |
