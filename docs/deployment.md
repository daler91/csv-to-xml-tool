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
worker has confirmed it can find its schemas.

### What compose sets up

- **Build context is the repo root for both images**, with the Dockerfile path
  given explicitly. This matters: `apps/web/Dockerfile` does
  `COPY apps/web/...`, so a `./apps/web` context would resolve that to
  `apps/web/apps/web/...` and fail on the first `COPY`.
- **A shared `shared-data` volume** mounted at `/data` in both containers. Only
  the web app actually uses it; the worker mounts it so a future path-passing
  design would not need a volume change, and so the directory is not root-owned.
- **Healthchecks on db, redis and worker**, with `depends_on: condition:
  service_healthy`, so the web never starts against a database that is not ready.
- **The worker healthcheck is a stdlib Python one-liner, not `curl`.**
  `python:3.12-slim` ships no curl; the previous probe failed with "executable
  file not found" on every attempt and the worker was permanently unhealthy. It
  also asserts on the response *body* (`status == "ok"`), because `/health`
  returns 200 even when degraded.

### CI builds and boots the stack

The `docker-build` job in `.github/workflows/ci.yml` runs `docker compose build`
followed by `up -d --wait`. That combination exists because three separate
deployment defects shipped while nothing in CI built an image: a build context
that could not resolve, a healthcheck calling a binary the image does not have,
and a failed migration that still started the server. `build` alone catches only
the first.

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
`481c0a2`). Do not reintroduce it.

### Worker (`apps/worker/railway.toml`)

Sets `ENVIRONMENT = "production"`, which disables `/docs`, `/redoc`,
`/openapi.json` and the route list in 404 bodies — all of which are served
unauthenticated and describe the entire API. Healthcheck path is `/health`.

### Required Railway variables

Web: `DATABASE_URL`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `WORKER_URL`,
`WORKER_AUTH_TOKEN`, `REDIS_URL`, `DATA_DIR` (a mounted volume).
Worker: `WORKER_AUTH_TOKEN` (identical), `ALLOWED_ORIGINS`, `ENVIRONMENT=production`.

Full reference: [configuration.md](./configuration.md).

---

## Images

Both run as **unprivileged users** and both create and `chown` `/data` so a
freshly mounted volume is writable.

### Web (`apps/web/Dockerfile`)

Three stages: deps → builder (`prisma generate`, `next build`) → runtime from the
Next.js standalone output. Runs as `node`.

```dockerfile
CMD ["sh", "-c", "node scripts/migrate.js && node server.js"]
```

The `&&` is load-bearing. It used to be `;`, so a failed migration still started
the server: the app came up against a half-migrated database and every query
failed at request time with Prisma `P2022` instead of the container failing at
boot. `scripts/migrate.js` exiting non-zero and the `&&` are a pair — either one
alone leaves the hole open.

### Worker (`apps/worker/Dockerfile`)

`python:3.12-slim` plus `libxml2-dev`/`libxslt1-dev` for lxml. Copies `src/`,
`schemas/` (landing at `/app/schemas`, which is exactly what
`app/core/paths.py` resolves to) and `apps/worker/app/`. Runs as uid 10001.
Carries a `HEALTHCHECK` mirroring the compose one, so `docker run` gets one too.

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

The script also normalizes existing emails to trimmed lowercase, skipping any row
whose normalized form already belongs to another user, so it can never abort the
boot migration on the unique index.

---

## Scaling

- **Conversion throughput**: run more web instances. Each runs one sequential
  consumer; claims are atomic, so consumers share the queue safely.
- **Worker replicas**: safe. Progress and cancellation live in Redis, not in
  process memory, so a poll or a cancel landing on a different replica works.
- **Redis is not configured for persistence.** A restart drops queued job ids.
  Jobs are recovered as `error` by the reaper rather than lost silently, but they
  are not resumed. Enable AOF or RDB if that matters to you — it is the one open
  item from Tier 2 of the codebase analysis.
- **Postgres**: standard. `Job` and `AuditEntry` are indexed on
  `(userId, createdAt DESC)`; `AuditEntry` is additionally indexed on `action`.

## Pre-deployment checklist

- [ ] `NEXTAUTH_SECRET` and `WORKER_AUTH_TOKEN` are freshly generated, not the
      `.env.example` placeholders
- [ ] `WORKER_AUTH_TOKEN` is byte-identical on web and worker
- [ ] `ENVIRONMENT=production` on the worker
- [ ] `ALLOWED_ORIGINS` names only your web origin
- [ ] The worker is **not** publicly reachable (private network or firewall)
- [ ] `NEXTAUTH_URL` is the real public origin
- [ ] `DATA_DIR` points at durable, writable storage
- [ ] Schema changes are mirrored in `scripts/migrate.js`
- [ ] `RETENTION_DAYS` matches what you tell users
- [ ] The three durability timeouts are still correctly ordered
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
