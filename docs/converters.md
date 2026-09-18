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
- **Field length caps**, applied with a record rather than a silent trim:

  | Element | Max |
  |---|---|
  | `CounselorNotes` | 1000 |
  | `Last`, `First` | 40 |
  | `Middle` | 1 |
  | `Street1`, `Street2`, `City` | 80 |
  | `Phone` | 10 |
  | `PartnerClientNumber`, `PartnerSessionNumber` | 20 |

- **Part 3 impact fallbacks.** `Date Started (Meeting)`,
  `Total No. of Employees (Meeting)`, `Gross Revenues/Sales (Meeting)` and
  `Profit & Loss (Meeting)` fall back to their intake counterparts when blank.
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
- **Event-level fields come from the first row of each group**
  (`training_converter.py:142`). If two rows for the same event disagree about
  the event name or start date, the first row wins and the disagreement is not
  reported. See [Known gaps](#known-gaps).

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

Applied by `src/data_cleaning.py` to every converter. The results page shows a
before/after diff for the date, phone, gender, numeric/money, percentage, state
and country cleaners. Two kinds of change are **not** in the diff today: the
enumeration mappers (ethnicity, disability, military status, export countries,
counselor-notes scrubbing) and any value a cleaner drops entirely (an
unparseable phone number, a bad date, an unknown country) — a dropped value is
omitted from the XML with no diff row and no issue. Tracked as
[`reviews/CODEBASE_ANALYSIS_2.md` §2.6 and §2.8](./reviews/CODEBASE_ANALYSIS_2.md).

| Rule | Behaviour |
|---|---|
| Dates | Parsed against `DATE_INPUT_FORMATS` in order, emitted as `YYYY-MM-DD` |
| Ambiguous dates | `03/04/2025` is read US-style (March 4) **and flagged** as `AMBIGUOUS_DATE` |
| Phone numbers | Reduced to digits; a leading country-code digit is dropped from an 11-digit number; too-short numbers are rejected rather than emitted malformed |
| Money | Parsed with `Decimal`, never `float`, so large financials do not lose precision |
| Percentages | Clamped to 0–100, recorded as `CLAMPED_VALUE` |
| States | Standardized to the schema's spelling (`IA` → `Iowa`) |
| Countries | Mapped to the schema's country codes; `EXPORT_COUNTRY_CODES` is pinned by a drift-guard test |
| Enumerations | Ethnicity, disability and military status are classified onto XSD values instead of passed through raw |
| Multi-value fields | Split on `;` (`MULTI_VALUE_DELIMITER`) |
| Headers | Whitespace-normalized, so a trailing space in an export header does not break every lookup |
| Empty optionals | **Omitted entirely** — never emitted as `<Element/>`, which would fail the element's pattern or type facet |

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
non-empty value. That value ships in a federal filing. For the nine columns in
`COUNSELING_FABRICATION_DEFAULTS` each substitution is recorded as a
`FABRICATED_DEFAULT` issue naming the column and the value emitted, and the
mapping page warns when the column is missing:

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

A missing column and a real zero are indistinguishable in the XML — the report is
the only place the difference is visible. This is why the worker **warns** at
conversion time when a fabrication-risk column is absent, and why the mapping
page flags them in the UI.

### Fabricated values that are *not* yet recorded

The following values are also emitted without coming from your CSV, but today
they produce **no** `FABRICATED_DEFAULT` issue and no mapping-page warning. They
are tracked as open items in
[`reviews/CODEBASE_ANALYSIS_2.md` Tier 2](./reviews/CODEBASE_ANALYSIS_2.md);
until they are fixed, check these by hand before filing.

| Converter | Field | Trigger | Value emitted |
|---|---|---|---|
| Counseling | `CounselingHours/Contact` | `Duration (hours)` blank or `0` on a session type that requires contact hours | `0.5` |
| Counseling | Part 3 `TotalNumberOfEmployees` | column blank or missing | `0` |
| Counseling | Part 3 `CurrentlyExporting` | always — `Are you currently exporting?(old)` is only read for Part 2 | `No` |
| Counseling | `ExportGrossRevenuesOrSales` (Part 2 and Part 3) | always | `0` |
| Training | `TrainingTopic/Code` | `Training Topic` blank (an *unrecognized* topic does warn) | `Technology` |
| Training | `ProgramFormat` | `Class/Event Type` blank or unrecognized | `In-person` |
| Training client | `HoursTrained` / `EmployeesTrained` | every record | `1.5` / `1` |
| Training client | `SessionType`, `Language`, `Services Provided` | every record (columns the short form does not collect) | `Training`, `English`, `Business Start-up/Preplanning` |

The training-client converter deliberately suppresses per-row warnings for the
columns it injects (`training_client_converter.py`), and has no file-level
summary equivalent to the training converter's `_warn_constant_defaults()`.

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

Every XML file carries `<LocationCode>249003</LocationCode>`. Training files carry
`<City>Des Moines</City>` and `<Code>Women's Business Center</Code>`. Any event
with an unparseable start date becomes 2023-12-12.

This was reviewed and **accepted as correct for a single-organization
deployment** ([`reviews/CODEBASE_ANALYSIS.md` §1.6](./reviews/CODEBASE_ANALYSIS.md)).
What changed was visibility: `_warn_constant_defaults()` records one file-level
`FABRICATED_DEFAULT` warning per conversion naming every value emitted from
configuration, and per-event warnings fire when a blank cell falls back to the
configured location, event title or start date.

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
- **Event-level fields are taken from the first row of the group.** Rows
  disagreeing about event name, type or start date are silently overruled.
- **The counseling converter still reads ~70 headers as string literals**
  (§5.2), so a differently-named column must be mapped, not auto-detected.
- **`training` has no exact-match required-column check** in the worker, on
  purpose: it resolves `Class/Event ID` through aliases, and a hard-fail on the
  exact spelling would reject valid aliased uploads. The converter flags a
  missing event id itself.
