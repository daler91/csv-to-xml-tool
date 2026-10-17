# API reference

Two HTTP surfaces:

- **[Web API](#web-api)** (`apps/web`) — what the browser calls. Session-authenticated.
- **[Worker API](#worker-api)** (`apps/worker`) — what the web calls. Bearer-token
  authenticated, server-to-server only. Not reachable from a browser and not
  intended to be exposed publicly.

---

## Web API

Base: the app's own origin. All routes are under `/api` — at 7b14f3b, 18
handlers in 14 `route.ts` files, each one below.

### Authentication

Auth.js credentials sessions. Every authenticated handler calls
`getRequiredUser()` itself; an expired or missing session returns **401** with
`{"error": "Unauthorized"}`.

`middleware.ts` does no access control; it has no `authorized` callback. On
`/api/jobs/*`, `/api/audit` and `/api/mapping-templates/*` (and the
`/dashboard`, `/convert`, `/validate` and `/audit` pages) it only refreshes the
session cookie. It deliberately does not run on `/api/upload`,
`/api/validate-xml` or `/api/fix-xml`. Next buffers the body of every request
middleware runs on and truncates it at 10 MB, so a file between 10 MB and the
upload cap arrived cut short and failed with a 5xx.

Every user-owned resource is fetched with `findFirst({ where: { id, userId } })`
before anything else happens, so another user's job id returns 404 rather than
leaking its existence. Writes are guarded `updateMany` / `deleteMany` calls; the
ones in `PATCH`, `DELETE` and `/start` repeat the `userId` scope, the ones in
`/cancel` and `/preview` rely on the ownership read before them.

### Rate limits

Redis fixed-window counters (`lib/rate-limit.ts:rateLimit`: `INCR`, with the
window's `EXPIRE … NX` in the same `MULTI`). **Fail-open**: if Redis is
unreachable the request is allowed through, because bricking uploads on a Redis
blip is worse than the window it opens. Responses that are limited return
**429** `{"error": "Too many requests"}` with `X-RateLimit-Remaining`. Upload,
validate-xml and fix-xml check the limit after the session and before any of the
body is read.

| Bucket | Limit | Key |
|---|---|---|
| `signup` | 5 / 60s | client IP (the `x-forwarded-for` entry added by our own proxy — see `TRUSTED_PROXY_HOPS` — validated); requests with no usable IP share one `unknown` bucket |
| `login:email` | 10 / 15 min | normalized email; cleared by a successful sign-in |
| `login:ip` | 50 / 15 min | client IP, as for `signup`; skipped when there is none |
| `upload` | 10 / 60s | user id |
| `validate-xml` | 10 / 60s | user id |
| `fix-xml` | 10 / 60s | user id |

Every sign-in attempt counts, not only failures. A throttled sign-in fails
exactly like a wrong password, never as a 429, so the throttle tells a caller
nothing about the account.

### Errors

Every error body is `{"error": "<message>"}` (the download 410 adds
`"expired": true`). A failure no branch anticipated is a **500** with a
route-specific message (`Failed to fetch jobs`, `Upload failed`, …);
`validate-xml` and `fix-xml` answer it as **502** instead, because their usual
cause is the worker. Every 413 says `File size exceeds 50MB limit`, whatever
`MAX_UPLOAD_BYTES` is set to.

The convert and re-upload pages do not show upload errors verbatim:
`lib/upload-errors.ts:uploadErrorMessage` turns each status into its own advice
and passes the server's text through only for a 400 it does not recognise.

Every response, the API's included, carries the security headers set in
`next.config.ts` — see [SECURITY.md](./SECURITY.md#response-hardening).

---

### `POST /api/auth/signup`

Create an account. JSON `{ email, password, name? }`. Passwords must be at least
8 characters and contain an uppercase letter, a digit and a special character.
`name` is trimmed and cut to 100 characters.

| Status | Meaning |
|---|---|
| 201 | Created; `{ "id": "<cuid>", "email": "<normalized>" }` |
| 400 | Validation failure: body not a JSON object, missing/invalid email (shape and ≤254 characters), missing password, non-string name, or password complexity |
| 409 | Email already registered — also when two signups for one address race past the pre-check |
| 429 | Rate limited (checked before the body is read) |
| 500 | Anything else, logged as `Signup error:` |

Emails are trimmed and lowercased on write and on lookup, so `User@example.com`
and `user@example.com` are one identity.

### `GET|POST /api/auth/[...nextauth]`

Auth.js handlers — sign in, sign out, session, CSRF. The credentials sign-in
(`POST /api/auth/callback/credentials`) is throttled as above and writes
`sign_in` / `sign_in_failed` audit entries.

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
| 413 | Over the size cap — checked against the declared `Content-Length` before any of the body is read, then by counting bytes as it streams (so a chunked request without a length cannot slip past), then against the file itself. The body allowance is the cap plus 64 KB of multipart framing |
| 429 | Rate limited |
| 500 | The file could not be saved — the job row is deleted and the partial upload directory removed, so no orphan is left behind. Also the answer, for now, to a body that is not parseable multipart form data, though that is the caller's mistake |

`previousJobId` is looked up scoped to your user before it is accepted. The
filename is reduced to its basename and stripped to `[A-Za-z0-9._-]`. Writes an
`upload` audit entry with the original name and size.

### `GET /api/jobs`

Your jobs, newest first, as a bare array. Before reading, this route lazily
fails jobs stuck `queued` or `converting` past `REAP_DEADLINE_MS` (1 hour by default) that
the queue no longer holds, and purges files past the retention window, so the
list reflects reality rather than a crashed conversion lingering forever. Both
are fail-open: a failure in either is logged and the list is read anyway.

Returns `id`, `converterType`, `status`, `inputFileName`, `totalRows`, `summary`,
`xsdValid`, `createdAt`, `completedAt`.

### `GET /api/jobs/:jobId`

The full job row, after the same stuck-job reap (not the retention sweep). While
a job is `converting`, the worker's live progress snapshot is fetched (3-second
timeout) and merged in: `processedRows` and `totalRows` become the worker's live
counts — that is what drives the progress bar — and `progressUpdatedAt` (the
worker's Unix time, in seconds) is added, though no page reads it. If the fetch
fails for any reason, a 404 included, the plain row is returned.

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
| 404 | Not found / not yours |
| 409 | The job is `cancelled`, `complete` or `error`, or the queue owns it (`queued` or `converting`; cancel the conversion first) |

The status is checked before the body's fields, so a locked job answers 409 even
to an invalid body. The update is a guarded `updateMany`; if a cancel or start
lands between the read and the write it returns 409 with the job's actual status
rather than reviving it. A `columnMapping` that differs from the stored one
writes a `mapping_changed` audit entry.

### `DELETE /api/jobs/:jobId`

| Status | Meaning |
|---|---|
| 200 | `{ "deleted": true }` |
| 404 | Not found / not yours |
| 409 | The job is `queued` or `converting` — cancel it first (also when it entered one of those states between the read and the delete) |

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
| 409 | Status is not `uploaded`, `previewed` or `mapping`, or it changed between the read and the guarded update |
| 410 | The uploaded file expired under the retention policy — upload it again |
| 413 | The file on disk exceeds the cap (re-checked server-side, not just at upload) |
| 500 | The upload is missing from disk though the row records no purge (`stat` fails), or the database failed |
| 503 | Could not reach Redis to enqueue; the status is rolled back so you can retry immediately |

The 503 path matters: without the rollback the row would sit `queued` with
nothing to pick it up, 409ing every retry until the reaper failed it an hour
later with no explanation.

### `GET /api/jobs/:jobId/preview`

Proxies the CSV to the worker's `/preview` and returns its answer unchanged:
headers, sample rows, column status (matched / missing / extra plus fuzzy rename
suggestions) and the data-quality summary — field by field under
[worker `/preview`](#post-preview). Flips the job to `previewed` unless it is
already terminal or in flight, and records `total_rows` on the job unless it is
`queued` or `converting` (any write there would reset the stuck-job reaper's
clock).

For the `training` converter a column counts as matched when the file carries
**any** of its accepted spellings (`city` for `City`, `Zip code` for
`Zip/Postal Code`); `column_status.aliases` maps each such canonical column to
the header that satisfied it. `training-client` expects only the columns its
converter reads, so export-only columns (`Member Status`, `Related Record ID`, …)
are neither expected nor reported missing.

`404` if the job is not yours; `400` with the worker's own message when the
worker rejects the CSV content with a 400 or 422 (malformed file); `410` if the
file has been purged; `413` if it exceeds the cap; `502` when the worker is
unreachable, passes the 5-minute timeout (the `workerFetch` default), refuses
`WORKER_AUTH_TOKEN` or fails, with the cause in the web log as
`Preview worker error: <jobId> …`; `500`, logged as `Preview error:`, when
reading the upload or updating the job fails.

The file is decoded as the conversion decodes it (`lib/csv-decode.ts:decodeCsvBuffer`):
a UTF-16 BOM selects UTF-16, otherwise strict UTF-8 (BOM preserved) with a
fallback to Windows-1252 for Excel's "CSV (Comma delimited)" exports — so the
preview shows the characters the filing will carry.

### `POST /api/jobs/:jobId/cancel`

**200** `{ "status": "<the job's resulting status>" }` for any job of yours;
**404** otherwise. Only a `queued` or `converting` job is cancelled, and writes a
`conversion_cancelled` entry. For any other status, before start or terminal,
it is a no-op that reports the existing status rather than an error, so repeat
clicks from a stale tab are safe.

The database is updated first (authoritative), then the worker is told —
fire-and-forget with a 5-second timeout; a failure there is swallowed. The
worker checks the flag at phase checkpoints, so cancellation is cooperative — an
in-flight phase completes before it takes effect.

### `GET /api/jobs/:jobId/download`

The generated XML as `application/xml` with a `Content-Disposition` attachment
header, named after the upload with its `.csv` suffix replaced by `.xml`. Writes
a `download` entry.

| Status | Meaning |
|---|---|
| 200 | The file |
| 404 | No output file, not yours, the file is no longer on disk, or the path failed the `DATA_DIR` confinement check |
| 410 | Files purged under the retention policy; the body carries `"expired": true` |

The path is resolved with `realpath` and checked against `DATA_DIR` with a
trailing separator, which defeats both symlink escapes and the `/data-evil`
prefix trick.

### `GET /api/mapping-templates?converterType=…`

Your saved mappings for that converter type, plus `lastJobMapping` — the mapping
from your most recent completed job of that type, so the mapping page can offer
"same as last time".

→ `{ "templates": [{ id, name, converterType, mapping, updatedAt }], "lastJobMapping": {…} | null }`,
most recently updated first. `converterType` is optional: without it you get
every template you have and `lastJobMapping: null`. An unknown type is a **400**.

### `POST /api/mapping-templates`

Save a named mapping. JSON `{ name, converterType, mapping }`. Name trimmed,
1–60 chars; `mapping` a non-empty flat object of strings, at most 200 entries,
each key and value 1–200 chars. Unique per `(user, converterType, name)`, and
saving under a name you already use for that type overwrites it (an upsert)
rather than failing, so "save again after tweaking" is one click.

**201** → `{ "template": { id, name, converterType, mapping, updatedAt } }`;
**400** for a bad name, converter type or mapping. Writes a
`mapping_template_saved` entry.

### `DELETE /api/mapping-templates/:templateId`

Delete one of your templates: **200** `{ "deleted": true }`, or **404** if it is
not yours or does not exist. Writes a `mapping_template_deleted` entry.

### `GET /api/audit`

Your audit trail, newest first, as
`{ entries, total, page, pageSize, totalPages }`. Each entry carries its job's
`inputFileName` and `converterType` as `job`, which is `null` once the job is
deleted.

| Param | Default | Bounds |
|---|---|---|
| `page` | 1 | ≥ 1 |
| `pageSize` | 50 | 1–200 |
| `action` | — | Exact match |
| `format` | JSON | `csv` for an export, capped at 10,000 rows |

Out-of-range and non-numeric values are clamped rather than rejected, so
`?pageSize=abc` and `?page=0` behave sensibly instead of 500ing.

`format=csv` ignores `page` and `pageSize`: it returns the newest 10,000
matching rows as `text/csv`, attached as `audit-trail.csv`, with the columns
`Date`, `Action`, `File`, `Type` and `Details` (the metadata as JSON). It escapes
quotes and prefixes any value starting with `=`, `+`, `-`, `@`, a tab or a
carriage return with an apostrophe, so user-controlled filenames cannot become
formulas when the file opens in Excel or Sheets.

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
`file` (a name ending `.xml`, case-insensitive, ≤ cap) and `schemaType`
(`counseling` | `training` | `training-client`). The body is read with the same
capped reader as `/api/upload` (`lib/xml-tool-route.ts:readCappedFormData`), so
the three-stage 413 is the same.

Returns the worker's `is_valid`, `errors`, `error_count` and `error_details`
unchanged. The file is decoded by its BOM (UTF-16 LE or BE) or, without one, by
the encoding its XML declaration names (UTF-8 when it names none), and the
declaration is restated as UTF-8 before the text goes to the worker — so a
UTF-16 or Windows-1252 file is checked rather than mangled into false failures.
Bytes that are not valid text in that encoding are a **400** naming the line of
the first unreadable character, since SBA's parser would refuse the file too.
Writes an `xml_validated` audit entry.

### `POST /api/fix-xml`

Same shape, but `schemaType` accepts **`counseling` | `training-client` only** —
auto-fix is offered for counseling-format XML. Returns `changed`, the
`fixed_xml_content`, `fix_error`, and the re-validation result. Writes an
`xml_autofix` entry, with `refused: true` when the worker could not process the
file.

Both routes use a 60-second worker timeout and send the worker the job id
`adhoc-<uuid>`.

| Status | Meaning |
|---|---|
| 200 | The worker's result (an invalid or refused document is still a 200) |
| 400 | Missing or non-file `file`, missing `schemaType`, a name not ending `.xml`, an unaccepted `schemaType`, undecodable bytes, or a worker 400/422 (its detail relayed) |
| 401 | Not signed in |
| 413 | Over the size cap |
| 429 | Rate limited |
| 502 | Everything else: the worker unreachable, past the timeout, refusing the token, or answering 413 or 5xx — and, for now, a body that is not parseable multipart form data |

---

## Worker API

FastAPI, default port 8000 (`$PORT` overrides it).

### Authentication

Every functional endpoint requires `Authorization: Bearer $WORKER_AUTH_TOKEN`,
compared in constant time; a missing or wrong header is **401**
`Invalid or missing worker credentials`. It is **fail-closed**: with no token
configured the worker answers functional requests **503**
`Worker authentication is not configured` rather than serving them
unauthenticated. `/health` is deliberately exempt so container and platform
health probes keep working; so, outside production, are `/docs`, `/redoc` and
`/openapi.json`.

CORS allows only `GET` and `POST`, only the `Authorization` and `Content-Type`
headers, and only the origins in `ALLOWED_ORIGINS` (default
`http://localhost:3000`).

Request bodies over `MAX_REQUEST_BYTES` (100 MB default) get **413**
`Request body too large`. The check looks at `Content-Length` first and then
counts bytes as the body streams, so a chunked request without a
`Content-Length` cannot slip past it. A `Content-Length` that is not a
non-negative integer is a **400** `Invalid Content-Length`.

At most `MAX_CONCURRENT_REQUESTS` (default 4) authenticated `/convert`,
`/preview`, `/validate-xsd` and `/fix-xml` requests run at once; the rest wait
for a slot before their body is read. `/health`, progress and cancel are never
queued.

Every error body is `{"detail": "<string>"}` (the development 404 below adds a
route list). A request that fails validation (a missing field, a body that is
not JSON, a `converter_type` / `schema_type` other than `counseling`,
`training` or `training-client`, a `source_encoding` over 64 characters) is a
**422** whose detail, `Invalid request: <field>: <rule>; …`, names the field and
the rule, without repeating the value that was sent. The generated OpenAPI
schema still describes that 422 as FastAPI's default list of errors; the body is
the string.

In production (`ENVIRONMENT` set to `production` or `prod`, case-insensitive),
`/docs`, `/redoc`, `/openapi.json` and the route list in 404 bodies are all
disabled.

Every `job_id`, in a body or a path, is cut to `[A-Za-z0-9_-]` and 64
characters (`app/logging_context.py:set_job_id`) before it reaches a log line or a
Redis key; responses that echo it echo the cleaned value.

### `GET /health`

Unauthenticated.

```json
{"status": "ok", "checks": {"api": "ok", "schemas": "ok", "data_dir": "unavailable"}}
```

`data_dir: unavailable` is normal outside Docker — the worker does not use
`DATA_DIR` during a conversion. `status` is `ok` as long as the API responds and
the schemas resolve, and `degraded` (with `schemas: "error"`) when they do not;
the compose and Dockerfile healthchecks assert on `status`, not the HTTP code,
because a degraded worker still returns 200.

The worker **refuses to start** if it cannot locate the XSDs, checked in the
lifespan hook rather than at import so that importing the app (as the tests do)
stays side-effect free.

### `POST /preview`

```json
{"job_id": "…", "csv_content": "…", "converter_type": "counseling"}
```

→ `headers`, `rows`, `total_rows`, `column_status`, `data_quality`.

`rows` is the first 20 data rows; `total_rows` counts them all. `column_status`
is `{matched, missing, extra, suggestions: [{csv_column, suggested_match,
score}], aliases, field_requirements, field_descriptions}`: `matched` and
`missing` name expected columns, `extra` the file's other headers,
`field_requirements` maps each expected column to `required`, `optional` or
`conditional`.

`data_quality` is `{"total_rows": int, "checks": [{key, label, count, severity,
detail, column}]}` and lists only checks with a non-zero count.

| Status | Meaning |
|---|---|
| 200 | The preview, even when no expected column matched |
| 400 | A `ValueError` while reading the CSV; the detail is its message |
| 422 | Validation failure, or a CSV that cannot be parsed at all |
| 500 | `Internal preview error` |

A CSV that cannot be parsed at all (typically an unclosed quote, which turns the
rest of the file into one oversized cell) is a `422` whose detail says so. An
unclosed quote that swallows fewer rows parses; the conversion then records an
error naming the row and column where it opened.

### `POST /convert`

```json
{"job_id": "…", "csv_content": "…", "converter_type": "counseling",
 "column_mapping": {"Your Header": "Expected Header"},
 "source_encoding": "windows-1252"}
```

→ `xml_content`, `stats`, `xsd_valid`, `xsd_errors`, `xsd_error_details`,
`issues`, `cleaning_diff`.

| Field | Shape |
|---|---|
| `stats` | `{total, successful, errors, warnings}` |
| `issues[]` | `{record_id, event_id, severity, category, field_name, message, timestamp}` (the web does not read `timestamp`) |
| `cleaning_diff[]` | `{row, record_id, field, original, cleaned, cleaning_type}` |
| `xsd_error_details[]` | As for [`/validate-xsd`](#post-validate-xsd); empty when `xsd_valid` |

`column_mapping` (optional, `{csvColumn: expectedColumn}`) renames headers
before conversion; an entry whose target is not a column the converter expects
is dropped rather than applied.

`source_encoding` (optional) is how the web read the upload before sending its
text, named as `decode_csv_bytes` names it: `utf-8`, `utf-16`, `utf-16 (odd
length)`, `utf-16 (damaged)`, `utf-16 (damaged, odd length)` or
`windows-1252`. The worker never sees the file's bytes, so this is what lets it
record the file-level encoding warning the command line records. A name it
doesn't know records nothing rather than failing the request (one over 64
characters is a 422).

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
set after the web has authoritatively cancelled the job. The `finally` clears
both, so a later run under the same id starts clean.

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

Each `error_details` entry is `{line, row_number, record_id, element,
field_label, csv_column, message, friendly_message}`; every field but the two
messages may be `null`.

| Status | Meaning |
|---|---|
| 200 | The result, valid or not |
| 400 | `xml_content` is empty or only whitespace |
| 422 | Validation failure |
| 500 | `Internal validation error` |

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
`training` passes validation and is then a **400**
`auto-fix supports counseling-format XML only`; empty or whitespace-only
`xml_content` is a **400** too, and an unexpected failure a **500**
`Internal fix error`.

→ `changed`, `fixed_xml_content`, `fix_error`, plus the re-validation result
(`is_valid`, `errors`, `error_count`, `error_details`) against the counseling
XSD.

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
Outside production the response also lists the registered routes, as
`registered_routes`; in production that list goes to the startup log only. A
route's own 404 (`/convert/{job_id}/progress`) keeps its own detail. A known
path with the wrong method is a **405** `{"detail": "Method Not Allowed"}`.

At 7b14f3b the worker registers 7 routes: `GET /health`, `POST /preview`,
`POST /convert`, `POST /convert/{job_id}/cancel`,
`GET /convert/{job_id}/progress`, `POST /validate-xsd` and `POST /fix-xml`.
