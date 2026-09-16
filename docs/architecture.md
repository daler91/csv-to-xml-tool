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

Inside `src/`, a conversion is always the same six steps:

1. **Read** — `csv.DictReader` with `utf-8-sig`, so an Excel BOM does not turn
   the first header into `﻿Contact ID`. All three converters use stdlib
   `csv`; there is no pandas anywhere in the project.
2. **Resolve columns** — each converter maps CSV headers to the fields it needs.
   Counseling declares its vocabulary once in `CounselingConfig.COLUMN_MAPPING`;
   training resolves aliases through `TrainingConfig.COLUMN_MAPPING`.
3. **Clean** — `src/data_cleaning.py` formats dates to `YYYY-MM-DD`, strips
   phone numbers to digits, maps free text onto XSD enumerations, converts
   money with `Decimal` (never `float`), and splits `;`-delimited multi-value
   Salesforce fields.
4. **Validate the row** — `src/data_validation.py` records every problem against
   a `ValidationTracker` with a severity and a category
   (`src/config.py:ValidationCategory`).
5. **Build XML** — elements are created in the exact order the XSD's
   `xs:sequence` demands, which is what prevents the `cvc-complex-type.2.4.a`
   errors that dominate hand-built SBA XML. `src/xml_utils.emit_optional` is the
   rule that a blank cell produces *no element*, never an empty one — an empty
   `<ZipCode/>` fails the `\d{5}` pattern, while omitting it is valid.
6. **Validate the document** — `src/xml_validator.py` runs lxml against the
   bundled XSD with `resolve_entities=False`, and `src/xsd_error_mapping.py`
   translates each schema error back to a CSV row and column name.

Step 6 is the part worth protecting. An unmapped lxml error reads
`Line 20: Element 'ZipCode': '' is not a valid value`. Mapped, it reads
*"Row 1 (Contact 003XX000004TMM1): 'Mailing Zip/Postal Code' is required but
blank."* That traceability is the tool's most valuable output.

## The web job lifecycle

`JobStatus` is a Postgres enum (`apps/web/prisma/schema.prisma`), so an invalid
status cannot be written by any future route or script.

```
uploaded ──► previewed ──► mapping ──┐
   │            │                    │
   └────────────┴────────────────────┴──► queued ──► converting ──► complete
                                              │           │
                                              │           ├──► error
                                              └───────────┴──► cancelled
```

- **uploaded** — `POST /api/upload` wrote the CSV under `DATA_DIR/uploads/<jobId>/`.
- **previewed** — the user opened the preview page, which asked the worker to
  parse headers and classify columns.
- **mapping** — the user saved a column mapping onto the job.
- **queued** — `POST /api/jobs/:id/start` pushed the job id onto the Redis queue.
- **converting** — the consumer claimed it and called the worker.
- **complete / error / cancelled** — terminal. Re-running means re-uploading.

### Durability

Conversion used to be a fire-and-forget promise inside the start route, which
meant a redeploy stranded jobs in `converting` forever. It is now a durable
queue (`apps/web/src/lib/job-queue.ts`):

- The start route enqueues an id with a **guarded `updateMany`**, so a job
  cancelled in the read-then-write window is never queued.
- A background consumer (`job-consumer.ts`, booted once per server process by
  `src/instrumentation.ts`) claims ids with `BLMOVE` onto a processing list.
- `job-runner.ts` runs one conversion to a terminal state. Every status write is
  a guarded `updateMany` with a `count === 0` check, so a cancel that lands
  mid-flight wins and the finished XML is discarded rather than reviving the job.
- A claim not acked within `VISIBILITY_TIMEOUT_MS` is swept back onto the queue
  (the sweep is `LREM`-gated, so competing consumers cannot double-requeue).
- `JOB_MAX_ATTEMPTS` exhausted → the job is dead-lettered to `error` with a
  `conversion_deadlettered` audit entry.
- `job-reaper.ts` is the backstop: anything stuck past `REAP_DEADLINE_MS` is
  failed. It runs lazily, on dashboard and job reads, rather than on a timer.

The three timeouts must stay ordered
`CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS`; see
[configuration.md](./configuration.md#job-durability).

**Conversion concurrency is 1 per web process** by design — one sequential
consumer, one job at a time. Scale throughput by running more web instances;
claims are atomic, so consumers share the queue safely.

## How data moves between web and worker

Web and worker are separate services (separate Railway deployments in
production) and **do not share a filesystem**. So:

- The web reads the uploaded CSV from its own disk and sends the **text** in the
  JSON request body (`csv_content`).
- The worker stages it in a `mkdtemp` directory, converts, reads the XML back,
  returns it as `xml_content`, and deletes the temp directory in a `finally`.
- The web writes that XML to `DATA_DIR/output/<jobId>/<jobId>.xml` and serves
  downloads from there.

`DATA_DIR` is therefore **web-only state**. The worker still accepts the variable
and creates the directory in its image so a mounted volume is not root-owned, but
it neither reads nor writes it during a conversion.

This is why `MAX_UPLOAD_BYTES` matters more than a request-body cap: the file is
held in memory on both sides during a conversion. The worker's
`BodySizeLimitMiddleware` (`MAX_REQUEST_BYTES`) is a backstop that rejects
oversized bodies before parsing — including bodies sent with
`Transfer-Encoding: chunked` and no `Content-Length`, which is how the earlier
Content-Length-only check was bypassable.

## Progress and cancellation

Both are per-job keys in Redis (`apps/worker/app/services/progress.py`,
`cancellation.py`), not in-process dicts. That is what lets the worker run more
than one uvicorn process or replica without a progress poll landing on the wrong
process.

Cancellation is **cooperative**: the web marks the job cancelled (authoritative),
then tells the worker; the worker checks the flag at phase checkpoints inside
`run_conversion` and raises `ConversionCancelledError`. A long CPU-bound row loop
finishes its current phase first.

## Security model at a glance

| Boundary | Control |
|---|---|
| Browser → web | Auth.js credentials session; `middleware.ts` gates `/dashboard`, `/convert`, `/validate`, `/audit` and the authenticated API routes |
| Web → worker | Shared bearer token (`WORKER_AUTH_TOKEN`), fail-closed: unset token means the worker refuses functional requests |
| Any user → any resource | Every owned resource is read with `findFirst({ where: { id, userId } })` and mutated with a `userId`-scoped `updateMany` |
| Download path | `realpath` + `DATA_DIR` prefix check with a separator suffix (`lib/paths.ts`), defeating symlink and `/data-evil` escapes |
| CLI output path | The same confinement in `src/path_safety.py`, widened only by `SBA_OUTPUT_BASE` |
| XML parsing | `defusedxml` everywhere, `resolve_entities=False` on every lxml parse — XXE is closed |
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
│       ├── app/services/          Conversion, preview, diff, progress, cancel
│       └── app/core/              Auth, schema-path resolution
├── schemas/                       The two SBA XSDs
├── tests/                         Python suite, including tests/golden/
└── docs/                          This folder
```

### `src/` module responsibilities

| Module | Responsibility |
|---|---|
| `config.py` | Column vocabularies, defaults, XSD enumerations, validation categories |
| `converters/base_converter.py` | Progress plumbing shared by all converters; `EmptyCSVError` |
| `converters/counseling_converter.py` | Form 641 counseling sessions |
| `converters/training_converter.py` | Form 888 events; rolls per-attendee rows up into event demographics |
| `converters/training_client_converter.py` | Form 641 built from per-attendee training rows |
| `data_cleaning.py` | Dates, phones, money, percentages, enum mapping, multi-value splitting |
| `data_validation.py` | Per-row validation and the preview data-quality report |
| `validation_report.py` | Issue tracking; CSV and HTML reports |
| `xml_utils.py` | `create_element` / `emit_optional` |
| `xml_validator.py` | XSD validation and element-order repair |
| `xsd_error_mapping.py` | Maps schema errors back to CSV rows and column names |
| `fix_sba_xml.py` | CLI wrapper around the order repair |
| `path_safety.py` | Output-path confinement |
| `logging_util.py` | Logging setup |

## Known architectural gaps

Tracked in [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md); the
ones that shape day-to-day work:

- **The converter abstraction is still inverted** (§5.1). `BaseConverter` shares
  progress plumbing while the counseling and training converters each carry their
  own read → validate → write pipeline. `TrainingClientConverter` shows the
  intended shape: 102 lines reusing ~470 through four hooks.
- **Counseling still reads ~70 headers as string literals** (§5.2). The
  vocabulary is declared in `COLUMN_MAPPING` and pinned by tests, but only the
  four fallback chains actually read through it.
- **Whole-file-in-memory** on both sides of a conversion; streaming would be a
  significant change ([`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md) #16).
- **No Redis persistence configured** — a Redis restart drops queued job ids.
  Jobs are recovered by the reaper as `error`, not lost silently, but they are
  not resumed.
