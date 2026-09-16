# Getting started

There are two ways to run this tool. Pick one:

- **[The web app](#the-web-app)** — a browser UI with accounts, upload, column
  mapping, progress, validation reports and downloads. This is what most people
  should use, and it is what a shared deployment serves.
- **[The desktop CLI](#the-desktop-cli)** — a double-clickable launcher that
  converts a CSV on your own machine with no server, no account and no network.
  Good for one-off conversions and for scripting.

Both run exactly the same conversion code, so they produce the same XML for the
same CSV.

---

## The web app

### Requirements

- Docker with Compose v2 (`docker compose`, not `docker-compose`)
- Nothing else — Postgres, Redis, Node and Python all run in containers

### Run it

```bash
cp .env.example .env
# Set NEXTAUTH_SECRET and WORKER_AUTH_TOKEN to real values:
#   openssl rand -hex 32
docker compose up
```

Wait for the worker to report healthy, then open <http://localhost:3000>, create
an account, and upload a CSV.

The example `.env` values are fine for a throwaway local stack — CI uses them
verbatim. They are **not** fine for anything reachable from a network; see
[configuration.md](./configuration.md) before deploying.

> The database schema is created at container start by
> `apps/web/scripts/migrate.js`, not by `prisma migrate`. You do not run a
> migration step by hand. See [deployment.md](./deployment.md#database-migrations)
> for why, and for the rule you must follow when changing the schema.

### Your first conversion

1. **Sign up.** Passwords need an uppercase letter, a digit and a special
   character; the signup page states the rules before you submit.
2. **Pick a converter type.** If you are not sure which, read
   [converters.md](./converters.md) — choosing wrong is the single most common
   way to get a confusing result.
3. **Upload a CSV** (drag and drop, or browse). `.csv` only, 50 MB max.
4. **Check the preview.** The mapping page tells you which expected columns were
   matched, which are missing, and which extra columns will be ignored. Missing
   *required* columns stop the conversion; missing *conditional* ones only warn.
5. **Map columns if needed.** If your export uses different header names, map
   them here. Save the mapping as a named template and recurring exports skip
   this step next time.
6. **Convert.** The progress page shows row-level progress and a Cancel button.
7. **Read the results.** You get the XML, a pass/fail against the SBA schema, a
   list of data-quality issues, and a cleaning diff showing every value the tool
   changed and why.
8. **Download.** Files are removed from disk after `RETENTION_DAYS` (30 by
   default); the job record and audit trail are kept.

### Sample CSVs

Three samples ship with the app, linked from the landing page and the dashboard
empty state, and served from `apps/web/public/samples/`:

| File | Converter | Rows | What it is |
|---|---|---|---|
| `counseling-sample.csv` | `counseling` | 3 | Individual counseling sessions (Form 641) |
| `training-sample.csv` | `training` | 7 | Per-attendee rows rolled up into Form 888 events |
| `training-client-sample.csv` | `training-client` | 3 | Per-attendee training rows emitted as Form 641 |

All three are covered by `TestShippedSamplesValidate` in
`tests/test_integration_xsd.py`, which asserts each one converts to XML that
validates clean against its bundled XSD. If a sample ever stops validating, that
test fails — that is the point of it.

### Running the web app without Docker

Useful when you are working on the web code and want fast reloads. You need
Python 3.12, Node 20, and a Postgres and Redis you can reach.

```bash
# Terminal 1 — worker
pip install -r apps/worker/requirements.txt
WORKER_AUTH_TOKEN=dev-token \
  uvicorn app.main:app --app-dir apps/worker --host 0.0.0.0 --port 8000

# Terminal 2 — web
cd apps/web
cp .env.example .env.local     # then edit DATABASE_URL, REDIS_URL, secrets
npm ci
node scripts/migrate.js        # creates the tables
npm run dev
```

`WORKER_AUTH_TOKEN` must be **identical** in both terminals. The worker
fail-closes: with no token configured it refuses every functional request, which
surfaces in the browser as a conversion that errors immediately.

The worker also refuses to start if it cannot find the XSDs. That is deliberate —
without them it would answer every request and report every document invalid with
no reasons attached. If startup fails, see
[troubleshooting.md](./troubleshooting.md#the-worker-exits-at-startup).

---

## The desktop CLI

### Requirements

[Python 3.12](https://www.python.org/downloads/). On Windows, tick **"Add Python
to PATH"** during install.

### Three steps

1. **Download.** On the GitHub page: **Code** → **Download ZIP**, then unzip
   anywhere.
2. **Set up** (once):
   - Windows: double-click `setup.bat`
   - macOS/Linux: `pip install -r requirements.txt`
3. **Run.** Put your CSV in the unzipped folder, then:
   - Windows: double-click `run.bat`
   - macOS/Linux: `python run.py`

`run.py` walks you through picking the converter type, the CSV, and where to save
the XML. No flags to remember.

Output lands in `output/`; the validation reports (CSV and HTML) land in
`reports/`; logs land in `logs/`. All three are relative to the folder holding
`run.py`.

> **Note:** `run.py` offers an optional XSD-validation step only when it finds
> `.xsd` files **directly beside `run.py`**. The bundled schemas live in
> `schemas/`, so the step does not appear on a clean checkout. To validate from
> the launcher, copy the XSD you need next to `run.py`, or use the scripted CLI
> below, which locates the schemas itself. This is a known bug — see
> [documentation-audit.md](./documentation-audit.md#code-issues-found-during-the-audit).

### Scripting it

For automation, skip `run.py` and call the module directly:

```bash
python -m src.main convert counseling \
  --input report.csv \
  --output output/counseling.xml
```

Full flag reference, the XML fixer, and the output-path confinement rules are in
[cli.md](./cli.md).

---

## Where to go next

- The CSV your export produces does not match what the tool expects →
  [csv-reference.md](./csv-reference.md)
- You need to know what the tool did to a value →
  [converters.md](./converters.md#the-cleaning-rules)
- Something failed → [troubleshooting.md](./troubleshooting.md)
- You are deploying this for a team → [deployment.md](./deployment.md)
