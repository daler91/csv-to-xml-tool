# Web app guide

A screen-by-screen walk through the web app, for resource-partner staff who
export counseling or training data from Salesforce and file the XML with SBA
Nexus/EDMIS. Most of it is about the results page: what each count and severity
means for your filing, and how to work a file down to a clean one. To run the
app, see [getting-started.md](./getting-started.md#the-web-app); to pick a
converter, [converters.md](./converters.md#which-one-do-i-want); for a specific
error message, [troubleshooting.md](./troubleshooting.md#using-the-web-app).

## The steps

Every conversion page shows the same strip:
**Upload › Preview › Map › Convert › Results**. Steps you have passed are ticked
and can be clicked to go back. **Map** is optional: you reach it from the preview
when columns need renaming, and saving a mapping returns you to **Preview**.
**Re-upload** counts as **Upload**.

## Signing in

**Create Account** asks for an email, a password and an optional name. The
password needs at least 8 characters, an uppercase letter, a digit and a special
character; the checklist under the field ticks each rule as you type. **Sign In**
answers every failure with "Invalid email or password", including a throttled
one: after 10 attempts for one address within 15 minutes, even the right password
is refused until the window passes. Once in, the top bar links **Dashboard**,
**Convert**, **Validate XML**, **Audit Trail** and **Help**, an in-app summary of
this guide and the common errors.

## Dashboard

Your conversions, newest first, 20 to a page; **New Conversion** starts one. With
no jobs yet it offers the three [sample CSVs](./getting-started.md#sample-csvs).
**File** is the uploaded name with every character other than a letter, digit,
`.`, `_` or `-` replaced by `_`; the XML downloads under the same name. **Records**
is successful/total and **XSD** is **Valid** or **Invalid**, once converted.

| Status | Meaning |
|---|---|
| Uploaded | The file is saved; its preview has not loaded yet |
| Ready to convert | The preview has loaded |
| Needs mapping | You saved a column mapping and have not reopened the preview since. Nothing more is needed: open the preview and convert |
| Queued | Waiting its turn; each server converts one job at a time |
| Converting | Running |
| Complete | Finished. The XML can be downloaded until retention removes it |
| Failed | The conversion gave up; the results page says why |
| Cancelled | You cancelled it. It can't be restarted; upload the file again |

**View** opens the results page. On a job never converted that page is empty:
click **Preview** in the step strip to pick the job up. **Delete** asks first, then
removes the CSV, the XML and the job; the audit trail keeps its entries. A running
job can't be deleted; cancel it first.

## Upload

Pick a **Converter Type** — **Counseling (Form 641)** (selected to start with),
**Training (Form 888)** or **Training Client (Form 641)**, each with a **See
sample** link — and drop or browse for the **CSV File**. The wrong type is the
commonest cause of a confusing result: nearly every column then shows as missing.
A file not named `.csv`, or over the upload cap (50MB by default,
`MAX_UPLOAD_BYTES`), is refused before it is sent. **Upload & Preview** saves the
file and opens the preview. You can upload 10 files a minute.

## Preview

**CSV Preview** shows the first 20 rows and three counts. **Matched** is expected
columns found by name (for `training`, by any accepted spelling). **Missing** is
expected columns the file lacks, optional ones included, so a non-zero number is
normal; the mapping page says which are required. **Extra** is columns the
converter does not read; they are ignored, which is harmless. When a missing
column looks like an extra one, **Column mapping suggestions** pairs them with a
percentage match.

**Data quality** checks every row, not only the 20 shown, and lists only the checks
that found something, errors first. Each says what will happen to those rows in
the XML and, where it can, names the column. Most errors are rows that will be
left out (no `Contact ID`, or for `training` no `Class/Event ID`; a cell an
unclosed quotation mark filled with the rows after it); warnings are rows that
convert with a value blanked, defaulted or shortened. It never blocks conversion.
Every check is in [csv-reference.md](./csv-reference.md#data-quality-checks-on-the-preview).

The table shows the file as it will be read, so check accented names there: a file
that isn't UTF-8, typically Excel's "CSV (Comma delimited)", is read as Windows-1252,
and the results page carries a warning saying so.

- **Map Columns**, shown when any column is missing, opens the mapping page.
- **Confirm & Convert** is never disabled. A missing *required* column fails the
  conversion afterwards, so check the mapping page first if **Missing** is not 0.
- **Cancel** returns to the upload page; the job stays on the dashboard.

## Map

**Column Mapping** lists every expected field with badges:

| Badge | Meaning |
|---|---|
| **Required** | The conversion fails without it |
| **Conditional** | Needed only when a related answer has a certain value; the rule is printed under the field ("When required: …") |
| **Optional** | Not needed to convert. Most columns whose absence makes the counseling converter [file a default](./converters.md#fabricated-defaults) carry this badge; their absence is a warning on the results page |
| **Auto-matched** | Found in the file; nothing to do |

For a field your file names differently, pick its column under **Map From CSV
Column**; leave the rest. A job with no saved mapping opens with every suggestion
already filled in (the chip beside the field shows ✓), so check each before
saving: a suggestion matches spelling, not meaning. **Apply All Suggestions** puts
them all back.

Mappings are kept per converter type, and none is applied without you:

- **Apply last mapping** is offered on a job with no mapping yet, when your last
  completed job of the same type used one.
- Pick from **Saved templates**, then **Apply**: it replaces the mapping on screen
  with the entries that fit this file, and says how many it skipped. **Delete**
  removes the selected template.
- **Save current mapping as**, then **Save template**. Saving under an existing
  name replaces that template.

**Save Mapping & Continue** stores the mapping on the job and returns you to the
preview. The preview's counts do not change: they describe the file as uploaded,
and the mapping is applied when the conversion runs.

## Convert

The progress page shows "N of M records" (events, for `training`), the time
running, and an estimate once 5% is done. The **Errors** and **Warnings** counters
stay at 0 while it runs. The results page opens by itself when the job ends.

- **Cancel conversion** marks the job cancelled at once and returns you to the
  dashboard; its output is discarded. It appears once the job is converting, not
  while it is queued.
- "We're having trouble checking the conversion status" follows three failed checks
  in a row. The job may still be running: **Retry**, or **Go to dashboard**.
- **Conversion Timed Out**, after five minutes, means the page stopped waiting, not
  that the job stopped. **Check status again** reloads it.

| On the server | What you see |
|---|---|
| A passing failure, such as the converter restarting | Nothing. The attempt is repeated after 30 seconds, then 2 minutes (`JOB_RETRY_BASE_MS`), up to 3 attempts (`JOB_MAX_ATTEMPTS`), then **Failed** |
| The file is rejected: a required column missing, or no row convertible | **Failed** at once, with the reason |
| One attempt runs past 30 minutes (`CONVERSION_TIMEOUT_MS`) | **Failed** at once, without a retry |
| The queue loses the job, which then sits for 60 minutes (`REAP_DEADLINE_MS`) | **Failed** the next time you open the dashboard or the job |

## Results

**Conversion Results** holds, in order: **Download XML** (while the XML is on
disk), **Re-upload** and **Delete job**; the summary cards; after a re-upload, the
comparison tabs; **XSD Validation**; **Preview XML output**, the first 100 KB
only; "Data cleaning made N changes" with **View cleaning diff**; and the
**Errors** and **Warnings** tables, 100 rows each until you click **Show all**.

A failed job shows a **Conversion failed** alert instead, with no counts or issues:

| The alert begins | Cause |
|---|---|
| "The file could not be converted: …" | The converter rejected the file and says why, such as "Missing required column(s) for counseling: Race" ([fix](./troubleshooting.md#required-columns-are-missing)) or "None of the 3 row(s) could be converted; the first was left out for …" |
| "The worker did not respond within the conversion time limit." | An attempt ran past `CONVERSION_TIMEOUT_MS`. Split the file |
| "The conversion did not finish within the time limit and was stopped." | The job sat past `REAP_DEADLINE_MS`. Try again |
| "The conversion was retried and crashed each time." | Usually a file too large. Split it |
| "The conversion service failed …" or "… could not be completed after several attempts." | The service failed, or hit its own time limit. Try again later; if it repeats, split the file |

## Reading the results

| Card | Counts |
|---|---|
| **Total Records** | Every row read, rows skipped as not records included. For `training`, events; a row with no `Class/Event ID` is dropped with an error before grouping, outside the count |
| **Successful** | Records written to the XML |
| **Errors** / **Warnings** | Issues of each severity — issues, not records |

**Total Records minus Successful is the number of records left out of the XML.**
Watch that, not the error count: one record can carry several errors, and some
errors leave the record in.

- **Error** — the record is not filed as the CSV has it. Usually it was left out:
  no ID ("Missing required Contact ID."), a required value SBA's schema can't
  accept, or a record the final schema check rejected; those messages end "so the
  record was left out of the XML". Some leave the record in: a value SBA requires
  in that case is blank, such as a branch of service for a veteran, and the record
  is filed without it.
- **Warning** — the record is filed, but something in it is not exactly your CSV:
  a default filled in; a value dropped, shortened, replaced, or read one of two
  ways; a column the file lacks; how the file was decoded. A row read as not a
  record (blank, a repeated header, a report title or footer) is a warning ending
  "so it was skipped".

Read `fabricated_default` and `downgraded_value` first: values in your filing that
are not in your CSV, and values your CSV gave that were dropped. Every category is
in [converters.md](./converters.md#issue-categories).

**Record** is the Contact ID (the event ID for `training`), `Row_N` for a row
without one, or `file` for the file as a whole. Row numbers count from 1 at the
first row under the header, so row 5 is row 6 in Excel.

**XSD Validation** checks the kept file against the SBA schema. The converter has
already left out every record the schema rejects, so a complete job normally reads
"XML is valid against the XSD schema" even with errors listed: the rejected records
are in the tables, not in the XML. "XML failed XSD validation (N errors)" means a
problem no single record explains; each entry names what it can of the row, field,
CSV column and contact, with the **Raw validator message** under it. Don't file
that XML.

**View cleaning diff** lists each value the cleaning rules changed — Row, Record
ID, Field, Original, Cleaned, Type — with a count per rule and **Filter by type:**
buttons, 200 rows at a time. A Cleaned cell reading "left out of the XML" is a
value dropped. The rules are in [converters.md](./converters.md#the-cleaning-rules).

## Fixing and re-uploading

1. Fix the rows the errors name, then the warnings you don't accept, in Salesforce
   or in the CSV.
2. On the results page, **Re-upload**. **Re-upload Fixed CSV** keeps the converter
   type (start a **New Conversion** to change it); choose the **Updated CSV File**
   and **Upload & Compare**. The earlier job stays as it was.
3. The new job starts with no mapping. On **Map**, use **Apply last mapping** or
   your template.
4. Convert. The results page opens on three tabs: **Resolved** (issues the earlier
   job had and this one doesn't), **New** (the reverse; shown first) and
   **Persistent** (in both).

Issues are matched on record, field and category, not message: a reworded issue is
persistent, and a record whose Contact ID you changed shows its issues as resolved
and new. The comparison is with the job you re-uploaded from, and disappears if you
delete that job. Repeat until **Successful** equals **Total Records**, **Errors**
is 0, the XSD check passes and every remaining warning is one you accept; then
**Download XML**.

## Checking an XML file you already have

**Validate XML** checks an existing file against the SBA schemas without
converting anything; files converted here are already checked. Pick **Counseling
(Form 641)**, which also covers Training Client output, or **Training (Form 888)**;
choose a `.xml` file (same size cap as uploads); **Validate**. You get a pass, or
the errors listed as on the results page. A file that isn't readable text in the
encoding it declares is refused; save it as UTF-8.

When a counseling file fails, **Attempt automatic fix** puts its elements in the
order the schema requires and re-checks it. It never adds, removes or changes a
value, so an element missing, repeated or under the wrong parent still fails, and
the result says so. If the order changed, **Download fixed XML** saves
`<name>-fixed.xml`. Training files are not offered the fix. Nothing is stored but
an audit entry; each check is limited to 10 a minute.

## Your job history and the audit log

The dashboard is your job history. **Audit Trail** lists what you did — Date,
Action, File, Type and Details, with **View raw** for the stored data — 25 to a
page, filtered by action. **Export CSV** downloads the current filter, up to the
10,000 newest entries. You see only your own entries.

Actions: Upload; Column mapping changed (when a saved mapping differs from the
last); Conversion started, retried, complete (with successful/total and errors),
failed, timed out, or cancelled; Download; Job deleted (naming the file); Files
removed (retention); XML validated and XML auto-fixed; Template saved and deleted;
Signed in and Sign-in failed (wrong password). Entries for a deleted job show — for
File and Type.

## What is kept and for how long

| What | Kept |
|---|---|
| The uploaded CSV and the XML | `RETENTION_DAYS` days from upload (30 by default), or until you delete the job. Queued and converting jobs are never swept |
| The job: counts, issues, cleaning diff, XSD result | Until you delete the job |
| The audit trail | Indefinitely; the app never removes it |
| Mapping templates | Until you delete them |
| Files checked on **Validate XML** | Not stored |

Removal runs hourly and whenever you open the dashboard
([configuration.md](./configuration.md#retention)). Afterwards the results page
says when the files went, **Download XML** and the XML preview are gone, and an old
download link answers "This file has expired and been removed." To get the XML
again, upload the CSV again.

The issues and the cleaning diff quote your CSV — Contact IDs, and values such as
dates, phone numbers and counselor notes — and they outlive the files. Delete the
job to remove them. Jobs and files are visible only to you.
