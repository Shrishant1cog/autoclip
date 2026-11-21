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
5. **The media was synthetic.** A generated podcast segment with real speech, real H.264 and real
   AAC — not a creator's footage, and nothing here claims it is.
6. **The re-export does not rebuild the webcam composition.** The per-clip `LayoutPath` is not
   persisted, so a re-export reuses the cached crop path. Named in AT-B-05.

---

## The three defects this testing found

All three were found by **running the application or its gates**, not by reading the code, and all
three are covered by tests that fail without the fix.

> **Amendment — 2026-11-21 (M5.1).** This application run found **three** product defects, and
> this section records them as they stood at M5. A **fourth product defect** was found afterwards,
> by closing the last PARTIAL matrix row: the eight-case ducking matrix, written as eight **real
> renders**, exposed that an empty speech timeline was indistinguishable from no timeline at all,
> so a clip with no talking had its music pulled down by the source. It was fixed and guarded —
> see `docs/FINAL_UPGRADE_REPORT.md` §4.2 (defect 4) and §4.3, and
> `docs/upgrade-audit.md` §13.2. **Nothing in this section is invalidated by it**; the three
> defects below remain exactly as measured here.

| # | Defect | Found by | Fix | Guard |
|---|---|---|---|---|
| 1 | The API export path ignored the user's music preference and the speech-interval ducking. | Clicking *Export this clip* on a clip with a track chosen. | `api/clips.py` resolves the music through the same three-scope precedence the pipeline uses, and hands the renderer the job's speech timeline sliced to the clip. | 7 regression tests in `tests/test_api.py::TestClipExportHonoursTheUsersMusic`; **6 of the 7 fail without the fix**. |
| 2 | The timeline-driven ducking filtergraph was malformed — a label in the middle of the bed's chain — and ffmpeg refused the whole graph. | The export failing with ffmpeg's own stderr. | The bed chain carries no output label; the label is added where the bed is used. | 3 real-render tests in `tests/test_export_render.py::TestMusicBedRender`; **2 of the 3 fail without the fix**. |
| 3 | The sidechain fallback consumed one filter output twice, which ffmpeg 9 accepts and ffmpeg 7 refuses. | The Linux CI reproduction leg, on ffmpeg 7.0.2. | The speech is split with `asplit=2` into a mix copy and a key copy, both on the bed's channel layout. | 3 real-render tests, plus a **structural** check in `tests/test_music.py` that no filter output is consumed twice and no filter follows an output label — version-independent, so it catches the defect on any ffmpeg. |

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
