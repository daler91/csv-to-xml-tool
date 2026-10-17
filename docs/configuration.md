# Configuration

Every environment variable this project reads, what it defaults to, and what
breaks if you get it wrong.

Three example files exist and serve different purposes:

| File | For |
|---|---|
| `.env.example` | The Docker Compose stack — web, worker and Postgres read it via `env_file`; Redis takes no configuration |
| `apps/web/.env.example` | Running the web app alone, against services you already have |
| — | The worker has no example file; it reads the same names from the environment |

Compose's own `environment:` entries win over the file. It sets `WORKER_URL` and
`NEXTAUTH_URL` for the web and `DATA_DIR` and `SCHEMAS_DIR` for the worker, so
those lines in `.env` have no effect on the stack. Each service that names the
file receives all of it, secrets included.

---

## Required

Nothing below has a safe default. Set all four before exposing the app to anyone.

| Variable | Read by | Notes |
|---|---|---|
| `DATABASE_URL` | web | Postgres connection string, read by Prisma (`prisma/schema.prisma`) and `scripts/migrate.js`. Missing or wrong, the migration fails and the container exits at boot |
| `NEXTAUTH_SECRET` | web | Session signing key. `openssl rand -hex 32`. Auth.js also accepts `AUTH_SECRET`, which wins if both are set. Missing, every auth request answers 500 "There was a problem with the server configuration" and the log names `MissingSecret` |
| `WORKER_AUTH_TOKEN` | web **and** worker | Shared bearer token; must be byte-identical on both sides |
| `REDIS_URL` | web, worker | Queue, progress, cancellation, rate limiting. Both sides fall back to `redis://localhost:6379`, which is right only for local development |

`WORKER_AUTH_TOKEN` fails **closed**, and the two failure modes are
distinguishable: a worker with **no token configured** returns **503** on every
functional endpoint, and a worker with a token that does not match the caller's
returns **401**. Either way nothing is served unauthenticated. In the browser
both look like a conversion that errors immediately. A web with no token sends
no `Authorization` header at all, which a configured worker answers 401.

Both sides read the token once, when the module loads, so changing it means
restarting both.

An unreachable Redis fails open rather than crashing anything: the rate limits
switch off, Start answers 503 *"Couldn't queue the conversion just now"*, and
the worker's progress bar and Cancel stop working until it is back.

## Service wiring

| Variable | Default | Notes |
|---|---|---|
| `NEXTAUTH_URL` | — | The app's public origin. Set it in production: Auth.js rewrites its own requests to this origin, so sign-in redirects follow it. It also accepts `AUTH_URL`. Compose sets `http://localhost:3000` |
| `WORKER_URL` | `http://localhost:8000` | Where the web reaches the worker. Compose sets `http://worker:8000` |
| `DATA_DIR` | `/data` | **Web-only state**: uploads and generated XML. The web image sets `/data`. See the note below |
| `SCHEMAS_DIR` | resolved automatically | The directory holding the SBA XSDs. Read by the worker and by the converters in `src/`, so the CLI too |
| `ENVIRONMENT` | `development` | Set to `production` (or `prod`, any case) on the worker to disable `/docs`, `/redoc`, `/openapi.json` and the route list in 404 bodies |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Worker CORS allowlist, comma-separated. Entries are not trimmed, so no spaces after the commas |
| `PORT` | web `3000`, worker `8000` | Listen port. Railway sets it; the worker image's `CMD` and `HEALTHCHECK` both follow it. Compose sets neither |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | — | Compose only, for the `db` service |

The frameworks read a few more that need no setting: `NODE_ENV` (the web image
and Next's `server.js` force `production`), `NEXT_RUNTIME` and `NEXT_PHASE`
(Next sets them; `src/instrumentation.ts` uses them to start the queue consumer
only on the Node runtime and never during `next build`), and `HOSTNAME` (see
[deployment.md](./deployment.md#web-appswebdockerfile)).

### About `DATA_DIR`

Web and worker do not share a filesystem — in production they are separate
services. CSV and XML content travels in the HTTP body; the worker stages it in a
`mkdtemp` directory and deletes it in a `finally`.

So `DATA_DIR` is used by the **web app only**, for `uploads/<jobId>/` and
`output/<jobId>/`. The web image's entrypoint creates it and re-owns it to `node`
at every start (see [deployment.md](./deployment.md#web-appswebdockerfile)).
Outside Docker the `/data` default is usually not writable; point it at a
directory you own.

The worker still accepts the variable and creates the directory in its image,
purely so a mounted volume does not land root-owned and unwritable. It only
lists the directory for `/health`, where `data_dir: unavailable` outside Docker
is expected, not a fault. `src/xml_validator.py` also reads it,
but only for a caller that passes `enforce_data_dir=True`, and none does.

### About `SCHEMAS_DIR`

The worker resolves the schema directory itself and works in both the repo layout
and the Docker layout (`/app/schemas`). You only need to set this if you relocate
the schemas.

It **refuses to start** when the schemas cannot be found. Without them it would
answer every request and report every document invalid with no reasons attached —
a silent failure in a federal-reporting tool. CI has a dedicated step that
imports the default with `SCHEMAS_DIR` unset and asserts the directory exists,
because every other test monkeypatches it.

The converters read it too (`src/schema_rules.py:schema_path`, falling back to
the repo's `schemas/`), and there nothing refuses. A CLI run pointed at a
directory without the XSDs logs *"Schema facets unavailable … value checks
skipped"*, writes the file without the final XSD check, and exits 0.

The values in each record are checked against the XSD's own types as the record
is built (`src/schema_rules.py`). If you replace the XSDs with ones where a type
can't be compiled on its own — one based on a type from a file the XSD includes,
or a pattern libxml2 refuses — a warning names the elements affected. Only their
patterns and other libxml2-only facets go unchecked at that stage; the XSD check
of the finished file still catches a bad value, but leaves out the whole record.

---

## Job durability

These three timeouts **must stay ordered**:

```
CONVERSION_TIMEOUT_MS  <  VISIBILITY_TIMEOUT_MS  <  REAP_DEADLINE_MS
```

| Variable | Default | Meaning |
|---|---|---|
| `CONVERSION_TIMEOUT_MS` | `1800000` (30 min) | How long the web waits for one `/convert` attempt before aborting it. A timed-out attempt is not retried |
| `VISIBILITY_TIMEOUT_MS` | `2400000` (40 min) | A claimed job not finished within this is treated as abandoned and re-queued by the sweep, which runs every minute |
| `REAP_DEADLINE_MS` | `3600000` (60 min) | Backstop: a job stuck `queued`/`converting` past this, and no longer held by the queue, is failed the next time its owner loads the dashboard or a job |
| `JOB_MAX_ATTEMPTS` | `3` | Conversion attempts before dead-lettering to `error`. Also checked at claim time, so it caps a job whose attempts crash the process instead of throwing |
| `JOB_RETRY_BASE_MS` | `30000` (30 s) | Wait before retrying a transiently failed attempt; each further retry waits 4× longer (30 s, 2 min with the defaults) |

The three timeouts are read by `apps/web/src/lib/durability-timeouts.ts`. Each
must be a positive number of milliseconds; anything else — empty, `0`, negative,
not a number — silently becomes the default. The two `JOB_*` values use
`Number(value) || default`, so empty, `0` or not a number becomes the default but
a negative value is taken as given.

**The web refuses to start on a misordered override.** The queue consumer calls
`assertTimeoutOrdering()` at startup, and the error names all three values. The
ordering exists because if `VISIBILITY_TIMEOUT_MS < CONVERSION_TIMEOUT_MS`, a
healthy long conversion is re-queued while it is still running and converted
twice. The reaper leaves alone any job the queue still holds — pending, backing
off or claimed — so it fails only jobs the queue has lost, such as one a Redis
restart dropped.

Raising `CONVERSION_TIMEOUT_MS` for large files means raising all three, and
the worker's `CONVERSION_DEADLINE_SECONDS` (see [Limits](#limits)). Past two
hours a fixed limit appears: the worker's cancel flag expires after 2 hours
(`apps/worker/app/services/redis_client.py:TTL_SECONDS`). A conversion still
running then no longer sees the Cancel and runs to the end; the job stays
cancelled and its result is discarded.

> `apps/web/src/lib/worker-client.ts` has its own 5-minute default timeout for
> ad-hoc worker calls, which the preview uses. The conversion path overrides it
> with `CONVERSION_TIMEOUT_MS`; the validate/fix routes use 60 seconds, the
> progress poll 3 seconds and the cancel 5. None of these is configurable.

## Proxies

| Variable | Default | Meaning |
|---|---|---|
| `TRUSTED_PROXY_HOPS` | `1` | Web: how many proxies sit in front of the app. The client IP used for the signup and login rate limits is the `X-Forwarded-For` entry that many from the right; `0` ignores the header. A value that is not a whole number ≥ 0 counts as `1` |

With no proxy in front (the compose stack), Next fills `X-Forwarded-For` from
the socket only when the request carries none, so the entry the limiter reads
is whatever the caller sent. That is fine locally and wrong on a public host.
With no usable entry (`0`, or fewer entries than hops), every signup shares one
`unknown` bucket and login is limited by email alone.

## Limits

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Web: max accepted CSV/XML upload, in bytes |
| `MAX_REQUEST_BYTES` | `104857600` (100 MB) | Worker's cap on the whole JSON envelope, in bytes |
| `MAX_CONCURRENT_REQUESTS` | `4` | Worker, per process: `/convert`, `/preview`, `/validate-xsd` and `/fix-xml` requests run at once; more wait for a slot. Below `1` counts as `1` |
| `CONVERSION_DEADLINE_SECONDS` | `1800` (30 min) | Worker's own limit on one conversion, in **seconds**; keep it at or under the web's `CONVERSION_TIMEOUT_MS` |

The web reads `MAX_UPLOAD_BYTES` with `Number(value) || default`: empty, `0` or
not a number gives 50 MB, but a negative value is taken as given and refuses
every upload. The worker parses its three numbers with `int()`/`float()` when it
starts, so a value that is not a number stops the worker from starting.

`MAX_UPLOAD_BYTES` is the one that bounds memory. Both services hold the file
content in memory during a conversion, so this cap — not the request body size —
is what keeps a conversion from exhausting the container.

It is enforced at upload **and re-checked server-side** before each worker call,
so a file that grew or a job resumed against a changed file cannot slip past.
The upload and validate/fix routes also stop reading a multipart body at the cap
plus 64 KB of framing, whether or not it declares a `Content-Length`
(`apps/web/src/lib/xml-tool-route.ts:readCappedFormData`). Those routes are left
out of the auth middleware's matcher (`apps/web/middleware.ts`) because Next
truncates any body middleware runs on at 10 MB.

`MAX_REQUEST_BYTES` is 100 MB rather than 50 because the CSV travels as a JSON
string, and escaping its quotes and line breaks can make the envelope larger
than the file. What bounds the worker's memory is `MAX_UPLOAD_BYTES` times
`MAX_CONCURRENT_REQUESTS`: requests beyond the cap wait before their body is
read. The worker never sees `MAX_UPLOAD_BYTES`, so raising it means raising
`MAX_REQUEST_BYTES` with it, about double. A conversion whose envelope passes
the worker's cap gets a 413, which the web retries as transient and then fails.

`CONVERSION_DEADLINE_SECONDS` stops a conversion the web has already given up
on. It applies to `/convert` only, and is checked between phases (column
mapping, cleaning diff, conversion, XSD validation), so a conversion stops at
the first boundary after it; the web treats the resulting 504 as final rather
than retrying it. Zero or a negative value fails every conversion at its first
checkpoint.

`MAX_REQUEST_BYTES` is defence in depth on the worker. It checks the declared
`Content-Length` first and then counts bytes as the body streams — the
stream-counting half is what closes the bypass where a request sent with
`Transfer-Encoding: chunked` and no `Content-Length` skipped the check entirely.

> **Editing the limit is two changes.** The convert and validate pages are
> handed the cap by their server component and format it
> (`apps/web/src/lib/limits.ts:formatMegabytes`), but 9 user-facing strings
> still hardcode 50MB: the *"File size exceeds 50MB limit"* error from the
> upload, start, preview and validate/fix routes, the home page, and three on
> the help page. Raising `MAX_UPLOAD_BYTES` without updating that copy leaves
> those naming the wrong number; only the upload route's is hidden, because the
> convert form shows its own message for a 413. Tracked as §5.6 in
> [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md).

## Retention

| Variable | Default | Meaning |
|---|---|---|
| `RETENTION_DAYS` | `30` | Days uploaded CSVs and generated XML stay on disk |

The sweep runs for all users from the web's job consumer when it starts and
then hourly, up to 200 jobs a run, and also on a user's dashboard and job-list
reads. It removes *files only*. Job rows and the audit trail are kept, `filesPurgedAt`
is stamped, and downloads then return 410 "expired" rather than 404. Jobs that
are `queued` or `converting` are never swept, because the runner still needs the
input file.

It is read with `Number(value) || 30`, so `0` means 30, not "keep nothing". A
negative value puts the cutoff in the future, and the next sweep purges the
files of every finished job.

The privacy copy shown in the browser reads this value, so changing it updates
what users are told.

## Conversion concurrency

There is no variable for this: **it is 1 per web process**, by design. A single
sequential consumer (`apps/web/src/lib/job-consumer.ts`) runs one job at a time.

To raise throughput, run more web instances. Consumers claim jobs atomically
(`BLMOVE` plus a guarded `updateMany`), so multiple consumers share one queue
without ever double-running a job. They must also share one `DATA_DIR`: the
instance that claims a job reads the upload from disk, and any instance may
serve the download.

---

## CLI-only

| Variable | Default | Meaning |
|---|---|---|
| `SBA_OUTPUT_BASE` | cwd (`src.main`, the fixer, the validator) / the `run.py` folder | Directory the conversion's writes, and the fixer's and validator's `--directory` mode, are confined to |

A conversion's writes — XML, reports, logs — are confined to this base, as are
the folder the fixer and validator walk in `--directory` mode and their output
directory. Passing a path outside it fails with *"Refusing to write outside …"*,
as a Python traceback. The fixer's and validator's **single-file** mode is not
confined: `--file`/`--xmlfile` and `--output` are used as given. See
[cli.md](./cli.md#output-path-confinement).

---

## Generating secrets

```bash
openssl rand -hex 32     # NEXTAUTH_SECRET
openssl rand -hex 32     # WORKER_AUTH_TOKEN (different value)
```

`.env` is gitignored and `.env.example` contains placeholders only. The
placeholder values are fine for a throwaway local stack — CI copies
`.env.example` to `.env` verbatim to build and boot the stack — and fine for
nothing else.

## Verifying your configuration

```bash
# Worker: schemas resolve without an explicit SCHEMAS_DIR
env -u SCHEMAS_DIR python -c "import sys; sys.path.insert(0, 'apps/worker'); \
  import os; from app.services.conversion_service import SCHEMAS_DIR; \
  assert os.path.isdir(SCHEMAS_DIR), SCHEMAS_DIR; print('schemas:', os.path.realpath(SCHEMAS_DIR))"

# Worker: healthy and finding its schemas
curl -s http://localhost:8000/health

# Worker: the token is actually enforced. 401 = configured and rejecting you.
# 503 = no token configured at all (fail-closed). 200 would be a bug.
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/preview \
  -H 'Content-Type: application/json' -d '{}'

# Whole stack
docker compose up -d --wait && docker compose ps
```
