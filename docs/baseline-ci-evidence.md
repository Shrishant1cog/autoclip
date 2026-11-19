# Baseline CI and test evidence

Captured **before** any functional change to the upgrade branch, on 2026-11-19, from
`feature/upgrade-u0-u10` @ `bf76811` on the reference machine (Windows, Python 3.11.16).

The purpose of this file is to be the "before" that every later claim is measured against. It is
not updated as the upgrade proceeds; later runs are recorded in `docs/UPGRADE-LEDGER.md`.

---

## Exact commands

```powershell
cd C:\Users\mdnik\OneDrive\Desktop\projects\autoclip
$env:PYTHONIOENCODING = "utf-8"

# Unit suite (the mandatory Lane A set)
.venv\Scripts\python.exe -m pytest tests -q --ignore=tests\test_pipeline_e2e.py

# Real-media suite - collected, not run (needs AUTOCLIP_E2E_MEDIA)
.venv\Scripts\python.exe -m pytest tests\test_pipeline_e2e.py --collect-only -q

# Lint and format
.venv\Scripts\python.exe -m ruff check . --output-format concise
.venv\Scripts\python.exe -m ruff format --check .

# Types
.venv\Scripts\python.exe -m mypy backend/autoclip
```

Tool versions: `ruff 0.17.5`, Python `3.11.16`, FFmpeg `9.0.2`, Node `24.21.0`.

---

## Results (as found)

| Gate | Result | Detail |
|---|---|---|
| pytest, excluding e2e | **672 passed** | 193.77 s |
| pytest, e2e collected | **24 collected** | requires `AUTOCLIP_E2E_MEDIA`; not run |
| `ruff check .` | **PASS** | "All checks passed!" |
| `ruff format --check .` | **FAIL** | "38 files would be reformatted, 109 files already formatted" |
| `mypy backend/autoclip` | **14 errors in 10 files** | CI runs mypy with `continue-on-error: true`, so this never blocks |
| Django/FastAPI import smoke | PASS | app imports in 755 ms cold |

### mypy errors as found

```
backend\autoclip\pipeline\runner.py:699: error: "object" has no attribute "__iter__"; maybe "__dir__" or "__str__"? (not iterable)  [attr-defined]
backend\autoclip\cli.py:231: error: Incompatible types in assignment (expression has type "bool", variable has type "list[str]")  [assignment]
... 12 more across 10 files
```

The 14 are pre-existing and are **not** fixed in M0; fixing them is type-only work that belongs with
the modules it touches. They are carried in `docs/upgrade-audit.md` §16 (T1).

### Why the format failure matters

`pyproject.toml:85` pins `ruff>=0.7` with no upper bound, so CI evaluates
`ruff format --check .` against whatever ruff it installs. The shipped tree did not satisfy the
current formatter. On GitHub the backend job therefore failed at the format step **before** it
reached the unit and render test steps — which is consistent with the inherited observation that
"backend unit tests were not executed" and "macOS backend job was cancelled" (the matrix
`fail-fast: false` prevents cancellation in principle, but a failed earlier step produces the same
practical result for the remaining steps in that job).

This is recorded as defect **D15** and fixed by two formatting-only commits:

- `26ebf00` — `runner.py` + `scripts/make_e2e_media.py` (the M0-mandated standalone commit)
- `3c290b2` — the remaining 36 files

After reformatting: `ruff format --check` → "147 files already formatted"; `ruff check` → clean;
full suite → **672 passed** again.

---

## CI workflow as found

`.github/workflows/ci.yml` (before this milestone's change):

| Job | Matrix | Steps |
|---|---|---|
| backend | ubuntu 3.11, ubuntu 3.12, macos 3.12, windows 3.12 | ruff check → ruff format --check → mypy (`continue-on-error: true`) → pytest (`-m "not slow and not golden and not e2e"`) → pytest (`-m "slow and not golden and not e2e"`) |
| frontend | ubuntu | `npm ci` → `npm run build` |
| docker | ubuntu | build image → smoke `/api/health` |

**Trigger:** `push` to `main` only, plus `pull_request` (D8). A push to any `feature/**` branch ran
nothing.

---

## Frontend baseline

`frontend/package.json` scripts as found:

```json
{ "dev": "vite", "build": "tsc -b && vite build", "preview": "vite preview", "typecheck": "tsc -b --noEmit" }
```

There is no `test` script and no test dependency (D9). The frontend therefore contributes **zero**
automated behavioural evidence at baseline; `npm run build` proves only that it compiles.

---

## Docker baseline

Not executed on this machine at audit time (no Docker daemon running). CI reports the docker job
green at `bf76811`. This is recorded as **Unverified locally**; the M5 release pass must build and
smoke-test the image on the build machine and record the digest.

---

## Interpretation

- **722 tests are collected** across 36 modules: **672 pass** in the mandatory set, **26 are the
  M0 SSRF target-policy xfails**, and the `test_pipeline_e2e` module collects **24** that need real
  media. Nothing in the mandatory set is skipped.
- The suite is genuinely green, which means the reformat did not change behaviour.
- The **CI** was not green at baseline, because of a formatter drift that had nothing to do with
  product code.
- The frontend and the docker image had no local evidence.

These four statements are the baseline. No later milestone may report "improved" without comparing
to them.
