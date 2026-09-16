# CSV input reference

What each converter expects in the header row, and what happens when a column is
absent.

## How columns are matched

1. **Headers are whitespace-normalized** (`src/data_cleaning.normalize_header`)
   before anything else, on both the preview path and the conversion path. A
   trailing space in an export header does not break the lookup, and the preview
   UI cannot disagree with what the converter actually reads.
2. **The file is read as `utf-8-sig`**, so an Excel BOM does not turn the first
   header into `﻿Contact ID`.
3. **Any column mapping you saved is applied first**, then required-column
   validation runs. A CSV you have correctly mapped is never rejected for a
   column name it no longer uses.
4. **Mapping entries whose target is not an expected column are dropped.** A
   mapping that renamed a real header to an internal key (`{"Class/Event ID":
   "event_id"}`) would rename the column out from under the converter, so such
   entries are ignored rather than applied.

## Requirement tiers

Defined once in `apps/worker/app/services/column_requirements.py` and shared by
the mapping page and the conversion.

| Tier | Column missing means | Where it shows |
|---|---|---|
| **Required** | Conversion fails with HTTP 422 naming the columns | Red on the mapping page; the convert button is blocked |
| **Conditional** | Warning — needed only when a related field has a particular value | Amber on the mapping page |
| **Fabrication-risk** | Warning — the converter will emit a non-empty default into your filing | Amber on the mapping page |
| **Optional** | Element is omitted | Not flagged |
| **Extra** | Column is ignored entirely | Listed as "extra" on the preview page |

Extra columns are harmless. The preview page also runs a fuzzy match (difflib,
0.6 cutoff) between missing and extra columns and suggests renames — that is what
catches `Zip Code` vs `Zip/Postal Code`.

---

## Counseling (Form 641)

**Required (12).** Missing any of these fails the conversion:

`Contact ID` · `Race` · `Ethnicity:` · `Gender` · `Disability` ·
`Veteran Status` · `Currently In Business?` · `Type of Session` ·
`Language(s) Used` · `Date` · `Name of Counselor` · `Duration (hours)`

> `Ethnicity:` really does end with a colon — that is the Salesforce export
> header, and it is matched literally.

**Conditional (9).** Each is required only in a particular case:

| Column | Required when |
|---|---|
| `Branch Of Service` | military status indicates service |
| `Internet (specify)` | the contact medium is Internet |
| `InternetUsage` | the contact medium is Internet |
| `Legal Entity of Business` | the client is in business |
| `Other legal entity (specify)` | legal entity is `Other` |
| `FIPS_Code` | Rural/Urban is set |
| `Nature of the Counseling Seeking?` | the client is in business |
| `Nature of the Counseling Seeking - Other Detail` | counseling sought is `Other` |
| `Other Counseling Provided` | counseling provided is `Other` |

**Fabrication-risk (9).** Absent → a non-empty value is invented. See
[converters.md](./converters.md#fabricated-defaults) for the exact values.

**Full expected set (74 columns).** These are the headers the converter reads;
anything else is extra.

<details>
<summary>All 74 counseling columns</summary>

```
Contact ID                                    Rural_vs_Urban
LocationCode                                  FIPS_Code
Last Name                                     Nature of the Counseling Seeking?
First Name                                    Nature of the Counseling Seeking - Other Detail
Middle Name                                   Export Countries
Email                                         Activity ID
Contact: Phone                                Funding Source
Contact: Secondary Phone                      Verified To Be In Business
Mailing Street                                Reportable Impact
Mailing City                                  Reportable Impact Date
Mailing State/Province                        Business Start Date
Mailing Zip/Postal Code                       Date Started (Meeting)
Mailing Country                               Total No. of Employees (Meeting)
Agree to Impact Survey                        Gross Revenues/Sales (Meeting)
Client Signature - Date                       Profit & Loss (Meeting)
Client Signature(On File)                     SBA Loan Amount
Race                                          Non-SBA Loan Amount
Ethnicity:                                    Amount of Equity Capital Received
Gender                                        Certifications (SDB, HUBZONE, etc)
Disability                                    Other Certifications
Veteran Status                                SBA Financial Assistance
Branch Of Service                             Other SBA Financial Assistance
What Prompted you to contact us?              Services Provided
Internet (specify)                            Other Counseling Provided
InternetUsage                                 Referred Client to
Currently In Business?                        Other (Referred Client to)
Are you currently exporting?(old)             Type of Session
Account Name                                  Language(s) Used
Type of Business                              Language(s) Used (Other)
Business Ownership - % Female(old)            Date
Conduct Business Online?                      Name of Counselor
8(a) Certified?(old)                          Duration (hours)
Employee Owned                                Prep Hours
Total Number of Employees                     Travel Hours
Number of Employees in Exporting Business     Comments
Gross Revenues/Sales
Profits/Losses
Legal Entity of Business
Other legal entity (specify)
```

</details>

The canonical list is `CounselingConfig.COLUMN_MAPPING` in `src/config.py`
(73 declared entries; `expected_columns()` unions the fallback chains to 74).
Four other structures are keyed by these columns —
`xsd_error_mapping._COUNSELING_ELEMENT_FIELDS`,
`diff_service.COUNSELING_CLEANING_MAP`, the `column_requirements` tier sets and
`COUNSELING_FIELD_METADATA` — and tests pin all of them to the mapping so they
cannot drift apart again.

### Sample

`apps/web/public/samples/counseling-sample.csv` carries 16 columns — the 12
required ones plus name, email and mailing state — and validates clean. Its
header row, wrapped here for readability but a single line in the file:

```
Contact ID,Last Name,First Name,Email,Mailing State/Province,Race,Ethnicity:,
Gender,Disability,Veteran Status,Currently In Business?,Type of Session,
Language(s) Used,Date,Name of Counselor,Duration (hours)
```

---

## Training (Form 888)

**Required (1):** `Class/Event ID`.

The worker does **not** hard-fail on the exact spelling for this converter,
because the converter resolves the column through aliases and flags a missing
event id itself. An exact-match check here would reject valid aliased uploads.

**Alias-based matching.** Each field accepts several spellings; the first one
present wins:

| Field | Accepted headers |
|---|---|
| Event ID | `Class/Event ID` |
| Event name | `Class/Event Name` |
| Start date | `Start Date` |
| Funding source | `Funding Source` |
| Training topic | `Training Topic` |
| Event type | `Class/Event Type` |
| Cosponsor | `Cosponsor`, `CosponsorsName`, `Partner Organization` |
| City | `City`, `city`, `Address`, `Street Line 1` |
| State | `State/Province`, `State`, `state` |
| ZIP | `Zip/Postal Code`, `Zip`, `zip`, `ZipCode`, `Zip code` |
| In business | `Currently in Business?`, `Currently in Business`, `In Business` |
| Gender | `Gender`, `gender`, `Sex` |
| Disability | `Disabilities`, `Disability`, `Has Disability` |
| Military | `Military Status`, `Military`, `Veteran Status` |
| Race | `Race`, `race`, `Racial Background` |
| Ethnicity | `Ethnicity`, `ethnicity`, `Ethnic Background` |

The mapping page shows the first spelling of each as the "expected" name.

**No total columns are needed.** Supply one row per attendee; the converter
computes female/male, race, ethnicity, veteran, disability and business-status
totals per event.

**Missing location.** If city, state and a 5-digit ZIP are not all present for an
event, the whole `TrainingLocation` falls back to
`TrainingConfig.DEFAULT_LOCATION` and a `FABRICATED_DEFAULT` warning is recorded.
It is all-or-nothing: a partial address does not produce a partial location.

**Funding source** must match an SBA funding code exactly (case-insensitively).
A partner's own label — `CORE`, `Federal` — is **omitted from the XML** with a
warning, because `FundingSource` is optional and a non-enumerated value would
fail schema validation. The accepted list is `VALID_FUNDING_SOURCES` in
`src/config.py`.

---

## Training client (Form 641 from training rows)

**Required (2):** `Class/Event ID`, `Contact ID`.
**Conditional (1):** `Member ID` — the per-attendee session id. Without it, every
attendee at an event shares the event id as their session number.

**Expected set (28 columns),** in the order the converter declares them:

```
Class/Event ID              Related Record ID
Member Type                 Training Topic
First Name                  Class/Event Type
Last Name                   Funding Source
Member Status               Member ID
Company                     Class Teacher
Phone                       Contact ID
Email                       Street
Unique Campaign Members     city
Currently in Business?      State
Ethnicity                   Zip code
Race                        Start Date
Disabilities                Class/Event Name
Gender
Military Status
```

Note the inconsistent casing — `city` is lowercase while `State` and `Zip code`
are not. That is what the Salesforce export produces, and the headers are matched
literally, so reproduce them exactly or map them.

**Renames applied internally** before the counseling converter sees the row:

| Your column | Read as |
|---|---|
| `Phone` | `Contact: Phone` |
| `Company` | `Account Name` |
| `Street` | `Mailing Street` |
| `city` | `Mailing City` |
| `State` | `Mailing State/Province` |
| `Zip code` | `Mailing Zip/Postal Code` |
| `Disabilities` | `Disability` |
| `Military Status` | `Veteran Status` |
| `Ethnicity` | `Ethnicity:` |
| `Class/Event ID` | `Activity ID` |
| `Class Teacher` | `Name of Counselor` |
| `Start Date` | `Date` |
| `Currently in Business?` | `Currently In Business?` |

Everything the counseling schema needs but a training export does not carry is
supplied from `TrainingClientConfig.DEFAULTS` — mostly empty strings, plus
`Type of Session: Training`, `Language(s) Used: English`,
`Services Provided: Business Start-up/Preplanning`, and zeroed hours and loan
amounts.

---

## Data-quality checks on the preview

Before you convert, the preview page reports counts for each problem it can see
in the first rows, with a severity and the column responsible. It is generated by
`src/data_validation.py` and only lists checks with a non-zero count, so an empty
data-quality panel means nothing was detected — not that nothing was checked.

Duplicate headers are preserved rather than deduplicated when the header row is
read, so two columns collapsing to the same normalized name can be detected
instead of one silently shadowing the other.
