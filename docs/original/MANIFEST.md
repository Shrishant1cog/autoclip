# Original requirements and visual references — MANIFEST

**Created:** 2026-11-19 (M0, Section 3 of the governing specification).

## Result: nothing found. Nothing reconstructed.

The governing specification says the original product requirements and **seven** visual workflow
reference files were supplied outside the document, and requires them to be located, copied here
byte-for-byte, and hashed. If any are missing they must be **reported, never reconstructed**.

They are not on this machine. `docs/original/` therefore contains **no copies**, and this file is a
missing-items report rather than a manifest of found files.

**Found: 0 of 8 expected items.**

---

## What was searched

| Location | Scope |
|---|---|
| `C:\Users\mdnik\OneDrive\Desktop\projects\autoclip` | entire working tree, including `docs/`, `.planning/`, `materials/` |
| `C:\Users\mdnik\OneDrive\Desktop\projects` | recursive |
| `C:\Users\mdnik\OneDrive\Desktop\git_other_projects\AutoClip` | the original clone, incl. its untracked `All-Branches/` |
| `C:\Users\mdnik\OneDrive\Desktop\git_other_projects\autoclip.git` | all branches (`main`, `feature/autonomous-platform`, `feature/autonomous-platform-v2`) |
| `All-Branches\*.zip` (3 non-empty archives) | archive contents listed |
| `C:\Users\mdnik\Desktop`, `Downloads`, `Documents`, `OneDrive` | recursive, by extension and by name |
| Git history across all branches | `git log --all`, `git show` on doc-like paths |

Patterns searched: `*requirement*`, `*REQUIREMENT*`, `*workflow*ref*`, `*n8n*`, `*autoclip*`,
`*original*`, `*reference*`; extensions `.md`, `.txt`, `.pdf`, `.docx`, `.png`, `.jpg`, `.jpeg`,
`.webp`, `.svg`.

## What was found instead (and ruled out)

These were inspected and are **not** the missing material:

| File | Why it is not the reference |
|---|---|
| `C:\Users\mdnik\Documents\community project 1.pdf` | A 3-page Canva community-project report by "Nikshith Md"; unrelated to AutoClip. |
| `C:\Users\mdnik\Documents\PPT Format.pdf` | A Canva presentation-format export; unrelated. |
| `C:\Users\mdnik\Documents\ai.jpeg` | A photograph; not a UI reference. |
| `C:\Users\mdnik\Downloads\WhatsApp Image 2026-10-28 at 3.04.53 PM.jpeg` | A photograph; not a UI reference. |
| `AutoClip.zip`, `All-Branches/*.zip` | Repository snapshots; contain only source, no requirement docs or reference images. |
| `docs/ARCHITECTURE.md`, `CHANGELOG.md`, `.planning/*` | Authored inside the project; they describe what was built, not the commissioning brief. |

`docs/original/` was created empty by this report. **No file is a stand-in for a missing one.**

---

## The missing items, enumerated

| # | Item | Expected form | Status |
|---|---|---|---|
| 1 | Original product requirements document | document (md/pdf/docx/txt) | **MISSING** |
| 2 | Visual workflow reference 1 of 7 | image | **MISSING** |
| 3 | Visual workflow reference 2 of 7 | image | **MISSING** |
| 4 | Visual workflow reference 3 of 7 | image | **MISSING** |
| 5 | Visual workflow reference 4 of 7 | image | **MISSING** |
| 6 | Visual workflow reference 5 of 7 | image | **MISSING** |
| 7 | Visual workflow reference 6 of 7 | image | **MISSING** |
| 8 | Visual workflow reference 7 of 7 | image | **MISSING** |

The specification does not describe the references beyond "seven visual workflow references", so even
their intended content is unknown here. Guessing would be worse than reporting.

---

## Consequence for the coverage matrix

`docs/ORIGINAL_REQUIREMENTS_MATRIX.md` cannot be marked complete. It is populated with:

- every requirement from the **governing M0–M5 specification** (status
  `Verified against consolidated prompt only`), and
- placeholder rows for the eight missing items, status `Blocked — source missing`.

No row may be marked `Verified against original source`, because no original source was found.

---

## If the owner supplies them

Drop the files into `docs/original/` with their exact original names, then run:

```powershell
cd C:\Users\mdnik\OneDrive\Desktop\projects\autoclip
Get-ChildItem docs\original -File | ForEach-Object {
  $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  "{0}  {1}" -f $h, $_.Name
}
```

Paste the output into a `## Found files` table below with the SHA-256 and where each came from, and
flip the corresponding matrix rows to `Verified against original source`. No code changes are needed
for the matrix to become fewer-blocked; only the evidence changes.

## Found files

_(none)_
