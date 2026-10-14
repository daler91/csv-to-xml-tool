# API reference

Two HTTP surfaces:

- **[Web API](#web-api)** (`apps/web`) — what the browser calls. Session-authenticated.
- **[Worker API](#worker-api)** (`apps/worker`) — what the web calls. Bearer-token
  authenticated, server-to-server only. Not reachable from a browser and not
  intended to be exposed publicly.

---

## Web API

Base: the app's own origin. All routes are under `/api`.

### Authentication

Auth.js credentials sessions. Every authenticated handler calls
`getRequiredUser()` itself; an expired or missing session returns **401** with
`{"error": "Unauthorized"}`.

`middleware.ts` does no access control; it has no `authorized` callback. On
`/api/jobs/*`, `/api/audit` and `/api/mapping-templates/*` it only refreshes the
session cookie. It deliberately does not run on `/api/upload`,
`/api/validate-xml` or `/api/fix-xml`. Next buffers the body of every request
middleware runs on and truncates it at 10 MB, so a file between 10 MB and the
upload cap arrived cut short and failed with a 5xx.

Every user-owned resource is fetched with `findFirst({ where: { id, userId } })`
and mutated with a `userId`-scoped `updateMany`, so another user's job id returns
404 rather than leaking its existence.

### Rate limits

Redis token buckets. **Fail-open**: if Redis is unreachable the request is
allowed through, because bricking uploads on a Redis blip is worse than the
window it opens. Responses that are limited return **429** with
`X-RateLimit-Remaining`.

| Bucket | Limit | Key |
|---|---|---|
| `signup` | 5 / 60s | client IP (the `x-forwarded-for` entry added by our own proxy — see `TRUSTED_PROXY_HOPS` — validated) |
| login | throttled per email **and** per IP | — |
| `upload` | 10 / 60s | user id |
| `validate-xml` | 10 / 60s | user id |
| `fix-xml` | 10 / 60s | user id |

---

### `POST /api/auth/signup`

Create an account. Passwords must contain an uppercase letter, a digit and a
special character.

| Status | Meaning |
|---|---|
| 201 | Created |
| 400 | Validation failure: body not a JSON object, missing/invalid email (shape and ≤254 characters), non-string name, or password complexity |
| 409 | Email already registered — also when two signups for one address race past the pre-check |
| 429 | Rate limited |

Emails are trimmed and lowercased on write and on lookup, so `User@example.com`
and `user@example.com` are one identity.

### `GET|POST /api/auth/[...nextauth]`

Auth.js handlers — sign in, sign out, session, CSRF.

---

### `POST /api/upload`

`multipart/form-data`.

| Field | Required | Notes |
|---|---|---|
| `file` | yes | `.csv` only, ≤ `MAX_UPLOAD_BYTES` (50 MB default) |
| `converterType` | yes | `counseling` \| `training` \| `training-client` |
| `previousJobId` | no | Links this job to an earlier one for the re-upload comparison |

**201** → `{ "jobId": "<cuid>" }`

| Status | Meaning |
|---|---|
| 400 | Missing field, a `file` part that is not a file, a name not ending in `.csv` (case-insensitive), unknown converter type, or a `previousJobId` that is not yours |
| 401 | Not signed in |
| 413 | Over the size cap — checked against the declared `Content-Length` before the body is buffered, then against the file itself |
| 429 | Rate limited |
| 500 | Write failed — the job row is deleted and the partial upload directory removed, so no orphan is left behind |

`previousJobId` is looked up scoped to your user before it is accepted. The
filename is reduced to its basename and stripped to `[A-Za-z0-9._-]`.

### `GET /api/jobs`

Your jobs, newest first. Before reading, this route lazily reaps jobs stuck past
the deadline and purges files past the retention window, so the list reflects
reality rather than a crashed conversion lingering forever.

Returns `id`, `converterType`, `status`, `inputFileName`, `totalRows`, `summary`,
`xsdValid`, `createdAt`, `completedAt`.

### `GET /api/jobs/:jobId`

The full job row. While a job is `converting`, the response is merged with the
worker's live progress snapshot and gains `processedRows`, a live `totalRows`,
and `progressUpdatedAt` — that is what drives the progress bar.

`404` if the job is not yours or does not exist.

> `Job.processedRows` exists in the schema but is never written to the database;
> the value above is computed per request from Redis.

### `PATCH /api/jobs/:jobId`

Update `columnMapping` and/or `status`. Any other field in the body is ignored.
`columnMapping` must be a flat object of non-empty column-name strings (at most
200 entries of 200 characters; `{}` is allowed). `status` may only be set to
`mapping` — every other transition belongs to a server-side actor (`/start`,
the queue consumer, `/cancel`, `/preview`).

| Status | Meaning |
|---|---|
| 200 | Updated; returns the fresh row |
| 400 | Body is not a JSON object, no updatable field, an invalid `columnMapping`, or a `status` other than `mapping` |
| 409 | The job is `cancelled`, `complete` or `error` and cannot be modified |

The update is a guarded `updateMany`; if a cancel lands between the read and the
write it returns 409 with the job's actual status rather than reviving it.

### `DELETE /api/jobs/:jobId`

| Status | Meaning |
|---|---|
| 200 | `{ "deleted": true }` |
| 409 | The job is `queued` or `converting` — cancel it first |

The database row is deleted **before** the files, deliberately: the guarded row
delete is the atomic claim, so a racing `POST /start` cannot pick up a job whose
input file is about to disappear. Audit entries survive (their `jobId` is set to
null), and a `job_deleted` entry is written.

### `POST /api/jobs/:jobId/start`

Enqueue the conversion.

| Status | Meaning |
|---|---|
| 202 | `{ "status": "queued" }` |
| 404 | Not found / not yours |
| 409 | Status is not `uploaded`, `previewed` or `mapping` |
| 410 | The uploaded file expired under the retention policy — upload it again |
| 413 | The file on disk exceeds the cap (re-checked server-side, not just at upload) |
| 503 | Could not reach Redis to enqueue; the status is rolled back so you can retry immediately |

The 503 path matters: without the rollback the row would sit `queued` with
nothing to pick it up, 409ing every retry until the reaper failed it an hour
later with no explanation.

### `GET /api/jobs/:jobId/preview`

Proxies the CSV to the worker's `/preview` and returns headers, sample rows,
column status (matched / missing / extra plus fuzzy rename suggestions) and the
data-quality summary. Flips the job to `previewed` unless it is already terminal
or in flight.

For the `training` converter a column counts as matched when the file carries
**any** of its accepted spellings (`city` for `City`, `Zip code` for
`Zip/Postal Code`); `column_status.aliases` maps each such canonical column to
the header that satisfied it. `training-client` expects only the columns its
converter reads, so export-only columns (`Member Status`, `Related Record ID`, …)
are neither expected nor reported missing.

`400` with the worker's own message when the worker rejects the CSV content
(malformed file); `410` if the file has been purged; `413` if it exceeds the cap;
`502` when the worker is unreachable, refuses `WORKER_AUTH_TOKEN` or fails, with
the cause in the web log as `Preview worker error: <jobId> …`.

The file is decoded as strict UTF-8 (BOM preserved) with a fallback to
Windows-1252 for Excel's "CSV (Comma delimited)" exports — the same decoding
the conversion itself uses — so the preview shows the characters the filing
will carry.

### `POST /api/jobs/:jobId/cancel`

Always **200**, with the job's resulting status. Cancelling an already-terminal
job is a no-op that reports the existing status rather than an error.

The database is updated first (authoritative), then the worker is told. The
worker checks the flag at phase checkpoints, so cancellation is cooperative — an
in-flight phase completes before it takes effect.

### `GET /api/jobs/:jobId/download`

The generated XML as `application/xml` with a `Content-Disposition` attachment
header.

| Status | Meaning |
|---|---|
| 200 | The file |
| 404 | No output file, not yours, or the path failed the `DATA_DIR` confinement check |
| 410 | Files purged under the retention policy |

The path is resolved with `realpath` and checked against `DATA_DIR` with a
trailing separator, which defeats both symlink escapes and the `/data-evil`
prefix trick.

### `GET /api/mapping-templates?converterType=…`

Your saved mappings for that converter type, plus `lastJobMapping` — the mapping
from your most recent completed job of that type, so the mapping page can offer
"same as last time".

### `POST /api/mapping-templates`

Save a named mapping. Name ≤ 60 chars; at most 200 entries; each key and value
≤ 200 chars. Unique per `(user, converterType, name)`.

### `DELETE /api/mapping-templates/:templateId`

Delete one of your templates.

### `GET /api/audit`

Your audit trail, newest first.

| Param | Default | Bounds |
|---|---|---|
| `page` | 1 | ≥ 1 |
| `pageSize` | 50 | 1–200 |
| `action` | — | Exact match |
| `format` | JSON | `csv` for an export, capped at 10,000 rows |

Out-of-range and non-numeric values are clamped rather than rejected, so
`?pageSize=abc` and `?page=0` behave sensibly instead of 500ing.

CSV export escapes quotes and prefixes any value starting with `=`, `+`, `-`, `@`
or a control character with an apostrophe, so user-controlled filenames cannot
become formulas when the file opens in Excel or Sheets.

**Actions actually written:** `upload`, `mapping_changed` (the column mapping
of a job changed; metadata holds the new and previous mapping),
`conversion_started`, `conversion_retried`, `conversion_complete`,
`conversion_cancelled`, `conversion_timeout`, `conversion_deadlettered`,
`download`, `files_purged`, `job_deleted`, `xml_validated`, `xml_autofix`,
`mapping_template_saved`, `mapping_template_deleted`, `sign_in` and
`sign_in_failed` (a wrong password for an existing account; an address with no
account has no user to file an entry under). The audit page labels each of
them and offers each as a filter.

### `POST /api/validate-xml`

Validate an existing XML file without creating a job. `multipart/form-data` with
`file` (`.xml`, ≤ cap) and `schemaType` (`counseling` | `training` |
`training-client`).

Returns the worker's `is_valid`, `errors`, `error_count` and `error_details`.
UTF-16 files (with a BOM, or declaring a non-UTF-8 encoding) are decoded
correctly rather than mangled into false failures. Writes an `xml_validated`
audit entry.

### `POST /api/fix-xml`

Same shape, but `schemaType` accepts **`counseling` | `training-client` only** —
auto-fix is offered for counseling-format XML. Returns `changed`, the
`fixed_xml_content`, `fix_error`, and the re-validation result. Writes an
`xml_autofix` entry, with `refused: true` when the worker could not process the
file.

Both routes return **400** for a worker-side client error, **502** when the
worker is unreachable, and use a 60-second worker timeout.

---

## Worker API

FastAPI, default port 8000.

### Authentication

Every functional endpoint requires `Authorization: Bearer $WORKER_AUTH_TOKEN`.
It is **fail-closed**: with no token configured the worker refuses functional
requests rather than serving them unauthenticated. `/health` is deliberately
exempt so container and platform health probes keep working.

CORS allows only `GET` and `POST`, only the `Authorization` and `Content-Type`
headers, and only the origins in `ALLOWED_ORIGINS` (default
`http://localhost:3000`).

Request bodies over `MAX_REQUEST_BYTES` (100 MB default) get **413**. The check
looks at `Content-Length` first and then counts bytes as the body streams, so a
chunked request without a `Content-Length` cannot slip past it.

At most `MAX_CONCURRENT_REQUESTS` (default 4) authenticated `/convert`,
`/preview`, `/validate-xsd` and `/fix-xml` requests run at once; the rest wait
for a slot before their body is read. `/health`, progress and cancel are never
queued.

Every error body is `{"detail": "<string>"}`. A request that fails validation (a
missing field, or a `converter_type` / `schema_type` other than `counseling`,
`training` or `training-client`) is a **422** whose detail names the field and
the rule, without repeating the value that was sent.

In production (`ENVIRONMENT=production`), `/docs`, `/redoc`, `/openapi.json` and
the route list in 404 bodies are all disabled.

### `GET /health`

Unauthenticated.

```json
{"status": "ok", "checks": {"api": "ok", "schemas": "ok", "data_dir": "unavailable"}}
```

`data_dir: unavailable` is normal outside Docker — the worker does not use
`DATA_DIR` during a conversion. `status` is `ok` as long as the API responds and
the schemas resolve; the compose healthcheck asserts on `status`, not the HTTP
code, because a degraded worker still returns 200.

The worker **refuses to start** if it cannot locate the XSDs, checked in the
lifespan hook rather than at import so that importing the app (as the tests do)
stays side-effect free.

### `POST /preview`

```json
{"job_id": "…", "csv_content": "…", "converter_type": "counseling"}
```

→ `headers`, `rows`, `total_rows`, `column_status`, `data_quality`.

`data_quality` is `{"total_rows": int, "checks": [{key, label, count, severity,
detail, column}]}` and lists only checks with a non-zero count.

A CSV that cannot be parsed at all (typically an unclosed quote, which turns the
rest of the file into one oversized cell) is a `422` whose detail says so. An
unclosed quote that swallows fewer rows parses; the conversion then records an
error naming the row and column where it opened.

### `POST /convert`

```json
{"job_id": "…", "csv_content": "…", "converter_type": "counseling",
 "column_mapping": {"Your Header": "Expected Header"}}
```

→ `xml_content`, `stats`, `xsd_valid`, `xsd_errors`, `xsd_error_details`,
`issues`, `cleaning_diff`.

| Status | Meaning |
|---|---|
| 200 | Converted (possibly with `xsd_valid: false`) |
| 400 | Invalid request parameters |
| 409 | Cancelled by the user mid-conversion |
| 422 | Unprocessable CSV — required columns missing, the file is empty/headers-only, it cannot be parsed as CSV (e.g. an unclosed quote), or it holds a lone UTF-16 surrogate (a JSON `\ud800` escape), which no file can; the detail gives its line and column |
| 500 | Internal conversion error |
| 504 | The conversion passed `CONVERSION_DEADLINE_SECONDS` (default 30 min, checked between phases); the web treats it as final, like its own timeout |

`422` is the important one: the detail string names exactly which required
columns are missing, so the web layer can tell the user what to fix. A
headers-only CSV is also a 422 rather than a "success" that produces an empty
document.

The CSV is staged in a `mkdtemp` directory and removed in a `finally`. Any stale
progress snapshot for the same `job_id` is cleared on entry — retries reuse the
id — but the cancel flag is deliberately **not** cleared, because it is only ever
set after the web has authoritatively cancelled the job.

### `POST /convert/{job_id}/cancel`

Sets the cancellation flag: 200 with `{"job_id": "…", "cancelled": true}`,
including for a job that already finished, or **503** when Redis did not store
the flag (so the conversion will not see it). The conversion stops at the next
phase checkpoint.

### `GET /convert/{job_id}/progress`

The current progress snapshot (`processed`, `total`, `updated_at`), or **404**
when none is recorded — either the job has finished (the `/convert` route clears
the snapshot in its `finally`) or it has not started yet. The web layer treats
404 as "no live progress" and falls back to the database row. **503** means
Redis is unavailable, so whether progress exists is unknown.

### `POST /validate-xsd`

```json
{"job_id": "…", "xml_content": "…", "schema_type": "counseling"}
```

→ `is_valid`, `errors`, `error_count`, `error_details`.

A document the validator cannot check is a result, not an error status:
unparseable XML (`XML parse error: …`), a DOCTYPE that declares or uses entities
(`DTD/entity declarations are not supported: …` — entities are never expanded),
or text holding a lone UTF-16 surrogate, which no XML file can (the error gives
its line and column).

`error_details[].row_number` is the 1-based ordinal of the record element in the
document, so an error can be traced to a record without counting lines. (There
is no CSV here. In a `/convert` result, `xsd_error_details[].row_number` is the
1-based CSV data row the record was built from — for a training event, its
first row — so a skipped row does not shift the numbers after it.)

### `POST /fix-xml`

Same request shape; `schema_type` must be `counseling` or `training-client`.

→ `changed`, `fixed_xml_content`, `fix_error`, plus the re-validation result
(`is_valid`, `errors`, `error_count`, `error_details`).

Reordering only. It never invents an element to satisfy the schema. Every
`xs:sequence` is put in the order the counseling XSD lists it, not only
`ClientIntake`'s; comments, processing instructions, the DOCTYPE and a carriage
return written as `&#13;` come through unchanged.

| Field | Meaning |
|---|---|
| `changed` | An element moved. Nothing else is ever changed |
| `fixed_xml_content` | The reordered document; exactly the text sent when nothing moved; empty only when that text cannot be sent back (a lone surrogate) |
| `fix_error` | Why the fixer could not process the document — unparseable, a DOCTYPE that declares entities (`DTD/entity declarations are not supported`), a root element the counseling XSD does not declare, a lone surrogate — or `null` when it ran. The validation result is then the original's |

### Unmatched paths

Any other path returns 404 `{"detail": "No route matched"}`, logged at INFO.
Outside production the response also lists the registered routes; in
production that list goes to the startup log only. A known path with the wrong
method is a **405**.
