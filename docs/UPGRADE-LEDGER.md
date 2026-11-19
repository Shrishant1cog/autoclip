# Upgrade ledger

**Branch:** `feature/upgrade-u0-u10` · **Base:** `bf76811` (`feature/autonomous-platform-v2`)
**Governing spec:** `docs/UPGRADE-SPEC.md` (M0–M5, supplied 2026-11-19)

Status values: **Not started** · **In progress** · **Complete** · **Blocked**.
A milestone is `Complete` only when every gate item has passing evidence. A failing gate keeps the
milestone `In progress` and is reported as such.

---

## Milestone summary

| Milestone | Status | Gate evidence |
|---|---|---|
| M0 — Audit and baseline | **Complete** | 16/16 gate items done or explicitly blocked; independent review folded in |
| M0.5 — Security and consent | Not started | — |
| M1 — Music intelligence | Not started | — |
| M2 — Webcam intelligence | Not started | — |
| M3 — Creative intelligence | Not started | — |
| M4a — YouTube hardening | Not started | — |
| M4b — Instagram | Not started | — |
| M5 — Audit and release | Not started | — |

---

## M0 — Audit and baseline

**Status: Complete**, with two items explicitly blocked on the owner (the missing original sources and
the Lane B credentials). The independent review returned 11 corrections; all were applied to the
documents before this milestone was recorded as complete.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | Repository state recorded, branch created, checkpoint pushed | Done | `bf76811` → branch `feature/upgrade-u0-u10`, pushed; `git branch` confirms |
| 2 | Specification saved verbatim | Done | `docs/UPGRADE-SPEC.md` (947 lines) |
| 3 | Original requirements + 7 references located | **Blocked — source missing** | `docs/original/MANIFEST.md` (0 of 8 found; full search record) |
| 4 | `docs/upgrade-audit.md` with all 18 sections | Done | 20 sections including §18 conflicts and §19 sequence |
| 5 | Feature coverage matrix | Done | `docs/feature-coverage-matrix.md`, 129 rows |
| 6 | Egress inventory | Done | `docs/EGRESS-INVENTORY.md`, 14 transfer paths (E1–E14, E14 added after review) |
| 7 | Security + SSRF audit | Done | `docs/SECURITY-AUDIT.md`, findings S1–S7 + 8 verified-good properties |
| 8 | Baseline CI evidence | Done | `docs/baseline-ci-evidence.md` — 672 passed, format FAIL on 38 files, mypy 14 errors |
| 9 | Benchmark baseline | Done | `docs/performance-baseline.md`, `docs/BENCHMARK-BASELINE.json`, `scripts/bench_baseline.py` |
| 10 | Formatting-only commit, `runner.py` + `make_e2e_media.py`, AST-compared | Done | `26ebf00`; AST identical incl. docstrings |
| 11 | Remainder of the formatter drift | Done | `3c290b2`; 36 files, whitespace only; suite re-run green |
| 12 | SECURITY.md docs-only commit, claim corrected | Done | `615f0e8` |
| 13 | SSRF target-policy tests pre-registered | Done | `tests/test_url_policy.py`, 26 strict xfails |
| 14 | `docs/EXTERNAL-CONSTRAINTS.md` | Done | G1–G9 |
| 15 | Independent review | Done | adversarial review returned 11 corrections (router/page/table counts, E14 trends egress, CR-15 score, YT-22 progress, wrong paths); all applied |
| 16 | D1–D13 re-verified; D14, D15 found | Done | `docs/upgrade-audit.md` §3, §13 |

### Decisions taken in M0

| Decision | Why | Where recorded |
|---|---|---|
| Keep the branch name `feature/upgrade-u0-u10` under an M0–M5 spec | Continuity; the branch and checkpoint already exist and are pushed | `docs/UPGRADE-SPEC.md` header, audit §18 |
| Preserve the out-of-scope features that already ship (canvas, assistant, trends, learning) rather than deleting them | "Preserve useful working functionality" outranks "do not add"; deleting tested screens would destroy user value and break the suite | audit §18 |
| Do not extend any out-of-scope feature | The specification forbids new work in those areas | audit §18 |
| Reformat the whole tree, not only the two named files | CI's format gate fails on the shipped tree, so nothing else can be verified through it | audit §13, commit `3c290b2` |
| Record SSRF gaps as strict xfails, not skips | A skip hides; a strict xfail forces removal once enforced | `docs/SECURITY-AUDIT.md`, `tests/test_url_policy.py` |
| Add `scripts/bench_baseline.py` rather than hand-recorded timings | The spec requires a comparable baseline; a script makes "before vs after" honest | `docs/performance-baseline.md` |
| Do not fix the 14 mypy errors in M0 | They are pre-existing and belong with the modules they touch; fixing them here would inflate a docs milestone | audit §16 T1 |

### Blockers

| Blocker | Effect | Action needed from owner |
|---|---|---|
| Original requirements + 7 visual references absent | Matrix rows blocked; nothing depends on them for the in-scope product work | Supply the files, or confirm they no longer matter |
| No ElevenLabs test key | E1/E2 stay `Automated test verified` only | Supply a test key + spend ceiling |
| No hosted-LLM test key | E4 stays `Automated test verified` only | Supply one key on a supported preset |
| No Google OAuth client / test channel | YT-* live rows blocked at M4a | Supply a client, add the test user, decide on the compliance audit |
| No Meta app / professional account | IG-* live rows blocked at M4b | Confirm eligibility, or accept a disabled integration |

---

## M0.5 — Security and consent

Not started. Plan on entry:

1. `security/urlpolicy.py` implementing the contract in `docs/SECURITY-AUDIT.md`; flip all 26
   xfails to passing tests and **delete the marker** (gate fails if any remains).
2. `security/egress.py`: endpoint classification, consent records, transfer log, redaction.
3. Retrofit E1, E2, E4, E9, E10, E11, E12, E13 and E14 through the gateway — including the existing
   ElevenLabs and LLM calls, not only new ones.
4. FFmpeg `-protocol_whitelist`, yt-dlp hardening args.
5. Non-silent fallback: a refused consent must fail the operation, never route elsewhere.
6. Update `SECURITY.md` with the enforcement detail.
7. Migration for the consent/transfer-log tables (append-only, v15).

---

## M1–M5

Not started. Sequence and ordering constraints are in `docs/upgrade-audit.md` §19.

---

## Change log

| Date | Commit(s) | Change |
|---|---|---|
| 2026-11-19 | `26ebf00` | Format `runner.py` + `make_e2e_media.py` (AST-identical) |
| 2026-11-19 | `3c290b2` | Format the remaining 36 files (D15) |
| 2026-11-19 | `24060ff` | CI on `feature/**`; ignore branch archives (D8) |
| 2026-11-19 | `615f0e8` | SECURITY.md corrected (docs only) |
| 2026-11-19 | `b2fae13` | M0 deliverable set: spec, audit, matrix, egress, security, baselines, ledger, 26 SSRF xfails |
