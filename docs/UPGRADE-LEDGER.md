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
| M0.5 — Security and consent | **Complete** | 12/12 gate items done; 49 security tests passing; the residual yt-dlp secondary-request surface is documented, not claimed |
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

**Status: Complete.** The milestone ships the URL policy, the egress gateway, the consent store, the
retrofit of every existing external call, the Settings surface, and the test evidence.

| # | Gate item | State | Evidence |
|---|---|---|---|
| 1 | `security/urlpolicy.py` implementing the target policy | Done | scheme, IPv4/IPv6 + CGNAT + IPv4-mapped classification, per-hop redirect re-classification, scheme-downgrade refusal, bounded chain, double-resolution rebinding guard |
| 2 | All 26 SSRF xfails flipped to passing tests, markers deleted | Done | `tests/test_url_policy.py` — 26 ordinary passing tests; zero `xfail` markers remain (gate condition) |
| 3 | `security/egress.py`: classification, consent, transfer log, redaction | Done | `EgressGateway.authorize/require/fetch/record`, `redact()` masks a credential completely |
| 4 | Consent storage + migration | Done | DB migration **v15** — `egress_consents`, `egress_log`; `SCHEMA_VERSION = 15` |
| 5 | Retrofit E1, E2, E4 through the gateway | Done | `speech/elevenlabs.py`, `speech/tts.py`, `providers/base.py:LLMProvider._send` |
| 6 | Retrofit E9, E11, E12, E14 through the gateway | Done | `youtube/uploader.py`, `pipeline/ingest.py`, `models.py`, `trends/research.py` |
| 7 | FFmpeg `-protocol_whitelist` | Done | `pipeline/ffmpeg.py:protocol_args()` → `file,pipe`, applied to all three command builders |
| 8 | yt-dlp hardening | Done | `yt_dlp_hardening_args()` → `--proxy ""`; the source URL is classified before the fetch and a private destination is refused |
| 9 | Non-silent fallback | Done | `providers/resolver.py` refuses to try another **external** provider after a consent refusal; only a local provider may answer. `ProviderConsentRequired` aborts the highlights stage |
| 10 | User-visible controls | Done | `api/privacy.py` → `GET`/`PUT /api/privacy/consents`, `GET /api/privacy/transfers`; Settings → External processing |
| 11 | `SECURITY.md` updated with the enforcement detail | Done | consent model table, URL and subprocess policy |
| 12 | Security test evidence | Done | `tests/test_url_policy.py` (26) + `tests/test_egress.py` (23) = 49 security tests, all passing; full suite 721 passing, 0 xfailed |

### Decisions taken in M0.5

| Decision | Why | Where recorded |
|---|---|---|
| A consent decision is keyed by **(operation, destination class)**, not by host | The useful question is "may transcript text leave the machine at all", and the class is what determines the risk. Keying by host would let a decision silently follow a `base_url` to a different machine | `security/consent.py` module docstring, `SECURITY.md` |
| A **configured** public destination is allowed once and recorded with `source="configured"` | An existing install must keep working after the upgrade, but the decision must be visible and revocable rather than implicit forever | `security/egress.py:authorize` |
| A private destination is **never** allowed implicitly | "The user configured it" is not evidence that a LAN address is safe to reach with content | `security/egress.py:authorize` |
| An explicit withdrawal always wins, even for a configured destination | Consent that can be overridden by configuration is not consent | `security/egress.py:authorize` |
| Only content-bearing operations are consent-gated; the rest are logged | Requiring a decision for a model download trains the user to click through prompts without reading them | `security/consent.py:Operation`, `Transfer.requires_consent` |
| Credentials are masked **entirely** in logs — no suffix fingerprint | A secret that appears in a log line is compromised whether or not its last four characters are readable | `security/egress.py:redact` |
| Adapters declare `DEFAULT_ENDPOINT` | The OpenAI, Anthropic and Gemini endpoints appear nowhere in the repository as literals, so a URL scan cannot classify them | `providers/*_provider.py` |
| `SpeechConsentDenied` is a distinct exception type | "Blocked by your settings" and "the service is down" need different remedies and different wording | `speech/base.py` |
| Loopback is never offered as a choice in the UI | It cannot be denied; offering it would imply it can be | `api/privacy.py` |

### Residual risk carried into later milestones

| Residual | Status | Action |
|---|---|---|
| yt-dlp's **secondary requests** (manifest, CDN, page assets) are made inside yt-dlp and cannot be re-classified hop by hop | Documented, not verified | Lane B controlled test against a redirecting host before the surface can be called verified |
| The **first-run MediaPipe model download** still happens inside the pipeline, with no pre-flight check at job start | Product limitation, not a security gap | M3 — pre-flight the check so an offline machine fails before the job starts |
| Legacy global OAuth token still coexists with per-account tokens | Finding S6, untouched by M0.5 | M4a |
| `ruff` still unpinned | Finding S7, untouched by M0.5 | M5 |

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
| 2026-11-19 | `4c869c6` | Ledger changelog row for the M0 deliverable commit |
| 2026-11-20 | *(M0.5 commits)* | SSRF policy, egress gateway, consent store, migration v15, retrofit of every existing external call, privacy API, Settings → External processing, SECURITY.md enforcement detail, 49 security tests |
