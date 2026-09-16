# Troubleshooting

Grouped by who hits it. The in-app `/help` page covers the same user-facing cases
with less detail; this page adds the operator and developer side.

---

## Using the web app

### "This file is larger than 50MB"

The upload cap. Split the CSV into batches, or drop unused columns via Excel or
Salesforce's export filters. Extra columns are ignored by the converter anyway,
so removing them costs nothing.

Operators can raise `MAX_UPLOAD_BYTES` — but read
[configuration.md](./configuration.md#limits) first: the number also appears in
about nine user-facing strings, and memory scales with it.

### "That file isn't a CSV"

The extension must be `.csv`. From Excel: **File → Save As → CSV (Comma
delimited)**. An `.xlsx` renamed to `.csv` will upload and then fail to parse.

### "You've uploaded several files in a short window"

Ten uploads per minute per user. Wait a minute.

### "Your session expired"

Sign in again. Sessions do expire; the tab does not notice until the next
request.

### Required columns are missing

The conversion returns 422 and names the columns. It is a hard stop by design —
converting without a required column would either fail the schema or invent data.

Two fixes:

- **Your export uses different header names** → map them on the mapping page, and
  save the mapping as a template so recurring exports skip the step.
- **The data genuinely is not in the export** → add the field in Salesforce and
  re-export.

Per-converter lists: [csv-reference.md](./csv-reference.md).

### Columns show as "missing" but they are in my file

Usually one of:

- **A different spelling.** Check the exact expected header — `Ethnicity:` really
  does end with a colon. The preview page fuzzy-matches missing against extra
  columns and suggests renames; take the suggestion if it looks right.
- **Two columns collapsing to one name** after whitespace normalization. The
  header row is read without deduplicating so this is detectable; look for a
  near-duplicate header.
- **The wrong converter type.** `training` and `training-client` read similar
  exports but expect different column sets.

### Preview fails to load

The CSV is probably malformed. Open it in a text editor and confirm the first row
holds headers and every line has the same number of fields. A stray unquoted
comma inside a value is the usual culprit. **Try again** first in case the worker
was momentarily busy.

### The conversion succeeded but XSD validation failed

Expected, and useful. The results page lists each schema error mapped back to a
**CSV row and column name** rather than a line number in the XML — fix those rows
and use **Re-upload** to compare the two runs.

If the errors are about element *order* rather than values, the file may have
been produced elsewhere; `/validate` → auto-fix reorders counseling-format XML.

### The progress bar sits at 0%

Progress appears once the worker starts reporting rows. If it stays at 0% and the
status stays `converting`, the job is genuinely stuck — see
[Jobs stuck in converting](#jobs-stuck-in-converting) below. The reaper will fail
it after `REAP_DEADLINE_MS` (60 minutes by default) on the next dashboard read.

### Download says the file expired

Files are deleted after `RETENTION_DAYS` (30 by default); job records and the
audit trail survive. Re-upload the CSV and convert again.

### Numbers in my report look wrong

Check the results page's **cleaning diff** — it shows every value the tool
changed and the rule that changed it. Then check the issues list for:

- `FABRICATED_DEFAULT` — a value in your filing did not come from your CSV.
- `DOWNGRADED_VALUE` — data was dropped to satisfy the schema (usually a
  multi-value field capped to one code).
- `AMBIGUOUS_DATE` — `03/04/2025` was read as March 4. If your export is
  day-first, that is wrong and you should reformat the column.
- `CLAMPED_VALUE` — a percentage outside 0–100 was clamped.

Also note: **training demographics count rows, not distinct people.** An attendee
listed twice is counted twice.

---

## Running the CLI

### `ModuleNotFoundError: No module named 'lxml'`

```bash
pip install -r requirements.txt
```

### "Refusing to write outside …"

Output-path confinement. All CLI writes are confined to `SBA_OUTPUT_BASE` — the
working directory for `src.main`, the launcher's folder for `run.py`. Either
write inside it or set the variable:

```bash
SBA_OUTPUT_BASE=/srv/sba-output python -m src.main convert counseling \
  --input report.csv --output /srv/sba-output/counseling.xml
```

### `run.py` never offers the XSD validation step

Known bug. It only looks for `.xsd` files **beside `run.py`**, and the bundled
schemas live in `schemas/`. Copy the schema you need next to `run.py`, or
validate separately — see [cli.md](./cli.md#runpy--interactive-launcher).

### The conversion "succeeded" but there is no output file

Should no longer happen: an empty or headers-only CSV now raises `EmptyCSVError`
rather than returning silently. If you see it, the CSV probably has no valid rows
for the converter's required id column — check the log and the report.

### Windows: `'python' is not recognized`

Python is not on PATH. Reinstall from python.org with **"Add Python to PATH"**
ticked, then re-run `setup.bat`.

---

## Running the stack

### The worker exits at startup

It refuses to start when it cannot find the XSDs — deliberate, because without
them it would answer every request and report every document invalid with no
reasons attached.

```bash
env -u SCHEMAS_DIR python -c "import sys; sys.path.insert(0, 'apps/worker'); \
  import os; from app.services.conversion_service import SCHEMAS_DIR; \
  print(os.path.realpath(SCHEMAS_DIR), os.path.isdir(SCHEMAS_DIR))"
```

In Docker the schemas land at `/app/schemas`. If you moved them, set
`SCHEMAS_DIR`.

### Every conversion fails immediately

Almost always the worker token.

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/preview \
  -H 'Content-Type: application/json' -d '{}'
```

- **503** — the worker has no `WORKER_AUTH_TOKEN` at all. Set it and restart; it
  is read at import time.
- **401** — a token is set but does not match what the web sends. Check both
  sides are byte-identical.
- **200** — a bug. The endpoint should never serve unauthenticated.

### Jobs stuck in converting

1. The reaper runs **lazily**, on dashboard and job reads, not on a timer. Load
   the dashboard; anything past `REAP_DEADLINE_MS` is failed then.
2. Check the worker log for that job id — every line of a conversion is tagged
   with it:
   ```bash
   docker compose logs --no-color worker | grep '<jobId>'
   ```
3. Check the queue. A growing processing list with a flat pending list means
   consumers are claiming and not acking:
   ```bash
   docker compose exec redis redis-cli LRANGE csvxml:jobs:processing 0 -1
   docker compose exec redis redis-cli HGETALL csvxml:jobs:attempts
   ```
4. Look for `conversion_deadlettered` in the audit trail — that means attempts
   were exhausted and the failure is real, not a wedged queue.

### Jobs stay queued and never start

The consumer is not running, or Redis lost the queue.

The consumer boots from `src/instrumentation.ts`, once per **Node.js** server
process, and never during `next build`. If you are running an unusual deployment
topology, confirm a Node runtime process actually started.

If Redis restarted, queued ids are gone — persistence is not configured. The
reaper fails those jobs after `REAP_DEADLINE_MS`; users re-run them.

### Long conversions get killed at 30 minutes

`CONVERSION_TIMEOUT_MS`. Raising it means raising all three durability timeouts
together, keeping
`CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS`. Break that
ordering and a healthy long conversion gets re-queued while it is still running,
and converted twice.

### The same job converts twice

The ordering above is wrong — `VISIBILITY_TIMEOUT_MS` is below
`CONVERSION_TIMEOUT_MS`, so the sweep reclaims jobs a live consumer is still
running. Fix the ordering.

### The worker container is permanently unhealthy

The healthcheck is a stdlib Python probe, not `curl` (`python:3.12-slim` ships no
curl). If you replaced it with a curl-based probe, that is the cause. It also
asserts on the response *body*, because `/health` returns 200 even when degraded.

### Prisma `P2022: column does not exist`

A `prisma/schema.prisma` change was not mirrored into
`apps/web/scripts/migrate.js`. That script — not `prisma migrate` — is what the
deployed container runs. Add the idempotent statement and redeploy. See
[deployment.md](./deployment.md#database-migrations).

### `docker compose build` fails on the first `COPY`

The build context must be the **repo root** with the Dockerfile path given
explicitly; both Dockerfiles do `COPY apps/...`. A `./apps/web` context resolves
that to `apps/web/apps/web/...`.

### Rate limits are not being applied

They fail **open**: if Redis is unreachable, requests pass unlimited. Check Redis
before concluding the limiter is misconfigured. This is deliberate — bricking
every upload on a Redis blip was judged worse — but it does mean a limit you rely
on silently stops applying during an outage.

---

## Developing

### 79 tests silently skipped

You did not install `apps/worker/requirements-dev.txt`. Six files begin with
`pytest.importorskip("fastapi")` or `("fakeredis")` and skip wholesale without
it. A green run with those missing is green because the tests did not execute.

```bash
pip install -r requirements.txt -r apps/worker/requirements-dev.txt
```

### Golden tests pass but assert nothing

`.gitignore` blanket-ignores `*.xml` with an explicit `!tests/golden/*.xml`
exception. If the exception is removed, the goldens are absent on a clean
checkout and the tests regenerate-and-skip. Confirm `tests/golden/` is populated.

### Coverage gate fails

The gate is 70% and actual coverage is around 89%, so a failure means you removed
a lot of covered code or added a lot of uncovered code. Run with
`--cov-report=term-missing` to see which lines.

### `npm run lint` fails on class names

`scripts/check-ui-classes.mjs` caught a page hand-rolling classes that belong to a
`components/ui/` primitive. Use the primitive.

### Everything passes but the XML is subtly wrong

The reason `ruff` exists here. A refactor once left the tail of a method
unreachable, silently dropping four elements from every counseling record — and
because all four are `minOccurs="0"`, the XML stayed schema-valid and the whole
suite stayed green. Run `ruff check .`, and compare against `tests/golden/`.

---

## Still stuck

- Known issues: [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md)
  and [`reviews/TECHNICAL_DEBT.md`](./reviews/TECHNICAL_DEBT.md)
- Open an issue: <https://github.com/daler91/csv-to-xml-tool/issues>
- Security problems: **do not** open a public issue — see
  [SECURITY.md](./SECURITY.md)
