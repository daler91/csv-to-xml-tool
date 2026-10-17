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
                            delayed requeue on  ◄───────┘
                            transient failure (30 s, 2 min)
                            dead-letter at once on 400/422/504/timeout,
                            or after JOB_MAX_ATTEMPTS
```

What happens to a job that does not complete:

| Mechanism | Trigger | Effect |
|---|---|---|
| Retry backoff | A transient failure (network, worker 5xx, a refused token) with attempts left | Job waits in the `delayed` set for `JOB_RETRY_BASE_MS` × 4ⁿ⁻¹ after failed attempt n, then is promoted back to the queue by the next claim |
| Dead-letter | A permanent failure — worker 400/422 (the file), 504 (its deadline), or the web's own timeout — at once; anything else once `JOB_MAX_ATTEMPTS` are used | Job → `error`, `conversion_deadlettered` audit entry with the error in `metadata.error` |
| Visibility sweep | Claim not acked within `VISIBILITY_TIMEOUT_MS`; runs at startup and every minute | Re-queues the job (LREM-gated, so competing consumers cannot double-requeue) |
| Claim-time cap | A job claimed more than `JOB_MAX_ATTEMPTS` times (its runs killed the process, so they never reached the failure handler) | Dead-lettered without running; `metadata.error` reads "Attempts exhausted: claimed N times…" |
| Reaper | `queued`/`converting` past `REAP_DEADLINE_MS` **and** no longer held by the queue | Job → `error`, `conversion_timeout` audit entry |

A worker 409 means the job was cancelled; it is acked and dropped.

A job the Redis queue still holds — waiting in `pending`, backing off in
`delayed`, or claimed in `processing` — is never reaped, however old: in a long
backlog it is simply waiting its turn. Only a job the queue has lost (or never
received) is failed. If Redis cannot be asked, nothing is reaped until it can.

The reaper runs **lazily**, for the reading user only, on the dashboard page,
`GET /api/jobs` and `GET /api/jobs/:id` — not on a timer. A stuck job is
therefore cleaned up the next time its owner looks at the dashboard or the
job, not at a fixed interval. If nobody looks, nothing is reaped; that is by
design, because the only consumer of the result is the person looking.

Like the retention sweep on the same reads, it **fails open**: an error inside it
(the database unreachable for a moment, a column the deployed schema lacks) is
logged as `[job-reaper] reap failed; reading jobs without it` and the jobs are
read anyway; the next read tries again. It used to fail the request instead, so
the whole job list returned 500 over jobs that were merely stuck.

### Redis keys

Queue keys are defined in `apps/web/src/lib/job-queue.ts` under the prefix
`csvxml:jobs:`:

| Key | Type | Holds |
|---|---|---|
| `csvxml:jobs:pending` | LIST | Job ids awaiting a consumer |
| `csvxml:jobs:processing` | LIST | Job ids currently claimed — crash-visible |
| `csvxml:jobs:claims` | ZSET | `jobId → claim epoch-ms`, so the sweep can find stale claims |
| `csvxml:jobs:attempts` | HASH | `jobId → attempt count`, for retry and dead-lettering |
| `csvxml:jobs:delayed` | ZSET | `jobId → epoch-ms it may run again`, for a retry waiting out its backoff |

The worker's own keys are in `apps/worker/app/services/redis_client.py`, with a
2-hour TTL so a crashed conversion cannot leak state forever:

| Key | Holds |
|---|---|
| `csvxml:progress:<jobId>` | Progress snapshot (hash) |
| `csvxml:cancel:<jobId>` | Cancellation flag |

Rate-limit counters are `rate-limit:<bucket>` (see [Rate limits](#rate-limits)).

```bash
docker compose exec redis redis-cli LLEN   csvxml:jobs:pending
docker compose exec redis redis-cli LRANGE csvxml:jobs:processing 0 -1
docker compose exec redis redis-cli ZRANGE csvxml:jobs:claims 0 -1 WITHSCORES
docker compose exec redis redis-cli ZRANGE csvxml:jobs:delayed 0 -1 WITHSCORES
docker compose exec redis redis-cli HGETALL csvxml:jobs:attempts
```

Each web process holds at most one live claim, so a `processing` list longer
than the number of web processes means abandoned claims: a consumer died
mid-run, or its failure handling itself failed (logged as `[job-consumer]
failure handling for job … threw`). The sweep re-queues each one
`VISIBILITY_TIMEOUT_MS` after its `claims` score. If the same ids keep coming
back, a conversion is killing the process; check `conversion_deadlettered`
audit entries and the `attempts` hash.

The consumer's blocking `BLMOVE` runs on a **dedicated** Redis connection, not the
shared client — a blocking command on the shared client would stall every
rate-limit `INCR` sharing it.

On the worker, a failed Redis call opens a 30 s circuit breaker
(`redis_client.BREAKER_SECONDS`): progress writes and cancel checks are skipped
while it is open, so conversions keep their speed and lose only the progress
bar, and `GET /convert/<jobId>/progress` answers 503 instead of 404.

### Redis restart

Queued job ids can be lost — this repo configures no Redis persistence (the
compose `redis` service has no named volume and no `appendonly`). Jobs waiting
in `pending` or backing off in `delayed` are then held by nothing, and the
reaper fails them `REAP_DEADLINE_MS` after their last write with a
`conversion_timeout` entry. Users re-upload them (the results page links to
`/convert/<jobId>/reupload`); a failed job cannot be started again. A
conversion running at the time still completes, because its result is written
to Postgres. While Redis is down, starting a job answers 503 and puts the job
back so it can be started again, and rate limits stop applying.

Enabling AOF or RDB on your Redis removes this. It is the open item from Tier 2
of [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md).

## Retention

Uploads and generated XML are deleted `RETENTION_DAYS` (30 by default) after
the upload (`Job.createdAt`). The sweep runs for every user from the job
consumer in each web process, at startup and then hourly
(`retention.ts:purgeAllExpiredJobFiles`: up to 8 batches of 25, so 200 jobs a
run; a backlog drains over successive hours), and also for the reading user on
the dashboard page and `GET /api/jobs` (one batch of 25). Concurrent sweeps are
safe: each purge is claimed with a guarded update first. Like the reaper it
fails open, logged as `[retention] …`.

What survives: the job row, its summary and issues, and the full audit trail.
`filesPurgedAt` is stamped, and downloads then return **410 "expired"** rather
than a bare 404, so users get an explanation. A job purged before it was
converted answers 410 to preview and start as well.

What is never swept: jobs in `queued` or `converting` — the runner still needs
the input file. The status is re-checked in the claiming update, so a start
that lands mid-sweep wins.

A `files_purged` audit entry is written for each job purged.

## The audit trail

Every consequential action is recorded against the user. Actions actually
written by the code:

| Action | Written when |
|---|---|
| `sign_in` | A user signs in |
| `sign_in_failed` | A wrong password for an existing account (an unknown address has no user to record it against) |
| `upload` | A CSV is accepted |
| `mapping_changed` | A saved column mapping differs from the job's previous one (`metadata.mapping`, `metadata.previous`) |
| `mapping_template_saved` | A mapping template is created or overwritten |
| `mapping_template_deleted` | A mapping template is deleted |
| `conversion_started` | The consumer claims a job for the first time (`metadata.attempt` = 1) |
| `conversion_retried` | A later claim of the same job — after a requeue or a sweep re-claim (`metadata.attempt` ≥ 2) |
| `conversion_complete` | The XML is persisted |
| `conversion_cancelled` | A user cancels a queued or converting job |
| `conversion_timeout` | The reaper fails a job the queue has lost |
| `conversion_deadlettered` | A permanent failure, or attempts exhausted (`metadata.error`) |
| `download` | XML downloaded |
| `files_purged` | Retention removed a job's files |
| `job_deleted` | A user deletes a job (no `jobId`, since the row is gone; `metadata.deletedJobId`) |
| `xml_validated` | Ad-hoc validation run |
| `xml_autofix` | Ad-hoc auto-fix run |

The sign-in and mapping actions go through `lib/audit.ts:recordAudit`, which
logs a failed write as `[audit] failed to record …` instead of failing a
request whose change has already happened. The others are written inline.

A failed job has no error column, so `conversion_deadlettered` and
`conversion_timeout` are also where the results page reads its reason from
(`lib/job-failure.ts:describeJobFailure`); `metadata.error` holds the raw
worker message behind the sentence the user sees.

Users read their own trail at `/audit` and can export it as CSV (capped at 10,000
rows). The export defuses spreadsheet formula injection: values starting with
`=`, `+`, `-`, `@`, a tab or a carriage return are prefixed with an apostrophe,
because filenames in the metadata are user-controlled.

The audit page labels and filters every action above
(`app/audit/page.tsx:ACTION_LABELS`). It keeps a label for `conversion_failed`,
which entries written before dead-lettering replaced it still carry, but does
not offer it in the filter.

## Logs

Worker log lines carry the active job id, defaulting to `-`:

```
2026-09-16 01:22:28,533 [-] app.main INFO: XSD schemas found at /app/schemas
2026-09-16 01:24:02,110 [clx9k2…] app.routes.convert INFO: Conversion cancelled for job clx9k2…
```

The id is bound per request and survives into the conversion thread
(`asyncio.to_thread` copies the context), so a whole conversion's log lines are
greppable by job id — the correlation handle across the web↔worker boundary.
It is cut to `[A-Za-z0-9_-]` and 64 characters first
(`logging_context.set_job_id`), so a request cannot forge log lines. Ad-hoc
validate and fix requests carry `adhoc-<uuid>`. A conversion that passes the
worker's deadline logs `Conversion for job … passed the 1800 s deadline` at
WARNING.

The web's lines carry no job tag; the queue's put the job id in the message.
Prefixes worth grepping for: `[job-consumer]` (start, claims, sweeps),
`[job-runner]` (an input decoded as Windows-1252 or UTF-16 rather than UTF-8),
`[job-reaper]`, `[retention]`, `[job-queue]` (the consumer's Redis connection)
and `[audit]`. A preview the worker failed logs `Preview worker error:` with
the job id and the error.

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

`status` is `ok` when the API responds and the schemas resolve; without them
the worker refuses to start at all (`main.lifespan`). `data_dir` is
informational — `unavailable` outside Docker is normal, because the worker does
not use `DATA_DIR` during a conversion.

The **container** healthcheck asserts on the body, not the status code, because a
degraded worker still returns 200.

The web app has no dedicated health endpoint; Railway probes `/`.

## Rate limits

Fixed-window Redis counters (`lib/rate-limit.ts`: `INCR` and `EXPIRE … NX` in
one `MULTI`, so a key can never be left without its expiry), **fail-open** — if
Redis is unreachable requests are allowed through. That is a deliberate trade:
a Redis blip that bricks every upload is worse than a short window with no
limiting. It also means *a rate limit you are relying on silently stops
applying when Redis is down*. Alert on Redis availability rather than assuming
the limiter covers you.

| Bucket | Key (`rate-limit:` + …) | Limit |
|---|---|---|
| Signup | `signup:<ip>` | 5 / 60 s per IP |
| Login | `login:email:<email>`, `login:ip:<ip>` | 10 / 15 min per email, cleared by a successful sign-in; **and** 50 / 15 min per IP |
| Upload | `upload:<userId>` | 10 / 60 s per user |
| Validate XML / Fix XML | `validate-xml:<userId>`, `fix-xml:<userId>` | 10 / 60 s per user each |

A throttled request gets 429 with `X-RateLimit-Remaining`; a throttled sign-in
looks exactly like a wrong password. To let someone back in early, delete the
key: `docker compose exec redis redis-cli DEL rate-limit:login:email:<email>`,
with the address trimmed and lowercased as the app stores it.

The IP is the `x-forwarded-for` entry our own proxy appended, counted
`TRUSTED_PROXY_HOPS` (default 1) from the right, and validated as an address.
Everything to the left of that entry is whatever the client sent, so the first
entry — which this used to take — let a client pick a new "IP" per request. Set
`TRUSTED_PROXY_HOPS=2` if a CDN sits in front of the platform's proxy, or `0`
to ignore the header. Set it too high, or to `0`, and no IP is found: every
signup lands in one shared `signup:unknown` bucket, and the per-IP sign-in
limit stops applying.

## Capacity

- **Memory is the binding constraint.** Both services hold the file content in
  memory during a conversion, so budget several multiples of
  `MAX_UPLOAD_BYTES` per concurrent conversion. Streaming is not implemented
  ([`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md) #16). A worker
  process runs at most `MAX_CONCURRENT_REQUESTS` (4) conversions, previews and
  validations at once, so its peak is that many multiples.
- **Conversion concurrency is 1 per web process.** Scale out, not up — and
  scale the worker with the web. A request waiting for a worker slot is
  already on the web's clock, so with more converting web processes than
  worker slots, conversions spend part of their `CONVERSION_TIMEOUT_MS`
  waiting for one.
- Raising `MAX_UPLOAD_BYTES` means raising memory limits, the worker's
  `MAX_REQUEST_BYTES` (the JSON envelope can be larger than the file),
  probably the three durability timeouts and `CONVERSION_DEADLINE_SECONDS`,
  and updating the 9 hardcoded "50MB" strings left in API error messages and
  the landing and help pages (counted at `7b14f3b`; the upload and validate
  forms already show the configured cap).

## Common operational tasks

### A user reports a stuck job

1. Check its status in the dashboard. A `queued` or `converting` job past
   `REAP_DEADLINE_MS` is failed on its owner's next dashboard or job read —
   unless the queue still holds it, in which case it is waiting its turn or a
   retry. To see which:

   ```bash
   docker compose exec redis redis-cli LPOS   csvxml:jobs:pending    <jobId>
   docker compose exec redis redis-cli ZSCORE csvxml:jobs:delayed    <jobId>
   docker compose exec redis redis-cli LPOS   csvxml:jobs:processing <jobId>
   ```

   All three `(nil)` means the queue has lost it (a Redis restart, or a crash
   between the status write and the push); the reaper fails it once it is past
   the deadline.
2. `docker compose logs worker | grep <jobId>` for the conversion's log lines.
3. Look for `conversion_deadlettered` in the audit trail — the failure is real,
   not a stuck queue, and `metadata.error` says what the worker answered. The
   user sees the same reason on the job's results page.
4. If the queue itself is wedged, inspect the processing list (above).

### Freeing disk

Retention handles this on its own, hourly. To force it sooner for one user, load
the dashboard as that user; restarting a web process runs the all-users sweep at
startup. Deleting a job removes its files immediately (a `queued` or
`converting` job must be cancelled first); note the row is deleted before the
files, deliberately, so a racing start cannot pick up a job whose input is about
to vanish. If removing them fails, the web logs `Job <id> deleted but removing
<path> failed — orphaned files need manual cleanup`: with the row gone, nothing
else will ever find those directories.

### Rotating `WORKER_AUTH_TOKEN`

Change it on both services and restart both. Each reads it once at startup (the
worker at import time, the web in `lib/worker-client.ts`). Between the two
restarts every worker call is refused, which the queue treats as transient: a
conversion is retried after 30 s and then 2 min, up to `JOB_MAX_ATTEMPTS` — so
a gap longer than about two and a half minutes can dead-letter it. A
conversion the web itself was running when it restarted is recovered more
slowly, by the sweep (see Upgrading).

### Upgrading

`docker compose build && docker compose up -d --wait`. The web container runs
`scripts/migrate.js` at boot and refuses to serve if it fails. Jobs waiting in
`pending` or `delayed` live in Redis and are picked up as soon as a consumer is
back. A conversion a web process was running is not drained: Next exits on
`SIGTERM` once open HTTP requests finish, and the consumer's own `SIGTERM`
handler only stops further claims. That job stays `converting` in `processing`
until the sweep re-queues it, `VISIBILITY_TIMEOUT_MS` (40 min) after it was
claimed, and then runs again as `conversion_retried`. Slow, but not lost — that
is what the durable queue is for. A worker-only restart costs less: the web
sees a network error and retries after 30 s.
