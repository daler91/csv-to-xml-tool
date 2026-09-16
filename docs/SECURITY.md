# Security

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.** Report it privately
through [GitHub Security Advisories](https://github.com/daler91/csv-to-xml-tool/security/advisories/new),
which is private to the maintainers until an advisory is published.

Include what you would want to receive: the affected component, reproduction
steps, and what an attacker gains. If you have a proof of concept, say so rather
than pasting it publicly anywhere else.

This is a small project with no funded security team. Expect acknowledgement in
days, not hours, and please give the maintainers a chance to ship a fix before
disclosing.

## What this system holds

Worth stating plainly, because it shapes what a vulnerability is worth:

- **Personally identifiable information about small-business owners** — names,
  home and mailing addresses, phone numbers, email addresses, race, ethnicity,
  gender, disability status, veteran status, and business financials.
- **Data destined for a federal filing.** Corrupting the output is as serious as
  leaking it: a wrong filing misreports a federal program.
- **Account credentials** (bcrypt hashes) and session cookies.

Uploaded CSVs and generated XML are removed from disk after `RETENTION_DAYS`
(30 by default). Job records and the audit trail are kept indefinitely.

## Controls in place

### Authentication and authorization

- Auth.js credentials sessions. Passwords are bcrypt-hashed and must contain an
  uppercase letter, a digit and a special character.
- Login is throttled per email **and** per IP.
- Emails are trimmed and lowercased on write and on lookup, so `User@x.com` and
  `user@x.com` cannot become two accounts.
- `middleware.ts` gates the authenticated pages and API routes; handlers
  additionally call `getRequiredUser()`.
- **Every user-owned resource** is read with `findFirst({ where: { id, userId } })`
  and mutated with a `userId`-scoped `updateMany`. A job id belonging to another
  user returns 404, not 403 — it does not confirm the id exists.
- `previousJobId` is validated for ownership before it is linked, closing the
  IDOR where a user could attach their job to someone else's.

### Service-to-service

- The worker requires `Authorization: Bearer $WORKER_AUTH_TOKEN` on every
  functional endpoint, compared in constant time. `/health` is exempt so probes
  work.
- **Fail-closed**: no token configured means 503 on every functional endpoint,
  never unauthenticated service.
- CORS allows only `GET`/`POST`, only `Authorization` and `Content-Type`, and
  only the origins in `ALLOWED_ORIGINS`.
- The worker is **not meant to be publicly reachable**. Keep it on a private
  network.

### Input handling

- **XXE is closed**: `defusedxml` for all ElementTree parsing and
  `resolve_entities=False` on every lxml parse.
- **Path traversal is closed on both sides**: `realpath` plus a `DATA_DIR` prefix
  check with a trailing separator (`lib/paths.ts`), which defeats symlink escapes
  and the `/data-evil` prefix trick alike; `src/path_safety.py` does the same for
  CLI output.
- Upload filenames are reduced to their basename and stripped to
  `[A-Za-z0-9._-]`.
- Size caps are enforced at upload **and re-checked server-side** before each
  worker call. The worker additionally caps the request envelope, counting bytes
  as the body streams so a chunked request with no `Content-Length` cannot bypass
  it.
- Audit CSV export defuses spreadsheet formula injection: values starting with
  `=`, `+`, `-`, `@` or a control character are apostrophe-prefixed.
- Audit pagination is clamped rather than trusted, and the export is capped at
  10,000 rows.

### Response hardening

`next.config.ts` sets, on every response:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`; `frame-ancestors 'none'`; `object-src 'none'`; `connect-src 'self'` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB all denied |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` |

`poweredByHeader` is off. `'unsafe-eval'` is enabled **only** outside production,
for the dev overlay. `'unsafe-inline'` for styles is required by Next's inlined
critical CSS. The app loads no third-party JavaScript, so there is nothing to
allowlist in `script-src`.

`frame-ancestors 'none'` is the one that matters most: before it, the dashboard
and the delete-job control could be framed and clickjacked.

In production the worker disables `/docs`, `/redoc`, `/openapi.json` and the
route list in 404 bodies — all previously served unauthenticated and describing
the entire API surface.

### Supply chain

- `pip-audit` on both requirements files and `npm audit --audit-level=high` run
  in CI. Any known Python advisory fails the build; high and critical npm
  advisories fail the build.
- Python dependencies are pinned exactly (`==`).
- `.env` is gitignored; `.env.example` contains placeholders only.

## Known weaknesses

Stated because you should know them, not because they are acceptable forever.

| Issue | Status |
|---|---|
| **`next-auth@5.0.0-beta.30`** — pre-release auth in production; APIs may change and security patches may lag | Open. Monitoring for a stable release. `TECHNICAL_DEBT.md` #5 |
| **Rate limiting fails open** — if Redis is unreachable, requests pass unlimited | Deliberate. A Redis blip that bricks every upload was judged worse. Alert on Redis availability |
| **Whole files are held in memory** during a conversion — a large upload is a memory-pressure vector bounded only by `MAX_UPLOAD_BYTES` | Open. `TECHNICAL_DEBT.md` #16 |
| **No log rotation**, and tracebacks are logged with `exc_info=True` | Open. Treat log access as privileged |
| **Redis has no persistence configured** — a restart drops queued job ids (jobs are failed by the reaper, not silently lost) | Open |
| **Tenant identity is hardcoded** in `src/config.py` while signup is open. A second organization on the same deployment would have its filings stamped with the first's location and partner codes | Accepted for single-organization use **only**. See [converters.md](./converters.md#-this-is-a-single-organization-tool) |

That last row is the one to act on before any shared deployment. It is a
data-integrity defect in a federal filing, not a configuration preference.

## For operators

See the [pre-deployment checklist](./deployment.md#pre-deployment-checklist).
The essentials:

- Generate real `NEXTAUTH_SECRET` and `WORKER_AUTH_TOKEN` values; never ship the
  `.env.example` placeholders.
- Set `ENVIRONMENT=production` on the worker.
- Keep the worker off the public internet.
- Set `ALLOWED_ORIGINS` to your web origin only.
- Terminate TLS in front of the app — HSTS is only meaningful over HTTPS.

## Scope

In scope: the web app, the worker, the conversion core, the CLI, and the
deployment configuration in this repository.

Out of scope: vulnerabilities in the SBA Nexus/EDMIS system itself, and issues
that require an attacker to already control the host or the database.
