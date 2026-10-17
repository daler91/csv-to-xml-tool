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

Wait for the worker to report healthy, then open <http://localhost:3000>,
**Create Account**, and upload a CSV.

The example `.env` values are fine for a throwaway local stack — CI uses them
verbatim. They are **not** fine for anything reachable from a network; see
[configuration.md](./configuration.md) before deploying.

> The database schema is created at container start by
> `apps/web/scripts/migrate.js`, not by `prisma migrate`. You do not run a
> migration step by hand. See [deployment.md](./deployment.md#database-migrations)
> for why, and for the rule you must follow when changing the schema.

### Your first conversion

1. **Sign up.** **Create Account** on the landing page. Passwords need at least
   8 characters, an uppercase letter, a digit and a special character; the form
   ticks each rule off as you type. You are signed in straight away.
2. **Pick a converter type.** **New Conversion** on the dashboard, then one of
   the three cards. If you are not sure which, read
   [converters.md](./converters.md) — choosing wrong is the single most common
   way to get a confusing result.
3. **Upload a CSV** (drag and drop, or click to browse), then **Upload &
   Preview**. `.csv` only, 50 MB max by default (`MAX_UPLOAD_BYTES`).
4. **Check the preview.** The preview page counts the expected columns that were
   **Matched**, the ones **Missing**, and the **Extra** ones that will be
   ignored, suggests renames, and lists data-quality problems; rows flagged as
   errors will be skipped. Missing *required* columns stop the conversion;
   missing *conditional* ones only warn.
5. **Map columns if needed.** If your export uses different header names,
   **Map Columns** opens the mapping page, where you point each expected field at
   one of your columns. Save the mapping as a named template; next time, pick it
   under **Saved templates** and **Apply** it — a template is not applied by
   itself. **Save Mapping & Continue** returns you to the preview, whose counts
   still describe the file's own headers: the conversion applies the mapping.
6. **Convert.** **Confirm & Convert**. The progress page shows the records
   processed, and a **Cancel conversion** button once the job is converting.
7. **Read the results.** You get the XML, a pass/fail against the SBA schema, a
   list of data-quality issues, and a cleaning diff showing every value the tool
   changed and why. A record SBA's schema rejects is left out of the XML and
   listed as an error, so compare **Successful** with **Total Records**.
8. **Download.** **Download XML**. Files are removed from disk after
   `RETENTION_DAYS` (30 by default); the job record and audit trail are kept.

Each screen, and how to work a file down to a clean one:
[web-app-guide.md](./web-app-guide.md).

### Sample CSVs

Three samples ship with the app, linked from the landing page, the dashboard
empty state and the converter cards, and served from `apps/web/public/samples/`:

| File | Converter | Rows | What it is |
|---|---|---|---|
| `counseling-sample.csv` | `counseling` | 3 | Individual counseling sessions (Form 641) |
| `training-sample.csv` | `training` | 7 | Per-attendee rows rolled up into Form 888 events |
| `training-client-sample.csv` | `training-client` | 3 | Per-attendee training rows emitted as Form 641 |

All three are covered by `TestShippedSamplesValidate` in
`tests/test_integration_xsd.py`, which asserts each one converts to XML that
validates clean against its bundled XSD. If a sample ever stops validating, that
test fails — that is the point of it. Because the converters now leave out a
record the XSD rejects, validity alone would not notice a sample losing one;
`test_shipped_sample_output_is_stable` in
`tests/test_converter_characterization.py` pins each sample's exact XML to
`tests/golden/`, which does.

The samples are not issue-free: the counseling sample reports five errors (a
client in business with no Legal Entity or Counseling Seeking, a veteran with no
branch of service) and still files all three records. Their issue lists are
examples to read, not faults.

### Running the web app without Docker

Useful when you are working on the web code and want fast reloads. You need
Python 3.12, Node 20.9 or later, a Postgres, and Redis 7 or later (the rate
limiter's `EXPIRE … NX` needs 7; on an older Redis every limit fails open).

```bash
# Terminal 1 — worker
pip install -r apps/worker/requirements.txt
WORKER_AUTH_TOKEN=dev-token \
  uvicorn app.main:app --app-dir apps/worker --host 0.0.0.0 --port 8000

# Terminal 2 — web
cd apps/web
cp .env.example .env.local     # then edit DATABASE_URL, REDIS_URL, DATA_DIR, secrets
npm ci
node --env-file=.env.local scripts/migrate.js   # creates the tables
npm run dev
```

`migrate.js` is plain Node: unlike `next dev` it does not read `.env.local`, so
without `--env-file` it stops with *"Environment variable not found:
DATABASE_URL"*. `DATA_DIR` defaults to `/data`, which a development machine
usually cannot write; point it at a folder you own, or every upload fails with
`EACCES` in the log.

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

Output lands in `output/`; the validation reports land in `reports/` (HTML
always, CSV when there are issues); logs land in `logs/`. All three are relative
to the folder holding `run.py`.

> **Note:** `run.py` offers an optional XSD-validation step only when it finds
> `.xsd` files **directly beside `run.py`**. The bundled schemas live in
> `schemas/`, so the step does not appear on a clean checkout. The conversion
> checks its XML against the bundled schema anyway, and leaves out a record that
> fails with an error in the report; what you miss is the printed pass/fail. To
> get it, copy the XSD you need next to `run.py`. This is a known bug — see
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
- What a screen or a result means → [web-app-guide.md](./web-app-guide.md)
- Something failed → [troubleshooting.md](./troubleshooting.md)
- You are deploying this for a team → [deployment.md](./deployment.md)
