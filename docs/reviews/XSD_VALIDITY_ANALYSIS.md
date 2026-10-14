# XSD validity analysis — will the XML we create pass SBA validation?

Date: 2026-10-11, against `master` at `2574104` (after PR #133).

Markers: **`[OPEN]`** reproduced at that commit; **`[FIXED]`** resolved (keep the entry,
add the fix underneath).

**Status (PR #135):** every finding below is fixed and decisions D1–D4 are taken as
recommended. Rerunning the fuzzing on the fixed code, every one of 5,400 generated
files across the three converters, with both input mixes, validates against the supplied
XSDs. With realistic input no row is left out. With adversarial input the only rows left
out are those with an ID over 20 characters or a bad `LocationCode` (D1), and the final
XSD check (D2) never had to step in. `tests/test_xsd_validity_fuzz.py` keeps a seeded
version of that run as a regression test, and `tests/test_xsd_validity.py` pins each fix.

**Second pass (2026-10-14):** see [Second pass](#second-pass) at the end. It found no
realistic input whose final file fails the XSDs, but several ways to get no file at all
(a hang, a crash), records lost to the final check because the schema guard judged
values differently from libxml2, blind spots in that final check, values changed or
dropped without a word, and a fix-XML tool that reported success on files that still
failed. All are fixed except the decisions listed there; `tests/test_xsd_validity_second_pass.py`
pins them.

## Question

The SBA validates each uploaded file against two XSDs. Does every file this tool
produces pass them? If it can't, does the tool say so?

## Short answer

- **The schemas are the right ones.** The two XSDs SBA supplied match the copies in
  `schemas/` byte for byte, and those copies are what the worker and the CLI
  validate against.
  - `SBA_NEXUS_Counseling-2-14.xsd`: sha256 `ffef51b7…9379524`
  - `SBA_NEXUS_Training-2-25-2025.xsd`: sha256 `5bd7675d…17778d6`
- **Training reports are in good shape.** No realistic input produced an invalid
  training file. The only way to break one is an event ID over 20 characters, and the
  tool reports that as an error.
- **Counseling and training-client files can still fail.** Five input patterns produce
  invalid XML.
  - Three of them do so **without any error being recorded** (V.2–V.4). The user only
    finds out from the "failed XSD validation" banner on the results page.
  - The most common realistic cause is a **Race** answer outside SBA's nine codes
    (V.1). Examples are "Middle Eastern or North African", "Two or More Races",
    "Hispanic or Latino" or "Decline to answer". Every file containing one fails.
- **Everything else holds up:**
  - element order under every combination generated;
  - dates, decimals and integers, including accounting negatives, thousands separators
    and exponent notation;
  - email, phone and ZIP patterns;
  - length limits (values are truncated and reported);
  - control characters;
  - the enumerations of optional fields (unrecognised values are left out and
    reported);
  - well-formedness.

## Method

1. **Golden outputs.** All nine files in `tests/golden/` validate against the supplied
   XSDs.
2. **Structure.** I dumped both schemas' element trees: order, `minOccurs`/`maxOccurs`,
   choices and facets. I then compared them with what each builder in
   `src/converters/` writes and with what `src/schema_rules.SchemaGuard` enforces. The
   guard enforces facets (length, enumeration, pattern, range) but not repeat counts or
   content models.
3. **Fuzzing.** Thousands of generated CSV rows went through each converter, and every
   output was validated with lxml against the supplied XSDs. Each XSD error was mapped
   back to its row and classed as *reported* (the converter recorded an error for that
   field) or *silent*. There were two input mixes.
   - **Adversarial.**
     - Every expected column, plus `LocationCode`, `FIPS_Code`, `Rural_vs_Urban` and
       `InternetUsage`.
     - Values drawn from the schema's own enumerations (exact, lower-cased, truncated,
       and joined as multi-selects of up to 14).
     - Blanks, junk, and odd dates and numbers.
     - Over-long text, control characters, separator-only cells, and IDs over 20
       characters.
   - **Realistic.**
     - Only values a Salesforce export plausibly contains: exact picklist values or
       2–3 of them joined, normal dates, numbers, emails, phones and ZIPs.
     - 18-character IDs, real-world race labels, and blanks.

| Run | Rows | Files valid | Distinct failure causes |
|---|---|---|---|
| Counseling, adversarial | 5,000 (200 files) | 0 / 200 | Race, LocationCode, IDs > 20, Other-without-Code ×4, Media > 13 codes |
| Training-client, adversarial | 5,000 | 0 / 200 | Race, IDs > 20, CounselingProvided without Code |
| Training, adversarial | 5,000 | 3 / 200 | Event ID > 20 (only) |
| Counseling, realistic | 5,000 | 0 / 200 | Race; CounselingSeeking and Media "Other" without a Code |
| Training-client, realistic | 5,000 | 0 / 200 | Race (only) |
| Training, realistic | 5,000 | **200 / 200** | — |

The rates overstate real data: the generators reach the problem values far more often
than a real export would. What matters is that one such row fails the whole file.

## Findings

### V.1 Race answers outside SBA's nine codes fail the file — `[FIXED]` — HIGH (reported)

`Race/Code` is required and limited to Asian, Black or African American, Middle
Eastern, Native American/Alaska Native, Native Hawaiian/Other Pacific Islander, North
African, White, Prefer not to say, and Prefer to Self-Describe.

- **What happens:** `data_cleaning.map_race_to_xsd` maps synonyms, but returns
  anything else unchanged. The schema guard can only report it, because Race is
  required, so the file fails.
- **Labels from a real export that fail today:**
  - "Middle Eastern or North African", which is the 2024 OMB wording and matches two
    codes;
  - "Two or More Races", "Multiracial", "Other" and "Some Other Race";
  - "Hispanic or Latino", "Hispanic" and "Latino", entered as a race;
  - "Decline to answer" and "Unknown";
  - specific groups such as "Chinese" or "Arab", and "MENA".
- **Scope:** counseling and training-client. Training only counts races, so it is
  unaffected.

**Fix:** the schema has a place for exactly this. Map refusal wordings ("Decline…",
"Refused", "No answer") to `Prefer not to say`. Map any other unrecognised label to
`Prefer to Self-Describe` and put the original text in `SelfDescribedRace` (after the
Codes, at most 80 characters). Record a warning that says so. This files what the
person actually said, without guessing a category. Where several races are listed,
recognised codes are kept alongside it.

> **Fixed** (`1301456`): `data_cleaning.classify_race_label` sends refusal wordings to
> `Prefer not to say` and any other unrecognised label to `Prefer to Self-Describe`, with
> the text in `SelfDescribedRace` and a warning saying so. "Prefer to Self-Describe: …"
> keeps the description without a warning.

### V.2 "Other" text with no code — `[FIXED]` — HIGH (silent)

`CounselingSeeking` and `Media` must start with at least one `<Code>`. When the code
column is blank but the matching "Other"/"specify" column has text, the converter
writes the section with just `<Other>`.

- `Nature of the Counseling Seeking - Other Detail` is filled, but `Nature of the
  Counseling Seeking?` is blank.
- `Internet (specify)` is filled, but `What Prompted you to contact us?` is blank.

No issue is recorded, and the guard cannot repair a missing element, so the file is
invalid with nothing in the report to explain it. (When codes are present but all of
them are invalid, the guard already drops the whole optional section with a warning.
That case is fine.)

**Fix, CounselingSeeking:** add `<Code>Other</Code>` before the detail text (the detail
is by definition an "Other" answer), with a warning. `LegalEntity`, `Certifications`
and `ReferredClient` already work this way.

**Fix, Media:** this depends on decision D3 below.

> **Fixed** (`fb8dcd3`): CounselingSeeking gets `<Code>Other</Code>` before detail text
> given without an answer. "Internet (specify)" now fills the `Internet` element (D3), so
> `Media` only ever holds codes.

### V.3 A code cell holding only separators — `[FIXED]` — MEDIUM (silent)

A cell of `;` or ` ; ` is not blank, so the converter's defaults don't apply, but it
splits into no codes.

- `CounselingProvided`, from `Services Provided` (counseling) or `Training Topic`
  (training-client), comes out with no `<Code>`.
- `Language` comes out with only `<Other>`.

No error is recorded.

**Fix:** treat an empty split as a blank cell, so the existing defaults (with their
fabricated-default warnings) apply.

> **Fixed** (`fb8dcd3`): `Services Provided`, `Training Topic` and `Language(s) Used`
> that split into nothing get the same defaults and warnings as a blank cell.

### V.4 Repeat limits aren't enforced — `[FIXED]` — LOW (silent)

The guard checks values but not `maxOccurs`.

- `Media/Code` allows 13. A multi-select with more fails silently.
- The same gap exists for `LegalEntity/Code` (6), `ExportCountries/Code` (100) and
  training `TrainingPartners/Code` (14), though no real input reaches those.

**Fix:** load `maxOccurs` into `schema_rules.ElementRule` and drop repeats beyond it
with a warning, as `_cap_single_code` already does for the two single-code fields.

> **Fixed** (`7630030`): `ElementRule.max_occurs` is loaded from the XSD. The guard keeps
> the first values up to the limit and warns with the ones it left out.

### V.5 Required identifiers over 20 characters, or a bad `LocationCode` — `[FIXED]` — LOW (reported)

`PartnerClientNumber` (Contact ID), `PartnerSessionNumber` (Activity ID or Member ID)
and `PartnerTrainingNumber` (Class/Event ID) are limited to 20 characters. They are
never truncated, because a cut-down ID could point at someone else. A `LocationCode`
column whose value isn't an integer from 1 to 9,999,999 also fails.

- **How it's handled today:** each case is reported as an error, but the record stays
  in the file, so the file fails.
- **Likelihood:** Salesforce IDs are 18 characters, so this happens only when a
  non-ID column is mapped onto an ID, or the `LocationCode` column holds a typo.

**Fix:** decision D1.

> **Fixed** (`7630030`): `SchemaGuard.enforce` returns why a record can't be filed, and the
> converters leave that record out with an error naming its row. The rest of the file
> stays valid. "Total Records" now counts every row, so the ones left out are the
> difference from "Successful". A file with nothing left fails like an empty CSV.

### V.6 Valid, but empty: blank Activity ID or First Name — `[FIXED]` — MEDIUM

A blank `Activity ID` writes `<PartnerSessionNumber/>`, and a blank `First Name` writes
`<First/>`.

- Both pass the XSD, because an empty string meets a maximum length.
- They carry no data, and nothing is reported. A blank `Last Name` does get a warning.
- SBA's own processing most likely rejects, or mis-files, a session with no session
  number.

**Fix:** report a blank Activity ID as an error (or apply D1's choice to it), and a
blank First Name as a warning.

> **Fixed** as warnings. Activity ID is not a required column, and the sample CSV the app
> ships has none, so an error or a left-out row would have rejected files that were fine
> before.
> - A blank `Activity ID` is a warning on its row, and a file without the column gets one
>   warning.
> - On the training-client form, a row with neither `Member ID` nor `Class/Event ID` gets
>   a warning.
> - A blank `First Name` is a warning, as a blank `Last Name` already was.
> - The preview's data-quality checks count both before conversion.

### V.7 An invalid file can still be downloaded — `[FIXED]` — INFO

The results page shows a red "XML failed XSD validation (N errors)" banner with the
mapped row and column for each error, but the download is not gated. Once V.1–V.4 are
fixed, this should only happen for D1's cases. Decision D2 is about closing it
completely.

> **Fixed** by D2 (`8be1055`). The converters validate the file they wrote, and any record
> that fails is left out with the XSD message mapped to its row and column. The banner
> remains for errors outside every record, which leaving records out can't fix.

## Decisions needed

> **Taken as recommended** (PR #135): D1 leave the row out, D2 add the safety net, D3
> option a, D4 self-described.

- **D1: rows that can't be made valid.** Applies to a required value the tool must not
  invent or truncate, such as an over-long ID or a bad `LocationCode`.
  - *Recommended:* leave the row out of the XML and record an error naming it, as a
    missing Contact ID already is. The rest of the file then stays valid and can be
    filed, and the bad row is fixed and filed later.
  - *Alternative:* keep today's behaviour, where the record stays and the whole file
    fails until the CSV is corrected.
- **D2: a final safety net.**
  - *Recommended:* after converting, validate the whole document. Remove any record
    that still fails and report it with its row and the XSD message. The file you
    download then always validates, whatever a future bug or unexpected input does.
    The targeted fixes above keep this from dropping data in practice.
  - *Alternative:* keep the current banner-only approach.
- **D3: what "Internet (specify)" means.**
  - *The conflict:* the converter writes this column to `Media/Other`. But SBA's note
    in the XSD says `Media/Other` is the specification for an **"Other"** media answer,
    and the schema has a separate `Internet` element (80 characters) right after
    `Media`. That element is where an Internet answer is specified. The converter
    currently fills it from `InternetUsage`.
  - *Option a:* map "Internet (specify)" to `<Internet>`. This fixes Media's half of
    V.2 at the root, because `Media` then never gets a code-less `Other`.
  - *Option b:* keep today's mapping and add `<Code>Other</Code>` when no media code is
    given.
  - *Needed to decide:* what `InternetUsage` holds in your Salesforce export.
- **D4: "Middle Eastern or North African" in counseling.** With V.1's fix it is filed as
  self-described with that exact text (recommended: no guessing). The alternative is
  both the `Middle Eastern` and `North African` codes. Training counts are the separate
  open question from the last review.

## Suggested order

1. **No decision needed:** V.1 (self-describe and refusal wordings), V.2 for
   CounselingSeeking, V.3, V.4 and V.6's reporting.
   - Each comes with a regression test, and the fuzz runs above become a test that
     fails if any generated file is invalid.
2. **After D1–D3:** V.5, the D2 safety net, and Media's half of V.2.

## Second pass

Date: 2026-10-14, against `master` at `721711b` (after PR #136), with the same two XSDs
(byte-identical to the ones SBA supplied).

### Short answer

- **Every file the converters produced from realistic input already validated.** That
  held before this pass and holds after it: across about 13,000 generated files (below),
  no final file failed the XSDs.
- **But "always validates" was carried by the final XSD check (D2), and D2 had gaps.**
  The schema guard judged values in Python, not as libxml2 does, so D2 left whole records
  out for one optional value. When libxml2 gave up on a value, or the file was not
  well-formed, D2 did nothing at all, and the command line reported a clean conversion.
- **Some inputs produced no file:** one Email cell hung the conversion for hours, an
  exponent such as `1E+99999999` never finished, and a UTF-16 CSV with a stray byte
  crashed the command line.
- **Many values were changed or dropped without a word,** against the tool's rule that
  every change is reported. Among them: training read every event value from its first
  row, and footer rows from a Salesforce report became training events.
- **The fix-XML tool reordered only `ClientIntake`,** said "Successfully fixed" (exit 0)
  on files that still failed, and could turn a valid file into an invalid one.

### Method

1. **Eight independent lenses**, each required to ship a script that reproduces its
   finding with the real code path and validates the final file with lxml:
   - counseling structure;
   - training structure;
   - the guard against libxml2;
   - every hard-coded value against the XSD;
   - two new fuzz campaigns, through `run_conversion` (with and without column
     mappings) and the CLI path;
   - the D2 plumbing;
   - the fix and validate tools.
   The pipeline and fix-tool lenses ran twice, independently.
2. **Every repro was run on the code before and after the fixes.** 98 findings came in,
   many of them duplicates across lenses. Each reproduced on `721711b`.
3. **An adversarial review of the fixes,** including a differential run of 2,250 generated
   files through both the old and the new code. Every difference in XML or issues was
   assigned to the commit that intended it. No file valid before became invalid. Its 31
   findings were fixed or answered below.

| Campaign | Files | Invalid final files |
|---|---|---|
| Training: realistic, adversarial, control/Unicode-heavy, 5,000- and 33,000-attendee events | 4,500+ | 0 |
| Counseling and training-client through `run_conversion` and the CLI, mapped and unmapped (incl. 36k realistic rows) | 3,600+ | 0 |
| Pipeline lens through `run_conversion`, all three converters | 660 | 0 |
| Differential (old vs new), all three converters | 2,250 | 0 (old: 0) |
| Same, schema guard switched off so D2 does all the work | 1,050 | new 0, old 146 |

### Findings

Each was fixed in this pass unless marked otherwise.

**W.1 The schema guard judged values differently from libxml2 — `[FIXED]`.**
SchemaGuard compiled XSD patterns with Python's `re` and checked numbers and dates with
`Decimal` and `date.fromisoformat`. As a result:
- **Email hang:** SBA's `EmailType` pattern backtracks exponentially in Python. A 74-character
  Email cell took about 47 seconds per check, and a 90-character one never finished.
- **Non-ASCII digits:** `１９１５３` in FIPS_Code, or a ZIP in Tamil or NKo digits, passed
  the guard and failed the XSD. D2 then left out the whole record, or the whole training
  event, for one optional value.
- **ISO date forms:** ISO basic and week dates (`20250115`, `2025-W03-3`) passed as
  `xs:date`.
- **A different regex dialect:** in XSD, `^`, `$` and `\p{..}` mean something else, or
  don't compile in Python, so a schema update could have stopped every conversion.
- **A crash on long numbers:** a whole number of more than 4,300 digits written with `.0`
  raised.

*Fix:* the Python checks now only put values in canonical form and explain the problem;
libxml2 makes the final call. Each value is validated against the element's own simple
type, in a small schema compiled once per XSD. The cache is bounded and thread-safe. If
libxml2 gives up on a value (about 2 s), the value counts as invalid.

**W.2 Inputs that produced no file — `[FIXED]`.**
- `clean_numeric` wrote exponents out in full. `1e5000` raised and cost the record;
  `1E+99999999` never finished.
- `'NaN%'` became a female share of 100.
- A UTF-16 CSV with a stray byte or half an emoji crashed the command line; the web read
  the same file.
- The new date-time pattern (W.4) was quadratic on long whitespace; caught in review.
- In the worker, any per-row exception became a `TypeError` that failed the whole job,
  because the logger wrapper rejects `exc_info`.

**W.3 Blind spots in the final XSD check (D2) — `[FIXED]`.**
- **Errors with no line:** D2 left out only the records it could place by an error's line.
  libxml2 giving up (as it does on the pathological email) reports no line and hides
  every other error in the file, so the file stayed invalid and nothing was recorded.
  Records are now checked one at a time when an error can't be placed. The file is
  re-validated after every rewrite, and a failure no record explains becomes a
  file-level error.
- **Speed:** leaving out 20,000 records took 45 s, because the work was quadratic; it is
  now one pass.
- **Thread safety (found in review):** the per-record check shared one compiled schema
  across worker threads. Two jobs could swap error messages, or crash.

**W.4 Values changed or dropped without a report — `[FIXED]`.**
Each now either keeps the value or records a warning naming the cell.

*Counseling and training-client:*
- **Demographic answers:** Gender, Ethnicity, Disability and Employee Owned answers it
  can't map were dropped silently. "Decline to answer" and "Unknown" are now
  `Prefer not to say`, as Race already did.
- **Branch Of Service:** a 'Prefer not to say' branch, one of SBA's values, was reported
  missing. A branch given without military service was dropped silently.
- **Legal Entity:** dropped silently for a client not in business.
- **FIPS_Code:** dropped silently when Rural_vs_Urban was not Rural or Urban.
- **Dates:** unreadable optional dates were dropped silently. Salesforce Date/Time exports
  (`1/15/2025 10:30 AM`, `…T14:30:00.000Z`) were not read at all, so the session date was
  lost. A UTC timestamp's date is now flagged.
- **Unreadable numbers:** employee counts and prep/travel hours were dropped silently. An
  unreadable `% Female` was filed as 0, and an unreadable `(Meeting)` amount filed 0
  instead of the intake value.
- **OnFile:** a Client Signature answer other than yes/no was filed as 'No'.
- **'Other' codes:** a Code of 'Other' was filed for "Other" text alone in five code lists.
- **Contact hours:** training-client invented 0.5 contact hours with no warning on the row.

*Training:*
- **Event values from the first row only:** every event value came from the event's first
  row. A Funding Source or Cosponsor on a later row was lost, a blank first row filed a
  fabricated default, and rows that disagreed went unreported.
- **LocationCode:** a `LocationCode` column was ignored; it is now honoured, as on the
  counseling forms (decision D1 applies).
- **ZIP:** a ZIP was taken from any five digits in the cell, so a phone number's first five
  digits became the ZIP. A ZIP+4 lost its +4.
- **Veteran Status:** a Yes/No checkbox counted no veterans.
- **Race labels:** labels such as "African-American" and "Alaskan Native" counted in no
  category, with nothing said.
- **Cosponsor:** `N/A ` and `None` were filed as cosponsor names.

**W.5 CSV shapes read wrongly without a report — `[FIXED]`.**
- **Non-records:** a Salesforce report's title and footer lines, a second header row, and
  `#N/A` IDs became training events (and counseling records).
- **Unclosed quote:** it swallowed every following row.
- **Long rows:** a row with more cells than the header lost the extra cells.
- **Column mapping:** a mapping on a header with stray spaces was never applied.
- **Training-client overwrites:** a blank counseling-named column erased the renamed
  training value.
- **Identifiers:** a cell of only control or zero-width characters became an empty or
  invisible ID. IDs differing only by such a character were filed twice.
- **Day-first dates:** `13/01/25` was read year-first.

**W.6 The fix-XML and validate tools — `[FIXED]`.**
- **Order:** the fixer reordered only `ClientIntake`. It now orders every sequence from the
  XSD itself.
- **Honest results:** both CLIs re-validate, say what still fails, and exit non-zero. The
  web page now tells an order problem from a data problem.
- **`--add-missing`:** it invented `CurrentlyInBusiness = 'No'` and could not supply Race.
  It now files 'Undetermined' with a warning and reports Race as still missing.
- **Parser mismatch:** the fixer parsed with expat and wrote with ElementTree, unlike the
  validator. So it applied DTD attribute defaults, dropped a namespace declaration used
  only in an `xsi:type` value, turned `&#13;` into LF, dropped comments, and reported
  `changed` when nothing moved. It now uses lxml with the validator's settings, and
  refuses DTDs that declare entities with a clear message.
- **Encoding:** the web decoded uploads leniently. A Windows-1252 file declared UTF-8 was
  called valid though SBA can't parse it, and `encoding = "…"` with spaces was ignored.
  Such files are now refused with the line of the first bad character.
- **Lone surrogates:** a lone surrogate in posted text was an HTTP 500.

### Decisions (not changed)

- **Blank Prep or Travel hours are still filed as 0.** The form asks for them, 0 is the
  natural reading of a blank, and a warning on nearly every row would bury the report.
- **A training event's location is still read from the `City`/`State`/`Zip` columns.** In
  a campaign-member export these are each attendee's mailing address. The first complete
  one is filed. Rows disagreeing about it are not reported, because they nearly always do.
- **libxml2 rejects an `xs:date` padded with whitespace,** though XSD allows it. The
  converters never write one, and the validator is not second-guessed.
- **Training counts rows, not distinct people.** This was already open in
  [`../converters.md`](../converters.md#known-gaps).
- **Training race answers that fit no category are reported, not counted.** "Two or More
  Races" and similar answers fit no single category, and no category is invented for them.
