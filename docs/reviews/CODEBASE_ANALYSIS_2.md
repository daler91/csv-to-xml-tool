# Codebase & Application Analysis — second pass

**Reflects commit:** `482d235` (Merge PR #123) · **Date:** 2026-09-16
**Scope:** full re-review of `src/`, `apps/worker`, `apps/web`, tests, CI and deployment config,
after the Tier 1–5 remediation recorded in [`CODEBASE_ANALYSIS.md`](./CODEBASE_ANALYSIS.md).
**Method:** as before, every finding was verified by *executing* the code — both toolchains
installed, both suites run, the app built, and crafted CSVs converted through each converter and
validated against the bundled XSDs with lxml. The reproduction script is at the end. Nothing here is
inferred from reading alone.

This document does not repeat the first register. Findings already tracked there (or in
[`TECHNICAL_DEBT.md`](./TECHNICAL_DEBT.md) and
[`../documentation-audit.md`](../documentation-audit.md)) are referenced, not restated. Everything
below is **new** at `482d235` unless marked otherwise.

## How to use this document

Same convention as the first register: every finding carries a marker, and **when you fix
something, flip its marker in the same commit.**

- **`[OPEN]`** — verified present at `482d235`.
- **`[FIXED]`** — resolved; leave the entry in place with a commit reference.

---

## Contents

- [1. Baseline health](#1-baseline-health)
- [2. What the first pass got right](#2-what-the-first-pass-got-right)
- [3. The shape of what is left](#3-the-shape-of-what-is-left)
- [Tier 1 — Schema compliance](#tier-1--schema-compliance)
- [Tier 2 — Audit-trail integrity](#tier-2--audit-trail-integrity)
- [Tier 3 — Correctness & robustness](#tier-3--correctness--robustness)
- [Tier 4 — Web application](#tier-4--web-application)
- [Tier 5 — Tests, docs, process](#tier-5--tests-docs-process)
- [Recommended remediation sequence](#recommended-remediation-sequence)
- [Reproductions](#reproductions)

---

## 1. Baseline health

Re-measured at `482d235`. The `d0e71f0` column is the documentation audit's reading from earlier
the same day; the two agree, so the numbers are stable.

| Check | At `d0e71f0` | At `482d235` |
|---|---|---|
| `pytest` (Python) | 374 passed | **374 passed** |
| Coverage (exact CI command) | 88.8% | **88.8%** against a 70% gate |
| `ruff check .` | clean | clean |
| `vitest` (web) | 173 passed, 23 files | **173 passed, 23 files** |
| `npm run lint` (`tsc --noEmit` + `check-ui-classes.mjs`) | clean | clean, 85 files |
| `next build` | succeeds | succeeds (one Turbopack tracing warning on `jobs/[jobId]/route.ts:213`, harmless) |
| Shipped sample CSVs validate | 3 of 3 | 3 of 3 |

The repository is green. **As with the first pass, the point of this document is that the suite is
green over every finding below** — each one was produced by input that no test exercises.

## 2. What the first pass got right

Briefly, because it shapes what remains. The Tier 1–4 fixes held up under adversarial input:
`emit_optional` is applied consistently to the facet-constrained optionals it was written for; the
three enum mappers (`map_ethnicity_to_xsd`, `map_disability_to_xsd`, `map_military_status_to_xsd`)
work; `_cap_single_code` keeps `CounselingProvided`/`CounselingSeeking` valid and auditable;
`_first_present` fixed the `(Meeting)` fallbacks; `normalize_row_keys` handles ragged rows; the
schema-path startup guard, the streaming body cap, the constant-time worker auth and the security
headers are all as described. `CounselingConfig.COLUMN_MAPPING` with its drift-guard tests is a
genuinely good piece of design.

## 3. The shape of what is left

The first pass fixed the specific bugs it found. What it did not do — and what this pass is mostly
about — is close the *classes* those bugs belong to. Three patterns account for nearly everything
below:

1. **Facets the converter never enforces.** The XSD constrains lengths (`Middle` is one character,
   `Last`/`First` forty, `Street1`/`City`/`CompanyName`/`CounselorName` eighty,
   `PartnerClientNumber`/`PartnerSessionNumber` twenty), patterns (`Email`, `FIPS_Code`) and integer
   types. The converter checks none of them. `CounselingConfig.MAX_FIELD_LENGTHS` declares the
   right numbers for most of these — and only `CounselorNotes` is ever applied.
2. **Yes/No is case-sensitive.** Eight elements are `YesNoType` or `YesNoUndeterminedType`. Three
   of them emit the raw cell (so `yes` is schema-invalid) and five compare against the literal
   `'Yes'` (so `yes` silently becomes `No` — a wrong federal answer with no warning). The fix for
   the `OnFile` case in the first pass (`is_affirmative`) was applied to one element out of nine.
3. **Values that change without an audit record.** Rule 4 in `CONTRIBUTING.md` is the project's
   central promise: *never fabricate data silently*. Seven places still do, and the cleaning diff
   the results page shows cannot represent a value that was *dropped*.

Sections 1.4 and 1.5 are the counterpart to the first pass's 1.4: the same "pass the CSV label
straight into an enumeration" defect, in the elements that were not fixed then.

---

## Tier 1 — Schema compliance

All verified by converting a one-row CSV and validating with lxml against the bundled XSD. Each
produces **schema-invalid output with no issue recorded** — the row converts "successfully", the
tracker reports zero errors, and only the post-hoc XSD validation (which the argparse CLI does not
run, see [cli.md](../cli.md)) reveals the problem.

### 1.1 Length facets are never enforced — `[OPEN]`

| Element | XSD facet | Converter | Result with over-length input |
|---|---|---|---|
| `Middle` (both `ClientNamePart1` and `ClientNamePart3`) | `maxLength=1` | `emit_optional(client_name, 'Middle', row.get('Middle Name'))` — full value | **invalid** for any middle *name* rather than initial |
| `Last`, `First` | `maxLength=40` | raw | invalid at 41 |
| `Street1`, `City` | `maxLength=80` | raw | invalid at 81 |
| `CompanyName`, `CounselorName`, `Internet` | `String80Type` | raw | invalid at 81 |
| `PartnerClientNumber`, `PartnerSessionNumber` | `String20Type` | raw | invalid at 21 |
| `TrainingTitle` (training) | `String255Type` | raw | invalid at 256 |

`counseling_converter.py:292,573` (Middle), `:290-291,571-572` (Last/First), `:763,765`
(Street1/City), `:395` (CompanyName), `:717` (CounselorName), `:250,560` (the two partner numbers).

`Middle` is the one that will bite first: a Salesforce "Middle Name" field holds a name, and every
test fixture in the repository sets it to `''` (`test_integration_xsd.py:45`,
`test_counseling_converter.py:47`, `test_converter_characterization.py:133`). The README
("long text truncated at the schema's limits", `README.md:73`) describes behaviour that exists only
for `CounselorNotes`. `MAX_FIELD_LENGTHS` already carries `Middle: 1, Last: 40, First: 40,
Street1: 80, City: 80, PartnerClientNumber: 20, PartnerSessionNumber: 20` — the table is right, it is
just not wired to anything, and there is no `TRUNCATED_VALUE` issue emitted anywhere in the codebase
despite the category existing.

### 1.2 `LocationCode` present-but-blank emits `<LocationCode/>` — `[OPEN]`

`counseling_converter.py:253`: `row.get('LocationCode', DEFAULT_LOCATION_CODE)`. A CSV that carries
the column with an empty cell yields an empty element; `LocationCode` is `xs:integer` with
`minInclusive=1`, so the document is invalid. This is precisely the `.get`-default-versus-`or` trap
the same file fixes (with a comment explaining it) at `:302` for `SurveyAgreement` and `:418` for
`ConductingBusinessOnline`. A non-numeric cell fails the same way.

### 1.3 Yes/No fields are case-sensitive, in two different wrong ways — `[OPEN]`

Nine elements take a Yes/No answer. Their handling:

| Element | Code | `yes` / `Y` / `TRUE` in the cell becomes |
|---|---|---|
| `OnFile` | `is_affirmative` (`:311`) | `Yes` ✓ |
| `SurveyAgreement` | raw cell or `'No'` (`:302`) | `<SurveyAgreement>yes</SurveyAgreement>` — **invalid** |
| `ConductingBusinessOnline` | raw cell or default (`:418`) | **invalid** |
| `ClientIntake_Certified8a` | raw cell or default (`:422`) | **invalid** |
| `CurrentlyInBusiness` | `in ('Yes','No','Undetermined')` else `'No'` (`:387`) | **`No`, silently** |
| `CurrentlyExporting` (intake) | `in ('Yes','No')` else `'No'` (`:392`) | **`No`, silently** |
| `ReportableImpact` | `in ('Yes','No')` else `'No'` (`:598`) | **`No`, silently** |
| `VerifiedToBeInBusiness` | `in (...)` else `'Undetermined'` (`:594`) | `Undetermined`, silently |
| `Employee_Owned` | `is_affirmative`/`is_negative` (`:430`) | `Yes` ✓ |

The second group is worse than the first. Schema-invalid output is at least detected downstream. A
client who answered `yes` to "Currently In Business?" is filed as **not** in business, the
in-business-only sections (`LegalEntity`, `CounselingSeeking`) are skipped, and nothing in the report
says so. `is_affirmative`/`is_negative` exist in `data_cleaning.py` and are used three lines away.

### 1.4 Enumerated elements with no mapping and no pre-check — `[OPEN]`

The first pass added mappers for `Ethnicity`, `Sex`, `Disability`, `MilitaryStatus`,
`FundingSource` and `ExportCountries`. These enumerations still receive the raw CSV label:

| Element | Enum size | Verified failing input |
|---|---|---|
| `Race/Code` | 9 | `Caucasian` (the training converter's own keyword list treats it as a synonym for White) |
| `Media/Code` | 20 | `Facebook` |
| `BusinessType` | ~20 | `Bakery` |
| `BranchOfService` | 7 | `USMC` |
| `LegalEntity/Code`, `Certifications/Code`, `SBAFinancialAssistance/Code`, `ReferredClient/Code`, `Language/Code` | 6–50 | any non-canonical spelling |
| `AddressPart1/State`, `AddressPart3/State` | 63 (US only) | `Ontario` — `standardize_state_name` returns unknown input unchanged (`data_cleaning.py:83`) |
| `Email` | pattern | `jane@localhost` |
| `FIPS_Code` | `\d{5}` | `1910` |
| `CounselorRecord/TotalNumberOfEmployees` | `xs:integer` | `12.5` — Part 2's element is decimal, Part 3's is not; `clean_numeric` preserves the fraction |

None of these is checked at preview time either: `data_validation.analyze_counseling_quality`
checks contact id, last name, dates and fabrication blanks, so the mapping page's "data quality"
panel shows nothing for a file full of `Caucasian`. The only detection is `xsd_error_mapping`, after
the fact. Since the enumerations are already parsed from the XSD by the drift-guard test in
`test_integration_xsd.py`, a generic "resolve against the schema's enumeration, case-insensitively,
omit with a warning otherwise" — the pattern `_build_export_countries` already implements — would
close all of them at once.

### 1.5 Training: `Caucasian` is counted as Asian *and* White *and* underserved — `[OPEN]`

`classify_races` (`data_cleaning.py:416-432`) is a substring test, and `'asian' in 'caucasian'` is true.
Verified: two `Caucasian` attendees produce

```xml
<Race><Asian>2</Asian><White>2</White></Race>
<NumberUnderservedTrained><Total>2</Total></NumberUnderservedTrained>
```

Every white attendee whose race is exported as "Caucasian" is reported to SBA as Asian and as a
member of an underserved group. The keyword table lists `caucasian` under `white`
(`config.py:652`), so the value is expected input. `_count_race_ethnicity` then counts them as
minorities because `any(c != 'white' for c in person_races)` sees `asian`. The fix is a word-boundary
match, or checking the longer keywords first.

### 1.6 `Non-veteran` maps to `Veteran` — `[OPEN]`

`map_military_status_to_xsd` (`data_cleaning.py:507`) walks `_MILITARY_STATUS_XSD_RULES` and the
last rule is `("veteran", "Veteran")`, with no negation check. Verified: `Non-veteran` and
`Not a veteran` both emit `<MilitaryStatus>Veteran</MilitaryStatus>`, and because that is a service
status the converter then records a `MISSING_REQUIRED` error for `BranchOfService` — an error caused
by the tool's own misreading. `classify_ethnicity` (`:411`) already does the `\bnon\b|\bnot\b` check
this function needs; the training-side `classify_military` has the same gap.

---

## Tier 2 — Audit-trail integrity

The project's stated non-negotiable: *"If the converter must emit a value the CSV did not supply,
record a `FABRICATED_DEFAULT` issue naming the column and the value. If it must drop data to
satisfy the schema, record a `DOWNGRADED_VALUE`."* Each item below emits or drops a value with **no
issue recorded and no cleaning-diff entry**. All produce schema-valid XML, so nothing downstream
notices.

### 2.1 Contact hours are fabricated as `0.5` — `[OPEN]`

`counseling_converter.py:723`: when the session type requires contact hours and `Duration (hours)`
is blank or zero, `contact_val = "0.5"`. Verified: a blank duration emits `<Contact>0.5</Contact>`
with no issue. Half an hour of federally reported counseling per affected row, invented.
`Duration (hours)` is not in `COUNSELING_FABRICATION_DEFAULTS`, so the mapping page does not warn
about the column either.

### 2.2 Part 3 `TotalNumberOfEmployees` is fabricated as `0` — `[OPEN]`

`counseling_converter.py:616`: `self._mapped(row, 'total_employees_part3', default='0')`. Part 2
(`:434`) omits the element when blank; Part 3 emits `<TotalNumberOfEmployees>0</TotalNumberOfEmployees>`.
Verified. A blank cell and "zero employees" are indistinguishable in the filing.

### 2.3 Part 3 `CurrentlyExporting` is hardcoded to `No`, contradicting Part 2 — `[OPEN]`

`counseling_converter.py:609`: `create_element(counselor_record, 'CurrentlyExporting',
DEFAULT_BUSINESS_STATUS)` — the CSV column `Are you currently exporting?(old)` that Part 2 reads is
ignored. Verified with an exporting client: the same record carries
`<CurrentlyExporting>Yes</CurrentlyExporting>` in `ClientIntake` and
`<CurrentlyExporting>No</CurrentlyExporting>` in `CounselorRecord`. `ExportGrossRevenuesOrSales` is
likewise hardcoded to `0` in both parts (`:450,633`) even for exporters. Neither is named in any
warning; the counseling path has no equivalent of the training converter's
`_warn_constant_defaults`.

### 2.4 `Services Provided = Other` is rewritten to `Business Operations/Management` — `[OPEN]`

`counseling_converter.py:673` replaces any `Other` code with `Business Operations/Management`
unconditionally. `Other` **is** a member of the `CounselingProvided/Code` enumeration (the 22nd
value), so this is not a schema workaround. Verified: `Services Provided=Other`, `Other Counseling
Provided=Grant writing` emits `<Code>Business Operations/Management</Code><Other>Grant writing</Other>`
— a service the counselor did not say they provided, with the "Other" text attached to it. No
`DOWNGRADED_VALUE`. The line dates from the original converter (2026-04) and no commit explains it.

### 2.5 `ReportableImpact=Yes` silently overrides `VerifiedToBeInBusiness` — `[OPEN]`

`counseling_converter.py:600-601`. Verified: `Verified To Be In Business=No` plus
`Reportable Impact=Yes` emits `<VerifiedToBeInBusiness>Yes</VerifiedToBeInBusiness>`. The rule may
be a legitimate SBA business rule, but overriding an explicit answer is exactly what
`DOWNGRADED_VALUE` was introduced to record.

### 2.6 Unparseable phone numbers vanish without a trace — `[OPEN]`

The first pass made `clean_phone_number` return `""` for anything not normalizable to ten digits
(correct). But `_build_phone` (`:785`) just omits the element, records nothing, and the cleaning
diff cannot show it either: `diff_service.py:131` skips any entry where `cleaned == ""`.
Verified: `Contact: Phone=555-0101` produces no `PhonePart1`, no issue, no diff row. The client's
phone number is gone from the filing and every surface the tool offers says nothing changed. The
same `cleaned != ""` guard hides every other value the cleaners drop (a bad date, an unknown
country, a `Prefer not to say` gender).

### 2.7 Training-side silent defaults — `[OPEN]`

- **Blank `Training Topic` → `Technology`, silently.** `_resolve_training_topic:307-308` returns the
  default for an empty value with no issue; its own docstring says so. An unrecognized value at least
  warns. The blank case is the common one.
- **Unknown `Class/Event Type` → `In-person`, silently.** `_build_training_record:199` uses
  `map_value(..., DEFAULT_PROGRAM_FORMAT)`; `Workshop` became `In-person` in verification with no
  issue. Compare `_resolve_training_topic`, which warns on the same situation.
- **The training-client path has no `_warn_constant_defaults`.** `TrainingClientConverter` injects
  `HoursTrained=1.5`, `EmployeesTrained=1`, `SessionType=Training`, `Language=English` and, when the
  event has no topic, `Services Provided=Business Start-up/Preplanning` into every record, and
  deliberately suppresses the per-row warnings (`training_client_converter.py:539`). The training
  converter solved the same "one warning per file, not per row" problem with a file-level issue
  (`training_converter.py:116`); the training-client converter emits nothing. Verified: a
  training-client conversion's issue list contains no `FABRICATED_DEFAULT` at all.
- **`Address` and `Street Line 1` are accepted as aliases for City** (`config.py:591`). Verified: a
  training CSV with `Address=123 Main St` and no city column emits `<City>123 Main St</City>`.

### 2.8 The cleaning diff does not cover the enum mappers — `[OPEN]`

`converters.md` says *"Every change is recorded, so the results page can show a before/after diff
for each value."* `diff_service.COUNSELING_CLEANING_MAP` has no entry for `Ethnicity:`, `Disability`,
`Veteran Status`, `Export Countries`, `Race` or `Comments`, so `Not Hispanic or Latino → Non Hispanic
or Latino`, `No → No military service`, `UK → United Kingdom` (export) and the whitespace/`[User]:`
scrubbing of counselor notes never appear in the diff. The map is pinned to `COLUMN_MAPPING` by a
test for *column names*, not for *coverage of the cleaners actually applied*.

---

## Tier 3 — Correctness & robustness

### 3.1 The validation reports crash on non-ASCII text under a non-UTF-8 locale — `[FIXED]`

> Fixed: both writers pass an explicit encoding (`utf-8-sig` for the CSV so Excel reads it as UTF-8, `utf-8` plus a `<meta charset>` for the HTML) and catch `UnicodeError` alongside `OSError`. `tests/test_validation_report.py::TestReportEncoding` runs the writers in a subprocess under an ASCII locale.


`validation_report.py:188` and `:334` open the CSV and HTML reports with no `encoding=`. Python
then uses the locale encoding — `cp1252` on the Windows machines that `run.bat`/`setup.bat` exist to
serve. A single character outside that codepage in any issue message (a name with a diacritic, the
curly apostrophe in `Cote d’Ivoire` from the country table itself) raises `UnicodeEncodeError`,
which is a `ValueError`, not the `OSError` the `except` at `:193`/`:336` catches.

Verified under an ASCII locale: both writers raise. In `run.py` this lands *after* the conversion
succeeded and *before* the XSD validation step (`run.py:276-277`), outside the `try` at `:261`, so a
double-click user sees a traceback and the console closes; in `src.main` it is caught by the outer
`except Exception` and the process exits 1 with "An unexpected error occurred" after writing a good
XML file. The XML writers are fine (they pass `encoding='utf-8'` explicitly).

### 3.2 Training-client issues and XSD error details cite columns the user's file does not have — `[FIXED]`

> Fixed: `TrainingClientConfig.reverse_column_mapping()` is applied in two places — `ValidationTracker.field_aliases` (set by `TrainingClientConverter.__init__`) renames every issue's `field_name` back to the user's header, and `xsd_error_mapping._TRAINING_CLIENT_ELEMENT_FIELDS` is derived from the counseling table through the same reverse map. The ZIP warning is recorded once per record (`_first_time`).


`TrainingClientConverter` renames `State → Mailing State/Province`, `Zip code → Mailing Zip/Postal
Code`, `Phone → Contact: Phone`, `Company → Account Name`, `Disabilities → Disability`, etc., before
handing rows to the counseling code — which then records issues and, via
`_TRAINING_CLIENT_ELEMENT_FIELDS`, maps XSD errors using the *counseling* names for every column it
does not explicitly override (`xsd_error_mapping.py:149-157` overrides five). Verified with
`State=Ontario` in a training-client CSV: the friendly message reads *"'Mailing State/Province' (CSV
column 'Mailing State/Province')"* and the tracker issue for the ZIP is filed under
`Mailing Zip/Postal Code`. The traceability that the first pass called "the tool's most valuable
asset" points at the wrong column for the third converter. `TrainingClientConfig.COLUMN_MAPPING` is
the reverse map needed; `analyze_training_client_quality` already applies it for the preview.

Also visible in that run: the ZIP warning is recorded **twice** per row (once each for
`AddressPart1` and `AddressPart3`), because `_build_address` dedupes only the fabrication warning.

### 3.3 The mapping page reports the shipped samples as incomplete — `[FIXED]`

> Fixed: `preview_service._match_columns` treats any accepted alias as a match for `training` and reports it in `column_status.aliases` (shown by the mapping page); `TRAINING_CLIENT_EXPECTED` now lists only the columns the converter reads. Both shipped samples are regression fixtures in `tests/test_preview_service.py`.


`get_expected_columns('training')` returns the *first* alias of each `TrainingConfig` entry
(`preview_service.py:273-279`), so for `training-sample.csv` — whose headers are `city`, `State`,
`Zip code` — the preview reports **4 missing columns** (`City`, `Cosponsor`, `State/Province`,
`Zip/Postal Code`) and offers two rename suggestions, although the converter resolves all three via
its alias list. `training-client-sample.csv` shows **8 missing** because `TRAINING_CLIENT_EXPECTED`
lists columns (`Class Teacher`, `Disabilities`, `Related Record ID`, `Street`, `city`, `State`,
`Zip code`, `Unique Campaign Members`) that the sample deliberately omits. The first thing a new user
sees after uploading the sample the landing page linked is a warning that it is wrong.

### 3.4 Smaller items — `[FIXED]`

> Fixed: `/preview` binds the job id; the cleaning-diff failure is logged with its traceback; the dead `Street2` call is gone; the web Dockerfile runs `npm ci --ignore-scripts`.


- `routes/preview.py` never calls `set_job_id`, so preview logs carry `[-]` and cannot be
  correlated with the job (every other route binds it).
- `conversion_service.py:135` swallows any exception from `generate_cleaning_diff` into
  `diffs = []`. A failure there means the results page silently shows "no cleaning changes".
- `_build_address:764` emits `Street2` from a literal `''` — dead call.
- `apps/web/Dockerfile:4` still runs `npm install --ignore-scripts`, not `npm ci`. The first
  register's 2.3 lists this under `[FIXED] (most)`; it was not fixed. The lockfile is not enforced in
  the image build.

---

## Tier 4 — Web application

The first pass found the job pipeline to be the strongest part of the codebase, and that still
holds: every status transition is a guarded `updateMany`, `migrate.js` matches `schema.prisma`
column for column, ownership scoping is consistent, and the middleware matcher covers every
authenticated route (all re-verified). What follows is what an adversarial read of the remaining
surface turned up. Items marked **verified** were confirmed against the code and, where noted, by
running it; **plausible** means the code path is clear but the trigger needs a runtime condition not
reproduced here.

### 4.1 The web server never starts if Redis is unreachable at boot — `[FIXED]` — HIGH, verified

> Fixed: `startConsumer` no longer awaits the boot sweep (fire-and-forget with its own error log), so `register()` resolves whatever Redis is doing. `job-consumer.test.ts` starts the consumer against a sweep whose promise never settles.


`instrumentation.ts:17` awaits `startConsumer()`, which awaits `sweepStaleClaims()`
(`job-consumer.ts:35`) on the queue client. That client is built with `maxRetriesPerRequest: null`
and ioredis's default offline queue (`job-queue.ts:48-52`), so while Redis is down the command is
queued and **never settles** — `retryStrategy` reconnects forever and nothing rejects, so the
`try/catch` around the sweep cannot fire. Next awaits `register()` before it starts listening.

Verified by running the same client configuration against a closed port: the `ZRANGEBYSCORE`
promise was still pending after eight seconds. Scenario: deploy or restart the web service while
Redis is restarting → the process listens on nothing → Railway's `/` healthcheck fails →
`restartPolicyMaxRetries = 3` is exhausted → the service stays down until someone redeploys. Every
other Redis path in the app deliberately fails open; this one fails closed at the worst moment. Fix:
do not block `register()` on the boot sweep (fire-and-forget, or race it against a short timeout).

### 4.2 `PATCH /api/jobs/[jobId]` lets the browser write any job status — `[FIXED]` — HIGH, verified

> Fixed: the body must be a JSON object; `status` is accepted only as `mapping`; `columnMapping` goes through the shared `lib/column-mapping.ts::sanitizeMapping` (moved out of the template route, with `allowEmpty` for the legitimate empty job mapping). `api-reference.md` says so.


`jobs/[jobId]/route.ts:110-134` whitelists `["columnMapping", "status"]` and guards the *current*
status (not terminal) but never validates the *target* value. The only legitimate client write is
`status: "mapping"` (`mapping/page.tsx:132`). Consequences, all reachable from the browser as the job's
owner: `{status:"complete"}` on an uploaded job shows Complete on the dashboard with no output;
`{status:"queued"}` or `"converting"` makes a job that was never enqueued look live until the reaper
marks it `error` an hour later with a `conversion_timeout` audit row; `{status:"cancelled"}` on
`uploaded` creates exactly the state `cancel/route.ts:16-20` says must not exist; `{status:"bogus"}`
is a Prisma enum error → 500. `columnMapping` is likewise unvalidated (any JSON, any size, arrays or
nested objects reach the worker's `dict[str,str]` and 422 → dead-letter) although
`mapping-templates/route.ts:17-39` already has `sanitizeMapping` for the identical shape. A non-object
body (`"abc"`, `null`) hits `key in data` at `:113` → TypeError → 500. `route.test.ts` never sends a
`status`, and `api-reference.md:109` documents `status` as freely updatable. Fix: accept only
`status: "mapping"` and reuse `sanitizeMapping`.

### 4.3 The consumer loop dies permanently if `handleFailure` throws — `[FIXED]` — HIGH, verified

> Fixed: the per-job work moved into `processClaim`, and `runLoop` wraps it in its own try/catch with a backoff, so a throwing failure handler is logged and the loop claims again. Tested with a `getAttempts` that rejects inside the handler.


`job-consumer.ts:72-77`: `handleFailure` runs inside the `catch` with no guard of its own and calls
`ackJob`/`getAttempts`/`requeueJob` (Redis) and `deadLetter` (Prisma). Any of those throwing rejects
`runLoop`, which was fire-and-forgotten at `:56`; Next's process handlers log the rejection rather
than exit, so the web keeps serving but **no job is ever claimed again**, and `jobConsumerStarted`
(`:31-32`) prevents a restart. The happy path is exposed too: `runJob` succeeds, `ackJob` at `:74`
throws on a Redis blip → `handleFailure(jobId, redisErr)` → `getAttempts` throws → loop gone. One
Redis restart during a completing conversion leaves every later job `queued` until the reaper
fails it. No test covers a throwing `handleFailure`. Fix: guard `handleFailure` with its own
try/catch and sleep, and clear the started flag (or restart the loop) on exit.

### 4.4 `JOB_MAX_ATTEMPTS` is not enforced for sweep-reclaimed jobs — `[FIXED]` — MEDIUM, plausible

> Fixed: `processClaim` reads the attempt counter before running and dead-letters a job claimed more than `JOB_MAX_ATTEMPTS` times, with a `conversion_deadlettered` audit row naming the count.


The attempts cap is checked only in `handleFailure` (`job-consumer.ts:100`). A job that kills the
process instead of throwing — realistic, since `job-runner.ts:44-54` holds the CSV string, its
`JSON.stringify` copy and the fetch body at once — never reaches it. Claim (attempts=1; the
converting→converting `updateMany` at `job-runner.ts:32-35` bumps `updatedAt`) → crash → restart → 40
minutes later `sweepStaleClaims` re-queues (`job-queue.ts:116-130` never consults attempts) → claim
(attempts=2, unchecked) → crash… The reaper never fires because `updatedAt` is refreshed every 40
minutes and its deadline is 60. Fix: check `getAttempts(jobId) > MAX_ATTEMPTS` at claim time.

### 4.5 `workerFetch` timeout does not cover the response body — `[FIXED]` — MEDIUM, verified

> Fixed: `return (await res.json())`. `worker-client.test.ts` (new) checks the abort fires while a body is still downloading and that a body-read failure goes through the same catch as a network error.


`worker-client.ts:32` is `return res.json()` with no `await`, inside `try … finally`. The `finally`
runs — and `clearTimeout` fires — as soon as headers arrive, so the `AbortController` never aborts a
stalled body download, and for `/convert` the body *is* the payload (`xml_content`). A body-read
failure (socket reset mid-body, invalid JSON) also bypasses the `catch`, so it surfaces as a raw
`SyntaxError`/`TypeError` instead of the "timed out"/"Worker error" shapes that
`job-consumer.ts:97-98` classifies on. Fix: `return await res.json()`.

### 4.6 CSV bytes are decoded as UTF-8 with no detection — `[FIXED]` — MEDIUM, verified

> Fixed: `lib/csv-decode.ts` decodes UTF-16 by BOM, then strict UTF-8, then Windows-1252; the runner and the preview route both use it and log a non-UTF-8 fallback. `csv-decode.test.ts` covers a cp1252 Excel export.


`job-runner.ts:44` and `preview/route.ts:39` do `readFile(path, "utf-8")`. Excel's default "CSV
(Comma delimited)" on Windows writes cp1252, so every non-ASCII byte (José, Muñoz, an en-dash in
an address) becomes U+FFFD before the worker sees it — and the worker records no issue, because the
text it receives is valid UTF-8. Silent corruption of names in a federal filing, which is the
spirit of rule 4. `xml-tool-route.ts:44-70` already has a BOM/declaration-aware decoder for XML
uploads; the CSV path has nothing. Fix: decode with `TextDecoder("utf-8", {fatal: true})` and fall
back to windows-1252, or reject invalid UTF-8 at upload with a clear message.

### 4.7 Client components read a server-only env var — `[FIXED]` — MEDIUM, verified

> Fixed: `MAX_UPLOAD_BYTES` is passed as a prop from the server pages (`convert/page.tsx`, and a new server `validate/page.tsx` wrapping the client `validate-tool.tsx`), and the size messages on that path are formatted from the real cap via `formatMegabytes`.


`limits.ts:9-10` reads `process.env.MAX_UPLOAD_BYTES`; it is imported by the client components
`convert-form.tsx:19` and `validate/page.tsx:20`. It is not `NEXT_PUBLIC_`, so in the browser it is
always `undefined` and the client always uses the 50 MB default. A deployment that lowers the cap
sees the client accept a 30 MB file, the server return 413, and `upload-errors.ts:19` tell the user
the file is "larger than 50MB". The header comment of `convert-form.tsx` explains exactly this trap
for `RETENTION_DAYS` and passes that one as a prop. Fix: pass `MAX_UPLOAD_BYTES` the same way.

### 4.8 Remaining items — `[OPEN]`

| # | Finding | Location | Severity |
|---|---|---|---|
| 4.8.1 | Rate-limit key can lose its TTL permanently: `INCR` then a separate `EXPIRE` only when `current === 1`; if the `EXPIRE` fails the key never expires and, after `limit` more hits, is 429 forever (`signup:unknown` and `upload:<userId>` included). Use `SET … EX … NX` + `INCR` or a MULTI. | `rate-limit.ts:21-25` | MEDIUM, plausible |
| 4.8.2 | **`[FIXED]`** Preview route hid the worker's 4xx detail behind a 500. The route now relays a worker 400/422 detail as a 400 through the shared `workerClientError`. "Failed to generate preview", so a malformed CSV reads as "server may be busy". `xml-tool-route.ts:86-97` already does the right translation. | `preview/route.ts:49-56,82-83` | MEDIUM, verified |
| 4.8.3 | **`[FIXED]`** Retention purge could race `POST /start`. The purge claim now repeats the `status notIn` predicate.: candidates are selected by status but the purge claim guards only `filesPurgedAt: null`, so a job started in the window loses its input and dead-letters after three ENOENTs. One predicate fixes it. | `retention.ts:44-66` | LOW/MEDIUM, plausible |
| 4.8.4 | A failed conversion has no user-visible reason: `deadLetter` and the reaper put it only in `AuditEntry.metadata`, and `results/page.tsx:97-105` renders an `error` job as an empty "Conversion Results" page. Distinct from the tracked audit-label item: fixing that only makes the reason findable on a different page. | `job-consumer.ts:113-116`, `results/page.tsx` | LOW/MEDIUM, verified |
| 4.8.5 | **`[FIXED]`** Upload extension check was case-sensitive on the server only (`endsWith(".csv")`); the client lower-cases. `EXPORT.CSV` passes the client and is told "That file isn't a CSV". | `upload/route.ts:35` | LOW, verified |
| 4.8.6 | **`[FIXED]`** Multipart bodies were fully buffered before the size cap applied: `declaredBodyTooLarge` now rejects on `Content-Length` first, and `isUploadedFile` rejects a non-file part with a 400. Previously, and a non-file `file` part → TypeError → 500. | `upload/route.ts:23`, `xml-tool-route.ts:121` | LOW, plausible |
| 4.8.7 | **`[FIXED]`** `workerClientError` now recognises only 400/422; a 401/403/413/429 falls through to the logged 502 path. Previously every worker 4xx was relabelled a user error: a wrong `WORKER_AUTH_TOKEN` (401), the worker's 413 or a 429 is shown to the partner as if their file were bad, and not logged. | `xml-tool-route.ts:86-97` | LOW, verified |
| 4.8.8 | **`[FIXED]`** Download filename replaced the *first* `.csv`; now the suffix, case-insensitively: `q1.csv_export.csv` downloads as `q1.xml_export.csv`. Use `/\.csv$/i`. | `download/route.ts:55` | LOW, verified |
| 4.8.9 | **`[FIXED]`** `lib/client-ip.ts` requires an IPv4/IPv6 address (`net.isIP`, ≤45 chars) and is shared by signup and login; `TECHNICAL_DEBT.md` #15 is corrected. The email-keyed lockout is unchanged and documented. Previously the login IP key was an unvalidated header string of any length; `getClientIdentifier` does not validate the IP as `TECHNICAL_DEBT.md` #15 claims, only splits and trims. Separately, the email-keyed login counter is checked before the user lookup, so ten junk POSTs lock a known account out for 15 minutes. | `auth.ts:42-56`, `signup/route.ts:7-18` | LOW, verified |
| 4.8.10 | **`[FIXED]`** Signup: malformed JSON → 400, non-string name → 400, email shape/length checked, P2002 → 409. Previously malformed JSON → 500 not 400; non-string `name` → Prisma error → 500; no email format/length check; `findUnique`→`create` race surfaces P2002 as 500 instead of 409. | `signup/route.ts:47-76` | LOW, verified |
| 4.8.11 | **`[FIXED]`** `conversion_started` was audited on every successful claim. `runJob` now takes the attempt number from the consumer and writes `conversion_retried` (with `metadata.attempt`) for later attempts; the audit page labels it. | `job-runner.ts` | LOW, verified |
| 4.8.12 | `Dockerfile:27-29` relies on Docker named-volume ownership inheritance for `/data`, which does not apply to Railway volumes (mounted root-owned). If `RAILWAY_RUN_UID=0` is not set, every upload fails with EACCES. Not verifiable here; confirm against the live service. | `apps/web/Dockerfile` | LOW, plausible |
| 4.8.13 | **`[FIXED]`** The three timeouts now live in `lib/durability-timeouts.ts` and `assertTimeoutOrdering()` runs at consumer startup, refusing to start on a misordered override. | `lib/durability-timeouts.ts` | LOW |

**Web test gaps:** no `worker-client.test.ts`; no test for `mapping-templates/[templateId]`; a throwing
`handleFailure` is untested; `PATCH` with a `status` value is untested; an upper-case `.CSV` upload is
untested. `GET /api/jobs/[jobId]` returns `inputFilePath`/`outputFilePath` (absolute server paths)
plus the full `issues` and `cleaningDiffs` arrays on every 1–5 s progress poll — not a bug, but
unnecessary disclosure and payload.

---

## Tier 5 — Tests, docs, process

### 5.1 The suite has structural blind spots — `[OPEN]`

Every counseling fixture in the repository — `test_integration_xsd.py`, `test_counseling_converter.py`,
`test_converter_characterization.py`, the goldens — uses canonical values: `Middle Name=''`, exactly
`Yes`/`No`, schema-spelled enumerations, short strings, ten-digit phones. That is why 1.1–1.6 and
2.1–2.6 pass. Three cheap tests would have caught most of this document:

1. **A facet fuzz test derived from the XSD.** The drift-guard in `test_integration_xsd.py` already
   parses enumerations from the schema; extend it to read `maxLength`/`pattern` facets and assert the
   converter never emits a value that violates one. Free coverage for 1.1, 1.2, 1.4.
2. **A case-variant Yes/No test** (`yes`, `Y`, `TRUE`, `true`) across every `YesNoType` element,
   asserting both validity *and* that `yes` lands as `Yes`, not `No`. Covers 1.3.
3. **An audit-completeness test**: for a row with a blank in every column, every emitted element
   whose value did not come from the row must correspond to a `FABRICATED_DEFAULT` or
   `DOWNGRADED_VALUE` issue. Covers all of Tier 2.

### 5.2 The sample gate proves less than it appears to — `[OPEN]`

`TestShippedSamplesValidate` is described in `CONTRIBUTING.md` as the gate. `counseling-sample.csv`
carries **16 of the 74** counseling columns and three rows; it exercises none of the address, phone,
Part 3, certification or referral paths. It is a smoke test, not a compliance test. Pair it with 5.1.

### 5.3 Documentation claims that the code does not meet — `[OPEN]`

| Claim | Where | Reality |
|---|---|---|
| "long text truncated at the schema's limits" | `README.md:73` | Only `CounselorNotes` (1.1) |
| "Every change is recorded, so the results page can show a before/after diff" | `converters.md` | Enum mappers and dropped values are not in the diff (2.6, 2.8) |
| Fabricated-defaults table lists nine columns | `converters.md` | `Duration (hours)`, Part 3 employees, Part 3 exporting, training topic, program format, training-client constants are all fabricated too (Tier 2) |
| `CODEBASE_ANALYSIS.md` 2.3 `[FIXED] (most)` including `npm ci` | `reviews/CODEBASE_ANALYSIS.md:315` | Dockerfile still uses `npm install` (3.4) |

### 5.4 Still open from the first pass, unchanged

For completeness, and so this register can stand alone: 1.7 (training aggregation counts rows, not
people; event fields from the first row), 3.10 (no CSRF/Origin check, `trustHost`), 3.11
(worker-client omits the header when the token is empty; unvalidated worker responses), 5.1/5.2
(converter abstraction; ~70 header literals outside `COLUMN_MAPPING`), 5.5 (no formatter, no type
checker, no ESLint), 5.6 (web duplication, dual DDL source), the SIGTERM/sweep-interval items in
Tier 4, Redis persistence, and the four code issues listed in `documentation-audit.md` (`run.py` XSD
discovery, audit action labels, `Job.processedRows`, training aggregation).

---

## Recommended remediation sequence

Ordered by risk to the filing per unit of effort. Each step is independently shippable, and each
should land with the test from 5.1 that would have caught it.

### Phase 1 — Stop producing invalid or wrong filings (Tier 1)

1. **Wire `MAX_FIELD_LENGTHS` up.** One `_bounded(value, key)` helper that truncates and records
   `TRUNCATED_VALUE`; route the ten elements in 1.1 through it. Add `CompanyName`, `CounselorName`,
   `Internet`, `TrainingTitle` to the table. Half a day.
2. **One Yes/No helper.** `_yes_no(row, column, default, *, record_id)` built on
   `is_affirmative`/`is_negative`, warning on unrecognized input; replace the nine call sites in 1.3.
   Fix `LocationCode` (1.2) with the same `or`-not-`.get` idiom the file already uses.
3. **Generic enumeration resolution (1.4).** Load each enumeration from the XSD once at import
   (the drift-guard test shows how), resolve case-insensitively with the existing synonym tables,
   omit-with-warning on miss — the `_build_export_countries` pattern generalized. Add the same check
   to `analyze_counseling_quality` so the mapping page shows it before conversion.
4. **Word-boundary keyword matching** in `classify_races`/`classify_military` and a negation check
   in `map_military_status_to_xsd` (1.5, 1.6).

### Phase 2 — Make the audit trail complete (Tier 2)

5. Record `FABRICATED_DEFAULT` for contact hours, Part 3 employees, Part 3 exporting/export revenue,
   blank training topic, unknown program format; add `_warn_constant_defaults` to the training-client
   converter; record `DOWNGRADED_VALUE` for the `Other` rewrite (or stop rewriting — `Other` is
   valid) and the `VerifiedToBeInBusiness` override.
6. Let the cleaning diff represent drops (`cleaned == ""` becomes a diff row with an empty "after"),
   and extend `COUNSELING_CLEANING_MAP` to the enum mappers and `Comments`. Record an issue when a
   phone is dropped.
7. Remove `Address`/`Street Line 1` from the City aliases.

### Phase 3 — Robustness (Tier 3)

8. `encoding='utf-8'` on both report writers; catch `UnicodeEncodeError` alongside `OSError`.
9. Reverse-map training-client column names in issues and error details; dedupe the ZIP warning.
10. Derive training expected columns from *all* aliases (or match on any alias) so the samples
    preview clean; trim `TRAINING_CLIENT_EXPECTED` to what the converter reads.
11. `npm ci` in the web Dockerfile; bind the job id in `/preview`.

### Phase 4 — Web application (Tier 4)

12. The three one-line fixes first: stop blocking `register()` on the boot sweep (4.1), guard
    `handleFailure` (4.3), `return await res.json()` (4.5). Then restrict `PATCH` to
    `status: "mapping"` and reuse `sanitizeMapping` (4.2), check attempts at claim time (4.4),
    decode CSVs with a strict-UTF-8-then-cp1252 fallback (4.6), and pass `MAX_UPLOAD_BYTES` as a
    prop (4.7). The 4.8 table is an afternoon of small fixes; take the rate-limit TTL (4.8.1) and
    the empty error page (4.8.4) first.

### Phase 5 — Tests and docs (Tier 5)

13. The three tests in 5.1. Then correct the README and `converters.md` claims in 5.3 — or better,
    make them true.

---

## Reproductions

```bash
# Baseline — all currently pass
python -m pytest tests/ -q --cov=src --cov=apps/worker/app --cov-fail-under=70
ruff check .
cd apps/web && npm run lint && npx vitest run && npm run build
```

Every Tier 1 and Tier 2 finding reproduces with this harness. Set a column, convert, validate:

```python
# save as repro.py in the repo root; run: python repro.py
import csv, logging, sys
from lxml import etree
from src.validation_report import ValidationTracker
from src.converters.counseling_converter import CounselingConverter

BASE = {"Contact ID": "003XX000004TMM1", "Last Name": "Doe", "First Name": "Jane", "Race": "White",
        "Ethnicity:": "Not Hispanic or Latino", "Gender": "Female", "Disability": "No",
        "Veteran Status": "No", "Currently In Business?": "No", "Type of Session": "Telephone",
        "Language(s) Used": "English", "Date": "2026-01-15", "Name of Counselor": "Sam",
        "Duration (hours)": "1"}
CASES = {
    "1.1 Middle":            {"Middle Name": "Marie"},
    "1.2 LocationCode":      {"LocationCode": ""},
    "1.3 SurveyAgreement":   {"Agree to Impact Survey": "yes"},
    "1.3 InBusiness->No":    {"Currently In Business?": "yes"},          # valid, but wrong
    "1.4 Race":              {"Race": "Caucasian"},
    "1.4 State":             {"Mailing State/Province": "Ontario"},
    "1.4 Part3 employees":   {"Total No. of Employees (Meeting)": "12.5"},
    "1.6 Non-veteran":       {"Veteran Status": "Non-veteran"},            # valid, but wrong
    "2.1 Contact hours":     {"Duration (hours)": ""},                     # valid; <Contact>0.5
    "2.3 Exporting":         {"Are you currently exporting?(old)": "Yes"}, # valid; Part 3 says No
    "2.4 Other rewritten":   {"Services Provided": "Other", "Other Counseling Provided": "x"},
    "2.6 Phone dropped":     {"Contact: Phone": "555-0101"},               # valid; no issue
}
schema = etree.XMLSchema(etree.parse("schemas/SBA_NEXUS_Counseling-2-14.xsd"))
log = logging.getLogger("repro"); log.addHandler(logging.NullHandler()); log.propagate = False
for name, extra in CASES.items():
    row = {**BASE, **extra}
    with open("repro.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row); w.writeheader(); w.writerow(row)
    tracker = ValidationTracker()
    CounselingConverter(log, tracker).convert("repro.csv", "repro.xml")
    ok = schema.validate(etree.parse("repro.xml"))
    issues = [i["category"] for i in tracker.issues if i["category"] != "fabricated_default"]
    print(f"{name:24s} valid={ok!s:5s} non-default issues={issues or 'none'}")
```

```bash
# 1.5 — training race counting
python -c "from src.data_cleaning import classify_races as c; \
  print(c('Caucasian', {'asian': ['asian'], 'white': ['white', 'caucasian']}))"   # {'asian', 'white'}

# 3.1 — report writers under a non-UTF-8 locale
PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 LC_ALL=C python -c "
from src.validation_report import ValidationTracker as T; t=T()
t.add_issue('r','warning','invalid_value','f','Cote d’Ivoire'); t.save_issues_to_csv('reports')"
# -> UnicodeEncodeError

# 3.3 — shipped training sample on the mapping page
python -c "import sys; sys.path.insert(0,'apps/worker'); \
  from app.services.preview_service import read_csv_preview as p; \
  print(p(open('apps/web/public/samples/training-sample.csv').read(),'training')['column_status']['missing'])"
# -> ['City', 'Cosponsor', 'State/Province', 'Zip/Postal Code']
```

**Files most implicated:** `src/converters/counseling_converter.py`, `src/data_cleaning.py`,
`src/validation_report.py`, `src/config.py`, `src/converters/training_converter.py`,
`src/converters/training_client_converter.py`, `src/xsd_error_mapping.py`,
`apps/worker/app/services/diff_service.py`, `apps/worker/app/services/preview_service.py`,
`tests/test_integration_xsd.py`.
