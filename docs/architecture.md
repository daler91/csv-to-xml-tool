# Architecture

## What the system does

SBA resource partners (SBDCs, WBCs, SCORE chapters) export client activity from
Salesforce as CSV. The federal SBA Nexus/EDMIS system accepts only XML that
validates against one of two XSDs. This tool is the bridge: CSV in, schema-valid
XML out, with an auditable record of every value it changed along the way.

Because the output is a federal filing, the guiding constraint is that **the tool
must never silently invent data**. Where a default is unavoidable it is recorded
as a `FABRICATED_DEFAULT` issue in the validation report rather than shipped
quietly. See [converters.md](./converters.md#fabricated-defaults).

## Two delivery forms, one core

```
                    ┌──────────────────────────────┐
                    │   src/  (shared Python core) │
                    │  converters, cleaning,       │
                    │  validation, XSD checking    │
                    └───────▲──────────────▲───────┘
                            │              │
          imported in-process              imported in-process
                            │              │
              ┌─────────────┴───┐     ┌────┴───────────────────┐
              │  run.py         │     │  apps/worker (FastAPI) │
              │  src/main.py    │     │  HTTP service          │
              │  (CLI)          │     └────▲───────────────────┘
              └─────────────────┘          │ HTTP + bearer token
                                           │
                                  ┌────────┴──────────────┐
                                  │  apps/web (Next.js)   │
                                  │  auth, uploads, jobs, │
                                  │  downloads, audit     │
                                  └────┬──────────┬───────┘
                                       │          │
                                 ┌─────▼───┐  ┌───▼─────┐
                                 │ Postgres│  │  Redis  │
                                 └─────────┘  └─────────┘
```

The worker **imports `src/` directly** (`apps/worker/app/services/conversion_service.py`
puts the repo root on `sys.path`). It does not shell out to the CLI. One
consequence matters for reasoning about bugs: a change to `src/` changes the CLI
and the web app simultaneously, and the Python test suite in `tests/` covers both.

## Components

| Component | Path | Runtime | Responsibility |
|---|---|---|---|
| Shared core | `src/` | Python 3.12 | Read CSV → clean → validate → build XML → validate against XSD → report |
| CLI | `run.py`, `src/main.py` | Python 3.12 | Interactive launcher and an argparse CLI over the core |
| Worker | `apps/worker/` | FastAPI + uvicorn | HTTP wrapper around the core; progress and cancellation registries |
| Web | `apps/web/` | Next.js (App Router) | Auth, upload, preview/mapping, job queue, downloads, audit trail |
| Postgres | — | 16 | Users, jobs, mapping templates, audit entries |
| Redis | — | 7 | Durable job queue, per-job progress and cancel flags, rate limiting |

### Why the worker exists at all

The web app is Node; the conversion logic is Python. The worker is the smallest
possible seam between them. It holds no state of its own: every request carries
the content it operates on, and anything that must outlive a request lives in
Redis or Postgres.

## The conversion pipeline

Inside `src/`, a conversion is always the same seven steps:

1. **Read** — `BaseConverter._read_csv`: the bytes are decoded by
   `data_cleaning.decode_csv_bytes` — UTF-16 when they start with its BOM,
   otherwise UTF-8 (an Excel BOM dropped) or, failing that, Windows-1252 — and
   a read that may have changed characters (Windows-1252, a damaged or
   odd-length UTF-16 file) is a file-level warning. The rows are read with
   `data_cleaning.NormalizedDictReader`, which normalizes header whitespace and
   keeps a blank duplicate column from erasing a filled one. A cell holding no
   value (an Excel error such as `#N/A`, or only invisible characters) is read
   as blank, and a row with values past the last column, or a cell that
   swallowed the rows after it, is reported. All three converters use stdlib
   `csv`; there is no pandas anywhere in the project.
2. **Resolve columns** — each converter maps CSV headers to the fields it needs.
   Counseling declares its vocabulary once in `CounselingConfig.COLUMN_MAPPING`;
   training resolves aliases through `TrainingConfig.COLUMN_MAPPING`.
3. **Clean** — `src/data_cleaning.py` formats dates to `YYYY-MM-DD`, reduces
   phone numbers to the ten digits the XSD allows (a number that is not ten US
   digits is left out, never cut to fit), maps free text onto XSD
   enumerations, converts money with `Decimal` (never `float`), and splits
   `;`-delimited multi-value Salesforce fields.
4. **Validate the row** — `src/data_validation.py` records every problem against
   a `ValidationTracker` with a severity and a category
   (`src/config.py:ValidationCategory`). A row that is not a record — blank, a
   repeat of the header row, a report's title or footer line — is skipped here,
   with a warning naming it.
5. **Build XML** — elements are created in the exact order the XSD's
   `xs:sequence` demands, which is what prevents the `cvc-complex-type.2.4.a`
   errors that dominate hand-built SBA XML. `src/xml_utils.emit_optional` is the
   rule that a blank cell produces *no element*, never an empty one — an empty
   `<ZipCode/>` fails the `\d{5}` pattern, while omitting it is valid.
6. **Enforce the schema's facets** — `src/schema_rules.py` reads each
   element's length, enumeration, pattern and range facets from the bundled
   XSD and applies them to the finished record (`SchemaGuard`): characters
   XML cannot carry are replaced with a space, enumeration values are matched
   case-insensitively, over-length text is truncated (never identifiers),
   repeats beyond `maxOccurs` are dropped, and a value that still fails is
   omitted where the schema allows.
   Where it doesn't (a required value no fix can make valid, such as an ID
   over 20 characters), the record is left out of the XML so the rest of the
   file can still be filed. Each case is an issue against the row.
7. **Validate the document** — `src/xml_validator.py` runs lxml against the
   bundled XSD with `resolve_entities=False`, and `src/xsd_error_mapping.py`
   translates each schema error back to a CSV row and column name. The
   converters run this check themselves as a safety net under step 6
   (`BaseConverter._write_valid_xml`): a record that still fails is left out
   with an error naming its row, so the file produced is one SBA accepts. A
   failure no record explains is a file-level error in the command line's
   report. The worker validates the file again for the results page, which
   lists such a failure among its XSD errors instead (`caller_reports_xsd_errors`),
   so it is not shown twice.

Leaving out is per record, never per file. A row skipped at step 4 is
reported and left out; a record left out at step 6 or 7, or whose build raised
an error, is also counted as unsuccessful in the summary. The rest of the file
is still written and the job still completes. Only when no record is left
does the conversion fail (`BaseConverter._nothing_converted` raises
`EmptyCSVError`, naming why the first was left out); the worker answers that
with 422, which the web treats as final.

Step 7 is the part worth protecting. An unmapped lxml error reads
`Line 16: Element 'ZipCode': [facet 'pattern'] The value '' is not accepted by the pattern '\d{5}'.`
Mapped, it reads *"Row 1 (Contact 003XX000004TMM1): 'Mailing Zip/Postal Code'
(CSV column 'Mailing Zip/Postal Code') — The value '' is not accepted by the
pattern '\d{5}'."* That traceability is the tool's most valuable output.

## The web job lifecycle

`JobStatus` is a Postgres enum (`apps/web/prisma/schema.prisma`), so an invalid
status cannot be written by any future route or script.

```
uploaded ──► previewed ──► mapping ──┐
   │            │                    │
   └────────────┴────────────────────┴──► queued ──► converting ──► complete
                                              │           │
                                              ├───────────┼──► error
                                              └───────────┴──► cancelled
```

- **uploaded** — `POST /api/upload` wrote the CSV under `DATA_DIR/uploads/<jobId>/`.
- **previewed** — the user opened the preview page, which asked the worker to
  parse headers and classify columns.
- **mapping** — the user saved a column mapping onto the job. `mapping` is the
  only status a client may write (`PATCH /api/jobs/:id`), and only before the
  job is queued: a queued, converting or terminal job answers 409, because
  editing a job the queue owns made the consumer skip it or discard its result.
- **queued** — `POST /api/jobs/:id/start` pushed the job id onto the Redis queue.
- **converting** — the consumer claimed it and called the worker. A job waiting
  out a retry backoff stays `converting`.
- **error** — dead-lettered by the consumer or failed by the reaper, from
  `queued` as well as `converting` (a job the queue lost before any claim, or
  a failure before the runner's flip). The job row has no error column; the reason is
  in the audit entry, and the results page turns it into a sentence
  (`lib/job-failure.ts:describeJobFailure`).
- **complete / error / cancelled** — terminal. Re-running means re-uploading
  (the results page links to `/convert/<jobId>/reupload`, which creates a new
  job with `previousJobId` set).

### Durability

Conversion used to be a fire-and-forget promise inside the start route, which
meant a redeploy stranded jobs in `converting` forever. It is now a durable
queue (`apps/web/src/lib/job-queue.ts`):

- The start route enqueues an id with a **guarded `updateMany`**, so a job
  cancelled in the read-then-write window is never queued. If the push to
  Redis then fails, the status is rolled back and the route answers 503, so
  the user can simply start it again instead of waiting for the reaper.
- A background consumer (`job-consumer.ts`, booted once per server process by
  `src/instrumentation.ts`) claims ids with `BLMOVE` onto a processing list.
  Startup awaits nothing from Redis, so a web process still comes up while
  Redis is down; the loop retries a failed claim after a second.
- `job-runner.ts` runs one conversion to a terminal state. Every status write is
  a guarded `updateMany` with a `count === 0` check, so a cancel that lands
  mid-flight wins and the finished XML is discarded — its file deleted —
  rather than reviving the job.
- A claim not acked within `VISIBILITY_TIMEOUT_MS` is swept back onto the queue,
  at startup and then every minute (the sweep is `LREM`-gated, so competing
  consumers cannot double-requeue).
- A transient failure (network, worker 5xx) is retried after a backoff —
  `JOB_RETRY_BASE_MS` (30 s), then four times that — so a retry outlasts a
  worker redeploy. The waiting job sits in a Redis `delayed` set and the next
  claim on any consumer promotes it back to the queue when it is due
  (`ZREM`-gated, like the sweep).
- A permanent failure is not retried: the worker's 400 or 422 (the file itself
  cannot be converted), its own deadline (504) or the web's timeout
  dead-letters the job at once. A 409 (cancelled) is acked and dropped.
- `JOB_MAX_ATTEMPTS` exhausted → the job is dead-lettered to `error` with a
  `conversion_deadlettered` audit entry. The cap is also checked at claim time,
  so a job whose runs kill the process — and so never reach the failure
  handler — is dead-lettered on its next claim instead of cycling through the
  sweep for ever.
- `job-reaper.ts` is the backstop: a job stuck `queued`/`converting` past
  `REAP_DEADLINE_MS` that the queue no longer holds is failed. It runs lazily,
  on dashboard and job reads, rather than on a timer, and fails open: an error
  in it is logged and the jobs are read anyway.

The three timeouts must stay ordered
`CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS`; see
[configuration.md](./configuration.md#job-durability).

**Conversion concurrency is 1 per web process** by design — one sequential
consumer, one job at a time. Scale throughput by running more web instances;
claims are atomic, so consumers share the queue safely. The worker has its own
cap: at most `MAX_CONCURRENT_REQUESTS` (4) conversions, previews and
validations run at once per worker process (`main.py:ConcurrencyLimitMiddleware`),
and the rest wait for a slot before any of their body is read.

## How data moves between web and worker

Web and worker are separate services (separate Railway deployments in
production) and **do not share a filesystem**. So:

- The web reads the uploaded CSV from its own disk and sends the **text** in the
  JSON request body (`csv_content`). It decodes it as the converters do
  (`lib/csv-decode.ts:decodeCsvBuffer` mirrors `decode_csv_bytes`) and names
  how in `source_encoding`; the worker only ever sees text, so that field is
  what lets it record the same encoding warning the command line records.
- The worker stages it in a `mkdtemp` directory, converts, reads the XML back,
  returns it as `xml_content`, and deletes the temp directory in a `finally`.
- The web writes that XML to `DATA_DIR/output/<jobId>/<jobId>.xml` and serves
  downloads from there.

`DATA_DIR` is therefore **web-only state**. The worker still accepts the variable
and creates the directory in its image so a mounted volume is not root-owned, but
it neither reads nor writes it during a conversion.

This is why `MAX_UPLOAD_BYTES` matters more than a request-body cap: the file is
held in memory on both sides during a conversion. The web's upload routes read
the multipart body as a stream and stop at the cap
(`lib/xml-tool-route.ts:readCappedFormData`), so a chunked upload with no
`Content-Length` costs at most the cap in the process that also runs the
consumer. The worker's `BodySizeLimitMiddleware` (`MAX_REQUEST_BYTES`) is a
backstop that rejects oversized bodies before parsing — including bodies sent
with `Transfer-Encoding: chunked` and no `Content-Length`, which is how the
earlier Content-Length-only check was bypassable.

## Progress and cancellation

Both are per-job keys in Redis (`apps/worker/app/services/progress.py`,
`cancellation.py`), not in-process dicts. That is what lets the worker run more
than one uvicorn process or replica without a progress poll landing on the wrong
process.

Cancellation is **cooperative**: the web marks the job cancelled (authoritative),
then tells the worker; the worker checks the flag at phase checkpoints inside
`run_conversion` and raises `ConversionCancelledError`. A long CPU-bound row loop
finishes its current phase first. A job cancelled while still `queued` never
reaches the worker: the runner's guarded flip to `converting` skips it.

The same checkpoints enforce the worker's own deadline,
`CONVERSION_DEADLINE_SECONDS` (30 min, `routes/convert.py`): past it `/convert`
answers 504, which the web dead-letters without retrying. Before it existed the
conversion thread ran on after the web had given up on the request.

Redis is best-effort on the worker. A failed call trips a circuit breaker
(`redis_client.BREAKER_SECONDS`, 30 s) during which progress writes and cancel
checks are skipped, so a stalled Redis costs the progress bar, not the
conversion — paying the 2 s socket timeout on every progress write once made
600 rows take 68 s. While the breaker is open the progress route answers 503
rather than 404, and a cancel Redis did not store answers 503.

## Security model at a glance

| Boundary | Control |
|---|---|
| Browser → web | Auth.js credentials session, enforced in the handlers: every authenticated API route calls `getRequiredUser()` (401), and the dashboard and results pages check the session server-side. `middleware.ts` only refreshes the session cookie, and is kept off the upload routes, whose bodies Next would truncate at 10 MB for it |
| Web → worker | Shared bearer token (`WORKER_AUTH_TOKEN`), fail-closed: unset token means the worker refuses functional requests (503). With `ENVIRONMENT=production` the unauthenticated docs, OpenAPI schema and 404 route list are off |
| Any user → any resource | Every owned resource is first read with `findFirst({ where: { id, userId } })`, a 404 when it is not the caller's. The job PATCH, start and delete routes and the template delete repeat `userId` in their guarded write; cancel and preview write by `id` after that check |
| Download path | `realpath` + `DATA_DIR` prefix check with a separator suffix (`lib/paths.ts`), defeating symlink and `/data-evil` escapes |
| CLI output path | The same confinement in `src/path_safety.py`, widened only by `SBA_OUTPUT_BASE` |
| XML parsing | Every parse is lxml with `resolve_entities=False` (and lxml's default `no_network`); ElementTree only builds output, and `defusedxml` is left to the tests. A document that declares entities is refused by the validator and the fixer (`xml_validator._entity_problem`) — XXE is closed |
| Response headers | CSP with `frame-ancestors 'none'`, HSTS, nosniff, Permissions-Policy (`next.config.ts`) |

Details and the reporting process are in [SECURITY.md](./SECURITY.md).

## Directory map

```
.
├── run.py, run.bat, setup.bat     Interactive launcher + Windows shortcuts
├── src/                           Shared conversion core (see table below)
├── apps/
│   ├── web/                       Next.js app — auth, jobs, UI, downloads
│   │   ├── src/app/api/           Route handlers
│   │   ├── src/lib/               Queue, runner, reaper, retention, auth, paths
│   │   ├── prisma/schema.prisma   Data model
│   │   └── scripts/migrate.js     Startup DDL (see deployment.md)
│   └── worker/                    FastAPI service
│       ├── app/routes/            /health /preview /convert /validate-xsd /fix-xml
│       ├── app/services/          Conversion, preview, diff, progress, cancel, Redis client
│       └── app/core/              Auth, schema-path resolution
├── schemas/                       The two SBA XSDs
├── tests/                         Python suite, including tests/golden/
└── docs/                          This folder
```

### `src/` module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Column vocabularies, defaults, XSD enumerations, validation categories |
| `converters/base_converter.py` | Shared by all converters: CSV reading (`_read_csv`), identifier cleaning, the final XSD check that leaves failing records out (`_write_valid_xml`), progress plumbing; `EmptyCSVError` |
| `converters/counseling_converter.py` | Form 641 counseling sessions |
| `converters/training_converter.py` | Form 888 events; rolls per-attendee rows up into event demographics |
| `converters/training_client_converter.py` | Form 641 built from per-attendee training rows |
| `data_cleaning.py` | CSV decoding and the header-normalizing reader; dates, phones, money, percentages, enum mapping, multi-value splitting |
| `data_validation.py` | Per-row validation and the preview data-quality report |
| `schema_rules.py` | Reads the XSD's facets and applies them to each finished record (`SchemaGuard`) |
| `validation_report.py` | Issue tracking; CSV and HTML reports |
| `xml_utils.py` | `create_element` / `emit_optional` / `write_document` |
| `xml_validator.py` | XSD validation, and element-order repair read from the XSD itself |
| `xsd_error_mapping.py` | Maps schema errors back to CSV rows and column names |
| `fix_sba_xml.py` | CLI wrapper around the order repair; re-validates and exits non-zero when a file still fails |
| `path_safety.py` | Output-path confinement |
| `logging_util.py` | Logging setup |

## Known architectural gaps

Tracked in [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md); the
ones that shape day-to-day work:

- **The converter abstraction is still inverted** (§5.1). `BaseConverter` now
  shares reading, identifier cleaning and the final XSD check, but there is no
  template-method `convert()`: the counseling and training converters each
  carry their own row loop and record building (1,192 and 847 lines at
  `7b14f3b`). `TrainingClientConverter` shows the intended shape: 176 lines at
  `7b14f3b` that reuse the counseling converter by overriding hooks such as
  `_preprocess_row` and `_csv_cell`.
- **Counseling still reads 64 of its 74 headers as string literals** (§5.2,
  counted at `7b14f3b`). The vocabulary is declared in `COLUMN_MAPPING` and
  pinned by tests, but only five keys — the Part 3 fallback chains, the
  internet source and the business start date — actually read through it.
- **Whole-file-in-memory** on both sides of a conversion; streaming would be a
  significant change ([`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md) #16).
- **No Redis persistence configured** — a Redis restart can drop queued and
  backing-off job ids. Jobs are recovered by the reaper as `error`, not lost
  silently, but they are not resumed.
