# Performance baseline (M0)

**Reference hardware.** Intel Core i5-8279U, 4 cores / 8 threads, 7.8 GB RAM, Intel Iris Plus 655
(no CUDA — every GPU-accelerated path runs on CPU here), Windows, Python 3.11.16, FFmpeg 9.0.2,
Node 24.21.0.

**Reproduce:** `.venv\Scripts\python.exe scripts\bench_baseline.py`
**Machine-readable output:** `docs/BENCHMARK-BASELINE.json`

The script is deliberately deterministic and offline: no network, no real media. It measures the
parts of the product that are cheap to measure repeatedly, so "before vs after" is a fair
comparison. Pipeline-level numbers require a real source video and are recorded separately under
Lane C.

---

## Deterministic measurements

| Measurement | min | median | max | Unit |
|---|---|---|---|---|
| Cold import `autoclip.app` | 698 | **755** | 2,283 | ms |
| Cold import `autoclip.pipeline.runner` | 102 | **110** | 144 | ms |
| Open existing DB + `PRAGMA user_version` | 2.19 | **2.72** | 31.75 | ms |
| `store.list_jobs()` (default limit) | 1.18 | **1.43** | 4.81 | ms |
| Fresh DB, all 14 migrations | 225 | **239** | 285 | ms |
| Build music/ducking filtergraph string | 0.02 | **0.02** | 0.08 | ms |
| Encode 5 s 1080×1920 H.264 (veryfast, CRF 23, + AAC) | 1,314 | **1,518** | 1,541 | ms |

Output size for the encode: **3,691,703 bytes** for 5 s — a stable reference for "did the encoder
output change" as well as "did it get faster".

---

## Suite-level measurement

| Measurement | Value |
|---|---|
| 672-test mandatory suite, wall clock | **193.77 s** (first run), 233.50 s (cold caches) |

The variance between runs is cache warmth (Whisper/MediaPipe imports, `.pytest_cache`), not test
content. Later comparisons should use the same machine and note the run order.

---

## Targets set by the specification

The M0–M5 specification does **not** set numeric performance targets; it requires that a baseline
exist before optimisation and that no speed claim be made without a comparable measurement
(Part 11.3). The two targets that *do* appear belong to the superseded U0–U10 document
(200-node drag ≤ 16 ms p95, 10k-row history ≤ 1 s) and to the earlier one (resolver ≤ 1 ms). Because
the new specification supersedes the old, these are **not** carried forward as acceptance criteria.
They are recorded here only so that a later reviewer does not think they were silently dropped:

| Superseded target | Status |
|---|---|
| Node drag p95 ≤ 16 ms in a 200-node graph | Not applicable — canvas is out of scope |
| 10,000-row run history first page ≤ 1 s | Not applicable — run history is out of scope |
| Settings resolver ≤ 1 ms per decision | Not applicable — no resolver is in scope |
| Startup recovery of 1,000 runs ≤ 10 s | Not applicable |
| SSE reconnect ≤ 5 s | Applies to existing SSE; still worth measuring if SSE work is touched |

The **in-scope** performance requirements that this baseline must serve are:

1. Long media work must not run in an HTTP handler (Part 1.2 / reliability).
2. A blocked upload must not delay another lane (implied by §8.3 + Part 11.1).
3. Rendering must remain within the resource ceilings the monitor reports (§11.3).

Those are measured when the lanes exist (M1 onwards) and reported in M5 against the numbers above.

---

## What is **not** measured yet, and why

| Not measured | Reason | When |
|---|---|---|
| Import (yt-dlp download) time | Needs network; Lane B | M5 with a controlled URL |
| Transcription time | Needs real audio; Lane C | M2 (shared timeline needs it) |
| Analysis (highlights/reframe) time | Needs real media | M3 |
| AI latency | Needs a provider; Lane B | M3 |
| Peak memory / CPU / GPU during a render | Needs a sampled run | M5 |
| Export size for real footage | Needs real media | M5 |

None of these is claimed as improved or unchanged until it is measured with this same harness and the
same source file.
