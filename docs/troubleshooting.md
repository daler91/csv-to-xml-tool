# Troubleshooting

Grouped by who hits it. The in-app `/help` page covers the same user-facing cases
with less detail; this page adds the operator and developer side. For what the
screens mean when nothing is wrong, see
[web-app-guide.md](./web-app-guide.md#reading-the-results).

---

## Using the web app

### "This file is larger than 50MB"

The upload cap. Split the CSV into batches, or drop unused columns via Excel or
Salesforce's export filters. Extra columns are ignored by the converter anyway,
so removing them costs nothing. The browser checks first, before anything is
sent, and says *"That file is larger than 50MB"*; the server's own refusal reads
*"This file is larger than 50MB"*. Both name the deployment's cap.

Operators can raise `MAX_UPLOAD_BYTES` — but read
[configuration.md](./configuration.md#limits) first: the number also appears in
about nine user-facing strings, and memory scales with it.

### "That file isn't a CSV"

The extension must be `.csv` (any case). From Excel: **File → Save As → CSV
(Comma delimited)**. The browser refuses a wrong extension before uploading, with
*"That doesn't look like a CSV. We accept .csv files only."*

An `.xlsx` renamed to `.csv` uploads and previews: its bytes are read as
Windows-1252 text, so the preview shows every expected column as **Missing** and
the conversion stops on the missing required columns. Export a real CSV.

### "You've uploaded several files in a short window"

Ten uploads per minute per user. Wait a minute. **Validate XML** and its
**Attempt automatic fix** have ten a minute each of their own; there the page
shows the server's bare *"Too many requests"*, as signup does after five
attempts a minute from one address.

### Other messages when uploading or starting

| Message | Cause |
|---|---|
| *"Please select a file and a converter type before uploading."* | The request reached the server without a file or a type: a page left open across a deploy, or a script. Reload and pick both |
| *"Please pick a converter type before uploading."* | The type is not `counseling`, `training` or `training-client` |
| *"Invalid previousJobId"* | A re-upload link for a job that is not yours, or was deleted. Start from **New Conversion** |
| *"Couldn't reach the server. Check your internet connection and try again."* | The browser got no response at all |
| *"This job is complete and can't be started. Upload the file again if you want to re-convert."* | **Confirm & Convert** on a job that already ran (or is `error`, `cancelled`, `queued`, `converting`). A job runs once; re-upload |
| *"Couldn't queue the conversion just now. Please try again in a moment."* | Redis refused the enqueue. The job is put back, so trying again works once Redis is back |

### "Something went wrong on our side" when uploading

The upload route answered 5xx. It only saves the file and creates the job row,
without reading the CSV, so the cause is on the server rather than in the file,
and retrying rarely helps. The web log has an `Upload error:` line naming it:

- **`EACCES: permission denied, mkdir '/data/uploads'`**: the app cannot write
  to `DATA_DIR`. Any image built before the ownership-fixing entrypoint does this
  on a Railway volume (mounted root-owned) unless `RAILWAY_RUN_UID=0` is set.
  Redeploy a current image; see
  [deployment.md](./deployment.md#volume-ownership-on-railway). Running without
  Docker, `DATA_DIR` still defaults to `/data`; point it at a writable folder.
- **`Failed to parse body as FormData`** on a file over 10 MB: the build predates
  the fix that took the upload routes out of `middleware.ts`, whose body buffer
  truncated anything larger. Redeploy.
- **A Prisma error**: the database is unreachable, or `P2022` if a schema change
  was not mirrored into `migrate.js` (see
  [below](#prisma-p2022-column-does-not-exist)).
- **`ENOSPC`**: the volume is full.

### "Your session expired"

Sign in again. Sessions do expire — 30 days after the session cookie was last
refreshed, Auth.js's default, since the app sets no `maxAge` — and the tab does
not notice until the next request.

### "Invalid email or password" with the right password

The login throttle. Ten attempts per email address in 15 minutes (and 50 per
client IP, where one can be trusted), and a throttled attempt gets the same
message as a wrong password, deliberately, so the message does not say which.
Wait 15 minutes; a successful sign-in resets the count
(`apps/web/src/lib/auth.ts`).

### Required columns are missing

The worker answers 422 naming the columns, and the job fails at once, without
retries. The results page says **Conversion failed** — *"The file could not be
converted: Missing required column(s) for counseling: …"*. The preview's
**Missing** count shows the same columns before you convert. It is a hard stop by
design — converting without a required column would either fail the schema or
invent data.

Two fixes:

- **Your export uses different header names** → map them on the mapping page, and
  save the mapping as a template. A template is not applied by itself: for the
  next export, open **Map Columns** again and **Apply** it (or **Apply last
  mapping**), then save.
- **The data genuinely is not in the export** → add the field in Salesforce and
  re-export.

`training` has no list of required columns; it needs its event ID column, and
says *"Required column 'Class/Event ID' is missing from the CSV."* without one.
Per-converter lists: [csv-reference.md](./csv-reference.md).

### Columns show as "missing" but they are in my file

Usually one of:

- **A different spelling.** Check the exact expected header — `Ethnicity:` really
  does end with a colon. The preview page fuzzy-matches missing against extra
  columns and suggests renames; take the suggestion if it looks right.
- **Two columns collapsing to one name** after whitespace normalization. The
  header row is read without deduplicating so this is detectable; look for a
  near-duplicate header.
- **The wrong converter type.** `training` and `training-client` read similar
  exports but expect different column sets.

### Columns still show as missing after I mapped them

Expected. **Save Mapping & Continue** returns you to the preview, and the
preview reads the file's own headers: it is not sent the saved mapping, so its
**Matched** and **Missing** counts do not change. The conversion applies the
mapping. Go ahead with **Confirm & Convert**.

### Preview fails to load

The preview reports broken rows rather than failing on them (see
[below](#rows-are-missing-from-the-output-or-values-are-in-the-wrong-columns)),
so a failure says something specific. **Couldn't load preview** shows one of:

- *"A cell in the CSV is longer than 131,072 characters. This usually means a
  quotation mark is opened and never closed; …"* — the one file problem that
  stops the reader. Find the row where the data stops looking right.
- *"The CSV could not be read: …"* — another reader error, quoted.
- *"The uploaded file for this job has expired and been removed. Upload it again
  to preview."* — retention removed it; see
  [Download says the file expired](#download-says-the-file-expired).
- *"The conversion service couldn't generate a preview. Try again in a minute;
  if it keeps happening, the worker service needs checking."* — the worker is
  down, unreachable, refused the token, or failed. **Try again** first in case it
  was momentarily busy; operators find a `Preview worker error:` line in the web
  log, and [Every conversion fails immediately](#every-conversion-fails-immediately)
  checks the token.

### Rows are missing from the output, or values are in the wrong columns

Look for these in the issues list:

- **"... cell runs on over N more line(s) that look like rows"** (an error) —
  a quotation mark in that cell is opened and never closed, so every line up to
  the next quotation mark was read into the one cell. Close or remove it.
- **"... has more values than the header has columns"** — a comma inside a
  value that isn't quoted (`Doe, LLC`) split it in two and moved every later
  value one column over. Quote the value or remove the comma.
- **"... was skipped"** — the row is blank, repeats the header row, or holds a
  single value like a report's title or footer line. If it is a real record,
  fill in its other columns.
- **"... This field is required, so the record was left out of the XML"** (an
  error) — a required value SBA's schema cannot accept, and no default stands
  in for it. Correct the cell.
- **"... SBA's schema rejects this, so the record was left out of the XML"** (an
  error) — the final check of the written file against SBA's XSD rejected the
  record. Every converted file is checked before it is kept, and a record that
  fails is taken out so the rest of the file stays valid
  (`src/converters/base_converter.py:_write_valid_xml`). The message names the
  row and the value.
- **"SBA's schema validator could not check a value in this record"**, **"the
  record holds a character XML cannot carry"** or **"SBA's schema validator found
  this record invalid but gave no reason"** — the same check, for a record that
  fails with no error line to place; it is left out all the same. The first is
  most often a malformed Email.

The **Successful** count on the results page is what was filed.

### "None of the N row(s) could be converted"

Every row was skipped or left out, and SBA's schema needs at least one record, so
no file is written and the job fails: *"The file could not be converted: None of
the 3 row(s) could be converted; the first was left out for row 1: no Contact
ID."* The reason given is the first row's. Training counts *"event(s)"*, and the
count is *"record(s)"* when the final XSD check left out the last one. Training
says *"No rows had a usable Class/Event ID to convert."* when no row has an event
ID; a CSV with headers and no rows says *"CSV has no data rows to convert."*

### "Conversion failed" on the results page

A failed job keeps its reason in the audit trail, and the results page turns it
into one of these (`apps/web/src/lib/job-failure.ts:describeJobFailure`):

| The page says | What happened |
|---|---|
| *"The file could not be converted: …"* | The worker refused the file's content (400/422), and the reason follows: missing required columns, nothing to convert, an unreadable CSV. Not retried. Fix the file and re-upload |
| *"The worker did not respond within the conversion time limit. …"* | The web gave up after `CONVERSION_TIMEOUT_MS` (30 minutes by default). Not retried. Split the file |
| *"The conversion service failed while processing this file. …"* | The worker answered with another error, three times: a 5xx, a wrong `WORKER_AUTH_TOKEN` (401) or none at all (503), a body over its `MAX_REQUEST_BYTES` (413). Also the worker's own deadline (504 *"The conversion took too long"*), which is not retried and which trying again will not fix — split the file |
| *"The conversion could not be completed after several attempts. …"* | Some other error, three times — usually no answer from the worker at all: down or unreachable |
| *"The conversion was retried and crashed each time. …"* | The process running it died each attempt, most often out of memory. Try a smaller batch |
| *"The conversion did not finish within the time limit and was stopped. …"* | The reaper: the job sat `queued` or `converting` past `REAP_DEADLINE_MS` and the queue had lost it (a Redis restart, say) |
| *"The conversion failed, but no reason was recorded. …"* | No failure entry was written. Re-upload |

Operators: the first five are a `conversion_deadlettered` audit entry
(**Conversion failed** on `/audit`) whose `metadata.error` is the raw message,
and the reaper's is `conversion_timeout` (**Conversion timed out**).

### The conversion succeeded but XSD validation failed

Rare now. A record the schema rejects is left out of the XML and listed as an
error (above), so **XSD Validation** reads *"XML is valid against the XSD
schema"* even when records were dropped: check **Successful** against **Total
Records** and read the errors. *"XML failed XSD validation"* means the file fails
while no record on its own does; the results page lists each schema error mapped
back to a **CSV row and column name** where it can — fix those rows and use
**Re-upload** to compare the two runs
([web-app-guide.md](./web-app-guide.md#fixing-and-re-uploading)).

If the errors are about element *order* rather than values, the file may have
been produced elsewhere; `/validate` → **Attempt automatic fix** reorders
counseling-format XML (and `python -m src.fix_sba_xml` either form) to the
schema's order. If an element is still "not expected" after that, it is missing,
repeated, or under the wrong parent, which reordering can't fix.

### Validate XML refuses the file

What the page does when it accepts one:
[web-app-guide.md](./web-app-guide.md#checking-an-xml-file-you-already-have).

| Message | Cause |
|---|---|
| *"The file is not valid UTF-8 text (first unreadable character on line N), so SBA could not read it either. …"* | The bytes are not text in the encoding the file declares (UTF-8 when it declares none) — usually a Windows-1252 file declaring UTF-8. Save it as UTF-8 |
| *"DTD/entity declarations are not supported: …"* | The DOCTYPE declares or uses entities, which the tool never expands ([SECURITY.md](./SECURITY.md#input-handling)). Write each value out in full and remove the DOCTYPE |
| *"Auto-fix couldn't process this file: …"* | The fixer refused it — not well-formed (*"XML parse error: …"*), entities, or not a Form 641 document — and says why |
| *"Auto-fix supports counseling-format XML only"* | Auto-fix orders by the Form 641 schema. For Form 888, use `python -m src.fix_sba_xml` |
| *"Validation failed — the validation service may be busy. …"*, *"Auto-fix failed — the fix service may be busy. …"* | The worker did not answer usefully; as for the preview above |

### "The file is not UTF-8, so it was read as Windows-1252"

A file-level warning, not an error. The CSV is not UTF-8, so it was decoded as
Windows-1252, which is what Excel's **CSV (Comma delimited)** writes; that is
almost always right. Check accented names in the XML preview. To take the guess
away, save as **CSV UTF-8 (Comma delimited)**.

The UTF-16 warnings — *"The file is UTF-16 but has bytes that are not text…"*,
*"…has an odd number of bytes, so one of them is stray…"* — mean the export is
damaged; export it again. The web and the CLI record the same warnings
(`src/data_cleaning.py:encoding_warning`).

### The progress bar sits at 0%

Progress appears once the worker starts reporting rows, and only while the job
is `converting`. A `queued` job is waiting its turn: each web process converts
one file at a time, so a job queues behind the others.

A `converting` job at 0% is either stuck — see
[Jobs stuck in converting](#jobs-stuck-in-converting) below — or converting
without reports: when the worker cannot reach Redis it skips progress writes, and
the bar stays at 0% until the job completes. The reaper fails a stuck job after
`REAP_DEADLINE_MS` (60 minutes by default) on the next dashboard read, unless the
queue still holds it.

### "Conversion Timed Out" on the progress page

The page gave up, not the conversion. The progress page stops polling after five
minutes and says *"The conversion is taking longer than expected. Please check
back later or try again."*; the job carries on up to `CONVERSION_TIMEOUT_MS` (30
minutes). **Check status again** watches for another five minutes; the dashboard
shows the outcome when there is one.

*"We're having trouble checking the conversion status."* means three status
checks in a row failed — the web app stopped answering, not the worker. The file
may still be converting; **Retry**.

### Download says the file expired

Files are deleted after `RETENTION_DAYS` (30 by default, counted from the upload);
job records and the audit trail survive. The results page says *"The uploaded
CSV and converted XML for this job were removed on … under the 30-day retention
policy."* and drops **Download XML**; a job not yet converted says *"The uploaded
file for this job has expired and been removed."* Re-upload the CSV and convert
again.

### Numbers in my report look wrong

Check the results page's **cleaning diff** — it shows every value the tool
changed and the rule that changed it. Then check the issues list for these
categories:

- `fabricated_default` — a value in your filing did not come from your CSV.
- `downgraded_value` — data was dropped to satisfy the schema (usually a
  multi-value field capped to one code).
- `ambiguous_date` — `03/04/2025` was read as March 4. If your export is
  day-first, that is wrong and you should reformat the column. A date-time in UTC
  is filed as the UTC date, which can be a day after the local one.
- `clamped_value` — a percentage outside 0–100 was clamped.

Also note: **training demographics count rows, not distinct people.** An attendee
listed twice is counted twice.

---

## Running the CLI

### `ModuleNotFoundError: No module named 'lxml'`

```bash
pip install -r requirements.txt
```

### "Refusing to write outside …"

Output-path confinement. The conversion CLIs' writes (XML, reports, logs) and
the fixer's and validator's directory modes are confined to `SBA_OUTPUT_BASE` —
the working directory for `src.main`, the launcher's folder for `run.py`; the
fixer's and validator's single-file mode is not
([cli.md](./cli.md#output-path-confinement)). A refused path ends in a traceback
whose last line is `ValueError: Refusing to write outside '…': '…'. Set
SBA_OUTPUT_BASE to allow a different location.` Either write inside it or set
the variable:

```bash
SBA_OUTPUT_BASE=/srv/sba-output python -m src.main convert counseling \
  --input report.csv --output /srv/sba-output/counseling.xml
```

### `run.py` never offers the XSD validation step

Known bug. It only looks for `.xsd` files **beside `run.py`**, and the bundled
schemas live in `schemas/`. Little is lost: every conversion, the launcher's
included, checks its own XML against the bundled schema and leaves out a record
that fails, with an error in the report. What the missing step costs is the
printed pass/fail. To get it, copy the schema you need next to `run.py`, or
validate separately — see [cli.md](./cli.md#runpy--interactive-launcher).

### The CLI exits 1 with no output file

The file had nothing to convert. The log says *"An unexpected error occurred: "*
followed by the reason — *"CSV has no data rows to convert."*, or *"None of the 3
row(s) could be converted; the first was left out for row 1: no Contact ID."* —
and a traceback. No XML and no report is written; the log file under `logs/` is
all there is. See
[None of the N row(s) could be converted](#none-of-the-n-rows-could-be-converted).

### `fix_sba_xml` exits 1

Either it could not process the file (*"Could not fix …: "* and why: not
well-formed, a DOCTYPE with entities, a root that is not Form 641 or 888), or it
reordered the file and the result *"still fails SBA's schema with N error(s),
which reordering can't fix"* — those errors are in the data. Exit codes:
[cli.md](./cli.md#python--m-srcfix_sba_xml--repair-element-order).

### Windows: `'python' is not recognized`

Python is not on PATH. Reinstall from python.org with **"Add Python to PATH"**
ticked, then re-run `setup.bat`.

---

## Running the stack

### The worker exits at startup

It refuses to start when it cannot find the XSDs — deliberate, because without
them it would answer every request and report every document invalid with no
reasons attached. The log says *"Schemas directory not found: '…'. Set
SCHEMAS_DIR to the directory containing …"*, or *"Schemas directory '…' is
missing: …"*, then *"Application startup failed. Exiting."*

```bash
env -u SCHEMAS_DIR python -c "import sys; sys.path.insert(0, 'apps/worker'); \
  import os; from app.services.conversion_service import SCHEMAS_DIR; \
  print(os.path.realpath(SCHEMAS_DIR), os.path.isdir(SCHEMAS_DIR))"
```

In Docker the schemas land at `/app/schemas`. If you moved them, set
`SCHEMAS_DIR`. On a Windows checkout without symlink support,
`apps/worker/schemas` is a text file rather than a link; the worker then walks up
to the repository's `schemas/` itself.

### Every conversion fails immediately

Almost always the worker token. It shows first on the preview — *"The conversion
service couldn't generate a preview…"*, with `Preview worker error: … Worker
error 401` (or `503`) in the web log. A conversion is retried twice, 30 s and
then 2 minutes apart, before it fails with *"The conversion service failed while
processing this file"*.

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/preview \
  -H 'Content-Type: application/json' -d '{}'
```

- **503** — the worker has no `WORKER_AUTH_TOKEN` at all. Set it and restart; it
  is read at import time.
- **401** — a token is set. If the web still fails, its token differs. Repeat the
  call with `-H "Authorization: Bearer $WORKER_AUTH_TOKEN"` using the web's
  value: **422** (the empty body refused) means it matches, **401** that it does
  not. Check both sides are byte-identical.
- **200** — a bug. The endpoint should never serve unauthenticated.

### Jobs stuck in converting

1. The reaper runs **lazily**, on dashboard and job reads, not on a timer. Load
   the dashboard; anything past `REAP_DEADLINE_MS` is failed then — **unless the
   queue still holds it**: waiting in `pending`, backing off in `delayed`
   between retries (a job stays `converting` meanwhile), or claimed in
   `processing`. Those are left to the queue. A failing reap is logged as
   `[job-reaper] reap failed` and the jobs are read without it.
2. Check the worker log for that job id — every line of a conversion is tagged
   with it:
   ```bash
   docker compose logs --no-color worker | grep '<jobId>'
   ```
3. Check the queue. A growing processing list with a flat pending list means
   consumers are claiming and not acking:
   ```bash
   docker compose exec redis redis-cli LRANGE csvxml:jobs:processing 0 -1
   docker compose exec redis redis-cli ZRANGE csvxml:jobs:delayed 0 -1 WITHSCORES
   docker compose exec redis redis-cli HGETALL csvxml:jobs:attempts
   ```
   A claim not finished within `VISIBILITY_TIMEOUT_MS` is re-queued by the sweep;
   after `JOB_MAX_ATTEMPTS` claims the job fails with *"Attempts exhausted:
   claimed N times without completing…"*. Per-job commands:
   [operations.md](./operations.md#a-user-reports-a-stuck-job).
4. Look for `conversion_deadlettered` in the audit trail — the consumer gave up
   and the failure is real, not a wedged queue. `metadata.error` says why: the
   worker refused the file, a deadline passed, or attempts ran out.
   `conversion_retried` entries are the attempts before it.

### Jobs stay queued and never start

The consumer is not running, or Redis lost the queue.

The consumer boots from `src/instrumentation.ts`, once per **Node.js** server
process, and never during `next build`. If you are running an unusual deployment
topology, confirm a Node runtime process actually started, and that its log has
`[job-consumer] started`. Each process converts one job at a time, so behind a
backlog a job waits; the reaper leaves a job the queue still holds alone, however
old.

If Redis restarted, queued ids are gone — persistence is not configured. The
reaper fails those jobs after `REAP_DEADLINE_MS`; users re-run them.

### Long conversions get killed at 30 minutes

Two limits stop them: the web's `CONVERSION_TIMEOUT_MS` and the worker's own
`CONVERSION_DEADLINE_SECONDS` (*"The conversion took too long"*), both 30
minutes. Raise both, keeping the worker's at or under the web's, and raise all
three durability timeouts together, keeping
`CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS`. Break that
ordering and the web refuses to start: *"Durability timeouts are misordered:
require CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS, got …"*
(`apps/web/src/lib/durability-timeouts.ts`). See
[configuration.md](./configuration.md#job-durability).

### The same job converts twice

A `conversion_retried` audit entry after `conversion_started` is a retry, not a
second run: the first attempt failed or its process died. Two runs at once would
need `VISIBILITY_TIMEOUT_MS` below `CONVERSION_TIMEOUT_MS`, so that the sweep
reclaims a job a live consumer is still running — the ordering check above
refuses to start the consumer on such a configuration.

### Large files fail at the worker with "Request body too large"

The worker caps the JSON envelope at `MAX_REQUEST_BYTES` (100 MB) and never sees
`MAX_UPLOAD_BYTES`. The CSV travels as a JSON string whose escaped quotes and
line breaks can make it larger than the file, so raising `MAX_UPLOAD_BYTES`
without raising `MAX_REQUEST_BYTES` about as much again fails the larger files:
the preview with `Worker error 413` in the web log, a conversion after its
retries. See [configuration.md](./configuration.md#limits).

### The worker container is permanently unhealthy

The healthcheck is a stdlib Python probe, not `curl` (`python:3.12-slim` ships no
curl). If you replaced it with a curl-based probe, that is the cause. It also
asserts on the response *body*, because `/health` returns 200 even when degraded.

### Prisma `P2022: column does not exist`

A `prisma/schema.prisma` change was not mirrored into
`apps/web/scripts/migrate.js`. That script — not `prisma migrate` — is what the
deployed container runs. Add the idempotent statement and redeploy. See
[deployment.md](./deployment.md#database-migrations).

### `docker compose build` fails on the first `COPY`

The build context must be the **repo root** with the Dockerfile path given
explicitly; both Dockerfiles do `COPY apps/...`. A `./apps/web` context resolves
that to `apps/web/apps/web/...`.

### Rate limits are not being applied

They fail **open**: if Redis is unreachable, requests pass unlimited. Check Redis
before concluding the limiter is misconfigured. This is deliberate — bricking
every upload on a Redis blip was judged worse — but it does mean a limit you rely
on silently stops applying during an outage. The limiter also needs Redis 7 or
later (`EXPIRE … NX`); on an older one every limit fails open.

The per-IP limits (signup, and login's second key) read the client IP from
`X-Forwarded-For`, `TRUSTED_PROXY_HOPS` entries from the right. Too high a value
lets a client choose its own IP; with `0`, or fewer entries than hops, every
signup shares one bucket and login is limited by email alone. See
[configuration.md](./configuration.md#proxies).

---

## Developing

### `No module named 'redis'` when collecting tests, or 140 tests silently skipped

You did not install `apps/worker/requirements-dev.txt`. With only
`requirements.txt`, `python -m pytest tests/` stops at collection:
`test_conversion_invariants.py` and `test_conversion_service_mapping.py` import
the worker without a guard and fail with `ModuleNotFoundError: No module named
'redis'` — *"Interrupted: 2 errors during collection"*.

The quieter trap is a partial install. Eleven more files begin with
`pytest.importorskip("fastapi")` or `("fakeredis")` and skip wholesale without
them — 140 tests. An environment that has `redis` but not `fastapi` or
`fakeredis` collects cleanly and goes green, `887 passed, 11 skipped`, with those
140 unrun: pytest counts each skipped file once, so the summary says `11
skipped`, not 140. Read the summary line for skips before trusting a local pass
([testing.md](./testing.md#a-caution-about-missing-dependencies)).

```bash
pip install -r requirements.txt -r apps/worker/requirements-dev.txt
```

### Golden tests pass but assert nothing

`.gitignore` blanket-ignores `*.xml` with an explicit `!tests/golden/*.xml`
exception. If the exception is removed, the goldens are absent on a clean
checkout and the tests regenerate-and-skip. Confirm `tests/golden/` is populated.

### Coverage gate fails

The gate is 70% and actual coverage is around 97%, so a failure means you removed
a lot of covered code or added a lot of uncovered code. Run with
`--cov-report=term-missing` to see which lines.

### `npm run lint` fails on class names

`scripts/check-ui-classes.mjs` caught a page hand-rolling classes that belong to a
`components/ui/` primitive. Use the primitive.

### Everything passes but the XML is subtly wrong

The reason `ruff` exists here. A refactor once left the tail of a method
unreachable, silently dropping four elements from every counseling record — and
because all four are `minOccurs="0"`, the XML stayed schema-valid and the whole
suite stayed green. Run `ruff check .`, and compare against `tests/golden/`.

---

## Still stuck

- Known issues: [`reviews/README.md`](./reviews/README.md#what-is-genuinely-still-open),
  which lists what is still open across every register
- Open an issue: <https://github.com/daler91/csv-to-xml-tool/issues>. On
  2026-10-17 issues were switched off for the repository, so until a maintainer
  turns them on (**Settings → General → Features**) there is nowhere to file
  one; the in-app **Help** page links there too
- Security problems: **do not** open a public issue — see
  [SECURITY.md](./SECURITY.md)
