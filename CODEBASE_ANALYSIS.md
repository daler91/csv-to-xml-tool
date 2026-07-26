# Codebase & Application Analysis

**Reflects commit:** `bd390af` (Merge PR #109) · **Date:** 2026-07-26
**Scope:** full review of `src/`, `apps/web`, `apps/worker`, tests, CI, and deployment config.
**Method:** every finding below was verified by *executing* the code — installing both toolchains,
running the full test suites, building the app, converting the shipped sample CSVs, and validating
the output against the bundled SBA schemas. Findings are not inferred from reading alone.

## How to use this document

Each finding carries a status marker. **When you fix something, flip its marker to `[FIXED]`
in the same commit** — the same convention `TECHNICAL_DEBT.md` and `UX_REVIEW.md` use.
`ARCHITECTURE_REVIEW.md` lacks these markers, which is why ~20 of its 24 findings are now stale
and actively misleading (see [5.7](#57-documentation-accuracy)). Please don't let this document
become the next one.

- **`[OPEN]`** — verified present at `bd390af`.
- **`[FIXED]`** — resolved; leave the entry in place with a commit reference.

---

## Contents

- [1. What this project is](#1-what-this-project-is)
- [2. Baseline health](#2-baseline-health)
- [3. What is well built](#3-what-is-well-built)
- [Tier 1 — Schema compliance (the core promise)](#tier-1--schema-compliance-the-core-promise)
- [Tier 2 — Deployment integrity](#tier-2--deployment-integrity)
- [Tier 3 — Security](#tier-3--security)
- [Tier 4 — Correctness & robustness](#tier-4--correctness--robustness)
- [Tier 5 — Architecture, quality, docs](#tier-5--architecture-quality-docs)
- [Recommended remediation sequence](#recommended-remediation-sequence)
- [Reproductions](#reproductions)

---

## 1. What this project is

Converts Salesforce CSV exports from SBA resource partners into XSD-compliant XML for the federal
SBA Nexus/EDMIS system. Three converters:

| Converter | Form | Root element | Schema |
|---|---|---|---|
| `counseling` | 641 Counseling | `<CounselingInformation>` | `SBA_NEXUS_Counseling-2-14.xsd` (4,738 lines) |
| `training` | 888 Mgmt Training | `<ManagementTrainingReport>` | `SBA_NEXUS_Training-2-25-2025.xsd` (2,269 lines) |
| `training-client` | 641, per-attendee | `<CounselingInformation>` | counseling XSD (reused) |

Two delivery forms share one core: a Python CLI (`run.py` + `src/`) and a web app
(Next.js `apps/web` + FastAPI `apps/worker`, which imports `src/` in-process — not via subprocess).
~20,200 LOC; 148 commits since 2026-03.

## 2. Baseline health

| Check | Result |
|---|---|
| `pytest` (Python) | **281 passed** |
| Coverage (exact CI command) | **86.79%** against a 70% gate — 17 pts of headroom |
| `vitest` (web) | **113 passed**, 18 files |
| `tsc --noEmit` | clean |
| `check-ui-classes.mjs` | clean, 78 files |
| `next build` | succeeds, 28 routes |
| `npm audit` (prod + dev) | **0 vulnerabilities** |
| `pip-audit` (both requirement files) | **0 vulnerabilities** |
| Committed secrets | none found |

The repo is green, dependencies are pinned and clean, and the CI gate passes with room to spare.
(Note: the CI comment claiming a "~71% baseline" is stale — actual is 86.79%, so the floor could be
raised.) **The significance of the findings below is that the test suite passes over every one of
them.**

## 3. What is well built

Worth stating plainly, because the findings list that follows is long.

- **The job pipeline is the strongest part of the codebase.** Every state transition is a guarded
  `updateMany` with an explicit status predicate and a `count === 0` check (`job-runner.ts:32,75`,
  `cancel/route.ts:53`, `start/route.ts:61`, `retention.ts:59`, `job-reaper.ts:41`). The `LREM`-gated
  queue sweep (`job-queue.ts:116-130`) is correct under competing consumers. Cancel semantics,
  dead-letter classification, and the deliberate row-before-files delete ordering are all commented
  with *why* and covered by tests.
- **XXE is properly closed everywhere** — `resolve_entities=False` on every lxml parse
  (`xml_validator.py:68`, `xsd_error_mapping.py:179`) and `defusedxml` for all ElementTree parsing.
- **Path confinement is real and tested** — `src/path_safety.py` and `lib/paths.ts:16-23` use
  `realpath` on both sides plus a `path.sep` suffix, defeating symlink and `/data-evil` escapes alike.
- **`src/xsd_error_mapping.py` is the standout module.** Run live, it turns
  `"Line 20: Element 'ZipCode'…"` into *"Row 1 (Contact 003XX000004TMM1): 'Mailing Zip/Postal Code'
  (CSV column 'Mailing Zip/Postal Code')…"*. That CSV traceability is the tool's most valuable asset.
- **Authorization is consistent — no IDOR was found.** Every user-owned resource route uses
  `findFirst({ where: { id, userId } })` and re-scopes mutations by `userId`.
- Accessibility is above average (role/aria discipline, shape-redundant status icons for WCAG 1.4.1).
- `Decimal`-based numeric cleaning, the `FABRICATED_DEFAULT` audit-trail concept, the
  `EXPORT_COUNTRY_CODES` drift-guard test, and the `check-ui-classes.mjs` design-drift lint are all
  thoughtful pieces of work.

---

## Tier 1 — Schema compliance (the core promise)

The tool's single job is producing XSD-valid federal XML. It does not reliably do that.

### 1.1 The shipped sample CSVs produce schema-invalid XML — `[FIXED]`

> Fixed by the Tier 1 remediation. All three samples now validate clean, guarded by
> `TestShippedSamplesValidate` in `tests/test_integration_xsd.py`. The original findings are
> preserved below for context.

Running all three samples — the ones linked from the landing page and the dashboard empty state —
through the CLI and validating against the bundled XSDs:

| Sample | Was | Now |
|---|---|---|
| `training-sample.csv` | PASS | **PASS** |
| `counseling-sample.csv` | FAIL — 13 errors | **PASS** |
| `training-client-sample.csv` | FAIL — 28 errors | **PASS** |

A first-time user following the README used to get an invalid file. Root causes were 1.2–1.5.

### 1.2 Multi-value Salesforce fields emit invalid XML — `[FIXED]`

> Fixed: `_cap_single_code` keeps the first code and records a `DOWNGRADED_VALUE` issue for the
> rest, so the loss is auditable rather than silent.

The README advertises: *"Correctly handles and splits multi-value fields from Salesforce
(e.g. `Race` or `Services Provided`)."* Tested directly:

```
Services Provided = "Business Plan;Customer Relations"
  → <CounselingProvided><Code>…</Code><Code>…</Code></CounselingProvided>
  → "Element 'Code': This element is not expected. Expected is ( Other )."
```

`CounselingSeeking/Code` and `CounselingProvided/Code` are **`maxOccurs=1`** in the XSD.
`Race` (unbounded) and `Media` (13) are fine — so the feature is correct for the first field the
README names and wrong for the second. `counseling_converter.py:323,468` loop unconditionally.
Not caught because `test_integration_xsd.py:242` passes only a single code.

### 1.3 Empty optional elements are emitted and fail their facets — `[FIXED]`

> Fixed: `emit_optional()` in `src/xml_utils.py` is now the single path for facet-constrained
> optional elements. `SurveyAgreement` is `minOccurs="1"`, so it falls back to `No` rather than
> being omitted. The `test_integration_xsd.py` fixture workaround noted below was removed, which
> is what lets the suite catch this class of bug.

`_build_address` emits `ZipCode` unconditionally; a blank cell yields `<ZipCode/>`, which fails
`\d{5}`. **The correct guard sits on the very next line** — `Zip4Code` is emitted only when matched,
with the comment *"only emit if we have it."*

Same class of bug: `State` (enum), `ClientSignature/Date` (`xs:date`), `Email`, `SurveyAgreement`,
`ConductingBusinessOnline`, `Rural_vs_Urban`, plus empty `<Language/>` and `<CounselingProvided/>`
containers that are missing a required child.

`_build_coded_section:450`, `Employee_Owned:266`, and `ExportCountries:342` all handle this
correctly — the pattern exists in the file, it just wasn't applied consistently.
`test_integration_xsd.py:159-162` **acknowledges one of these bugs in a comment and routes the
fixture around it** rather than asserting it.

### 1.4 Enum values pass through unnormalized — `[FIXED]`

> Fixed: `map_ethnicity_to_xsd`, `map_disability_to_xsd`, and `map_military_status_to_xsd` in
> `src/data_cleaning.py`; unmappable values are omitted with a warning rather than emitted.
> `FundingSource` had the same shape — the `VALID_FUNDING_SOURCES` list existed and was used by
> the training converter but not the counseling one; it is now shared at module level.

`_build_demographics` (`counseling_converter.py:179-190`) writes CSV text straight into
`Ethnicity`, `Disability`, and `MilitaryStatus`:

| CSV value (standard Salesforce export) | XSD requires |
|---|---|
| `Not Hispanic or Latino` | `Non Hispanic or Latino` |
| Veteran Status `No` | `No military service` |

`classify_ethnicity` (`data_cleaning.py:379`) **already handles this correctly** — its docstring
explicitly calls out the "Not Hispanic" trap — but it is only wired into the training converter's
*counting* logic, never into element emission. Meanwhile `Sex` on line 184 *is* normalized via
`map_gender_to_sex`. The inconsistency lives inside a single 12-line method.

### 1.5 `clean_phone_number` has no lower bound — `[FIXED]`

> Fixed: anything that can't be normalized to exactly 10 digits now returns `""` and the element
> is omitted.

`data_cleaning.py:202` truncates to 10 digits but never rejects shorter input, so `5550101`
(7 digits) is emitted and fails the `[0-9]{10}` pattern. The docstring claims it "normalizes to
10 digits."

### 1.6 Single-tenant values are stamped into every filing — `[FIXED]` by decision — **most severe**

> **Resolved as a deliberate scope decision, not a code change: this is a single-organization
> tool, so the constants are correct for it and stay in `config.py`.** What changed is that they
> are no longer invisible — `_warn_constant_defaults()` records one file-level
> `FABRICATED_DEFAULT` warning per conversion naming every value emitted from configuration
> (location code, partner code, sessions, hours, fees, language), and per-event warnings now fire
> when a blank cell falls back to the configured location, event title, or start date. The
> training path previously emitted all of these with no warning at all, unlike the counseling path.
>
> **This decision does not survive the tool becoming multi-tenant.** If a second organization ever
> uses the same deployment, the analysis below applies again in full and tenant identity has to
> move into per-user settings.

`src/config.py` hardcodes one organization's identity:

```python
DEFAULT_LOCATION_CODE = "249003"                           # :45
DEFAULT_TRAINING_PARTNER_CODE = "Women's Business Center"  # :387
DEFAULT_LOCATION = {"city": "Des Moines", "state": "Iowa", "zip": "50312"}  # :392
DEFAULT_START_DATE = "2023-12-12"                          # :389
```

Verified in generated output: **every** XML file carries `<LocationCode>249003</LocationCode>`, and
training files carry `<City>Des Moines</City>` and `<Code>Women's Business Center</Code>`.
`training_converter.py:94` emits `LocationCode` with **no CSV override at all** — counseling at
least allows `row.get('LocationCode', …)`. Training defaults are emitted with **no
`FABRICATED_DEFAULT` warning**, unlike the counseling path.

In a multi-tenant web app with open signup, this means every other organization's federal filing is
silently stamped with this organization's location code and partner code, and any unparseable date
becomes 2023-12-12.

### 1.7 Silent data loss in the training converter — `[FIXED]` (blank-ID + silent-success); `[OPEN]` (aggregation)

> Fixed: `validate_training_record` now uses `is_empty()`, so NaN event IDs are rejected and
> recorded instead of being dropped by `groupby()`; `_read_and_validate_csv` raises `EmptyCSVError`
> instead of returning `(None, None)`, so a conversion can no longer "succeed" with no output file.
> **Still open:** demographics counting rows rather than distinct people, and event-level fields
> being taken from an arbitrary `iloc[0]`.

- **Blank event IDs vanish with zero warnings.** `pd.read_csv(dtype=str)` makes blank cells `NaN`
  (a float), and `validate_training_record` tests `if not record_id:` — but `not float('nan')` is
  `False`, so the row passes validation. `groupby(...)` then drops `NaN` keys. No issue is recorded
  anywhere. The preview path uses `is_empty()`, which *does* catch this — so the UI promises an
  error the converter never records.
- **No output file, exit code 0.** A missing event-ID column or zero valid rows makes `convert`
  return at `training_converter.py:145` without writing anything, while `main.py:115` logs
  "Conversion process completed."
- **Demographics count rows, not people** (`:255`), and event-level fields are taken from an
  arbitrary `iloc[0]` (`:80`), silently discarding disagreeing rows.

---

## Tier 2 — Deployment integrity

### 2.1 `SCHEMAS_DIR` default is wrong in *every* layout — `[FIXED]`

> **Correction to this finding as originally written.** It claimed "no single `..` count fixes both
> layouts — this needs a real anchor, not an off-by-one correction." That was wrong: it missed that
> **`apps/worker/schemas` is a git-tracked symlink** (mode `120000`) to `../../schemas`, which makes
> **two** `..` resolve correctly in both layouts (repo → symlink → `<root>/schemas`; Docker →
> `/app/schemas`). It was a plain off-by-one — 3 `..` where 2 was intended — and the symlink exists
> precisely to make the 2-dot form work. The *impact* below was accurate; only the diagnosis of the
> fix was wrong.
>
> Fixed in `apps/worker/app/core/paths.py`: `default_schemas_dir()` tries the 2-`..` path then falls
> back to walking up for a `schemas/` directory holding both XSDs (a Windows checkout without
> symlink support turns the symlink into a plain text file). `XSD_MAP` is deduplicated there too.
> `SCHEMAS_DIR` stays a module-level name in each consumer — 16 tests monkeypatch it, and `fix.py`'s
> re-import is a separate binding patched independently. A `lifespan` hook now refuses to start when
> the schemas are absent, `/health` reports a `schemas` check, and
> `tests/test_worker_schema_paths.py` covers the default **without** monkeypatching.

`conversion_service.py:37` and `validate.py:18` both built the default with three `..`:

| Layout | Resolved to | Existed |
|---|---|---|
| Repo | `apps/schemas` | ✗ |
| Docker (`/app/app/services`) | `/schemas` | ✗ |

It works today only because `docker-compose.yml:27` sets the variable explicitly.
`apps/worker/railway.toml` sets **no environment variables at all**, and `SCHEMAS_DIR` is absent
from both `.env.example` files. On Railway, unless someone set it by hand in the dashboard,
`/convert` silently skips XSD validation and returns `xsd_valid=false` **with an empty error list** —
i.e. "your federal filing is invalid, and here are no reasons why."

**The test suite masks this.** Every relevant test monkeypatches `SCHEMAS_DIR`. The one that does
not (`test_worker_content_routes.py:293`) asserts `is_valid is False` and **passes for the wrong
reason** — not because the document violates the schema, but because the XSD file could not be
opened.

### 2.2 The documented local-dev path cannot work — `[FIXED]`

> Fixed: `docker-compose.yml` now builds web with `context: .` + `dockerfile: apps/web/Dockerfile`,
> matching the worker service and Railway. A `docker-build` CI job builds both images and runs
> `docker compose up -d --wait`, so this cannot silently regress again.

`docker-compose.yml:3` sets `build: ./apps/web`, but `apps/web/Dockerfile:3,9` uses
`COPY apps/web/…`, which is repo-root-relative. Under the compose context those resolve to
`apps/web/apps/web/…`, which does not exist. The README's `docker compose up` fails at the first
`COPY`. It works on Railway only because `apps/web/railway.toml` builds from the repo root.
CI never builds either image, which is why this went unnoticed.

### 2.3 Other deployment gaps — `[FIXED]` (most); `[OPEN]` (Redis persistence)

> Fixed: the `curl` healthcheck is now a stdlib Python probe that reads the body (and both images
> gained a `HEALTHCHECK`); web's `depends_on` for worker is now `service_healthy`; `migrate.js` exits
> non-zero and the Dockerfile CMD uses `&&`, so a failed migration can no longer boot a serving app;
> the dead `startCommand` is gone from `apps/web/railway.toml`, leaving the Dockerfile CMD as the
> single source of truth; both images run as a non-root user with `DATA_DIR` owned by that user; and
> a repo-root `.dockerignore` now exists.
> **Still open:** Redis has no persistence volume, so a restart drops queued jobs until the reaper
> catches them.

- The worker healthcheck shells out to `curl`, which is **not installed in `python:3.12-slim`** —
  the check is permanently red.
- `scripts/migrate.js:116` catches migration failure without exiting non-zero, and
  `apps/web/Dockerfile:24` uses `;` rather than `&&` → **the app starts on a broken schema**.
- `apps/web/railway.toml:6` runs `prisma db push`, bypassing `migrate.js` and contradicting that
  script's own header comment; the runtime image contains neither `prisma/schema.prisma` nor the
  Prisma CLI.
- Both images run as **root**, with no `HEALTHCHECK` instruction, no `.dockerignore`, and
  `npm install` rather than `npm ci`.
- Redis has no persistence volume, so a restart drops every queued job until the 1-hour reaper.
- `/health` returns HTTP 200 even when degraded, so the platform healthcheck only proves the
  process is up.

---

## Tier 3 — Security

Nothing here is a live exploit against an authenticated boundary — the ownership model holds — but
several are availability- or DoS-grade.

| # | Finding | Location | Status |
|---|---|---|---|
| 3.1 | **`/api/audit` unbounded pagination.** No clamping or finiteness check. `?pageSize=1e8` → `take: 1e8`; `?pageSize=abc` → `NaN` → 500; `?page=0` → negative `skip` → 500. The `format=csv` branch **ignores pagination entirely** and materializes every row into one string. No rate limit, and **no tests on this route**. | `api/audit/route.ts:9-10,30` | `[FIXED]` |
| 3.2 | **Redis client stops reconnecting permanently.** `retryStrategy` returns `null` after 3 attempts — in ioredis that means *never reconnect*. Rate limiting then fails open forever and every `enqueueJob` throws until the container restarts. Compounding: the shared client has **no `'error'` listener**, while `job-queue.ts:55` adds one with a comment explaining that its absence *"would crash the process."* | `lib/redis.ts:41-44,47-55` | `[FIXED]` |
| 3.3 | **Zero security headers.** `next.config.ts` is 7 lines. No CSP, HSTS, `X-Frame-Options`, `nosniff`, or `Referrer-Policy`; `poweredByHeader` is not disabled. **The app is fully clickjackable.** | `next.config.ts` | `[FIXED]` |
| 3.4 | **No rate limit or lockout on login.** Signup (5/min) and upload (10/min) are limited, but `/api/auth/callback/credentials` is not in the middleware matcher and is unlimited. bcrypt cost 12 is the only brake on online guessing. | `middleware.ts:3-16` | `[FIXED]` |
| 3.5 | **Stored XSS in the HTML validation report.** `_generate_issues_table` interpolates `record_id`, `field_name`, and `message` — all carrying raw CSV content — into HTML **unescaped**. A CSV cell containing `<script>` lands executable in `reports/*.html`. | `validation_report.py:260-268` | `[FIXED]` |
| 3.6 | **Non-ASCII `Authorization` header → 500, not 401.** Verified live: `secrets.compare_digest` raises on non-ASCII `str`, so `Bearer café` produces an unhandled `UnicodeEncodeError`. | `worker/app/core/auth.py:34` | `[FIXED]` |
| 3.7 | **Body-size cap is bypassable.** Only `Content-Length` is inspected, so a chunked request skips the guard entirely and Starlette buffers the whole body. The cap is 100 MB — double the 50 MB upload limit it backstops. Worker peak memory is ~8-10× input, the thread pool is uncapped, and there is no worker-side rate limiting. | `worker/app/main.py:40-51` | `[FIXED]` |
| 3.8 | **Unauthenticated API disclosure.** Verified live: the catch-all 404 returns the **complete route table**, and `/docs` + `/openapi.json` are public (HTTP 200). | `worker/app/main.py:74-84` | `[FIXED]` |
| 3.9 | **8 authenticated handlers return 500 instead of 401** (`jobs` list; 2 of 3 in `jobs/[jobId]`; `cancel`, `start`, `download`, `preview`, `audit`). `upload-errors.ts:22` maps 401 → "session expired", a message the app can essentially never show. | 7 route files | `[FIXED]` |
| 3.10 | No CSRF token or Origin check on state-changing routes — safe today only via NextAuth's default `SameSite=Lax`, an implicit dependency pinned nowhere. Also `trustHost: true` with no allowlist, and a 30-day non-revocable JWT with no `maxAge`. | `lib/auth.ts:8,36` | `[OPEN]` |
| 3.11 | **Worker auth fails open**: `worker-client.ts:20` omits the header entirely when `WORKER_AUTH_TOKEN` is empty, with no startup assertion. Worker responses are `res.json() as T` with no validation before being written to disk and into JSONB. | `lib/worker-client.ts:20,32` | `[OPEN]` |
| 3.12 | CSV formula injection is unguarded in the audit export and `save_issues_to_csv`. `upload/route.ts:117` stores the **raw** filename in audit metadata while the job row stores the sanitized one. | `api/audit/route.ts:47` | `[FIXED]` |
| 3.13 | `job_id` reaches Redis keys and the log format unsanitized (log forging, key-namespace pollution). `core/security.py:9` contains a `sanitize_id()` written for exactly this — **it is never called anywhere**. | `worker/app/routes/convert.py:49` | `[FIXED]` |

> **Note on 3.3 — `script-src 'unsafe-inline'`.** The CSP added for this finding keeps
> `'unsafe-inline'` in `script-src`, and SonarCloud flags it (correctly — it defeats most of CSP's
> XSS protection). It is load-bearing: Next's App Router emits inline `self.__next_f` bootstrap
> scripts, so removing it without a per-request nonce breaks every page. The proper fix is a
> nonce-based CSP generated in `middleware.ts`, which requires widening the middleware matcher to
> all routes and moving route protection into an `authorized` callback — i.e. it lands on the auth
> boundary. Deferred pending that decision; see the discussion on PR #112.

---

## Tier 4 — Correctness & robustness

Status: `[FIXED]` except where noted.

> **Fixed in the Tier 4 pass:** the `defusedxml` `SubElement` crash (it exports the parsing API but
> deliberately not the tree-building API, so `--add-missing` raised `AttributeError` that escaped
> the caller's `except`); the Windows-broken `startswith(os.sep)` check, now `os.path.isabs`; the
> `/data-evil` prefix bypass, now a shared `_is_within` with a separator suffix; the `(Meeting)`
> fallbacks via `_first_present` (`row.get(a, row.get(b))` is not a fallback — the inner get is a
> *default argument*, consulted only when `a` is absent entirely); `Client Signature(On File)` now
> via `is_affirmative`; ragged rows fixed at the shared `normalize_row_keys` choke point so preview
> and diff benefit too; the training demographics element order, now pinned by a test that derives
> the expected order **from the schema**; and the web-side purged-file (410) and wedged-job
> (enqueue rollback) cases, plus the unguarded `totalRows` write that reset the reaper's clock.
>
> **Still open:** SIGTERM does not drain in-flight jobs, and the 60s sweep interval is never cleared.

- **`--add-missing` crashes.** `xml_validator.py:128` calls `ET.SubElement`, but line 7 imports
  `defusedxml.ElementTree`, which **does not export `SubElement`** (verified). The resulting
  `AttributeError` escapes the `except (OSError, ET.ParseError)` at `:170`. No test passes
  `add_missing=True`.
- **XSD validation is broken on Windows** — the platform `run.bat`/`setup.bat` exist to serve.
  `xml_validator.py:45` checks `startswith(os.sep)`; a realpath'd `C:\…` fails that test, so
  `validate_against_xsd` returns *"Invalid XSD file path"* for every call. Separately, line 43 omits
  the `os.sep` suffix, so `/data-evil/x.xml` passes as being inside `/data`.
- **`(Meeting)` fallbacks never fire for blank cells** (`counseling_converter.py:414,422,423`) — the
  inner `row.get` is a *default argument*, evaluated only when the outer key is absent, so a present
  but empty `(Meeting)` column wins and the base column is never consulted.
- **`Client Signature(On File)` only accepts `'1'`** (`:167`) — a literal `Yes` is silently recorded
  as `No` in a federal filing. `is_affirmative` exists and is used elsewhere in the same file.
- **Ragged CSV rows drop whole records** — `DictReader` yields `None` for missing fields, and ~25
  `.strip()` calls raise `AttributeError`, caught as an opaque `PROCESSING_ERROR`.
- **Uncaught `ValueError` from the path guard** produces a raw traceback on a bad `--output` or
  `--log-dir` (`main.py:76,94`, `run.py:109`); launched via `run.bat`, the console window simply
  closes. `SBA_OUTPUT_BASE` — the documented escape hatch named in the error message — appears in no
  `.env.example` and is absent from the README.
- **Training XSD element order depends on dict insertion order** (`training_converter.py:348`)
  matching an `xs:sequence`. Reordering `DEMOGRAPHIC_KEYWORDS` — an edit that looks purely cosmetic —
  silently produces invalid XML. No test guards it.
- **Purged files produce opaque errors** — `start` and `preview` don't check `filesPurgedAt` and end
  up calling `stat("")` → 500; `download` returns a flat 404 where the schema comment promises an
  "expired" response.
- `POST /start` commits `status=queued` *before* `enqueueJob`. On Redis failure the user gets a 500,
  a retry returns 409, and the job is wedged for the full 1-hour reaper deadline.
- `preview/route.ts:54` writes `totalRows` with no status guard, bumping `updatedAt` on a converting
  job and silently resetting the reaper clock that `job-reaper.ts:15-17` depends on.
- SIGTERM does not drain in-flight jobs, and the 60s sweep interval is never cleared.

---

## Tier 5 — Architecture, quality, docs

Status: mixed — see each item.

> **Fixed in the Tier 5 pass:** 5.3 dead code (`check_element_order` with its two contradictory
> implementations, the `analyze_*_csv` pair written for a `--analyze-only` flag that doesn't exist,
> `ValidationTracker.failed_records`, the worker's never-called `sanitize_id`/`sanitize_filename`,
> `components/ui/card.tsx`, the unused `@auth/prisma-adapter`, and the stale `patch_tests.diff`);
> 5.4 (`from __future__` moved below the docstrings in all five modules, so `__doc__` is populated
> again; the import-time global logger that cleared handlers is gone; the fiscal-year cutoff is now
> computed per call instead of frozen at import, which mattered for a long-lived worker crossing
> October 1); and 5.7 docs — `ARCHITECTURE_REVIEW.md` now carries per-finding status markers and a
> banner stating plainly that it is a historical record with stale citations, `TECHNICAL_DEBT.md`
> #3/#11/#19 are refreshed, and the README covers the third converter, the real module list and
> `SBA_OUTPUT_BASE`.
>
> **Still open:** 5.1 (the inverted converter abstraction and the two CSV engines) and 5.2 (no
> column mapping in the counseling converter) — both are large refactors of code that now has real
> test coverage but no strong behavioural contract, and are worth scoping deliberately rather than
> doing opportunistically. 5.5 is partial: ruff is in CI, but there is still no formatter, no type
> checker and no ESLint. 5.6 (web duplication, `results/page.tsx` at 685 LOC, the dual
> schema/migrate.js source of truth, the stale audit action labels) is untouched.

### 5.1 The converter abstraction is inverted

`BaseConverter` shares 99 lines of progress plumbing while two 400–600 line converters duplicate the
entire read → validate → write pipeline **on two different CSV engines** (`csv.DictReader` vs
pandas). pandas is pulled in solely for one `groupby`. `TrainingClientConverter` demonstrates the
right pattern: 102 lines reusing ~470 via four explicit hooks.

### 5.2 No column mapping in the counseling converter

~90 hardcoded header string literals inside `row.get(...)` calls. Three mutually incompatible
mapping styles across the three converters.

### 5.3 Dead code

`check_element_order` (58 LOC, no callers — and containing *two contradictory implementations in one
body* with an unreachable `except`); `analyze_counseling_csv` / `analyze_training_csv` (written for
an `--analyze-only` flag that does not exist); `ValidationTracker.failed_records` (never assigned);
worker `sanitize_id` / `sanitize_filename` (never called — see 3.13); `Job.processedRows` (never
written); `components/ui/card.tsx`; the `@auth/prisma-adapter` dependency; and `patch_tests.diff`,
a stale already-applied patch committed at the repo root.

### 5.4 Python packaging and idiom

`from __future__ import annotations` sits **before** the module docstring in 5 modules, so
`__doc__` is `None` and `help()` shows nothing. Import-time side effects: `logging_util.py:129`
instantiates a global logger that clears handlers, and `config.py:69` freezes the fiscal year at
import time.

### 5.5 Tooling gaps

No Python linter, formatter, or type checker (no ruff/black/mypy, no `pyproject.toml`) and **no
ESLint** — `npm run lint` is `tsc --noEmit` plus a class-name script. CI builds neither Docker image.

### 5.6 Web duplication

`results/page.tsx` is 685 LOC holding a page plus 7 components, and re-declares `ValidationIssue`
and `CleaningDiffEntry` verbatim from `src/types/index.ts`. `DATA_DIR` is redefined 5×; "50MB" is
hardcoded in 9 user-facing strings; job-status sets are re-declared 7×. The Prisma schema and
`scripts/migrate.js` are two independent sources of truth for the DDL. `audit/page.tsx` labels a
`conversion_failed` action **no code writes**, while 4+ actions that *are* written fall through to
`"—"` and are missing from the filter dropdown.

### 5.7 Documentation accuracy

- **README** omits the `training-client` converter entirely, lists 4 of 20 test files, documents a
  `docker compose up` that cannot work (2.2), and never mentions `SBA_OUTPUT_BASE`.
- **`ARCHITECTURE_REVIEW.md` is the main hazard.** Roughly **20 of its 24 findings are already
  fixed**, it carries no per-finding status markers, and its line citations are uniformly stale —
  so it reads as a current risk register while describing a codebase that no longer exists. Its
  "Verification (how to reproduce)" section is entirely obsolete.
- **`TECHNICAL_DEBT.md`** is stale on #3 (CSV column pre-checks) and #11 (no web tests) — both since
  fixed. Items #5, #16, #18, and #19 remain genuinely open.
- **`UX_REVIEW.md`** is well maintained (inline `[RESOLVED]` markers); only §6.7, §9.3, and §10.3
  appear still open.
- No `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODEOWNERS`, or `CLAUDE.md`.

---

## Recommended remediation sequence

Ordered by risk-to-mission per unit of effort. Each phase is independently shippable.

### Phase 1 — Make the output trustworthy (Tier 1)

1. Add a shared `emit_optional(parent, name, value)` helper to `src/xml_utils.py` and route every
   facet-constrained optional element through it, reusing the existing guard style from
   `_build_coded_section:450` and `ExportCountries:342`.
2. Wire `classify_ethnicity` into `_build_demographics`; add `classify_disability` and
   `classify_military_status` mappers alongside it; add a lower-bound check to `clean_phone_number`.
3. Cap `CounselingSeeking/Code` and `CounselingProvided/Code` at one code, recording a
   `DOWNGRADED_VALUE` issue for dropped values so the loss stays auditable.
4. Move tenant identity (`LocationCode`, partner code, default location) out of `config.py` into
   per-user settings surfaced in the web UI plus a CLI flag; emit `FABRICATED_DEFAULT` warnings on
   every training default, matching the counseling path.
5. Fix the training `NaN` event-ID hole (use `is_empty()` in `validate_training_record`) and raise
   `EmptyCSVError` instead of returning silently.
6. **Gate: the three shipped sample CSVs must validate clean.** Add this as an integration test — it
   is the single regression test this repo most needs, and it would have caught all of the above.

### Phase 2 — Deployment integrity (Tier 2)

7. Anchor `SCHEMAS_DIR` properly (walk up for `schemas/`, or fail fast at startup when unset or
   missing); add it to both `.env.example` files and to `railway.toml`; add a test that does **not**
   monkeypatch it.
8. Fix the compose build context; add `docker compose build` to CI so it stays fixed.
9. Replace `curl` in the healthcheck with a Python one-liner; make `migrate.js` exit non-zero;
   change the Dockerfile `;` to `&&`; reconcile `railway.toml` with the Dockerfile CMD; add `USER`
   to both images.

### Phase 3 — Security (Tier 3)

10. Clamp `/api/audit` pagination, cap the CSV export, and add tests.
11. Fix the Redis `retryStrategy` and attach an `'error'` listener to the shared client.
12. Add a `headers()` block to `next.config.ts` and set `poweredByHeader: false`.
13. Rate-limit login; escape the HTML report; fix the worker auth 500; close the chunked-body
    bypass; disable `/docs` and the route-table dump in production; call the existing `sanitize_id`.
14. Extract a `withAuth` wrapper so `Unauthorized` → 401 is handled in one place.

### Phase 4 — Correctness & hygiene (Tiers 4–5)

15. Fix the `defusedxml` `SubElement` crash, the Windows path check, the `(Meeting)` fallbacks,
    `OnFile` via `is_affirmative`, and `None`-safe row access.
16. Delete the dead code listed in 5.3; move `from __future__` below the docstrings.
17. Add ruff + mypy to CI; add ESLint.
18. Rewrite `ARCHITECTURE_REVIEW.md` with per-finding status markers; refresh `TECHNICAL_DEBT.md`
    #3 and #11; update the README (third converter, test list, `SBA_OUTPUT_BASE`, docker instructions).

---

## Reproductions

```bash
# Baseline — all of these currently pass
python -m pytest tests/ --cov=src --cov=apps/worker/app --cov-fail-under=70
cd apps/web && npx vitest run && npx tsc --noEmit && npx next build
```

```bash
# Tier 1 gate — currently 2 of 3 FAIL
export SBA_OUTPUT_BASE=/tmp/sba-out && mkdir -p "$SBA_OUTPUT_BASE"
for t in counseling training training-client; do
  python -m src.main convert "$t" --input "apps/web/public/samples/$t-sample.csv" \
    --output "$SBA_OUTPUT_BASE/$t.xml" --report-dir "$SBA_OUTPUT_BASE/r" --log-dir "$SBA_OUTPUT_BASE/l"
done
python - <<'EOF'
from lxml import etree
for name, xsd in [("counseling", "SBA_NEXUS_Counseling-2-14"),
                  ("training-client", "SBA_NEXUS_Counseling-2-14"),
                  ("training", "SBA_NEXUS_Training-2-25-2025")]:
    schema = etree.XMLSchema(etree.parse(f"schemas/{xsd}.xsd"))
    ok = schema.validate(etree.parse(f"/tmp/sba-out/{name}.xml"))
    print("PASS " if ok else "FAIL ", name, len(list(schema.error_log)), "errors")
EOF
```

```bash
# 1.2 — multi-value regression. Set Services Provided to "Business Plan;Customer Relations"
# on a counseling row, convert, and validate: the output must be schema-valid.

# 2.1 — SCHEMAS_DIR must fail loudly when unset, not silently skip validation
env -u SCHEMAS_DIR python -c \
  "from apps.worker.app.services.conversion_service import SCHEMAS_DIR; \
   import os; assert os.path.isdir(SCHEMAS_DIR), SCHEMAS_DIR"

# 2.2 — must succeed (currently fails at the first COPY)
docker compose build
```

**Files most implicated:** `src/converters/counseling_converter.py`, `src/data_cleaning.py`,
`src/config.py`, `src/converters/training_converter.py`,
`apps/worker/app/services/conversion_service.py`, `apps/worker/app/routes/validate.py`,
`apps/worker/app/main.py`, `apps/web/src/lib/redis.ts`, `apps/web/src/app/api/audit/route.ts`,
`apps/web/next.config.ts`, `docker-compose.yml`, `apps/web/scripts/migrate.js`,
`tests/test_integration_xsd.py`.
