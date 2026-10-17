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
dropped silently. The web worker also refuses a file that lacks any of eleven
other columns ([csv-reference.md](./csv-reference.md#counseling-form-641)); the
command line needs only `Contact ID`.

What it handles that hand-built XML usually gets wrong:

- **Conditional elements.** `BranchOfService` is emitted only when the military
  status indicates service, `LegalEntity` only for a client in business, and
  `FIPS_Code` only beside a `Rural_vs_Urban` of `Rural` or `Urban`, because SBA
  asks for them only then. A filled cell its case doesn't call for (`Army` beside
  a Veteran Status of `No`) is left out with a `DOWNGRADED_VALUE` warning saying
  why. When the case does call for one and it is blank — a branch for a veteran,
  a legal entity or the counseling sought for a client in business, a
  `FIPS_Code` for `Rural`/`Urban`, the text for a counseling sought or provided
  of `Other`, the internet source for a media answer of `Internet` — a
  `MISSING_REQUIRED` error is recorded but the record is still filed: the XSD
  can't express these conditions, so the file validates. A blank legal entity
  is filed as `Other`. `Other legal entity (specify)` is filed as
  `LegalEntity/Other` whenever it is filled, beside whatever code is given.
- **Session types without contact hours.** `Prepare Only`, `Training` and
  `Update Only` are contact-hour-free session types and are treated as such.
  `Update` reads as `Update Only`, and case, spaces and hyphens are ignored
  (`Face to Face` is `Face-to-face`); a blank or unrecognized type is filed as
  `Telephone` with an `INVALID_VALUE` warning.
- **Multi-value Salesforce fields.** `Race`, `Services Provided` and the media,
  legal-entity, counseling-sought, certification, financial-assistance,
  referral, language and export-country columns arrive semicolon-delimited and
  are split into repeated elements — except `Services Provided` and
  `Nature of the Counseling Seeking?`, where the schema allows only one code: the
  first is kept and the dropped values are recorded as a `DOWNGRADED_VALUE` issue
  so the loss stays auditable. A cell holding only separators (`;`) counts as
  blank, so the usual default applies rather than a code list with no code.
- **Race answers outside SBA's nine codes.** "Two or More Races", "Middle
  Eastern or North African", "Hispanic or Latino" and the like are filed the way
  the schema provides: `Prefer to Self-Describe`, with the answer as written in
  `SelfDescribedRace` (up to 80 characters) and an `INVALID_VALUE` warning.
  Answers that decline the question ("Decline to answer", "Unknown", "N/A") are
  `Prefer not to say`, the value SBA renamed "Unknown/Not Stated" to.
- **"Other" text with no code.** `Nature of the Counseling Seeking - Other
  Detail` without a `Nature of the Counseling Seeking?` answer is filed under the
  code `Other`; on its own it would leave the section without the `Code` the
  schema requires. The "Other" text of legal entity, certifications and referral
  is filed under `Other` the same way, and of SBA financial assistance under
  `Other(SBIR, SBIC, 7(a) 504, etc)`, each with a `DOWNGRADED_VALUE` warning.
- **Internet source.** `Internet (specify)` fills the schema's `Internet`
  element (the internet source behind a media answer of `Internet`), with
  `InternetUsage` as the fallback. It is not written to `Media/Other`, which SBA
  defines as the text for a media answer of `Other`.
- **Field length caps**, read from the XSD itself (`src/schema_rules.py`) and
  applied with a record rather than a silent trim. Among them:

  | Element | Max |
  |---|---|
  | `CounselorNotes` | 1000 |
  | `Last`, `First` | 40 |
  | `Middle` | 1 |
  | `Street1`, `Street2`, `City`, `CompanyName`, `Internet`, `SelfDescribedRace` | 80 |

  `PartnerClientNumber` and `PartnerSessionNumber` (20) are never cut: a longer
  ID leaves the record out with an error, since a shortened one names a
  different client or session. A phone number is not cut either; one that isn't
  ten digits is left out (see [the cleaning rules](#the-cleaning-rules)).

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

**Required column:** `Class/Event ID`, matched by that exact header (it has no
aliases). Without it the conversion fails; a row with a blank one is an error
and is left out.

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
  state. A `Cosponsor` of `N/A`, `None` or `-` means there was none.

Each attendee row is counted with the counseling form's readers
(`src/data_cleaning.py`): gender by whole word, race by keyword at the start of a
word (a multi-race answer counts once in each of its categories), `Not Hispanic`
apart from `Hispanic`, and a Veteran Status checkbox (`Yes`/`No`) as a veteran
or not. A blank or unrecognized answer lands in no count, and the race and
military answers no count takes (`Two or More Races`, `Retired`) are named in
one `INVALID_VALUE` warning per event. The underserved total counts each
attendee who is Hispanic or gives any race but White, once. `CurrentlyInBusiness`
and `NotYetInBusiness` are emitted only when the file has a business-status
column.

Column matching for this converter is **alias-based**: `TrainingConfig.COLUMN_MAPPING`
lists several accepted spellings per field (`Cosponsor` / `CosponsorsName` /
`Partner Organization`, and so on), so common export variations work without a
manual mapping. Full list in [csv-reference.md](./csv-reference.md#training-form-888).

## `training-client` — Form 641 from training rows

The smallest converter (176 lines) and the one that shows the intended shape:
it reuses the counseling pipeline through explicit hooks. `_preprocess_row`
renames the columns and supplies counseling-specific defaults
(`TrainingClientConfig`); `_partner_session_number`, `_resolve_in_business` and
`_build_counselor_record_section` shape the record; `_warn_constant_defaults`,
`_check_renamed_columns`, `_check_session_column` and `_csv_cell` adjust what is
reported.

**Required columns:** `Contact ID` (a row without one is an error) and, in the
web worker, a `Class/Event ID` column.
**Conditional:** `Member ID` — the per-attendee session id; falls back to
`Class/Event ID` when absent or blank, which makes every attendee at an event
share a session number. A row with neither is filed with an empty session
number and a warning.

What it adds to the counseling record:

- **The event's `Training Topic`** is filed as the counseling sought and the
  counseling provided wherever those columns are blank.
- **`Currently in Business?` = `Yes` is filed as `No`**, with a
  `DOWNGRADED_VALUE` warning, unless the row also gives a legal entity and the
  counseling sought (a topic counts): SBA asks both of a client in business, and
  the training form doesn't collect them.
- **`TrainingSession`**, the record's last element: the start date, the event
  id, and the configured `EmployeesTrained` = 1 and `HoursTrained` = 1.5.

Because it emits counseling XML, its output validates against the **counseling**
XSD, not the training one. The web UI, the worker and `run.py` all apply that
rule automatically.

---

## The cleaning rules

Applied to every converter, by `src/data_cleaning.py` unless the row names
another module. Every change is recorded, so the results page can show a
before/after diff for each value.

| Rule | Behaviour |
|---|---|
| Encoding | UTF-16 when the file starts with its BOM, else UTF-8, else Windows-1252 (`decode_csv_bytes`), the order the web upload uses. A Windows-1252 file, or a damaged UTF-16 one (bytes that aren't text read as `�`, a stray last byte left out), gets a file-level `FILE_ACCESS` warning. Details in [csv-reference.md](./csv-reference.md#how-columns-are-matched) |
| Dates | Parsed against `DATE_INPUT_FORMATS` in order — numeric forms and month names (`Jan 15, 2025`, `January 15, 2025`) — and emitted as `YYYY-MM-DD`; a two-digit year more than a year ahead is last century (`01/05/68` is 1968). A time after the date, as Salesforce exports a Date/Time field (`1/15/2025 10:30 AM`, `2025-01-15T14:30:00.000Z`), is dropped; an optional date that can't be read is left out with a warning. A time in UTC or with an offset (the API and Data Loader form) keeps the date written, which for an evening session in the US is already the next day, so wherever such a date is filed an `AMBIGUOUS_DATE` warning names the value and the date filed |
| Ambiguous dates | `03/04/2025` is read US-style (March 4) **and flagged** as `AMBIGUOUS_DATE`. A slash date only day-first can read (`13/01/25`, `15/01/2025`) is read day-first, before the year-first `%y/%m/%d` that used to turn `13/01/25` into 2013-01-25 |
| Phone numbers | Read as ten ASCII digits, with a leading `1` or `+1` country code dropped; whatever follows the number, such as an extension or a second number (`515-555-1234 x12`), is cut off where it starts. A number that is too short, whose digits run on past ten (`515-555-12345`), or that has another country code (`+44 20 7946 0958`) is left out with a warning. Such numbers used to be cut to their first ten digits, filing a different number without a word |
| Money | Parsed with `Decimal`, never `float`, so large financials do not lose precision. An exponent is written out (`1.5E+6` → `1500000`), so an amount too large for its field (`1E+40`) is omitted by the schema check as over the maximum; only a magnitude past 10^1000 is unreadable |
| Percentages | Clamped to 0–100, recorded as `CLAMPED_VALUE`. Text that isn't a number (`Majority`, `NaN%`) is filed as `0` and recorded as `FABRICATED_DEFAULT` |
| States | Standardized to the schema's spelling (`IA` → `Iowa`, `D.C.` → `District of Columbia`); a value the schema doesn't list (`Ontario`) is left out with a warning |
| Countries | Mapped to the schema's country names (`USA` → `United States`, `UK` → `United Kingdom`, case ignored); one not in the list is left out with a warning. `EXPORT_COUNTRY_CODES` is pinned by a drift-guard test |
| Enumerations | Ethnicity, disability, military status and race are classified onto XSD values instead of passed through raw (a race outside the list is filed as self-described). An ethnicity or disability label that declines the question ("Decline to answer", "Unknown") is `Prefer not to say`, but one that also gives the answer ("Hispanic or Latino (origin unknown)") keeps it. Punctuation in a race answer reads as a space (`African-American`), and `Alaskan Native` is Native American/Alaska Native. Gender is read by whole words of any alphabet, so `Préfère ne pas répondre` is not Female. A Veteran Status checkbox is `Veteran` or `No military service`, as is `Non-veteran`; `USMC` is `Marine Corps`. An answer that maps to none of the schema's values is left out with an `INVALID_VALUE` warning |
| Yes/No columns | `yes`/`y`/`true`/`1` and `no`/`n`/`false`/`0` in any case (`Undetermined` too where the schema has it; `CounselingConverter._yes_no`). Anything else is filed as the column's default with an `INVALID_VALUE` warning, so `Maybe` can't quietly become a federal `No` |
| Multi-value fields | Split on `;` (`MULTI_VALUE_DELIMITER`) |
| Headers | Whitespace-normalized, so a trailing space in an export header does not break every lookup; invisible format characters are removed. A header that appears twice is reported, and each row uses the last of those columns that has a value |
| Surrounding spaces | Trimmed from every value filed. First and last name and the company name used to be filed as written (`<Last>  Doe </Last>`), the one place a padded cell reached the XML; `tests/test_conversion_invariants.py` pads every cell to keep it that way |
| Cells | An Excel error (`#N/A`, `#REF!`, ...) or a cell of only invisible characters or `�` is blank; one file-level warning counts the Excel errors, and one per column names the rows whose cells held only invisible or unreadable characters |
| Rows | A blank row, a repeat of the header row, or a title/footer line (one filled cell in a file of three or more columns) is skipped with a warning naming it (`src/data_validation.py`); a row with values past the last column, and a cell that swallowed further rows (an unclosed quote), are reported |
| Identifiers | `Contact ID`, `Activity ID`, `Member ID` and `Class/Event ID` lose invisible format characters, and control characters become a space, before they are compared or grouped, as `STANDARDIZED_VALUE` (`src/schema_rules.py:clean_identifier`) |
| Empty optionals | **Omitted entirely** — never emitted as `<Element/>`, which would fail the element's pattern or type facet |
| Schema facets | Checked on every element against the XSD itself (`src/schema_rules.py`): enumeration values matched case-insensitively (`english` → `English`, `Y` → `Yes`); text over the schema's length truncated as `TRUNCATED_VALUE` (a middle name keeps its initial; Contact, Activity, Member and Class/Event IDs are never cut); control characters replaced with a space as `STANDARDIZED_VALUE`; codes beyond the schema's repeat limit (Media allows 13, LegalEntity 6) dropped as `DOWNGRADED_VALUE`; anything still invalid omitted as `INVALID_VALUE` where the element is optional, and a code list such as `Media` left with no valid code dropped whole as `DOWNGRADED_VALUE`. Whether a value is valid is decided by libxml2 against the element's own type, so the guard and SBA's validation never disagree about a pattern, a number or a date. Where it is required (an ID over 20 characters, a `LocationCode` that isn't a number), the record is **left out of the XML** with an error naming the row, and the rest of the file is filed |
| Final XSD check | The written file is validated against the XSD (`BaseConverter._write_valid_xml`), the safety net under the facet checks. A record that still fails is left out with an `INVALID_VALUE` error per XSD message naming its row, and the file is written again, so the file kept is one SBA's schema accepts. A failure no record explains is a file-level `PROCESSING_ERROR` on the command line (the web shows the XSD errors themselves); a file with no record left fails the conversion |

### Issue categories

Every issue in the report carries one of these (`src/config.py:ValidationCategory`),
with a severity of `error` or `warning`:

| Category | Severity | Recorded when |
|---|---|---|
| `missing_required_field` | error | A row has no `Contact ID` (counseling forms) or `Class/Event ID` (training) and is left out, or the file has no rows, no `Class/Event ID` column, or nothing that converts. Also when a value SBA asks for only in some case is blank, or was dropped as one SBA doesn't accept (see [conditional elements](#counseling--form-641)); that record is still filed |
| `missing_field` | warning | A blank last or first name; a blank `Race`, filed as `Prefer not to say`; a blank session number, or no `Activity ID` column; a training location filed without a ZIP. From the worker: a conditional or fabrication-risk column the file lacks, or a saved mapping for a column it lacks |
| `invalid_format` | warning; error for an unclosed quote | A cell that isn't a date, number, phone or ZIP this tool can read, left out or passed over for a fallback column; a row skipped as not a record; a repeated header, or both columns of a training-client rename; rows with values past the last column. An error for a cell that swallowed the rows after it |
| `invalid_value` | warning; error when a record is left out | An answer SBA doesn't accept, left out or filed as the column's default; a race filed as self-described; an event's rows giving different values; a training answer no count takes; cells of Excel errors or invisible characters read as blank. An error for a required value the schema rejects, or a record the final XSD check rejects: the record is left out |
| `invalid_date` | warning | A counseling or training-client session date before the start of the current fiscal year (October 1) |
| `ambiguous_date` | warning | A date month-first and day-first read differently (filed month-first), or a date-time in UTC or at an offset (filed with the date written) |
| `truncated_value` | warning | Text over the schema's length was cut; counselor notes at a sentence or word |
| `clamped_value` | warning | A `% Female` outside 0–100 was clamped |
| `standardized_value` | warning | Characters XML can't carry were replaced with a space, or invisible characters taken out of an ID |
| `fabricated_default` | warning | A value that is not in the CSV was filed: a default for a blank or unusable cell, or, once per file under `configured_defaults`, the values taken from configuration |
| `downgraded_value` | warning | A value the CSV gave was dropped or overridden: codes past the schema's limit or its one-code sections, a code list with no valid code, a cell its case doesn't call for, an `Employee Owned` that isn't Yes or No, a code of `Other` filed for "Other" text, `Verified To Be In Business` set to `Yes`, a training client's in-business `Yes` filed as `No` |
| `processing_error` | error | An unexpected error while building a record (it is left out), or a file that fails the XSD with no record to blame |
| `file_access` | error; warning | The CSV can't be read (error); it was read as Windows-1252 or damaged UTF-16 (warning) |
| `file_write` | error | The counseling or training-client XML couldn't be written |

An issue's `record_id` is the Contact ID or event id, `Row_N` for a row without
one, or `file` for the file as a whole. An error does not always mean a record is
missing from the XML; the summary's failed-record count is what was left out.

`fabricated_default` and `downgraded_value` are the ones to read first:
`fabricated_default` means a value in your filing did not come from your CSV, and
`downgraded_value` means data was dropped to satisfy the schema.

---

## Fabricated defaults

When a column is absent or its cell blank, the counseling converter fills some
fields with a non-empty value. That value ships in a federal filing, so each one
is recorded as a `FABRICATED_DEFAULT` issue naming the column and the value
emitted (`src/config.py:COUNSELING_FABRICATION_DEFAULTS`).

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

A number cell that is present but unusable (`n/a`, a `0` duration) is replaced the
same way, and the issue quotes what the cell held. Accounting-format negatives such
as `(1,500)` are read as `-1500`, not replaced. A Yes/No cell that is neither
(`Maybe`) is filed as `No` with an `INVALID_VALUE` warning instead, and a
`Mailing Country` SBA doesn't list is left out.

The counseling converter fills these for a blank cell or absent column without a
`FABRICATED_DEFAULT` — the form's own reading of a blank, a required element's
fallback, or configuration (see the [single-organization
section](#-this-is-a-single-organization-tool)). The training-client form names
most of them in its `configured_defaults` warning instead (below):

| Blank or absent | Filed as | Reported |
|---|---|---|
| `Agree to Impact Survey`, `Client Signature(On File)`, `Currently In Business?`, `Reportable Impact` | `No` | not reported |
| `Verified To Be In Business`, `Rural_vs_Urban` | `Undetermined` | not reported |
| `Language(s) Used` | `English` | not reported |
| `Prep Hours`, `Travel Hours` | `0` | not reported (see [Known gaps](#known-gaps)) |
| `Type of Session` | `Telephone` | not reported when the column is absent; an `INVALID_VALUE` warning for a blank cell |
| `LocationCode` | `249003` | not reported on the counseling form |
| `Race` | `Prefer not to say` | `MISSING_FIELD` warning |
| `Legal Entity of Business`, for a client in business | `Other` | `MISSING_REQUIRED` error; the record is still filed |

What is **not** fabricated: a blank Part 3 `Total Number of Employees` is omitted,
as in Part 2, rather than filed as `0`; `ExportGrossRevenuesOrSales` (no CSV column
holds it) is `0` only for a client who is not exporting and omitted for an
exporter; `Services Provided = Other` is filed as `Other`. When `Reportable Impact`
is `Yes`, `Verified To Be In Business` is recorded as `Yes` whatever the CSV says,
and that override is recorded as a `DOWNGRADED_VALUE`. Counselor notes over 1,000
characters are cut at a sentence or word boundary near the limit and recorded as
`TRUNCATED_VALUE`.

The training converter records a `FABRICATED_DEFAULT` per event for a blank
`Training Topic` (→ `Technology`), `Class/Event Type` (→ `In-person`) or
`Class/Event Name` (→ `Training Event <id>`), a blank or unreadable `Start Date`
(→ `2023-12-12`), and no row giving both a city and a state (→ the configured
location) — blank meaning blank in every row of the event. A topic or event type
it doesn't recognize is filed as the same default with an `INVALID_VALUE`.
Values configured rather than read — the location code, sessions, hours,
partner, fees and language for training; the location code, hours trained,
employees trained, session type and every other non-empty default the shorter
training-client form has no column for — are listed once per file in a
`configured_defaults` warning. The counseling converter records none.
A training-client row's own cell is still reported when it can't be used (a `%
Female` of `Majority` filed as `0`), and the 0.5 contact hours filed for a session
type that needs them say the duration was blank, not that the configured `0` was
the row's. Its revenue and profit are the exception: their default is blank, so
they appear in no `configured_defaults` list, and `0` is filed for them in Part 2
and Part 3 with no report at all — even for a `Gross Revenues/Sales` cell of the
CSV's own that reads `n/a`.

A missing column and a real zero are indistinguishable in the XML — the report is
the only place the difference is visible. This is why the worker **warns** at
conversion time when a fabrication-risk column is absent (a `MISSING_FIELD`
warning on the results page). The mapping page does not single them out: most
carry the plain **Optional** badge there.

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
`LocationCode` column (all three converters read one); a blank cell in it gets
`249003` too. Every training record carries
`<Code>Women's Business Center</Code>`, and an event no row of which gives a city
and a state carries `<City>Des Moines</City>`. Any event no row of which gives a
readable start date becomes 2023-12-12.

This was reviewed and **accepted as correct for a single-organization
deployment** ([`reviews/CODEBASE_ANALYSIS.md` §1.6](./reviews/CODEBASE_ANALYSIS.md)).
What changed was visibility: the training and training-client converters'
`_warn_constant_defaults()` records one file-level `FABRICATED_DEFAULT` warning
per conversion, field `configured_defaults`, naming every value emitted from
configuration, and per-event warnings fire when a blank or unusable cell falls
back to the configured location, event title or start date. Two gaps remain: the
counseling converter's `_warn_constant_defaults()` records nothing, so a
counseling file without a `LocationCode` column is filed under `249003` with no
warning; and the training-client warning names `LocationCode='249003'` even when
the CSV's own `LocationCode` column is what was filed.

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
| `CounselingConfig.DEFAULT_SESSION_TYPE` | `Telephone` |
| `CounselingConfig.DEFAULT_URBAN_RURAL` | `Undetermined` |
| `TrainingClientConfig.EMPLOYEES_TRAINED` | `1` |
| `TrainingClientConfig.HOURS_TRAINED` | `1.5` |
| `TrainingClientConfig.DEFAULTS` | every counseling column the training form lacks; the non-empty ones are listed in its `configured_defaults` warning |

---

## Outputs

Every conversion produces:

- **The XML**, ordered to satisfy the schema, and checked against the bundled
  XSD by the converter itself before it is kept: a record that fails is left out,
  with its row and the XSD message in the report (see
  [Final XSD check](#the-cleaning-rules)).
- **A pass/fail** against the bundled XSD on the web results page (and from
  `run.py` when asked), with each failure mapped back to a CSV row and column
  name by `src/xsd_error_mapping.py`.
- **A validation report** — CSV and HTML from the CLI (`reports/`), rendered
  in-page by the web app — listing every issue by category and severity.
- **A cleaning diff** (web only) showing each value the tool changed, with the
  before, the after, and the rule that changed it.

## Known gaps

From [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md) and the
decisions in [`reviews/XSD_VALIDITY_ANALYSIS.md`](./reviews/XSD_VALIDITY_ANALYSIS.md#decisions-not-changed),
still open:

- **Training demographics count rows, not distinct people.** Total is
  `max(len(rows), 1)`. An attendee listed twice is counted twice.
- **A training event's location is read from the `City`/`State`/`Zip` columns**,
  which in a campaign-member export are each attendee's mailing address. The
  first row with a city, state and ZIP (else the first with a city and state)
  is filed as the event's. Rows that give different addresses are not reported,
  since in such an export they differ on nearly every event.
- **Training race answers that fit no category are reported, not counted.**
  `Two or More Races` and the like fit no single category and none is invented
  for them, so such an attendee is in no race count, and in the underserved
  total only if Hispanic.
- **Blank `Prep Hours` and `Travel Hours` are filed as `0`** without a warning:
  the form asks for them, `0` is the natural reading of a blank, and a warning on
  nearly every row would bury the report.
- **Two defaults are filed with no report at all**: a counseling file's
  `LocationCode` of `249003` when it has no such column, and a training client's
  revenue and profit of `0` (see [Fabricated defaults](#fabricated-defaults)).
- **Training counts "Middle Eastern or North African" twice** — once under
  `MiddleEastern` and once under `NorthAfrican` — because `classify_races`
  matches both keywords (`reviews/CODEBASE_ANALYSIS_3.md` D.9). The counseling
  forms file it as self-described.
- **The counseling converter reads 64 of its 74 headers as string literals**
  rather than through `CounselingConfig.COLUMN_MAPPING` (§5.2, counted at
  `7b14f3b`), and has no aliases, so a differently-named column must be mapped,
  not auto-detected.
- **`training` has no required-column check in the worker**
  (`column_requirements.get_requirement_sets` returns empty sets). The reason
  given there, that `Class/Event ID` is resolved through aliases, does not hold:
  `TrainingConfig.COLUMN_MAPPING["event_id"]` is the single header
  `Class/Event ID`. The converter fails the conversion itself when that exact
  header is missing, so the outcome is the same HTTP 422; only the message
  differs.
