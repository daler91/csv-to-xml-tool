# Documentation audit

Each audit of this documentation set, newest first: what was checked, what was
wrong, what changed, and what is still wrong in the code that documentation can
only flag.

- [Second audit — 2026-10-17, at `7b14f3b`](#second-audit--2026-10-17)
- [First audit — 2026-09-16, at `d0e71f0`](#first-audit--2026-09-16)

## Second audit — 2026-10-17

**Commit audited:** `7b14f3b` · **Branch:** `ccr-41bb63ef-t032b4`

### Why it was needed

131 commits had landed since the first audit (112 of them not merges),
changing 194 files: +22,623 / −2,015 lines. Most of it was the conversion core
— `src/` +3,764 and `tests/` +5,852, for the XSD facet checks, the final XSD
check, and leaving a record out instead of failing the file — and the job
pipeline. Guides had been edited along the way, one change at a time; the
registers' markers and the counted figures had not kept up.

### Method

The same rule as the first audit: verify by running, not by reading.

- Both suites, both linters, both dependency audits and the build were run at
  `7b14f3b`: 1027 pytest at 97.5% coverage, 395 vitest in 38 files, ruff, `tsc`
  and `check-ui-classes.mjs` clean, `next build` 28 routes, `pip-audit` and
  `npm audit` clean ([testing.md](./testing.md#current-baseline)).
- pytest was re-run with only `requirements.txt` installed, and again with
  `redis` added, to measure the missing-dependency failure the docs warn about.
- Each guide was checked against facts dumped from the code rather than read
  off it: the worker's routes and OpenAPI schema from the FastAPI app and every
  `route.ts`; every environment variable, by grep across web, worker, CLI,
  compose, both Dockerfiles and both Railway files; Redis keys, audit actions,
  issue categories, column vocabularies and requirement tiers from the source;
  every CLI's `--help`.
- The converters were checked by running crafted CSVs through all three and
  validating the output with lxml; the three samples went end to end through
  the CLI ([testing.md](./testing.md#manual-verification)).
- Every finding not marked fixed in the seven maintained registers was
  re-checked, most by reproducing it, and about 70 `[FIXED]` markers were
  spot-checked.
- Every relative link and `#anchor` in the 26 Markdown files was checked after
  each change.

Two things could not be run here. There is no Docker daemon, so the compose and
`redis-cli` commands were checked against the source only. Railway's docs site
was unreachable, so Railway behaviour was checked against its documentation's
search results and a Railway staff answer on its forum.

### What was wrong

| Document | What was wrong (a selection) |
|---|---|
| `README.md`, `CONTRIBUTING.md`, `testing.md`, `troubleshooting.md` | "140 tests silently skip" without the worker's dev requirements. With only `requirements.txt`, pytest stops at collection on `No module named 'redis'`; with `redis` but not `fastapi`/`fakeredis` it passes, `887 passed, 11 skipped` |
| `testing.md` | CI's web job runs `npm ci --ignore-scripts` then `npm run generate`; the counseling drift guards are in `test_counseling_column_mapping.py`; the sample test called the single most important test covers 16 of 74 columns, and the fuzz test that covers them all was not mentioned |
| `CONTRIBUTING.md` | Rule 6 required `defusedxml` for ElementTree — production code parses only with lxml; the first good-first contribution (the audit page) was done in `629e206` |
| `docs/README.md` | The index omitted the two newest registers |
| `architecture.md` | The read step's encoding order; phones "stripped to digits" (a number that isn't ten digits is left out); `queued` could not go to `error`; the reaper failed anything stuck (only what the queue has lost) |
| `operations.md` | Token-bucket rate limits; a `4ⁿ` backoff (`4ⁿ⁻¹`); the `delayed` key and five audit actions missing; "users re-run them from the dashboard" (a failed job cannot be re-run); in-flight conversions "re-claimed after restart" (not drained; back after 40 minutes) |
| `api-reference.md` | Twelve wrong claims, among them token buckets, an unnumbered login throttle, PATCH's 409 set, cancel "always 200", a two-stage 413 and `ENVIRONMENT=production` as the only production spelling |
| `configuration.md` | Redis reading the env file; the token reload; no `REDIS_URL` default; what a misordered timeout does (the web refuses to start); "every CLI write is confined" |
| `deployment.md` | The worker image's apt packages (none; digest-pinned); `redis:7`; `railway.toml` setting `ENVIRONMENT` (Railway does not take variables from it); CI catching a failed migration (not reliably) |
| `converters.md` | The legal-entity "Other" text; which multi-value fields keep one code; the length caps; aliases for training's required column; the training-client converter's size; the single-organization specifics; the mapping page "flagging" fabrication-risk columns |
| `csv-reference.md` | Nine fabrication-risk columns (12); 73 mapping entries (72); the 28-column training-client set (22); tiers that "fail the conversion" on the command line (only in the web app); a convert button that is "blocked" (never) |
| `cli.md` | `src.main` does no XSD check (every converter checks its own file); logs never rotate (10 MB, five kept); every write confined (not the fixer's or validator's single-file mode) |
| `troubleshooting.md`, `getting-started.md`, `SECURITY.md` | `node scripts/migrate.js` fails without `--env-file`; "the mapping page" showing the column counts (the preview does); templates "skip this step" (they apply only on **Apply**); "XSD failed after a successful conversion — expected" (rare since the final check); `conversion_deadlettered` "means attempts exhausted"; a stray comma "fails the preview"; `defusedxml` "for all ElementTree parsing"; a CSP row without `script-src 'unsafe-inline'` |
| `reviews/README.md` | Its "still open" list dated from `d0e71f0` and named fixed items |
| The registers | Fixes that never moved their marker: first pass 1.7 (event fields), 2.3, 3.7, 5.4 and part of 5.6; second pass 5.2, 5.3 and §2 of the third; UX §9.3. Two links broke when a heading's marker flipped |

### What was added

- **[`web-app-guide.md`](./web-app-guide.md)**, new: each screen in the step
  strip's order, and above all how to read a results page — what the counts
  mean for the filing, what an error or a warning means for its record, how the
  re-upload comparison matches issues, and what is kept for how long.
- `converters.md`: a table of all 14 issue categories with severity and cause;
  the defaults filed with no `fabricated_default`; the two filed with no report.
- `api-reference.md`: an errors section, every status each handler returns,
  response shapes, worker call timeouts, and route counts.
- `configuration.md`: how each value is parsed and what a bad one does, `PORT`,
  and the CLI's behaviour with a bad `SCHEMAS_DIR`.
- `deployment.md`: base-image updates, migration coverage, published ports.
- `operations.md`: `redis-cli` commands that tell a waiting job from a lost one,
  log prefixes, unlocking a throttled sign-in.
- `cli.md` and `csv-reference.md`: exit codes, file names, multi-value columns,
  accepted spellings.
- `testing.md`: the fuzz test, the missing-dependency measurements, and audit
  rows in the baseline.
- `troubleshooting.md`: entries for the messages added since the first audit —
  every "Conversion failed" reason, upload and start messages, encoding
  warnings, left-out records, Validate XML refusals, the progress page's own
  timeout. `SECURITY.md`: five known weaknesses it did not list.

### Code issues found during the audit

None were fixed: the audit was scoped to documentation. Each is documented as
the code behaves, and listed here so it is easy to pick up.

**What is filed can change without a word**

1. Two defaults are filed with no report: a counseling file without a
   `LocationCode` column gets `249003` (`CounselingConverter._warn_constant_defaults`
   records nothing), and a training client's revenue and profit are `0` even
   for a cell reading `n/a`.
2. The training-client `configured_defaults` warning names `LocationCode='249003'`
   even when the CSV's own `LocationCode` was filed.
3. On the command line a missing `Type of Session` column becomes `Telephone`
   without a warning; a blank `Currently In Business?` becomes `No` and a blank
   `Language(s) Used` `English` without one, in the web app too.
4. Training counts "Middle Eastern or North African" under both `MiddleEastern`
   and `NorthAfrican` (`classify_races`; third pass D.9).
5. A blank legal entity is filed as `Other` but reported only as
   `missing_required_field`, not `fabricated_default`.

**What the user is told**

6. `lib/job-failure.ts:describeJobFailure` does not recognise the worker's 504:
   a conversion past its deadline reads "The conversion service failed", with
   no advice to split the file. A 422 detail lacks its full stop
   ("…: Race You can re-upload…").
7. The download route's 410 says "Re-run the conversion"; a finished job cannot
   be re-run, only re-uploaded.
8. The progress page offers Cancel only while `converting`, though the API
   accepts `queued`, so a queued job can be neither cancelled nor deleted from
   the UI. Its Errors and Warnings counters read a summary written only at the
   end, so they show 0 throughout, and after five minutes of polling it shows
   "Conversion Timed Out" for a job that is still running.
9. The preview ignores a saved mapping, so after **Save Mapping & Continue** the
   Missing count is unchanged; and "Needs mapping" is the label for a job whose
   mapping was just saved.
10. **View** on the dashboard always opens the results page, which for a job
    never converted says "No validation issues found".
11. The training-client preview check for a missing `Class/Event ID` is an
    error, but the converter files the row with a warning, so "rows flagged with
    errors above will be skipped" is wrong for it.
12. Training and training-client read `LocationCode`, but the preview lists it
    under extra columns "ignored", and a mapping onto it is dropped.
13. "50MB" is hardcoded in 9 user-facing strings, and the re-upload page's 413
    message always says 50MB.
14. `/help`'s contents omit its Validate section, and its "XSD validation fails
    after a successful conversion" entry predates the final XSD check.
15. On the results page, **Show all** drops `?compare=`, and the comparison tabs
    drop `showAll`.
16. The worker's duplicate-header warning says "only the last occurrence was
    used"; the reader keeps the last *non-blank* value.
17. **Apply All Suggestions** keeps the alphabetically last of several
    suggestions for one column, not the best-scored.

**Deployment and operations**

18. The web has no healthcheck, in compose or its Dockerfile, so CI's
    `up --wait` cannot reliably catch a failed migration — and the first
    register's 2.3 `[FIXED]` note that both images gained one is wrong.
19. `apps/worker/railway.toml` declares `ENVIRONMENT` under `[deploy.variables]`,
    which Railway does not apply, so `/docs` is public unless the variable is set
    on the service; and its `startCommand`'s `$PORT` is not expanded, since
    Railway runs a Dockerfile service's start command without a shell.
20. The web's `node:20-alpine` is a floating tag with no digest: builds are not
    reproducible, and Dependabot, ignoring major and minor bumps, has nothing to
    propose for it.
21. The web reads numbers as `Number(x) || default`, unsigned: a negative
    `RETENTION_DAYS` purges every finished job's files at the next sweep, a
    negative `MAX_UPLOAD_BYTES` refuses every upload, a negative
    `JOB_MAX_ATTEMPTS` dead-letters every job at its first claim, and
    `RETENTION_DAYS=0` means 30.
22. On `SIGTERM` the conversion in flight is not drained — Next exits — and
    comes back only through the sweep, `VISIBILITY_TIMEOUT_MS` (40 minutes)
    after its claim.
23. The CLI pointed at a `SCHEMAS_DIR` without the XSDs writes the XML with no
    XSD check and exits 0.
24. The web image does not set `HOSTNAME`, so the server binds the container's
    address, not all interfaces; `ALLOWED_ORIGINS` entries are not trimmed; and
    `.dockerignore`'s `.env` patterns match only at the context root, so an
    `apps/web/.env` would be copied into the web image (from Docker's documented
    matching; not run).

**Repository settings**

- On 2026-10-17 the repository was public with **private vulnerability
  reporting off** and **issues off**, so `SECURITY.md`'s reporting link and the
  "open an issue" links in `troubleshooting.md` and `/help` led nowhere for
  anyone but a maintainer. It has no `LICENSE` either. These are settings, not
  code: a maintainer changes them on GitHub.

**API**

25. A body that is not valid multipart is answered 500 on `/api/upload` and 502
    on the XML tools, where 400 is due.
26. If the upload's audit entry fails after the file is saved, the route answers
    500 but keeps the job and the file; the user never learns the job id.
27. `GET /api/jobs/:jobId` returns absolute file paths and the full issue and
    diff arrays on every progress poll (second pass 4.8).
28. The worker's `/preview` echoes a `ValueError`'s text in its 400, and its
    OpenAPI schema describes the 422 body wrongly.

**Command line**

29. `run.py`'s `_pick_xsd` still looks only beside `run.py`, so the launcher's
    validation step is never offered on a clean checkout (first audit, item 1).
    It matters less now that every conversion checks its own file.
30. The fixer's and validator's single-file mode is not confined to the output
    base; a refused path ends in a traceback; a bad `--report-dir` is refused
    only after the XML is written.
31. The launcher cannot convert with an `SBA_OUTPUT_BASE` that does not contain
    its own folder: it always writes `logs/` beside `run.py`.
32. File names are stamped to the second, so runs in the same second share a
    log and overwrite each other's reports.
33. The fixer's directory mode loses its per-file log lines; its backups are
    made for refused and unchanged files too; its `--help` still says it fixes
    counseling files only.
34. The training converter records no `file_write` issue when the XML cannot be
    written; counseling does.

**Stale comments and dead code**

35. `rate-limit.ts` calls itself token-bucket-style (it is a fixed window);
    `signup/route.ts:getClientIdentifier` says it takes the first
    `X-Forwarded-For` token (it counts from the right); a comment in
    `durability-timeouts.ts` predates the reaper's queue check; the
    `column_requirements.get_requirement_sets` docstring gives an alias reason
    for training that does not hold.
36. Unused: `apps/worker/app/core/security.py:DATA_DIR`, `xml_validator`'s
    `enforce_data_dir`, the `ProgressEvent` type, `progressUpdatedAt`, and
    `defusedxml` as a runtime dependency. `Job.processedRows` is still never
    written (first audit, item 3).

### The first audit's code issues, now

| # | Issue | At `7b14f3b` |
|---|---|---|
| 1 | `run.py` never offers XSD validation | Open — item 29 above |
| 2 | The audit page's action list | Fixed in `629e206` |
| 3 | `Job.processedRows` never persisted | Open — item 36 above |
| 4 | Training aggregation | Event-level fields fixed in `2a794b0`; rows, not people, still counted — now a recorded decision |

### Not done, and why

- **No code fixes**, for the reason above. The list is the backlog, and
  [`reviews/README.md`](./reviews/README.md#what-is-genuinely-still-open)
  folds it into the registers' open items.
- **Railway's config-as-code may be ending.** A Railway bot reply on its forum
  says `railway.toml` files stop being read on 2026-12-01. That could not be
  confirmed against Railway's own announcements here. If it holds, both
  `railway.toml` files stop applying — the Dockerfile paths, the worker's start
  command, the healthcheck paths and the restart policies — and each must be set
  on its service instead. Check before then.
- **`ARCHITECTURE_REVIEW.md`** is still deliberately untouched.
- **No `LICENSE`, `CODEOWNERS` or `CLAUDE.md`** — still the owner's decision.
- The clone is shallow from 2026-06-24, so two commits the UX register cites
  (`2b7ab37`, `89d9355`) were confirmed through GitHub rather than locally.

### What this audit says about keeping it accurate

The rule that a behaviour change updates its guide in the same commit mostly
held: no guide described a mechanism that had been removed. What drifted was
what that rule does not reach — figures counted once and never again, register
markers for fixes made under another finding's name, and claims about one part
of the system written in a guide about another (`configuration.md` repeating
`cli.md`'s confinement rule). One new failure mode: a status marker in a heading
is part of its anchor, so flipping it broke two links. Run a link check when a
marker moves.

## First audit — 2026-09-16

**Commit audited:** `d0e71f0` · **Branch:** `claude/bold-brown-tv16bq`

### Method

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

### Before

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

### After

```
README.md                    Short front door, pointing into docs/
docs/
├── README.md                Index and conventions
├── getting-started.md       Web app and CLI, first conversion
├── architecture.md          Components, pipeline, job lifecycle, data flow
├── converters.md            The three converters, cleaning rules, fabricated defaults
├── csv-reference.md         Expected columns and requirement tiers per converter
├── cli.md                   run.py, src.main, fix_sba_xml, xml_validator, path confinement
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

### Documentation errors found and corrected

#### README

| Claim | Reality |
|---|---|
| "343 tests (pytest)" | 374 |
| Linked five root-level docs | All five moved under `docs/reviews/` |
| Mixed a 3-step CLI quick start with web app setup, project structure and a partial CLI reference | Split: the README is now a front door; the reference lives in `docs/` |

#### `.env.example`

| Claim | Reality |
|---|---|
| "After ARCH-4 the web↔worker bodies carry only paths (not file content)" | **Wrong.** `ConvertRequest.csv_content` and `ConvertResponse.xml_content` carry the file content; there is no shared volume between the services. Corrected in place. |

This one mattered: it is the comment explaining *why* `MAX_UPLOAD_BYTES` bounds
conversion memory, and its stated reason was the opposite of what the code does.

#### `CODEBASE_ANALYSIS.md`

Section 2 "Baseline health" carried figures from commit `bd390af`: 281 pytest,
86.79% coverage, 113 vitest across 18 files, and "148 commits since 2026-03".
Re-measured to 374 pytest, 88.8%, 173 vitest across 23 files, and 131 commits
first dated 2026-04-03. Both readings are now shown side by side so the trend
stays visible.

#### `TECHNICAL_DEBT.md`

| Item | Was | Now |
|---|---|---|
| #2 | Listed `pd.errors.ParserError` among the specific exception types caught | pandas was removed entirely; the type appears nowhere |
| #7 | "Added version range pins (e.g. `pandas>=2.2.0,<3`)" | Pins are **exact** (`lxml==6.1.3`), and pandas is not a dependency |
| #11 | "166 tests across 22 files" | 173 across 23 |

A verification date was added at the top.

#### `UX_REVIEW.md`

§7.8 "Nav doesn't collapse on mobile **[P1]**" carried no resolution marker,
while §1.1 recorded the same fix as `[RESOLVED]`. The nav does collapse —
`components/nav.tsx` hides the links on `md:hidden` behind an `aria-expanded`
toggle. Marked `[RESOLVED]`.

The rest of `UX_REVIEW.md` held up well; its inline markers are accurate.

#### `ARCHITECTURE_REVIEW.md` — deliberately not corrected

Its banner already states that it is a historical record, that ~20 of its 24
findings are fixed, and that every `file:line` citation is stale. Rewriting it to
match current code would destroy the only thing it is useful for. It is filed
under `reviews/` and flagged in the index.

#### Source comments

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

### Code issues found during the audit

These are **code** defects, not documentation defects. They are documented
accurately as-is rather than silently glossed, and listed here so they are easy
to pick up. None were fixed as part of this audit — it was scoped to
documentation.

#### 1. `run.py` never offers XSD validation

`_pick_xsd()` calls `find_files(script_dir, ".xsd")`, which looks for schemas
**beside `run.py`**. The bundled schemas live in `schemas/`, so on a clean
checkout the list is empty, step 4 is skipped silently, and the XML is written
unvalidated.

The README previously advertised this step as part of the guided flow, so a user
following it would never see the prompt and would not know why. Documented in
[cli.md](./cli.md#runpy--interactive-launcher) and
[troubleshooting.md](./troubleshooting.md) with workarounds.

**Fix:** search `schemas/` (and the script directory) in `_pick_xsd`.

#### 2. The audit page's action list is out of sync — fixed

> **Fixed:** the page labels and summarises every action written (including
> the D.8 additions), and the filter is built from the same label map, without
> `conversion_failed`. The label is still kept for entries written before
> dead-lettering replaced it.

`apps/web/src/app/audit/page.tsx` labels and offers a filter for
`conversion_failed`, which **no code writes**. Six actions that *are* written —
`conversion_timeout`, `conversion_deadlettered`, `files_purged`, `job_deleted`,
`xml_validated`, `xml_autofix` — have no label and render as `"—"`, and are
missing from the filter dropdown.

This is §5.6 in `CODEBASE_ANALYSIS.md`, still open. It is user-visible: a job
that timed out shows a dash instead of a reason.

**Fix:** derive the label map and the filter options from one exported constant
that the writers also use.

#### 3. `Job.processedRows` is never persisted

The column exists in `prisma/schema.prisma` with `@default(0)` and is never
written by any Prisma call. The value the progress page reads is computed per
request from the worker's Redis snapshot. Listed as dead in §5.3.

**Fix:** drop the column, or write it.

#### 4. Training aggregation findings are still open, with a stale mechanism

`CODEBASE_ANALYSIS.md` §1.7 lists two open aggregation problems and describes
them in pandas terms (`iloc[0]`, `pd.read_csv`). pandas is gone, but **both
problems survived the rewrite** in dict form:

- `'total': max(len(rows), 1)` — demographics count **rows, not distinct
  people**. An attendee listed twice is counted twice.
- `first_record = group_rows[0]` (`training_converter.py:142`) — event-level
  fields come from the first row; disagreeing rows are silently overruled.
  *(Fixed since by the second XSD validity pass: each field comes from the
  first row that has it, and disagreements are reported.)*

The findings are correct; only their mechanism description is out of date. Both
are documented in [converters.md](./converters.md#known-gaps).

### Not done, and why

- **No `LICENSE`.** The repository has none, and choosing one is the owner's
  decision, not a documentation task. Worth resolving: without a license, the
  default is "all rights reserved", which blocks reuse by other resource
  partners.
- **No `CODEOWNERS`** — needs a decision about who reviews what.
- **No `CLAUDE.md`** — [`CONTRIBUTING.md`](./CONTRIBUTING.md) now carries the
  conventions such a file would encode.
- **`ARCHITECTURE_REVIEW.md` was not rewritten**, for the reason above.
- **No code fixes**, including the four above. They are flagged, not patched.

### Keeping it accurate

The failure mode this documentation set is built to avoid is the one
`ARCHITECTURE_REVIEW.md` demonstrates: a document that still reads as current
while describing a codebase that no longer exists. Three habits prevent it, and
they are stated in [CONTRIBUTING.md](./CONTRIBUTING.md#documentation):

1. A behaviour change updates its guide **in the same commit**.
2. Fixing a tracked finding flips its marker **in the same commit**.
3. Counted figures carry the commit they were measured at, and re-measuring
   re-stamps them.
