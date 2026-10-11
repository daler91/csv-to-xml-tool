# Codebase & Application Analysis — third pass

**Reflects commit:** `5d865e4` (Merge PR #129) · **Date:** 2026-10-10
**Scope:** `src/`, `apps/worker`, `apps/web`, tests, CI, dependencies.
**Method:** same as the first two passes — both toolchains installed (Python 3.12 venv from the
hash-locked requirements, `npm ci` in `apps/web`), both suites run, the app built, and findings
reproduced by executing the code: crafted CSVs through each converter validated against the bundled
XSDs with lxml, the worker driven as an ASGI app against fakeredis and a stalled TCP listener, and
web state transitions exercised in vitest. Anything that could not be reproduced or traced to a
concrete request was dropped.

This document does not repeat [`CODEBASE_ANALYSIS.md`](./CODEBASE_ANALYSIS.md),
[`CODEBASE_ANALYSIS_2.md`](./CODEBASE_ANALYSIS_2.md) or [`TECHNICAL_DEBT.md`](./TECHNICAL_DEBT.md).
Section 2 re-verifies the second pass's open items; everything from section 3 on is **new** at
`5d865e4`.

Markers: **`[OPEN]`** verified present at `5d865e4`; **`[FIXED]`** resolved (keep the entry, add the
commit). **Flip the marker in the same commit as the fix.**

---

## Contents

- [1. Baseline health](#1-baseline-health)
- [2. Second-pass Tier 1–2 items: all still open](#2-second-pass-tier-12-items-all-still-open)
- [Tier A — Output correctness (core)](#tier-a--output-correctness-core)
- [Tier B — Job pipeline integrity (web)](#tier-b--job-pipeline-integrity-web)
- [Tier C — Resource limits & availability](#tier-c--resource-limits--availability)
- [Tier D — Smaller items](#tier-d--smaller-items)
- [What is in good shape](#what-is-in-good-shape)
- [Recommended sequence](#recommended-sequence)

---

## 1. Baseline health

| Check | At `482d235` (2nd pass) | At `5d865e4` |
|---|---|---|
| `pytest` | 374 passed | **388 passed** |
| Coverage (CI command) | 88.8% | **89.0%** (gate 70%) |
| `ruff check .` | clean | clean |
| `pip-audit` | — | no known vulnerabilities |
| `vitest` | 173 passed, 23 files | **253 passed, 29 files** |
| `npm run lint` | clean | clean, 97 files |
| `next build` | succeeds | succeeds (same Turbopack tracing warning) |
| **`npm audit --audit-level=high`** | clean | **FAILS — 2 high** (fixed since; see 1.1) |

### 1.1 CI's npm audit gate is red on a clean install — `[FIXED]` — HIGH (process)

`npm audit` reports two high-severity advisories, both fixable with `npm audit fix`:

- `sharp <0.35.5` — GHSA-wq5f-xc86-pv6w (librsvg CVE). The `overrides.next.sharp` pin in
  `apps/web/package.json` is `^0.35.4`; raise it to `^0.35.5`.
- `source-map-js 1.0.0–1.2.1` — GHSA-68fv-2mgg-jv7q, via `postcss` and `@tailwindcss/node`.

`web-lint` in `.github/workflows/ci.yml` runs `npm audit --audit-level=high`, so the next push on any
branch fails until the lockfile is refreshed. Runtime reachability was not assessed; the gate fails
regardless.

**Fixed:** the `next.sharp` override is now `^0.35.5`, and a top-level `source-map-js: ^1.2.2` override
was added — `npm audit fix` would not lift it on its own even though `postcss` and
`@tailwindcss/node` both declare `^1.2.1`. `npm audit --audit-level=high` reports 0 vulnerabilities.

---

## 2. Second-pass Tier 1–2 items: all still open

Every `[OPEN]` item in `CODEBASE_ANALYSIS_2.md` Tiers 1 and 2 was re-reproduced at `5d865e4`.
The markers there are accurate; nothing has been remediated since.

| Item | Still reproduces with |
|---|---|
| 1.1 Length facets | `Middle Name=Marie`; 41-char Last; 81-char City/Street/Company/Counselor; 21-char Contact ID; 256-char TrainingTitle |
| 1.2 `LocationCode` | blank or `abc` → invalid |
| 1.3 Yes/No case | `yes`/`Y`/`TRUE` → invalid for 3 elements; silently `No` for in-business, exporting, reportable impact; `Verified=yes` → `Undetermined` |
| 1.4 Unmapped enums | `Caucasian`, `Facebook`, `Bakery`, `USMC`, `llc`, `english`, `Ontario`, `jane@localhost`, FIPS `1910`, employees `12.5` |
| 1.5 Caucasian counted 3× | 2 attendees → `Asian=2`, `White=2`, `Underserved=2` |
| 1.6 `Non-veteran` | counseling → `Veteran` + spurious BranchOfService error; training counts it in `<Veterans>` |
| 2.1–2.5 Fabrications | `Contact=0.5`, Part 3 employees `0`, Part 3 exporting `No` vs intake `Yes`, `Other` → `Business Operations/Management`, `ReportableImpact` overriding `Verified` — none audited |
| 2.6 Phone dropped | `555-0101` → no PhonePart1, no issue, empty diff |
| 2.7 Training defaults | blank topic → `Technology`, `Workshop` → `In-person`, `Address` used as City — no issue. (Line refs in the 2nd pass are stale; behaviour is not.) |
| 2.8 Diff coverage | `generate_cleaning_diff` returns `[]` for a row whose ethnicity, veteran status, export country and phone were all changed or dropped |

Tier 5 (test blind spots 5.1, sample gate 5.2, doc claims 5.3) is likewise unchanged. **This is the
most important conclusion of this pass:** the remediation since the second pass went to the web and
worker; the federal-filing correctness backlog has not moved.

---

## Tier A — Output correctness (core)

### A.1 `CounselorNotes` truncation can destroy the note, unaudited — `[FIXED]` — HIGH

> **Fixed:** a sentence or word boundary only counts in the last fifth of the 1,000-character
> window, and the cut is recorded as `TRUNCATED_VALUE` on `Comments`.

`src/data_cleaning.py:613-627`. `truncate_counselor_notes` cuts at the *last* `.`/`!`/`?`/newline
anywhere in the first 1000 chars, however early. No `TRUNCATED_VALUE` issue is recorded.

Repro: Comments = `"Met with Mr. Smith "` + 1,700 chars without a period →
`<CounselorNotes>Met with Mr.</CounselorNotes>`. Fix: only accept a boundary in the last ~20% of
the window, otherwise fall back to the word boundary; record the truncation.

### A.2 Control characters produce a non-well-formed file — `[FIXED]` — HIGH

> **Fixed:** `src/schema_rules.SchemaGuard` replaces every character XML 1.0 cannot carry with a
> space, on every element, and records a `STANDARDIZED_VALUE` warning.

`src/xml_utils.py` (`create_element`) writes cell text verbatim. XML 1.0 forbids `\x00–\x08`,
`\x0b`, `\x0c`, `\x0e–\x1f`. Only `Comments` is safe (via `clean_whitespace`).

Repro: `Mailing Street="123 Main St\x0bSuite 5"` (a vertical tab — what Word line breaks paste as)
→ validator: `XML parse error: PCDATA invalid Char value 11`. The *whole file* is rejected, the error
cannot be mapped to a row, and the converter recorded nothing. Fix: strip/replace illegal characters
in `create_element` and record a `DOWNGRADED_VALUE` issue.

### A.3 XSD errors cite the wrong column or the wrong row — `[OPEN]` — MEDIUM

- **Wrong column.** `src/xsd_error_mapping.py:79,84-85,103` maps Part 3 `TotalNumberOfEmployees`,
  `GrossRevenues`, `ProfitLoss`, `BusinessStartDatePart3` to the base column, but `_first_present`
  (`config.py:185-188`) takes the value from the `(Meeting)` column. Meeting=`12.5`, base=`12` → the
  error blames `'Total Number of Employees'`, a cell holding a valid `12`.
- **Wrong row.** `xsd_error_mapping.py:219,296`: "Row N" is the ordinal of the emitted XML record,
  not the CSV row. Any skipped row shifts all later numbers. 3 rows, row 2 has no Contact ID → row
  3's error reads "Row 2 (Contact CCC)". The contact id is right, so it is recoverable — but the
  row number is what users look at.

### A.4 Numbers: no range checks; accounting negatives become a fabricated zero — `[FIXED]` — MEDIUM

> **Range checks fixed** by `src/schema_rules.py`: a value outside the XSD's min/max is omitted with
> an `INVALID_VALUE` warning when the element is optional, or reported as an error when required.
> **Accounting negatives fixed** too: `clean_numeric` reads `(1,500)` as `-1500`, and a cell that
> still can't be read is reported as "'n/a' could not be used and was replaced with '0'" rather than
> "Blank value defaulted".

`src/data_cleaning.py:527-551`; `counseling_converter.py:348,359,636-641`.

- Negative or out-of-range values pass straight through and fail min/maxInclusive: Gross Revenues
  `-500`, employees `-3`, Prep Hours `-1`, `Prepare Only` duration `-1`, revenue `1500000000`.
- `(1,500)` — how Excel formats a negative in accounting style — becomes `<ProfitLoss>0</ProfitLoss>`
  with the warning "Blank value defaulted", which is false: the cell was not blank.

### A.5 Duplicate headers: the later column silently wins — `[OPEN]` — MEDIUM

`src/data_cleaning.py:298-316`. The docstring says callers detect duplicates; none do. Header
`...,Date,...,Date` with the first cell `10/05/2026` and the second blank → no `DateCounseled`, no
issue. Salesforce report builders produce duplicate column labels easily. Fix: detect in
`normalize_row_keys` and record a `FILE_ACCESS`/structure issue (or prefer the non-blank value).

### A.6 Gender mapper ignores `F` / `M` / `Woman` — `[OPEN]` — MEDIUM

`src/data_cleaning.py:350-366` matches only full words; `config.py:637`
`DEMOGRAPHIC_KEYWORDS['gender']` lists the abbreviations but is dead config. Counseling `Gender=F` →
`Sex` omitted, no issue. Training rows `F`, `M` → no Female/Male counts.

### A.7 All rows skipped → schema-invalid empty file — `[FIXED]` — MEDIUM

> **Fixed:** the counseling (and so training-client) converter now raises `EmptyCSVError` with a
> file-level error when no row converted, and writes nothing.

`counseling_converter.py:131-135` writes `<CounselingInformation />` when every row was skipped,
which fails the XSD (`minOccurs=1`). `training_converter.py:75-82` already raises `EmptyCSVError`
for the equivalent case; counseling and training-client should match.

### A.8 Unrecognised Mailing Country passes through raw — `[OPEN]` — LOW/MEDIUM

`counseling_converter.py:693` / `data_cleaning.py:201`. `Deutschland` → enum error (twice). The
`EXPORT_COUNTRY_LOOKUP` already used for export countries isn't consulted. Not covered by 2nd-pass
1.4's list.

### A.9 Unreadable input fails the whole file without an issue — `[OPEN]` — LOW/MEDIUM

`counseling_converter.py:126` catches only `OSError` and `csv.Error` around the read loop:

- cp1252 bytes in the CLI path → `UnicodeDecodeError` traceback (the web path decodes upstream).
- A cell over 131,072 chars → `csv.Error: field larger than field limit`. In the worker this
  surfaces as a **500** from `/convert` and `/preview` (`convert.py:112-114`, `preview.py:38`)
  rather than a 4xx, so the web consumer (`job-consumer.ts:165` treats only 400/422/timeout as
  permanent) retries a deterministic input error three times before showing a generic message.

---

## Tier B — Job pipeline integrity (web)

### B.1 `PATCH` can pull a queued or converting job back to `mapping` — `[OPEN]` — MEDIUM

`apps/web/src/app/api/jobs/[jobId]/route.ts:81,140-166`. The 2nd-pass fix (4.2) restricted the
writable status to `mapping`, but the guarded `updateMany` only excludes *terminal* statuses. From
`queued` or `converting`, `{status:"mapping"}` (and a new `columnMapping`) returns 200.

Trace: start a conversion, press Back to the mapping page, Save.
- **queued** → `runJob`'s guard expects queued/converting, so the claim is skipped and acked; the
  job never runs.
- **converting** → the conversion finishes, the runner's update to `complete` (`job-runner.ts:94-109`)
  matches 0 rows, and the result is discarded silently.
- Restart → a second queue entry. With more than one replica the original run can land on the new
  `converting` row and save XML built from the *old* mapping.

Fix: add `queued` and `converting` to the excluded set for PATCH (and return 409), plus a test
seeded in each state.

### B.2 The retry budget lasts about 4 seconds — `[OPEN]` — MEDIUM

`apps/web/src/lib/job-consumer.ts:150-175`. On a transient failure the consumer sleeps a fixed
2 s and requeues; `BLMOVE` reclaims immediately. Three attempts finish in ~4 s (measured: 4006 ms,
2 requeues, then dead-letter). Any worker redeploy longer than that fails every in-flight job
permanently with `conversion_deadlettered` — contradicting `docs/operations.md`, which says
such jobs "are retried by the queue". Fix: exponential backoff (e.g. 5 s, 30 s, 2 min) via a
delayed-requeue sorted set, or at minimum a longer per-attempt delay.

Variant: if Postgres blips *before* the queued→converting flip, `deadLetter` (`:181`, guarded on
`converting`) matches 0 rows; the job is acked while still `queued`, with no audit row, and is
reaped as a timeout an hour later.

### B.3 Retention only runs for users who come back — `[OPEN]` — MEDIUM (privacy)

`apps/web/src/lib/retention.ts:27,40-52` runs only from `api/jobs/route.ts:16` and
`dashboard/page.tsx:29`, for the viewing user, 25 jobs per visit. The convert form promises
files "are automatically deleted after N days" (`convert-form.tsx:224`). A user who uploads client
PII (names, phones, addresses) and never signs in again keeps it on the volume indefinitely. Fix:
a global sweep from the consumer's background loop (it already runs per process).

### B.4 Cancel-then-delete can orphan converted XML — `[OPEN]` — LOW

`job-runner.ts:77-80` writes the XML before the guarded status update at `:94`. If the user cancels
and then deletes (the 409 message tells them to) while the worker misses the cancel, the runner
writes `output/<id>/<id>.xml` after the row and directory are gone. No row → retention never finds
it. Fix: write to a temp path and rename only after the guarded update succeeds, or delete on
`count === 0`.

### B.5 The reaper fails jobs still waiting in a long queue — `[OPEN]` — LOW

`job-reaper.ts:23,38` times `queued` jobs from when they were queued. With one serial consumer per
process and a 30-minute attempt budget, a backlog over 60 minutes gets jobs reaped as
`conversion_timeout` before they are ever claimed.

---

## Tier C — Resource limits & availability

### C.1 Chunked uploads bypass the size cap before buffering — `[OPEN]` — MEDIUM

`apps/web/src/lib/xml-tool-route.ts:123-132` (`declaredBodyTooLarge`), used by `/api/upload`,
`/api/validate-xml`, `/api/fix-xml`. The check reads only `Content-Length`; with
`Transfer-Encoding: chunked` it is absent, `Number(null)` is `0`, and `req.formData()` buffers the
whole body before `file.size` is checked.

This became reachable in `18b1048`, which removed these routes from the middleware matcher. That
change was correct (the middleware truncated bodies at 10 MB and broke legitimate uploads), but
the truncation was incidentally also the memory bound. Any signed-in user (signup is open) can OOM
the web process, which also hosts the job consumer. Fix: reject requests without a
`Content-Length` on these routes, or read `req.body` through a counting stream that aborts past the
cap.

### C.2 A stalled Redis adds ~2 s per progress write to every conversion — `[OPEN]` — MEDIUM

`apps/worker/app/services/redis_client.py:186-187` (`socket_timeout=2`), `routes/convert.py:78,87`.
Progress and cancel checks are synchronous Redis calls in the conversion thread; "fail-soft" catches
the exception only after the full timeout, with no circuit breaker. Against a listener that accepts
but never replies, 600 counseling rows took **68.5 s** (vs 0.4 s with fakeredis) — about 16k rows
exceeds the web's 30-minute convert timeout and the job is dead-lettered. Fix: after one timeout,
disable Redis calls for that conversion (or for N seconds process-wide).

### C.3 `/fix-xml` parses on the event loop — `[OPEN]` — MEDIUM

`apps/worker/app/routes/fix.py:99` calls `_canonical()` (`:45-58`) twice synchronously inside
`async def`. Measured 1.6 s at 5.7 MB and 9.7 s at 28.5 MB per call — ~19 s per request, well
inside the 100 MB body cap. Meanwhile `/health` (3 s healthcheck timeout), progress polls and
cancels all stall. Fix: `await asyncio.to_thread(...)`, as every other route already does.

### C.4 CODEBASE_ANALYSIS 3.7 was only partly fixed — `[OPEN]` — LOW/MEDIUM

3.7 is marked `[FIXED]`, but only the chunked-body bypass landed. `MAX_REQUEST_BYTES` is still
100 MB (`apps/worker/app/main.py:60`), there is no conversion concurrency cap (no semaphore, no
uvicorn `--limit-concurrency`), and the worker has no deadline of its own, so a conversion keeps
running after the web's 30-minute abort. Update that marker to `[PARTIAL]`.

---

## Tier D — Smaller items

| # | Where | Finding |
|---|---|---|
| D.1 | `src/xml_validator.py:173,193`; `apps/worker/app/routes/fix.py:54,118` | defusedxml's `EntitiesForbidden` is a `ValueError`, not `ParseError`, so `/fix-xml` returns **500** for any XML with an entity declaration (`/validate-xsd` correctly returns `is_valid=false`), and the `fix_sba_xml` CLI crashes with a traceback. No XXE leak — external entities are not resolved. |
| D.2 | `apps/worker/app/routes/convert.py:145`; `services/cancellation.py:46-57` | Cancel returns `{"cancelled": true}` even when Redis swallowed the signal; progress returns 404 "No progress recorded" when Redis is down, indistinguishable from a finished job. |
| D.3 | `apps/worker/app/main.py:181-191` | On FastAPI 0.141 `include_router` adds `_IncludedRouter` entries without `methods`, so the startup route log and the dev 404 route list show none of the real routes. The catch-all also turns 405s into 404s and logs every unauthenticated probe at ERROR. |
| D.4 | `apps/worker/app/models/schemas.py:7` | `PreviewRequest.converter_type` is a plain `str`: `"bogus"` → 200 with empty `column_status` (`/convert` returns 400). Use `Literal[...]`. |
| D.5 | `apps/worker/app/routes/validate.py:46` | Error responses have two shapes (`detail` list from FastAPI 422, string from the worker's own 422) and echo input verbatim (`"Unknown schema type: <script>x"`). JSON-only, so not XSS, but inconsistent. |
| D.6 | `apps/worker/Dockerfile:1,4-5` | Base image pinned by tag not digest; `libxml2-dev`/`libxslt1-dev` installed although the install is wheels-only; `HEALTHCHECK` hardcodes 8000 while Railway uses `$PORT`. |
| D.7 | `apps/web/src/app/api/auth/signup/route.ts:89-95`; `src/lib/auth.ts:64-71` | Account enumeration: signup returns 409 "Email already registered"; login skips bcrypt for unknown emails (~250 ms timing difference at cost 12). Signup's 5/min limit is keyed on spoofable `X-Forwarded-For`. |
| D.8 | web routes | Audit-trail gaps: column-mapping changes (which change what gets filed), template save/delete, and sign-in success/failure write no `AuditEntry`. |
| D.9 | core | Smaller data issues: `%y` dates map `01/05/68` → 2068; training event id `"EV1 "` splits into a second event (`training_converter.py:86`); training-client `City` (capitalised) dropped (`config.py:679` maps only `city`); 9-digit ZIP loses +4 silently; export employees `12.7` truncated to 12; whitespace-only Contact ID emitted as `"   "`; `clean_whitespace` deletes `[Q3]:` from notes; "Middle Eastern or North African" counted under both MiddleEastern and NorthAfrican. |

---

## What is in good shape

- **Web state machine.** Every status write is a guarded `updateMany` with a `count === 0` check;
  enqueue failure rolls back with a 503; the consumer loop cannot die; startup does not block on
  Redis; timeout ordering is checked at boot. B.1 is a gap in one guard, not in the pattern.
- **Authorization.** Every API route and server page filters on `userId` (including
  `previousJobId` and template delete). Dropping the upload routes from the middleware cost no
  authorization — each calls `getRequiredUser()`. Login ignores `callbackUrl` (no open redirect).
- **File handling.** Sanitised filenames, DB-issued ids for paths, `realpath` containment on
  download, header-safe `Content-Disposition`, CSV formula-injection guard, encoding-aware decoding.
- **Worker.** Constant-time bytes comparison for the token, fail-closed on an empty token, streaming
  ASGI body cap, docs/OpenAPI off in production, startup refuses to run without the XSDs, unprivileged
  uid, `asyncio.to_thread` everywhere except C.3, fail-soft Redis with TTL backstops.
- **Supply chain.** Hash-locked, wheels-only Python installs; `npm ci --ignore-scripts`;
  pip-audit and npm audit in CI; least-privilege `GITHUB_TOKEN`; Compose stack brought up with
  `--wait` in CI.
- **Core design.** `CounselingConfig.COLUMN_MAPPING` with drift-guard tests, `emit_optional`, and
  the XSD-error-to-CSV mapping remain the project's strongest pieces.

Code-quality notes (no action required now): the largest functions are `run.py:main` (122 lines),
`CounselingConverter.convert` (87), `_build_business_fields` (69),
`TrainingConverter._build_training_record` (69). `_resolve_funding_source` and
`_warn_fabricated_default` are near-copies across the counseling and training converters, and Yes/No
normalisation is reimplemented about six ways in `counseling_converter.py` — consolidating that into
one `normalize_yes_no` is also the fix for 2nd-pass 1.3. About 250 of `config.py`'s 790 lines are
`EXPORT_COUNTRY_CODES` hand-copied from the XSD; that and the other enumerations (plus the length
facets in 2nd-pass 1.1, and the unused `MAX_FIELD_LENGTHS`) could be loaded from the schema, which
would close the drift risk structurally. `DEMOGRAPHIC_KEYWORDS['gender'/'ethnicity']` is dead (A.6).

---

## Recommended sequence

1. ~~**Unblock CI (1.1).**~~ Done.
2. **Stop invalid files (A.2, A.7, then 2nd-pass Tier 1).** A single sanitising pass in
   `create_element` for control characters, and facet-driven length/pattern enforcement loaded from
   the XSD, close the largest classes. Add the three tests from 2nd-pass 5.1 — they would have
   caught most of Tier A as well.
3. **Stop silent wrong answers (A.1, A.4, A.6, 2nd-pass 1.3/1.5/1.6, Tier 2).** One shared
   `normalize_yes_no`, the gender abbreviations, accounting negatives, and an audit-completeness
   test.
4. **Job pipeline (B.1, B.2, C.1).** Each is a small, local change: widen the PATCH guard, add
   backoff, reject bodies without `Content-Length`.
5. **Worker availability (C.2, C.3, D.1, A.9's 500s).** `to_thread` for `/fix-xml`, a Redis circuit
   breaker, and map `csv.Error`/`EntitiesForbidden` to 4xx.
6. **Privacy (B.3, B.4).** A global retention sweep and the temp-then-rename write.
