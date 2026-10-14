# Converters

Three converters ship, and picking the wrong one is the most common source of
confusing output. They are not interchangeable: two of them produce Form 641
counseling XML and differ in what a CSV *row* means.

| Converter | Form | Root element | Schema | One CSV row is… |
|---|---|---|---|---|
| `counseling` | 641 Counseling | `<CounselingInformation>` | `SBA_NEXUS_Counseling-2-14.xsd` | one counseling session with one client |
| `training` | 888 Management Training | `<ManagementTrainingReport>` | `SBA_NEXUS_Training-2-25-2025.xsd` | one **attendee** at an event; rows are rolled up per event |
| `training-client` | 641 Counseling | `<CounselingInformation>` | `SBA_NEXUS_Counseling-2-14.xsd` | one attendee, emitted as a counseling record |

### Which one do I want?

- You are reporting **one-to-one advising sessions** → `counseling`.
- You are reporting **an event** — a workshop, a webinar, a class — and you need
  the attendee demographics totalled per event → `training`.
- You need each **training attendee to appear as a 641 counseling record**
  (some partners report training attendance this way) → `training-client`.

`training` and `training-client` read the same kind of per-attendee export. The
difference is entirely in what comes out: one event record with totals, versus
one counseling record per attendee.

---

## `counseling` — Form 641

Reads one session per row and emits one `<CounselingRecord>` per row, with
elements in the order the XSD's `xs:sequence` requires.

**Required column:** `Contact ID`. Rows without one are recorded as errors, not
dropped silently.

What it handles that hand-built XML usually gets wrong:

- **Conditional elements.** `BranchOfService` is emitted only when the military
  status indicates service; `Other legal entity (specify)` only when the legal
  entity is `Other`; and so on. Emitting them unconditionally fails the schema.
- **Session types without contact hours.** `Prepare Only`, `Training` and
  `Update Only` are contact-hour-free session types and are treated as such.
- **Multi-value Salesforce fields.** `Race` and `Services Provided` arrive
  semicolon-delimited and are split into repeated elements — except where the
  schema allows only one code, in which case the first is kept and the dropped
  values are recorded as a `DOWNGRADED_VALUE` issue so the loss stays auditable.
  A cell holding only separators (`;`) counts as blank, so the usual default
  applies rather than a code list with no code.
- **Race answers outside SBA's nine codes.** "Two or More Races", "Middle
  Eastern or North African", "Hispanic or Latino" and the like are filed the way
  the schema provides: `Prefer to Self-Describe`, with the answer as written in
  `SelfDescribedRace` (up to 80 characters) and an `INVALID_VALUE` warning.
  Answers that decline the question ("Decline to answer", "Unknown", "N/A") are
  `Prefer not to say`, the value SBA renamed "Unknown/Not Stated" to.
- **"Other" text with no code.** `Nature of the Counseling Seeking - Other
  Detail` without a `Nature of the Counseling Seeking?` answer is filed under the
  code `Other`; on its own it would leave the section without the `Code` the
  schema requires.
- **Internet source.** `Internet (specify)` fills the schema's `Internet`
  element (the internet source behind a media answer of `Internet`), with
  `InternetUsage` as the fallback. It is not written to `Media/Other`, which SBA
  defines as the text for a media answer of `Other`.
- **Field length caps**, applied with a record rather than a silent trim:

  | Element | Max |
  |---|---|
  | `CounselorNotes` | 1000 |
  | `Last`, `First` | 40 |
  | `Middle` | 1 |
  | `Street1`, `Street2`, `City` | 80 |
  | `Phone` | 10 |
  | `PartnerClientNumber`, `PartnerSessionNumber` | 20 |

- **Part 3 impact fallbacks.** `Total No. of Employees (Meeting)`,
  `Gross Revenues/Sales (Meeting)` and `Profit & Loss (Meeting)` fall back to
  their intake counterparts, and `Business Start Date` to
  `Date Started (Meeting)`, when blank — or when the cell isn't a number or a
  date this tool can read, with a warning naming the cell passed over. With
  nothing to fall back on, an unreadable revenue or profit cell is reported as
  replaced with the `0` Part 3 files.
  Note that `Total Number of Employees`, `Gross Revenues/Sales` and
  `Profits/Losses` are *also* read on their own — they are fallback sources, not
  aliases. (Treating them as aliases is exactly the bug that once dropped three
  real columns from the expected-column list.)

## `training` — Form 888

Takes **per-attendee rows** and produces **one event record per `Class/Event ID`**,
computing every demographic total the schema requires: female, male, race,
ethnicity, veterans, disabilities, business status. You do not need to
pre-calculate totals; there are no total columns to supply.

**Required column:** `Class/Event ID`.

Two behaviours to be aware of:

- **Events are emitted sorted by event id.** Grouping is insertion-ordered, so
  the converter sorts explicitly. This is load-bearing: the earlier pandas
  implementation used `groupby(sort=True)`, and output has always been ordered.
  The characterization goldens in `tests/golden/` exist to pin this.
- **Event-level fields come from the first row of each group that has them**
  (`TrainingConverter._event_value`). A funding source or cosponsor only a
  later row gives is still filed. A value the converter parses or the schema
  checks — start date, funding source, training topic, event type,
  `LocationCode` — comes from the first row where it is usable, so a first
  row's `TBD` or `0` gives way to a later row's real date or code instead of
  costing the event. If rows for the same event disagree, the disagreement is
  reported as a warning naming the value filed; values are compared as they
  would be filed, so `1/15/2025` and `2025-01-15`, or `249003` and
  `249003.0`, agree. The location is the first row with a complete city,
  state and ZIP, else the first with a city and state, filed without a ZIP;
  the configured location is used only when no row gives both a city and a
  state.

Column matching for this converter is **alias-based**: `TrainingConfig.COLUMN_MAPPING`
lists several accepted spellings per field (`Cosponsor` / `CosponsorsName` /
`Partner Organization`, and so on), so common export variations work without a
manual mapping. Full list in [csv-reference.md](./csv-reference.md#training-form-888).

## `training-client` — Form 641 from training rows

The smallest converter (102 lines) and the one that shows the intended shape:
it reuses the counseling pipeline through four explicit hooks, renaming columns
and supplying counseling-specific defaults.

**Required columns:** `Class/Event ID` and `Contact ID`.
**Conditional:** `Member ID` — the per-attendee session id; falls back to
`Class/Event ID` when absent, which makes every attendee at an event share a
session number.

Because it emits counseling XML, its output validates against the **counseling**
XSD, not the training one. The web UI, the worker and `run.py` all apply that
rule automatically.

---

## The cleaning rules

Applied by `src/data_cleaning.py` to every converter. Every change is recorded,
so the results page can show a before/after diff for each value.

| Rule | Behaviour |
|---|---|
| Dates | Parsed against `DATE_INPUT_FORMATS` in order, emitted as `YYYY-MM-DD`. A time after the date, as Salesforce exports a Date/Time field (`1/15/2025 10:30 AM`, `2025-01-15T14:30:00.000Z`), is dropped; an optional date that can't be read is left out with a warning. A time in UTC or with an offset (the API and Data Loader form) keeps the date written, which for an evening session in the US is already the next day, so wherever such a date is filed an `AMBIGUOUS_DATE` warning names the value and the date filed |
| Ambiguous dates | `03/04/2025` is read US-style (March 4) **and flagged** as `AMBIGUOUS_DATE`. A slash date only day-first can read (`13/01/25`, `15/01/2025`) is read day-first, before the year-first `%y/%m/%d` that used to turn `13/01/25` into 2013-01-25 |
| Phone numbers | Reduced to digits; a leading country-code digit is dropped from an 11-digit number; too-short numbers are rejected rather than emitted malformed |
| Money | Parsed with `Decimal`, never `float`, so large financials do not lose precision. An exponent is written out (`1.5E+6` → `1500000`), so an amount too large for its field (`1E+40`) is omitted by the schema check as over the maximum; only a magnitude past 10^1000 is unreadable |
| Percentages | Clamped to 0–100, recorded as `CLAMPED_VALUE` |
| States | Standardized to the schema's spelling (`IA` → `Iowa`) |
| Countries | Mapped to the schema's country codes; `EXPORT_COUNTRY_CODES` is pinned by a drift-guard test |
| Enumerations | Ethnicity, disability, military status and race are classified onto XSD values instead of passed through raw (a race outside the list is filed as self-described). An ethnicity or disability label that declines the question ("Decline to answer", "Unknown") is `Prefer not to say`, but one that also gives the answer ("Hispanic or Latino (origin unknown)") keeps it. Punctuation in a race answer reads as a space (`African-American`), and `Alaskan Native` is Native American/Alaska Native. Gender is read by whole words of any alphabet, so `Préfère ne pas répondre` is not Female |
| Multi-value fields | Split on `;` (`MULTI_VALUE_DELIMITER`) |
| Headers | Whitespace-normalized, so a trailing space in an export header does not break every lookup; invisible format characters are removed |
| Cells | An Excel error (`#N/A`, `#REF!`, ...) or a cell of only invisible characters or `�` is blank; one file-level warning counts the Excel errors, and one per column names the rows whose cells held only invisible or unreadable characters |
| Rows | A blank row, a repeat of the header row, or a title/footer line (one filled cell in a file of three or more columns) is skipped with a warning naming it; a row with values past the last column, and a cell that swallowed further rows (an unclosed quote), are reported |
| Identifiers | `Contact ID`, `Activity ID`, `Member ID` and `Class/Event ID` lose invisible format characters, and control characters become a space, before they are compared or grouped, as `STANDARDIZED_VALUE` |
| Empty optionals | **Omitted entirely** — never emitted as `<Element/>`, which would fail the element's pattern or type facet |
| Schema facets | Checked on every element against the XSD itself (`src/schema_rules.py`): enumeration values matched case-insensitively (`english` → `English`, `Y` → `Yes`); text over the schema's length truncated as `TRUNCATED_VALUE` (a middle name keeps its initial; Contact and Activity IDs are never cut); control characters replaced; codes beyond the schema's repeat limit (Media allows 13) dropped as `DOWNGRADED_VALUE`; anything still invalid omitted as `INVALID_VALUE` where the element is optional. Whether a value is valid is decided by libxml2 against the element's own type, so the guard and SBA's validation never disagree about a pattern, a number or a date. Where it is required (an ID over 20 characters, a `LocationCode` that isn't a number), the record is **left out of the XML** with an error naming the row, and the rest of the file is filed |

### Issue categories

Every issue in the report carries one of these (`src/config.py:ValidationCategory`):

`missing_required_field` · `missing_field` · `invalid_format` · `invalid_value` ·
`invalid_date` · `truncated_value` · `standardized_value` · `processing_error` ·
`file_access` · `file_write` · `ambiguous_date` · `clamped_value` ·
`fabricated_default` · `downgraded_value`

The last two are the ones to read first: `fabricated_default` means a value in
your filing did not come from your CSV, and `downgraded_value` means data was
dropped to satisfy the schema.

---

## Fabricated defaults

When a column is absent, the counseling converter fills some fields with a
non-empty value. That value ships in a federal filing, so each one is recorded as
a `FABRICATED_DEFAULT` issue naming the column and the value emitted.

| Missing column | Value emitted |
|---|---|
| `Gross Revenues/Sales` | `0` |
| `Profits/Losses` | `0` |
| `SBA Loan Amount` | `0` |
| `Non-SBA Loan Amount` | `0` |
| `Amount of Equity Capital Received` | `0` |
| `Business Ownership - % Female(old)` | `0` |
| `Mailing Country` | `United States` |
| `Conduct Business Online?` | `No` |
| `8(a) Certified?(old)` | `No` |
| `Are you currently exporting?(old)` | `No` (in both Part 2 and Part 3) |
| `Duration (hours)` | `0.5` contact hours — only for session types that require contact hours; a `0` is replaced the same way |
| `Services Provided` | `Business Start-up/Preplanning` |

A cell that is present but unusable (`n/a`, a `0` duration) is replaced the same
way, and the issue quotes what the cell held. Accounting-format negatives such as
`(1,500)` are read as `-1500`, not replaced.

What is **not** fabricated: a blank Part 3 `Total Number of Employees` is omitted,
as in Part 2, rather than filed as `0`; `ExportGrossRevenuesOrSales` (no CSV column
holds it) is `0` only for a client who is not exporting and omitted for an
exporter; `Services Provided = Other` is filed as `Other`. When `Reportable Impact`
is `Yes`, `Verified To Be In Business` is recorded as `Yes` whatever the CSV says,
and that override is recorded as a `DOWNGRADED_VALUE`. Counselor notes over 1,000
characters are cut at a sentence or word boundary near the limit and recorded as
`TRUNCATED_VALUE`.

The training converter records a `FABRICATED_DEFAULT` for a blank `Training Topic`
(→ `Technology`) or `Class/Event Type` (→ `In-person`), and an `INVALID_VALUE` for an
event type it doesn't recognize. Values configured rather than read — the location
code, sessions, hours, partner, fees and language for training; hours trained,
employees trained, session type and every other default the shorter training-client
form has no column for — are listed once per file in a `configured_defaults` warning.
A training-client row's own cell is still reported when it can't be used (a `%
Female` of `Majority` filed as `0`), and the 0.5 contact hours filed for a session
type that needs them say the duration was blank, not that the configured `0` was
the row's.

A missing column and a real zero are indistinguishable in the XML — the report is
the only place the difference is visible. This is why the worker **warns** at
conversion time when a fabrication-risk column is absent, and why the mapping
page flags them in the UI.

## ⚠ This is a single-organization tool

`src/config.py` hardcodes one organization's identity, and it is stamped into
**every** filing this tool produces:

```python
GeneralConfig.DEFAULT_LOCATION_CODE            = "249003"
TrainingConfig.DEFAULT_TRAINING_PARTNER_CODE   = "Women's Business Center"
TrainingConfig.DEFAULT_LOCATION                = {"city": "Des Moines", "state": "Iowa",
                                                  "zip": "50312", "country": "United States"}
TrainingConfig.DEFAULT_START_DATE              = "2023-12-12"
```

Every XML file carries `<LocationCode>249003</LocationCode>` unless the CSV has a
`LocationCode` column (all three converters read one). Training files carry
`<City>Des Moines</City>` and `<Code>Women's Business Center</Code>`. Any event
with an unparseable start date becomes 2023-12-12.

This was reviewed and **accepted as correct for a single-organization
deployment** ([`reviews/CODEBASE_ANALYSIS.md` §1.6](./reviews/CODEBASE_ANALYSIS.md)).
What changed was visibility: `_warn_constant_defaults()` records one file-level
`FABRICATED_DEFAULT` warning per conversion naming every value emitted from
configuration, and per-event warnings fire when a blank or unusable cell falls
back to the configured location, event title or start date.

**If a second organization ever uses the same deployment, this is a data-integrity
bug, not a configuration preference.** The web app has open signup, so a shared
deployment must move tenant identity into per-user settings before onboarding
anyone else. Treat that as a prerequisite, not a nice-to-have.

Other configured constants that appear in output without coming from your CSV:

| Constant | Value |
|---|---|
| `GeneralConfig.DEFAULT_LANGUAGE` | `English` |
| `GeneralConfig.DEFAULT_BUSINESS_STATUS` | `No` |
| `TrainingConfig.DEFAULT_TRAINING_SESSIONS` | `1` |
| `TrainingConfig.DEFAULT_TRAINING_HOURS` | `1.5` |
| `TrainingConfig.DEFAULT_TRAINING_FEES` | `0` |
| `TrainingConfig.DEFAULT_TRAINING_TOPIC` | `Technology` |
| `TrainingConfig.DEFAULT_PROGRAM_FORMAT` | `In-person` |
| `TrainingConfig.DEFAULT_TRAINING_EVENT_TITLE_PREFIX` | `Training Event ` |

---

## Outputs

Every conversion produces:

- **The XML**, ordered to satisfy the schema.
- **A pass/fail** against the bundled XSD, with each failure mapped back to a CSV
  row and column name by `src/xsd_error_mapping.py`.
- **A validation report** — CSV and HTML from the CLI (`reports/`), rendered
  in-page by the web app — listing every issue by category and severity.
- **A cleaning diff** (web only) showing each value the tool changed, with the
  before, the after, and the rule that changed it.

## Known gaps

From [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md), still open:

- **Training demographics count rows, not distinct people.** Total is
  `max(len(rows), 1)`. An attendee listed twice is counted twice.
- **A training event's location is read from the `City`/`State`/`Zip` columns**,
  which in a campaign-member export are each attendee's mailing address. The
  first complete address among the event's rows is filed as the event's. Rows
  that give different addresses are not reported, since in such an export
  they differ on nearly every event.
- **The counseling converter still reads ~70 headers as string literals**
  (§5.2), so a differently-named column must be mapped, not auto-detected.
- **`training` has no exact-match required-column check** in the worker, on
  purpose: it resolves `Class/Event ID` through aliases, and a hard-fail on the
  exact spelling would reject valid aliased uploads. The converter flags a
  missing event id itself.
