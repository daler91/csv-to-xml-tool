# SBA Counseling and Training Data Conversion Tool

Converts SBA counseling and training CSV exports into XSD-compliant XML for the
federal SBA Nexus/EDMIS system — and tells you, row by row and column by column,
what it changed and why.

Because the output is a federal filing, the tool's guiding rule is that it never
silently invents data. Where a default is unavoidable it is recorded in the
validation report rather than shipped quietly.

It ships in two forms, both running the same conversion core:

- **A web application** (`apps/web` + `apps/worker`) — accounts, uploads, column
  mapping, live progress, validation reports, job history, downloads. Recommended
  for most people.
- **A Python CLI** (`run.py`, `src/`) — a double-clickable launcher for one-off
  conversions, and an argparse CLI for scripting.

---

## Quick start

### Web app

```bash
cp .env.example .env
# Set NEXTAUTH_SECRET and WORKER_AUTH_TOKEN: openssl rand -hex 32
docker compose up
```

Open <http://localhost:3000>, create an account, upload a CSV.

### Desktop CLI

1. **Download** — **Code** → **Download ZIP**, unzip anywhere.
2. **Set up** (once) — Windows: double-click `setup.bat`. macOS/Linux:
   `pip install -r requirements.txt`. Requires
   [Python](https://www.python.org/downloads/) (tick **"Add Python to PATH"** on
   Windows).
3. **Run** — put your CSV in the folder, then double-click `run.bat`, or run
   `python run.py`.

Output lands in `output/`, reports in `reports/`, logs in `logs/`.

Converting your first file: **[docs/user-guide.md](./docs/user-guide.md)**.
Installing and running the app: [docs/getting-started.md](./docs/getting-started.md).

---

## The three converters

| Converter | Form | A CSV row is… |
|---|---|---|
| `counseling` | 641 Counseling | one counseling session with one client |
| `training` | 888 Management Training | one **attendee**; rows are rolled up per event, with demographic totals computed automatically |
| `training-client` | 641 Counseling | one training attendee, emitted as a counseling record |

Picking the wrong one is the most common source of confusing output.
**[docs/converters.md](./docs/converters.md)** explains which you want.

Sample CSVs for each live in `apps/web/public/samples/` and are linked from the
landing page and the dashboard empty state. All three are covered by a test that
asserts they convert to schema-valid XML.

## What it does

- **Schema-correct output** — elements emitted in the exact order the XSD
  requires, which is what prevents the `cvc-complex-type.2.4.a` errors that
  dominate hand-built SBA XML. A blank cell produces no element, never an empty
  one.
- **Cleaning and standardization** — dates to `YYYY-MM-DD`, phone numbers to
  ten digits (anything else is refused and reported, not cut), money with
  `Decimal`, states and countries mapped onto schema enumerations
  (`IA` → `Iowa`), semicolon-delimited Salesforce multi-value fields split, long
  text truncated at the schema's limits with a warning.
- **Every value checked against the XSD before it is written** — the schema's
  own facets are applied to each record (`src/schema_rules.py`). A value that
  cannot be filed is dropped with a warning when the schema lets it be omitted;
  a record that still cannot be filed is left out and reported as an error,
  instead of failing the whole file. Each finished file is then validated
  against SBA's XSD, and any record that still fails is left out with an error
  naming its row and column (`BaseConverter._write_valid_xml`).
- **Conditional logic** — `BranchOfService` only when military status indicates
  service, and so on.
- **Errors traced back to your CSV** — instead of *"Line 20: Element 'ZipCode'…"*
  you get *"Row 1 (Contact 003XX…): 'Mailing Zip/Postal Code'…"*.
- **An audit trail of every change** — CSV and HTML validation reports from the
  CLI, a before/after cleaning diff in the web app, and a `FABRICATED_DEFAULT`
  warning wherever a value did not come from your data.
- **An XML repair tool** — reorders the elements of existing SBA XML into the
  order its XSD requires and re-validates the result: counseling and training
  files from the CLI (`src/fix_sba_xml.py`), counseling-format files from the web
  app's Validate page.

> **This is currently a single-organization tool.** `src/config.py` hardcodes one
> organization's location code and partner code, and they are stamped into every
> filing. Read
> [docs/converters.md](./docs/converters.md#-this-is-a-single-organization-tool)
> before deploying it for anyone else.

## Documentation

Everything lives in **[`docs/`](./docs/README.md)**.

| | |
|---|---|
| [**User guide**](./docs/user-guide.md) | **Start here to convert a CSV**: the steps, what the results mean, a checklist before filing |
| [Getting started](./docs/getting-started.md) | Install and run, web or CLI |
| [Web app guide](./docs/web-app-guide.md) | Each screen, and how to read the results and work a file clean |
| [Architecture](./docs/architecture.md) | How the pieces fit together |
| [Converters](./docs/converters.md) | What each one emits, and when it defaults |
| [CSV reference](./docs/csv-reference.md) | Expected columns per converter |
| [CLI reference](./docs/cli.md) | Every flag, and output-path confinement |
| [API reference](./docs/api-reference.md) | Web and worker HTTP surfaces |
| [Configuration](./docs/configuration.md) | Every environment variable |
| [Deployment](./docs/deployment.md) | Compose, Railway, migrations |
| [Operations](./docs/operations.md) | Queue, retention, audit, runbook |
| [Troubleshooting](./docs/troubleshooting.md) | Errors and what to do about them |
| [Testing](./docs/testing.md) | Suites, CI gates, the tests that matter |
| [Contributing](./docs/CONTRIBUTING.md) | Setup and the rules that are not negotiable |
| [Security](./docs/SECURITY.md) | Reporting, controls, known weaknesses |
| [Review registers](./docs/reviews/README.md) | Audits and debt registers, with status markers |

## Repository layout

```
run.py, run.bat, setup.bat    Interactive launcher + Windows shortcuts
src/                          Shared conversion core (converters, cleaning,
                              validation, XSD checking, error mapping)
apps/web/                     Next.js — auth, jobs, UI, downloads
apps/worker/                  FastAPI — HTTP wrapper around src/
schemas/                      The two SBA XSDs
tests/                        Python suite (covers src/ and the worker)
docs/                         Documentation
```

## Development

```bash
pip install -r requirements.txt -r apps/worker/requirements-dev.txt
python -m pytest tests/ -v --cov=src --cov=apps/worker/app --cov-fail-under=70
ruff check .

cd apps/web && npm ci && npm run lint && npm test && npm run build
```

Installing `apps/worker/requirements-dev.txt` matters — without it pytest stops
at collection on `No module named 'redis'`, and a partial install that has
`redis` but not `fastapi`/`fakeredis` passes green with 140 tests skipped. See
[docs/testing.md](./docs/testing.md#a-caution-about-missing-dependencies).
