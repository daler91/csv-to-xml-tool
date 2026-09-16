# Configuration

Every environment variable this project reads, what it defaults to, and what
breaks if you get it wrong.

Three example files exist and serve different purposes:

| File | For |
|---|---|
| `.env.example` | The Docker Compose stack — web, worker, Postgres and Redis all read it via `env_file` |
| `apps/web/.env.example` | Running the web app alone, against services you already have |
| — | The worker has no example file; it reads the same names from the environment |

---

## Required

Nothing below has a safe default. Set all four before exposing the app to anyone.

| Variable | Read by | Notes |
|---|---|---|
| `DATABASE_URL` | web | Postgres connection string |
| `NEXTAUTH_SECRET` | web | Session signing key. `openssl rand -hex 32` |
| `WORKER_AUTH_TOKEN` | web **and** worker | Shared bearer token; must be byte-identical on both sides |
| `REDIS_URL` | web, worker | Queue, progress, cancellation, rate limiting |

`WORKER_AUTH_TOKEN` fails **closed**, and the two failure modes are
distinguishable: a worker with **no token configured** returns **503** on every
functional endpoint, and a worker with a token that does not match the caller's
returns **401**. Either way nothing is served unauthenticated. In the browser
both look like a conversion that errors immediately.

The token is read at import time, so changing it means restarting the worker.

## Service wiring

| Variable | Default | Notes |
|---|---|---|
| `NEXTAUTH_URL` | — | The app's public origin. Set it in production |
| `WORKER_URL` | `http://localhost:8000` | Where the web reaches the worker. Compose sets `http://worker:8000` |
| `DATA_DIR` | `/data` | **Web-only state**: uploads and generated XML. See the note below |
| `SCHEMAS_DIR` | resolved automatically | The directory holding the SBA XSDs |
| `ENVIRONMENT` | `development` | Set to `production` on the worker to disable `/docs`, `/redoc`, `/openapi.json` and the route list in 404 bodies |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Worker CORS allowlist, comma-separated |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | — | Compose only, for the `db` service |

### About `DATA_DIR`

Web and worker do not share a filesystem — in production they are separate
services. CSV and XML content travels in the HTTP body; the worker stages it in a
`mkdtemp` directory and deletes it in a `finally`.

So `DATA_DIR` is used by the **web app only**, for `uploads/<jobId>/` and
`output/<jobId>/`. The worker still accepts the variable and creates the
directory in its image, purely so a mounted volume does not land root-owned and
unwritable. Its `/health` reporting `data_dir: unavailable` outside Docker is
expected, not a fault.

### About `SCHEMAS_DIR`

The worker resolves the schema directory itself and works in both the repo layout
and the Docker layout (`/app/schemas`). You only need to set this if you relocate
the schemas.

It **refuses to start** when the schemas cannot be found. Without them it would
answer every request and report every document invalid with no reasons attached —
a silent failure in a federal-reporting tool. CI has a dedicated step that
imports the default with `SCHEMAS_DIR` unset and asserts the directory exists,
because every other test monkeypatches it.

---

## Job durability

These three timeouts **must stay ordered**:

```
CONVERSION_TIMEOUT_MS  <  VISIBILITY_TIMEOUT_MS  <  REAP_DEADLINE_MS
```

| Variable | Default | Meaning |
|---|---|---|
| `CONVERSION_TIMEOUT_MS` | `1800000` (30 min) | How long the web waits for one `/convert` attempt before aborting it |
| `VISIBILITY_TIMEOUT_MS` | `2400000` (40 min) | A claimed job not finished within this is treated as abandoned and re-queued by the sweep |
| `REAP_DEADLINE_MS` | `3600000` (60 min) | Backstop: a job stuck `queued`/`converting` past this is failed |
| `JOB_MAX_ATTEMPTS` | `3` | Conversion attempts before dead-lettering to `error` |

Break the ordering and you get one of two failure modes. If
`VISIBILITY_TIMEOUT_MS < CONVERSION_TIMEOUT_MS`, a healthy long conversion is
re-queued while it is still running and converted twice. If
`REAP_DEADLINE_MS < VISIBILITY_TIMEOUT_MS`, the reaper fails jobs the queue would
otherwise have recovered.

Raising `CONVERSION_TIMEOUT_MS` for large files means raising all three.

> `apps/web/src/lib/worker-client.ts` has its own 5-minute default timeout for
> ad-hoc worker calls. The conversion path overrides it with
> `CONVERSION_TIMEOUT_MS`; the validate/fix routes use 60 seconds.

## Limits

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Max accepted CSV/XML upload |
| `MAX_REQUEST_BYTES` | `104857600` (100 MB) | Worker's cap on the whole JSON envelope |

`MAX_UPLOAD_BYTES` is the one that bounds memory. Both services hold the file
content in memory during a conversion, so this cap — not the request body size —
is what keeps a conversion from exhausting the container.

It is enforced at upload **and re-checked server-side** before each worker call,
so a file that grew or a job resumed against a changed file cannot slip past.

`MAX_REQUEST_BYTES` is defence in depth on the worker. It checks the declared
`Content-Length` first and then counts bytes as the body streams — the
stream-counting half is what closes the bypass where a request sent with
`Transfer-Encoding: chunked` and no `Content-Length` skipped the check entirely.

> **Editing the limit is two changes.** The number is also hardcoded in ~9
> user-facing strings ("larger than 50MB"). Raising `MAX_UPLOAD_BYTES` without
> updating that copy leaves the UI telling users the wrong number. Tracked as
> §5.6 in [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md).

## Retention

| Variable | Default | Meaning |
|---|---|---|
| `RETENTION_DAYS` | `30` | Days uploaded CSVs and generated XML stay on disk |

The sweep is **lazy** — it runs on dashboard and job reads, not on a timer — and
it removes *files only*. Job rows and the audit trail are kept, `filesPurgedAt`
is stamped, and downloads then return 410 "expired" rather than 404. Jobs that
are `queued` or `converting` are never swept, because the runner still needs the
input file.

The privacy copy shown in the browser reads this value, so changing it updates
what users are told.

## Conversion concurrency

There is no variable for this: **it is 1 per web process**, by design. A single
sequential consumer (`apps/web/src/lib/job-consumer.ts`) runs one job at a time.

To raise throughput, run more web instances. Consumers claim jobs atomically
(`BLMOVE` plus a guarded `updateMany`), so multiple consumers share one queue
without ever double-running a job.

---

## CLI-only

| Variable | Default | Meaning |
|---|---|---|
| `SBA_OUTPUT_BASE` | cwd (`src.main`) / the `run.py` folder | Directory all CLI writes (and the validator's `--directory`) are confined to |

Every CLI write — XML, reports, logs — is confined to this base, as is the
directory the XML validator is pointed at. Passing a path outside it fails with
*"Refusing to write outside …"*. See
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
