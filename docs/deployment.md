# Deployment

Four services: **web** (Next.js), **worker** (FastAPI), **Postgres**, **Redis**.

## Docker Compose

```bash
cp .env.example .env
# Set NEXTAUTH_SECRET and WORKER_AUTH_TOKEN to real values
docker compose up -d --wait
```

`--wait` blocks until every healthcheck passes, which is what you want in a
script — without it, `up -d` returns as soon as the containers start, before the
worker has confirmed it can find its schemas. The web has no healthcheck, so for
it `--wait` means only *running*: it can return while `migrate.js` is still
going. `docker compose ps` afterwards shows whether the web stayed up.

### What compose sets up

- **Build context is the repo root for both images**, with the Dockerfile path
  given explicitly. This matters: `apps/web/Dockerfile` does
  `COPY apps/web/...`, so a `./apps/web` context would resolve that to
  `apps/web/apps/web/...` and fail on the first `COPY`. The root
  `.dockerignore` keeps the context to what the Dockerfiles copy, and keeps
  `.env` out of it.
- **A shared `shared-data` volume** mounted at `/data` in both containers. Only
  the web app actually uses it; the worker mounts it so a future path-passing
  design would not need a volume change, and so the directory is not root-owned.
  Postgres keeps its data in a `pgdata` volume; Redis gets none.
- **Ports 3000 (web) and 8000 (worker) are published on the host**; db and redis
  are not. The worker's port is there for local debugging. On a host anyone else
  can reach, remove it: the worker must not be public.
- **`environment:` overrides `.env`** for `WORKER_URL=http://worker:8000` and
  `NEXTAUTH_URL=http://localhost:3000` on the web, and `DATA_DIR=/data` and
  `SCHEMAS_DIR=/app/schemas` on the worker. Serving the stack under another
  origin means editing `NEXTAUTH_URL` here, not in `.env`.
- **Healthchecks on db, redis and worker**, with `depends_on: condition:
  service_healthy`, so the web never starts against a database that is not ready.
  The worker waits for redis the same way. Images: `postgres:16-alpine`,
  `redis:7-alpine`.
- **The worker healthcheck is a stdlib Python one-liner, not `curl`.**
  `python:3.12-slim` ships no curl; the previous probe failed with "executable
  file not found" on every attempt and the worker was permanently unhealthy. It
  also asserts on the response *body* (`status == "ok"`), because `/health`
  returns 200 even when degraded.

### CI builds and boots the stack

The `docker-build` job in `.github/workflows/ci.yml` copies `.env.example` to
`.env`, runs `docker compose build` followed by `up -d --wait`, dumps the logs if
a step failed, and always ends with `down -v`. That combination exists because
three separate deployment defects shipped while nothing in CI built an image: a
build context that could not resolve, a healthcheck calling a binary the image
does not have, and a failed migration that still started the server. `build`
alone catches only the first.

`up --wait` catches the second for certain. The third only if the web exits
before compose sees it running: with no web healthcheck, a migration that fails
after that can still pass the job.

---

## Railway

Both apps carry a `railway.toml`. They deploy as **separate services** with no
shared filesystem, which is why conversion payloads travel over HTTP.

### Web (`apps/web/railway.toml`)

```toml
[build]
builder = "dockerfile"
dockerfilePath = "apps/web/Dockerfile"

[deploy]
healthcheckPath = "/"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

**There is deliberately no `startCommand`.** The Dockerfile `CMD` is the single
source of truth. The command that used to live here ran `npx prisma db push`,
which could not work — the runtime stage copies neither `prisma/schema.prisma`
nor the Prisma CLI — and contradicted `scripts/migrate.js`, which is what the
container actually runs. That divergence caused a production incident (commit
`481c0a2`). Do not reintroduce it. Railway documents that a start command on a
Dockerfile service replaces the image's `ENTRYPOINT` as well, so one here would
also skip the [entrypoint](#web-appswebdockerfile) that makes `DATA_DIR`
writable.

### Worker (`apps/worker/railway.toml`)

Declares `ENVIRONMENT = "production"` under `[deploy.variables]`, meant to
disable `/docs`, `/redoc`, `/openapi.json` and the route list in 404 bodies — all
of which are served unauthenticated and describe the entire API. Railway's
config as code covers a service's build and deploy settings, not its variables,
so do not rely on this line: set `ENVIRONMENT=production` on the service and
check that `/docs` returns 404 (see
[Verifying a deployment](#verifying-a-deployment)).

`startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"` replaces the
image's `CMD`. Railway documents that a Dockerfile service's start command runs
without a shell, so `$PORT` is not expanded; if the worker log shows `'$PORT' is
not a valid integer`, this line is why, and the image's own `CMD` (which expands
`${PORT:-8000}`) is the fix. Healthcheck path is `/health`; restarts are
`on_failure`, at most 3.

### Required Railway variables

Web: `DATABASE_URL`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `WORKER_URL`,
`WORKER_AUTH_TOKEN`, `REDIS_URL`, and a volume mounted at `DATA_DIR` (`/data`
unless you set it).
Worker: `WORKER_AUTH_TOKEN` (identical), `REDIS_URL` (the same Redis),
`ALLOWED_ORIGINS`, `ENVIRONMENT=production`. Without `REDIS_URL` the worker falls
back to `localhost`, and the progress bar and Cancel silently stop working.

### Volume ownership on Railway

**A Railway volume is mounted root-owned**, and that is not configurable. The web
app runs as the unprivileged `node` user, so the image's
[entrypoint](#web-appswebdockerfile) re-owns `DATA_DIR` to `node` on every start,
before dropping privileges. No Railway setting is needed. `RAILWAY_RUN_UID=0`,
Railway's usual workaround, is harmless if already set: the entrypoint still
drops to `node`.

An image built before that entrypoint cannot write to the volume. Every upload
fails with `EACCES`, the browser shows only *"Something went wrong on our side.
Please try again in a minute. If it keeps happening, contact support."*, and the
web log shows:

```
Upload error: Error: EACCES: permission denied, mkdir '/data/uploads'
```

Redeploying a current image fixes it. A non-zero `RAILWAY_RUN_UID` prevents the
re-own; the entrypoint then logs `entrypoint: /data is not writable by uid …` at
boot.

Redis must be **7.0 or newer**: the rate limiter arms its window with
`EXPIRE … NX`, which older servers reject (the limiter then fails open, so the
signup, sign-in, upload and validate/fix limits would all be silently off).
Below 6.2 the queue's `BLMOVE` fails too, and no job is ever claimed. Compose
uses `redis:7-alpine`.

Full reference: [configuration.md](./configuration.md).

---

## Images

Both apps run as **unprivileged users**, and both images create and `chown`
`/data` so a fresh Docker named volume, which inherits that ownership on first
mount, is writable.

### Web (`apps/web/Dockerfile`)

Three stages, all `node:20-alpine`: deps (`npm ci --ignore-scripts`, so the
lockfile CI tested) → builder (`npm run generate`, `npm run build`; `npm run`
rather than `npx`, which could fetch an unpinned `prisma`) → runtime from the
Next.js standalone output, plus `su-exec`. The app runs as `node`.

Next's `server.js` listens on `PORT` (default 3000) at `HOSTNAME` (default
`0.0.0.0`). Docker sets `HOSTNAME` to the container id in every container, and
the image does not override it, so the server binds to the container's own
address rather than all interfaces: a probe from inside the container must use
that address, not `localhost`.

The runtime stage deliberately has no `USER`. `scripts/entrypoint.sh` starts as
root, creates `DATA_DIR`, re-owns whatever under it is not already `node`'s, and
then `su-exec`s to `node`. No root process stays behind, and `migrate.js` and
`server.js` never run as root. The build-time `chown` alone was not enough: a
volume mounted at runtime keeps its own ownership. That covers a Railway volume
(always root-owned, see [above](#volume-ownership-on-railway)) and a volume
first written while this image still ran as root, before `6fad498`.

The re-own takes a symlink itself, never its target, and leaves alone a file
with more than one hard link. A failed re-own is logged
(`entrypoint: could not give … to user node`), not fatal: the app still serves
everything but uploads.

Because the entrypoint runs as root, it is installed as a root-owned
`/usr/local/bin/web-entrypoint.sh`, not run from `/app/scripts`: everything
under `/app` belongs to `node`, and a compromised app could otherwise rewrite
the script and have root run it at the next container start.

```dockerfile
ENTRYPOINT ["/bin/sh", "/usr/local/bin/web-entrypoint.sh"]
CMD ["sh", "-c", "node scripts/migrate.js && node server.js"]
```

The `&&` is load-bearing. It used to be `;`, so a failed migration still started
the server: the app came up against a half-migrated database and every query
failed at request time with Prisma `P2022` instead of the container failing at
boot. `scripts/migrate.js` exiting non-zero and the `&&` are a pair — either one
alone leaves the hole open.

### Worker (`apps/worker/Dockerfile`)

`python:3.12-slim`, pinned by digest so a rebuild gets the image CI tested. No
apt packages: dependencies install wheels-only and hash-checked
(`pip install --only-binary :all: --require-hashes -r requirements.txt`, the
lock compiled from `apps/worker/requirements.in`), and the lxml wheel bundles
its own libxml2/libxslt. Copies `src/`, `schemas/` (landing at `/app/schemas`,
which is exactly what `app/core/paths.py` resolves to) and `apps/worker/app/`.
Runs as user `worker`, uid 10001.

`CMD` is `uvicorn app.main:app` on `${PORT:-8000}`. It carries a `HEALTHCHECK`
mirroring the compose one, probing the same `$PORT`, so `docker run` gets one
too.

### Base-image updates

`.github/dependabot.yml` checks the `apps/worker` and `apps/web` Dockerfiles
weekly, labels its PRs `dependencies` and `docker`, and holds at most 5 open.
Major and minor version bumps are ignored: Python 3.12 → 3.13 or Node 20 → 22 is
a deliberate change, made together with CI's `python-version` and
`node-version`, not a weekly one.

So the worker picks up base-image security fixes through a Dependabot PR for
each new digest of `3.12-slim`; to refresh by hand, take the digest from
`docker buildx imagetools inspect python:3.12-slim`. The web's `node:20-alpine`
is a tag, not a digest: every build takes whatever it points at that day, and
Dependabot has no digest to bump there. npm and pip dependencies are not in
Dependabot at all.

---

## Database migrations

**`apps/web/scripts/migrate.js` is what runs**, not `prisma migrate` and not
`prisma db push`. It executes a list of idempotent DDL statements
(`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, enum creation wrapped
in a `DO $$ … EXCEPTION WHEN duplicate_object`) one at a time, because Prisma
does not accept multiple statements per call.

> ### The rule
>
> **Every change to `prisma/schema.prisma` must be mirrored into
> `scripts/migrate.js` as an idempotent statement, in the same commit.**
>
> Miss it and production boots against a database missing the new column, and
> every query on that model fails with `P2022`.

This is a known wart — two independent sources of truth for the DDL, tracked as
§5.6 in [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md). Until
it is resolved, the rule above is the mitigation.

As of `7b14f3b` every model, column, index, foreign key and enum value in the
schema has its statement. Every `Job` column but one has been in its
`CREATE TABLE` since the script was written; `filesPurgedAt`, added later, has
its own `ADD COLUMN IF NOT EXISTS`. That is the pattern to follow: a column added
only to a `CREATE TABLE IF NOT EXISTS` reaches new databases and never existing
ones, and a new `JobStatus` value needs `ALTER TYPE … ADD VALUE IF NOT EXISTS`,
since the `CREATE TYPE` guard skips a type that already exists.

The script runs as `node`, connects with `DATABASE_URL`, and sets a non-zero exit
code on any failure, which the `&&` in `CMD` turns into a container that exits at
boot.

The script also normalizes existing emails to trimmed lowercase, skipping any row
whose normalized form already belongs to another user, so it can never abort the
boot migration on the unique index.

---

## Scaling

- **Conversion throughput**: run more web instances. Each runs one sequential
  consumer; claims are atomic, so consumers share the queue safely. Every
  instance must mount the same `DATA_DIR`: the one that claims a job reads its
  upload from disk, and any one may serve the download.
- **Worker replicas**: safe. Progress and cancellation live in Redis, not in
  process memory, so a poll or a cancel landing on a different replica works.
  `MAX_CONCURRENT_REQUESTS` applies per process, so worker memory scales with
  replicas too.
- **Redis is not configured for persistence.** A restart drops queued job ids.
  Jobs are recovered as `error` by the reaper rather than lost silently — once
  `REAP_DEADLINE_MS` has passed, on their owner's next dashboard or job read —
  but they are not resumed. Enable AOF or RDB if that matters to you — it is the
  one open item from Tier 2 of the codebase analysis.
- **Postgres**: standard. `Job` and `AuditEntry` are indexed on
  `(userId, createdAt DESC)`; `AuditEntry` is additionally indexed on `action`,
  and `MappingTemplate` on `(userId, converterType)`.

## Pre-deployment checklist

- [ ] `NEXTAUTH_SECRET` and `WORKER_AUTH_TOKEN` are freshly generated, not the
      `.env.example` placeholders
- [ ] `WORKER_AUTH_TOKEN` is byte-identical on web and worker
- [ ] `REDIS_URL` is set on both web and worker, to the same Redis
- [ ] `ENVIRONMENT=production` on the worker, set on the service itself, and
      `/docs` answers 404
- [ ] `ALLOWED_ORIGINS` names only your web origin
- [ ] The worker is **not** publicly reachable (private network or firewall;
      compose publishes port 8000)
- [ ] `NEXTAUTH_URL` is the real public origin
- [ ] `DATA_DIR` points at durable storage (on Railway, a mounted volume), shared
      by every web instance. The entrypoint makes it writable by `node`; the log
      carries an `entrypoint:` warning if it could not (see [Volume ownership](#volume-ownership-on-railway))
- [ ] Redis is 7.0 or newer
- [ ] Schema changes are mirrored in `scripts/migrate.js`
- [ ] `RETENTION_DAYS` matches what you tell users, and is positive
- [ ] The three durability timeouts are still correctly ordered (the web
      refuses to start otherwise)
- [ ] A changed `MAX_UPLOAD_BYTES` came with a matching `MAX_REQUEST_BYTES` and
      the hardcoded "50MB" copy (see [configuration.md](./configuration.md#limits))
- [ ] **`src/config.py` tenant constants match the organization filing** — see
      [converters.md](./converters.md#-this-is-a-single-organization-tool). This
      is the one that produces wrong federal filings if you skip it.

## Verifying a deployment

```bash
curl -s https://your-worker/health                       # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' \
  https://your-worker/docs                               # 404 in production
curl -sI https://your-app/ | grep -i content-security    # CSP present
```

Then sign up, convert `counseling-sample.csv`, and confirm the results page
reports the XML as schema-valid.
