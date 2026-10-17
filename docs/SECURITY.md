# Security

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.** Report it privately
through [GitHub Security Advisories](https://github.com/daler91/csv-to-xml-tool/security/advisories/new),
which is private to the maintainers until an advisory is published.

That form exists only while *private vulnerability reporting* is enabled in the
repository's settings (**Settings → Code security**). On 2026-10-17 it was off,
so the link worked for maintainers only and there was no private channel for
anyone else. Turning it on is the fix; a public issue is not the fallback.

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
(30 by default), by an hourly sweep and on dashboard reads
(`apps/web/src/lib/retention.ts`). Job records and the audit trail are kept
indefinitely, and a job record is not free of client data: its issues list and
cleaning diff quote cell values — phone numbers, demographic answers, counselor
notes — against each Contact ID, and retention clears only the file paths.

## Controls in place

### Authentication and authorization

- Auth.js credentials sessions. Passwords are bcrypt-hashed (cost 12) and must
  be at least 8 characters with an uppercase letter, a digit and a special
  character.
- Login is throttled per email (10 attempts in 15 minutes) **and**, where the
  client IP can be trusted (`TRUSTED_PROXY_HOPS`), per IP (50). Every failure,
  throttled included, gets the same answer, and an unknown email is compared
  against a decoy hash so it takes as long as a wrong password
  (`apps/web/src/lib/auth.ts`). Sign-ins and failed sign-ins to existing
  accounts are audited.
- Emails are trimmed and lowercased on write and on lookup, so `User@x.com` and
  `user@x.com` cannot become two accounts.
- Access control lives in the handlers. Every authenticated API route calls
  `getRequiredUser()` and answers 401 without a session, and the two
  server-rendered pages that read the database (dashboard, results) check the
  session and redirect to `/login`. The other `/convert`, `/validate` and
  `/audit` pages render no user data until those API routes return it.
  `middleware.ts` enforces nothing: it has no `authorized` callback, so on the
  routes it matches it only refreshes the session cookie. It is kept off the
  file-upload routes, where Next's body buffering truncated uploads at 10 MB.
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
- At most `MAX_CONCURRENT_REQUESTS` (4) conversion, preview and validation
  requests run at once; the rest wait before their body is read, and a request
  without the token never takes a slot (`apps/worker/app/main.py`). A conversion
  stops at `CONVERSION_DEADLINE_SECONDS`.
- Error responses carry a string `detail`; a rejected request is described by
  field, without echoing the value sent.
- The worker is **not meant to be publicly reachable**. Keep it on a private
  network.

### Input handling

- **XXE is closed**: every XML parse is lxml with `resolve_entities=False`;
  ElementTree only builds and writes the output, and parses nothing. XML a user
  hands the tool (the validator, `/validate-xsd`, `/fix-xml` and the fixer CLIs)
  is parsed with entities never expanded and nothing fetched
  (`src/xml_validator.py:_parser`, `no_network=True`), and a document whose
  DOCTYPE declares or uses entities is refused ("DTD/entity declarations are not
  supported"), as defusedxml refused it before. `defusedxml` is still pinned,
  but only the tests import it.
- An uploaded XML file whose bytes are not text in the encoding it declares is
  refused rather than repaired, and text holding a lone surrogate is answered
  as invalid input, not a 500.
- **Path traversal is closed on both sides**: `realpath` plus a `DATA_DIR` prefix
  check with a trailing separator (`lib/paths.ts`), which defeats symlink escapes
  and the `/data-evil` prefix trick alike. On disk the web builds every path from
  the database-issued job id (and, for an upload, its sanitized name). `src/path_safety.py` does the same for the
  conversion CLIs' output and the fixer's and validator's directory modes, but
  not their single-file mode, whose paths are used as given
  ([cli.md](./cli.md#output-path-confinement)).
- Upload filenames are reduced to their basename, with every character outside
  `[A-Za-z0-9._-]` replaced by `_`.
- Size caps are enforced at upload **and re-checked server-side** before each
  worker call. The upload and validate/fix routes read the multipart body as a
  stream and stop at the cap plus 64 KB, declared length or not
  (`apps/web/src/lib/xml-tool-route.ts:readCappedFormData`). The worker
  additionally caps the request envelope, counting bytes as the body streams so
  a chunked request with no `Content-Length` cannot bypass it.
- Audit CSV export defuses spreadsheet formula injection: values starting with
  `=`, `+`, `-`, `@`, a tab or a carriage return are apostrophe-prefixed.
- Audit pagination is clamped rather than trusted, and the export is capped at
  10,000 rows.

### Response hardening

`next.config.ts` sets, on every response:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`; `script-src 'self' 'unsafe-inline'`; `style-src 'self' 'unsafe-inline'`; `img-src 'self' data: blob:`; `font-src 'self' data:`; `connect-src 'self'`; `object-src 'none'`; `base-uri 'self'`; `form-action 'self'`; `frame-ancestors 'none'`; `upgrade-insecure-requests` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB all denied |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` |

`poweredByHeader` is off. `'unsafe-eval'` is enabled **only** outside production,
for the dev overlay. `'unsafe-inline'` for styles is required by Next's inlined
critical CSS, and for scripts by its inline bootstrap scripts — which leaves
`script-src` little protection against injected script (see
[Known weaknesses](#known-weaknesses)). The app loads no third-party
JavaScript, so there is nothing to allowlist.
`apps/web/src/lib/security-headers.test.ts` checks that every header is set and
that the CSP keeps its framing, object, base and form-action limits.

`frame-ancestors 'none'` is the one that matters most: before it, the dashboard
and the delete-job control could be framed and clickjacked.

In production the worker disables `/docs`, `/redoc`, `/openapi.json` and the
route list in 404 bodies — all previously served unauthenticated and describing
the entire API surface.

### Supply chain

- `pip-audit` on both requirements files and `npm audit --audit-level=high` run
  in CI. Any known Python advisory fails the build; high and critical npm
  advisories fail the build.
- Python dependencies are hash-locked: each `requirements*.txt` is compiled from
  its `.in` file with hashes, and CI and the worker image install wheels only
  with `--require-hashes`. npm installs come from the lockfile with `npm ci
  --ignore-scripts`, in CI and in the web image.
- The worker's base image is pinned by digest; the web's `node:20-alpine` is
  pinned by tag only. Dependabot proposes base-image updates for both
  (`.github/dependabot.yml`). CI's `GITHUB_TOKEN` is read-only.
- `.env` is gitignored; `.env.example` contains placeholders only.
  `.dockerignore` keeps the root `.env` out of image builds, but its patterns
  match at the build-context root only, so an `apps/web/.env` would be sent with
  the context and copied into the web image's standalone output.

## Known weaknesses

Stated because you should know them, not because they are acceptable forever.

| Issue | Status |
|---|---|
| **`next-auth` 5.0.0 beta** (`^5.0.0-beta.30` in `package.json`, `5.0.0-beta.32` in the lockfile) — pre-release auth in production; APIs may change and security patches may lag | Open. Monitoring for a stable release. `TECHNICAL_DEBT.md` #5 |
| **The CSP allows inline scripts** — `script-src 'unsafe-inline'`, which Next's inline bootstrap scripts need without a per-request nonce | Open. A nonce-based CSP means running middleware on every route. `CODEBASE_ANALYSIS.md` 3.3 |
| **No CSRF token or Origin check** — state-changing routes rely on Auth.js's `SameSite=Lax` session cookie alone. Sessions are 30-day JWTs that sign-out does not revoke, and `trustHost` is `true` with no allowlist | Open. `CODEBASE_ANALYSIS.md` 3.10 |
| **Signup reveals registered emails** — it answers 409 "Email already registered" | Open. Hiding it needs email verification, which the app has no mail for. `CODEBASE_ANALYSIS_3.md` D.7 |
| **Per-IP limits are only as good as `TRUSTED_PROXY_HOPS`** — too high and a client picks its own IP; `0` or no header puts every signup in one shared bucket | Deliberate. Set it to the number of proxies in front of the web app |
| **Rate limiting fails open** — if Redis is unreachable, or older than 7, requests pass unlimited | Deliberate. A Redis blip that bricks every upload was judged worse. Alert on Redis availability |
| **Retention removes files, not the client data in job records** — issues and cleaning diffs keep cell values indefinitely | Open |
| **Whole files are held in memory** during a conversion — a large upload is a memory-pressure vector, bounded by `MAX_UPLOAD_BYTES` per request and, on the worker, by `MAX_CONCURRENT_REQUESTS` requests at a time | Open. `TECHNICAL_DEBT.md` #16 |
| **Logs grow without bound, and hold tracebacks.** Each CLI log file rotates at 10 MB, but every run starts a new one, so `logs/` keeps growing; web and worker log to stdout and are kept as long as the platform keeps them. Tracebacks are logged with `exc_info=True` | Open. Treat log access as privileged |
| **The web trusts its own configuration and the worker's answers** — with no `WORKER_AUTH_TOKEN` it calls the worker without one (the worker then refuses every call), and worker responses are written to disk and the database unvalidated | Open. `CODEBASE_ANALYSIS.md` 3.11 |
| **Redis has no persistence configured** — a restart drops queued job ids and retries waiting out their backoff (jobs are failed by the reaper, not silently lost) | Open |
| **Tenant identity is hardcoded** in `src/config.py` while signup is open. A second organization on the same deployment would have its training filings stamped with the first's partner code, and every filing with the first's location code wherever its CSV has no `LocationCode` | Accepted for single-organization use **only**. See [converters.md](./converters.md#-this-is-a-single-organization-tool) |

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
- Set `TRUSTED_PROXY_HOPS` to the number of proxies in front of the web app.
- Terminate TLS in front of the app — HSTS is only meaningful over HTTPS.

## Scope

In scope: the web app, the worker, the conversion core, the CLI, and the
deployment configuration in this repository.

Out of scope: vulnerabilities in the SBA Nexus/EDMIS system itself, and issues
that require an attacker to already control the host or the database.
