# Operations

Running the web stack day to day. For error messages users report, see
[troubleshooting.md](./troubleshooting.md).

## The job queue

A durable Redis queue owned by the web app (`apps/web/src/lib/job-queue.ts`).

```
POST /start ──► guarded updateMany ──► status=queued ──► LPUSH pending
                                                              │
                      ┌───────────────────────────────────────┘
                      ▼
       job-consumer  ──BLMOVE──►  processing  ──►  job-runner
                                       │                │
                      ack (LREM) ◄─────┘        worker POST /convert
                                                        │
                            requeue on failure  ◄───────┘
                            dead-letter after JOB_MAX_ATTEMPTS
```

Three recovery mechanisms, in order of how quickly they act:

| Mechanism | Trigger | Effect |
|---|---|---|
| Visibility sweep | Claim not acked within `VISIBILITY_TIMEOUT_MS` | Re-queues the job (LREM-gated, so competing consumers cannot double-requeue) |
| Dead-letter | `JOB_MAX_ATTEMPTS` exhausted | Job → `error`, `conversion_deadlettered` audit entry |
| Reaper | Stuck `queued`/`converting` past `REAP_DEADLINE_MS` | Job → `error` |

The reaper runs **lazily**, on `GET /api/jobs` and `GET /api/jobs/:id` — not on a
timer. A stuck job is therefore cleaned up the next time anyone looks at their
dashboard, not at a fixed interval. If nobody looks, nothing is reaped; that is
by design, because the only consumer of the result is the person looking.

### Redis keys

Queue keys are defined in `apps/web/src/lib/job-queue.ts` under the prefix
`csvxml:jobs:`:

| Key | Type | Holds |
|---|---|---|
| `csvxml:jobs:pending` | LIST | Job ids awaiting a consumer |
| `csvxml:jobs:processing` | LIST | Job ids currently claimed — crash-visible |
| `csvxml:jobs:claims` | ZSET | `jobId → claim epoch-ms`, so the sweep can find stale claims |
| `csvxml:jobs:attempts` | HASH | `jobId → attempt count`, for retry and dead-lettering |

The worker's own keys are in `apps/worker/app/services/redis_client.py`, with a
2-hour TTL so a crashed conversion cannot leak state forever:

| Key | Holds |
|---|---|
| `csvxml:progress:<jobId>` | Progress snapshot (hash) |
| `csvxml:cancel:<jobId>` | Cancellation flag |

```bash
docker compose exec redis redis-cli LLEN   csvxml:jobs:pending
docker compose exec redis redis-cli LRANGE csvxml:jobs:processing 0 -1
docker compose exec redis redis-cli ZRANGE csvxml:jobs:claims 0 -1 WITHSCORES
docker compose exec redis redis-cli HGETALL csvxml:jobs:attempts
```

A growing `processing` list with a flat `pending` list means consumers are
claiming jobs and not acking them: either conversions are genuinely slow, or the
consumer process is dying mid-run. Check `conversion_deadlettered` audit entries
and the `attempts` hash.

The consumer's blocking `BLMOVE` runs on a **dedicated** Redis connection, not the
shared client — a blocking command on the shared client would stall every
rate-limit `INCR` sharing it.

### Redis restart

Queued job ids are lost — persistence is not configured. Jobs sitting in `queued`
will not be picked up, and the reaper fails them after `REAP_DEADLINE_MS` with a
`conversion_timeout` entry. Users re-run them from the dashboard.

Enabling AOF or RDB on your Redis removes this. It is the open item from Tier 2
of [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md).

## Retention

Uploads and generated XML are deleted after `RETENTION_DAYS` (30 by default).
The sweep is lazy, like the reaper, and runs on dashboard reads.

What survives: the job row, its summary and issues, and the full audit trail.
`filesPurgedAt` is stamped, and downloads then return **410 "expired"** rather
than a bare 404, so users get an explanation.

What is never swept: jobs in `queued` or `converting` — the runner still needs
the input file.

A `files_purged` audit entry is written for each sweep.

## The audit trail

Every consequential action is recorded against the user. Actions actually
written by the code:

| Action | Written when |
|---|---|
| `upload` | A CSV is accepted |
| `conversion_started` | The consumer claims a job for the first time (`metadata.attempt` = 1) |
| `conversion_retried` | A later claim of the same job — after a requeue or a sweep re-claim (`metadata.attempt` ≥ 2) |
| `conversion_complete` | The XML is persisted |
| `conversion_cancelled` | A user cancels |
| `conversion_timeout` | The reaper fails a stuck job |
| `conversion_deadlettered` | Attempts exhausted |
| `download` | XML downloaded |
| `files_purged` | Retention removed a job's files |
| `job_deleted` | A user deletes a job |
| `xml_validated` | Ad-hoc validation run |
| `xml_autofix` | Ad-hoc auto-fix run |

Users read their own trail at `/audit` and can export it as CSV (capped at 10,000
rows). The export defuses spreadsheet formula injection: values starting with
`=`, `+`, `-`, `@` or a control character are prefixed with an apostrophe,
because filenames in the metadata are user-controlled.

> The audit **page** filter is out of sync with this list — it offers a
> `conversion_failed` option no code writes, and omits six actions that are
> written, which render as "—". See
> [documentation-audit.md](./documentation-audit.md#code-issues-found-during-the-audit).

## Logs

Worker log lines carry the active job id, defaulting to `-`:

```
2026-09-16 01:22:28,533 [-] app.main INFO: XSD schemas found at /app/schemas
2026-09-16 01:24:02,110 [clx9k2…] app.routes.convert INFO: Conversion cancelled
```

The id is bound per request and survives into the conversion thread
(`asyncio.to_thread` copies the context), so a whole conversion's log lines are
greppable by job id — the correlation handle across the web↔worker boundary.

There is **no log rotation**. Ship logs off the container or rotate them
externally. Tracebacks are logged with `exc_info=True`, so treat log access as
privileged.

```bash
docker compose logs -f worker
docker compose logs -f web
docker compose logs --no-color worker | grep 'clx9k2abc'
```

## Health

```bash
curl -s http://localhost:8000/health
# {"status":"ok","checks":{"api":"ok","schemas":"ok","data_dir":"ok"}}
```

`status` is `ok` when the API responds and the schemas resolve. `data_dir` is
informational — `unavailable` outside Docker is normal, because the worker does
not use `DATA_DIR` during a conversion.

The **container** healthcheck asserts on the body, not the status code, because a
degraded worker still returns 200.

The web app has no dedicated health endpoint; Railway probes `/`.

## Rate limits

Redis token buckets, **fail-open** — if Redis is unreachable requests are allowed
through. That is a deliberate trade: a Redis blip that bricks every upload is
worse than a short window with no limiting. It also means *a rate limit you are
relying on silently stops applying when Redis is down*. Alert on Redis
availability rather than assuming the limiter covers you.

| Bucket | Limit |
|---|---|
| Signup | 5 / 60s per IP |
| Login | throttled per email **and** per IP |
| Upload | 10 / 60s per user |
| Validate XML / Fix XML | 10 / 60s per user each |

The IP is the first entry of `x-forwarded-for`, validated — not the whole header,
which is trivially spoofable.

## Capacity

- **Memory is the binding constraint.** Both services hold the file content in
  memory during a conversion, so budget several multiples of
  `MAX_UPLOAD_BYTES` per concurrent conversion. Streaming is not implemented
  ([`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md) #16).
- **Conversion concurrency is 1 per web process.** Scale out, not up.
- Raising `MAX_UPLOAD_BYTES` means raising memory limits, probably raising the
  three durability timeouts, and updating ~9 hardcoded "50MB" strings in the UI.

## Common operational tasks

### A user reports a stuck job

1. Check its status in the dashboard. `converting` past `REAP_DEADLINE_MS` will
   be reaped on the next dashboard read.
2. `docker compose logs worker | grep <jobId>` for the conversion's log lines.
3. Look for `conversion_deadlettered` in the audit trail — that means attempts
   were exhausted and the failure is real, not a stuck queue.
4. If the queue itself is wedged, inspect the processing list (above).

### Freeing disk

Retention handles this on its own. To force it, hit the dashboard as the affected
user — the sweep is per-user and lazy. Deleting a job removes its files
immediately; note the row is deleted before the files, deliberately, so a racing
start cannot pick up a job whose input is about to vanish.

### Rotating `WORKER_AUTH_TOKEN`

Change it on both services and restart both. The worker reads it at import time.
Conversions in flight during the restart fail and are retried by the queue, up to
`JOB_MAX_ATTEMPTS`.

### Upgrading

`docker compose build && docker compose up -d --wait`. The web container runs
`scripts/migrate.js` at boot and refuses to serve if it fails. In-flight
conversions are re-claimed by the consumer after restart — that is what the
durable queue is for.
