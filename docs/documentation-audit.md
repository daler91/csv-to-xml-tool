# Documentation audit

**Date:** 2026-09-16 · **Commit audited:** `d0e71f0` · **Branch:** `claude/bold-brown-tv16bq`

What was checked, what was wrong, what changed, and what is still wrong in the
code that documentation can only flag.

## Method

Claims were verified by running the code, not by reading it:

- Both test suites were installed and executed with coverage.
- `ruff check .`, `npm run lint` and `npm run build` were run.
- The worker was started with the command this documentation recommends, and
  `/health` was queried to confirm the documented response shape.
- All three sample CSVs were converted through the CLI and validated against the
  bundled XSDs with lxml.
- Column vocabularies, defaults, enumerations, Redis key names, audit actions,
  rate limits and route tables were dumped from the code rather than transcribed.

Anything that could not be verified this way is marked as such where it appears.

## Before

Six Markdown files, all at the repository root:

| File | Lines | Kind |
|---|---|---|
| `README.md` | 189 | Mixed front door and reference |
| `ARCHITECTURE_REVIEW.md` | 211 | Historical register |
| `CODEBASE_ANALYSIS.md` | 606 | Current findings register |
| `TECHNICAL_DEBT.md` | 150 | Debt register |
| `UX_REVIEW.md` | 1,471 | UX register |
| `UX_IMPLEMENTATION_PLAN.md` | 829 | UX plan |

Four of the six were **registers of problems**. The only description of how the
system actually works was the README, and it was a mix of a getting-started page
and a partial reference. There was no architecture document, no API reference, no
configuration reference, no CSV column reference, no deployment or operations
guide, no testing guide, no contributing guide, no security policy and no
troubleshooting guide.

## After

```
README.md                    Short front door, pointing into docs/
docs/
├── README.md                Index and conventions
├── getting-started.md       Web app and CLI, first conversion
├── architecture.md          Components, pipeline, job lifecycle, data flow
├── converters.md            The three converters, cleaning rules, fabricated defaults
├── csv-reference.md         Expected columns and requirement tiers per converter
├── cli.md                   run.py, src.main, fix_sba_xml, path confinement
├── api-reference.md         Web API and worker API, with status codes
├── configuration.md         Every env var, defaults, failure modes
├── deployment.md            Compose, Railway, images, migrations, checklist
├── operations.md            Queue, retention, audit, logs, limits, runbook
├── testing.md               Suites, CI, the tests worth understanding
├── troubleshooting.md       Errors grouped by user / operator / developer
├── CONTRIBUTING.md          Setup, non-negotiable rules, conventions
├── SECURITY.md              Reporting, controls, known weaknesses
├── documentation-audit.md   This file
└── reviews/
    ├── README.md            What each register is and whether to trust it
    ├── ARCHITECTURE_REVIEW.md
    ├── CODEBASE_ANALYSIS.md
    ├── TECHNICAL_DEBT.md
    ├── UX_REVIEW.md
    └── UX_IMPLEMENTATION_PLAN.md
```

The five registers were moved with `git mv`, keeping their original filenames —
they are referenced by name from ~25 source comments and from commit messages,
and renaming them would break those references for no benefit.

## Documentation errors found and corrected

### README

| Claim | Reality |
|---|---|
| "343 tests (pytest)" | 374 |
| Linked five root-level docs | All five moved under `docs/reviews/` |
| Mixed a 3-step CLI quick start with web app setup, project structure and a partial CLI reference | Split: the README is now a front door; the reference lives in `docs/` |

### `.env.example`

| Claim | Reality |
|---|---|
| "After ARCH-4 the web↔worker bodies carry only paths (not file content)" | **Wrong.** `ConvertRequest.csv_content` and `ConvertResponse.xml_content` carry the file content; there is no shared volume between the services. Corrected in place. |

This one mattered: it is the comment explaining *why* `MAX_UPLOAD_BYTES` bounds
conversion memory, and its stated reason was the opposite of what the code does.

### `CODEBASE_ANALYSIS.md`

Section 2 "Baseline health" carried figures from commit `bd390af`: 281 pytest,
86.79% coverage, 113 vitest across 18 files, and "148 commits since 2026-03".
Re-measured to 374 pytest, 88.8%, 173 vitest across 23 files, and 131 commits
first dated 2026-04-03. Both readings are now shown side by side so the trend
stays visible.

### `TECHNICAL_DEBT.md`

| Item | Was | Now |
|---|---|---|
| #2 | Listed `pd.errors.ParserError` among the specific exception types caught | pandas was removed entirely; the type appears nowhere |
| #7 | "Added version range pins (e.g. `pandas>=2.2.0,<3`)" | Pins are **exact** (`lxml==6.1.3`), and pandas is not a dependency |
| #11 | "166 tests across 22 files" | 173 across 23 |

A verification date was added at the top.

### `UX_REVIEW.md`

§7.8 "Nav doesn't collapse on mobile **[P1]**" carried no resolution marker,
while §1.1 recorded the same fix as `[RESOLVED]`. The nav does collapse —
`components/nav.tsx` hides the links on `md:hidden` behind an `aria-expanded`
toggle. Marked `[RESOLVED]`.

The rest of `UX_REVIEW.md` held up well; its inline markers are accurate.

### `ARCHITECTURE_REVIEW.md` — deliberately not corrected

Its banner already states that it is a historical record, that ~20 of its 24
findings are fixed, and that every `file:line` citation is stale. Rewriting it to
match current code would destroy the only thing it is useful for. It is filed
under `reviews/` and flagged in the index.

### Source comments

~25 comments across `apps/web/src`, `apps/web/scripts`, `apps/worker/app` and
`src/` referenced the registers by bare filename (`UX_REVIEW.md §3.6`). Updated to
the new paths (`docs/reviews/UX_REVIEW.md §3.6`).

Two were real hyperlinks in the in-app `/help` page, pointing at
`blob/master/UX_REVIEW.md` and `blob/master/TECHNICAL_DEBT.md` — both would have
404ed after the move. They now point at `docs/troubleshooting.md` (the
troubleshooting guide) and `docs/reviews/TECHNICAL_DEBT.md` (the known-issues
register), which also suits the "Getting help" section better than sending a
partner to a UX audit.

`.dockerignore` gained `docs` so the new folder is not sent to the build daemon,
and lost its `patch_tests.diff` entry, which refers to a file deleted some time
ago.

## Code issues found during the audit

These are **code** defects, not documentation defects. They are documented
accurately as-is rather than silently glossed, and listed here so they are easy
to pick up. None were fixed as part of this audit — it was scoped to
documentation.

### 1. `run.py` never offers XSD validation

`_pick_xsd()` calls `find_files(script_dir, ".xsd")`, which looks for schemas
**beside `run.py`**. The bundled schemas live in `schemas/`, so on a clean
checkout the list is empty, step 4 is skipped silently, and the XML is written
unvalidated.

The README previously advertised this step as part of the guided flow, so a user
following it would never see the prompt and would not know why. Documented in
[cli.md](./cli.md#runpy--interactive-launcher) and
[troubleshooting.md](./troubleshooting.md) with workarounds.

**Fix:** search `schemas/` (and the script directory) in `_pick_xsd`.

### 2. The audit page's action list is out of sync

`apps/web/src/app/audit/page.tsx` labels and offers a filter for
`conversion_failed`, which **no code writes**. Six actions that *are* written —
`conversion_timeout`, `conversion_deadlettered`, `files_purged`, `job_deleted`,
`xml_validated`, `xml_autofix` — have no label and render as `"—"`, and are
missing from the filter dropdown.

This is §5.6 in `CODEBASE_ANALYSIS.md`, still open. It is user-visible: a job
that timed out shows a dash instead of a reason.

**Fix:** derive the label map and the filter options from one exported constant
that the writers also use.

### 3. `Job.processedRows` is never persisted

The column exists in `prisma/schema.prisma` with `@default(0)` and is never
written by any Prisma call. The value the progress page reads is computed per
request from the worker's Redis snapshot. Listed as dead in §5.3.

**Fix:** drop the column, or write it.

### 4. Training aggregation findings are still open, with a stale mechanism

`CODEBASE_ANALYSIS.md` §1.7 lists two open aggregation problems and describes
them in pandas terms (`iloc[0]`, `pd.read_csv`). pandas is gone, but **both
problems survived the rewrite** in dict form:

- `'total': max(len(rows), 1)` — demographics count **rows, not distinct
  people**. An attendee listed twice is counted twice.
- `first_record = group_rows[0]` (`training_converter.py:142`) — event-level
  fields come from the first row; disagreeing rows are silently overruled.

The findings are correct; only their mechanism description is out of date. Both
are documented in [converters.md](./converters.md#known-gaps).

## Not done, and why

- **No `LICENSE`.** The repository has none, and choosing one is the owner's
  decision, not a documentation task. Worth resolving: without a license, the
  default is "all rights reserved", which blocks reuse by other resource
  partners.
- **No `CODEOWNERS`** — needs a decision about who reviews what.
- **No `CLAUDE.md`** — [`CONTRIBUTING.md`](./CONTRIBUTING.md) now carries the
  conventions such a file would encode.
- **`ARCHITECTURE_REVIEW.md` was not rewritten**, for the reason above.
- **No code fixes**, including the four above. They are flagged, not patched.

## Keeping it accurate

The failure mode this documentation set is built to avoid is the one
`ARCHITECTURE_REVIEW.md` demonstrates: a document that still reads as current
while describing a codebase that no longer exists. Three habits prevent it, and
they are stated in [CONTRIBUTING.md](./CONTRIBUTING.md#documentation):

1. A behaviour change updates its guide **in the same commit**.
2. Fixing a tracked finding flips its marker **in the same commit**.
3. Counted figures carry the commit they were measured at, and re-measuring
   re-stamps them.
