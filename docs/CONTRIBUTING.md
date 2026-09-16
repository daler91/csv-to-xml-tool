# Contributing

## Development setup

```bash
git clone https://github.com/daler91/csv-to-xml-tool.git
cd csv-to-xml-tool

# Python core + worker (installing the dev file matters — see below)
pip install -r requirements.txt -r apps/worker/requirements-dev.txt

# Web
cd apps/web && npm ci && cd ../..
```

`apps/worker/requirements-dev.txt` pulls in `fastapi` and `fakeredis`. Without
them, 79 tests **silently skip** rather than fail
([testing.md](./testing.md#test_converter_characterizationpy)). Install it.

To add or bump a Python dependency, edit the matching `requirements*.in` file,
not the `.txt`: the `.txt` files are hash-locked lockfiles that CI and the
worker image install with `--require-hashes`, regenerated with the
`uv pip compile` command in each file's header
([testing.md](./testing.md#running-everything)).

Full-stack work is easiest under Compose:

```bash
cp .env.example .env
docker compose up
```

For fast web reloads without Docker, see
[getting-started.md](./getting-started.md#running-the-web-app-without-docker).

## Before you open a pull request

```bash
python -m pytest tests/ -v --cov=src --cov=apps/worker/app --cov-fail-under=70
ruff check .
cd apps/web && npm run lint && npm test && npm run build
```

CI runs all of this plus `pip-audit`, `npm audit --audit-level=high`, a
`SCHEMAS_DIR`-unset schema-resolution check, and a full
`docker compose build && up -d --wait`. Running the first two locally catches
almost everything.

## The rules that are not negotiable

These each exist because breaking them shipped a real defect.

### 1. The three sample CSVs must validate clean

`TestShippedSamplesValidate` in `tests/test_integration_xsd.py` is the gate. If
your change makes a sample produce schema-invalid XML, the change is wrong — the
samples are the first thing a new user converts.

### 2. A blank cell never becomes an empty element

Route every facet-constrained optional element through
`src/xml_utils.emit_optional`. An empty `<ZipCode/>` fails the `\d{5}` pattern;
omitting it is valid.

### 3. A schema change means a `migrate.js` change, in the same commit

`apps/web/scripts/migrate.js` — not `prisma migrate` — is what the deployed
container runs. Mirror every `prisma/schema.prisma` change as an idempotent
statement (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`). Miss it and
production boots against a database missing the column, failing every query on
that model with `P2022`.

### 4. Never fabricate data silently

If the converter must emit a value the CSV did not supply, record a
`FABRICATED_DEFAULT` issue naming the column and the value. If it must drop data
to satisfy the schema, record a `DOWNGRADED_VALUE`. The output is a federal
filing; an unrecorded invention is a defect even when the XML validates.

### 5. Status transitions stay guarded

Every job status write is an `updateMany` with an explicit status predicate and a
`count === 0` check. That is what stops a cancel losing a race and a finished
conversion reviving a cancelled job. Do not replace one with an `update`.

### 6. Do not weaken the XML parsing defaults

`defusedxml` for ElementTree, `resolve_entities=False` for lxml. Everywhere.

### 7. Keep the durability timeouts ordered

`CONVERSION_TIMEOUT_MS < VISIBILITY_TIMEOUT_MS < REAP_DEADLINE_MS`, in code and
in both `.env.example` files.

## Code conventions

### Python

- Target 3.12. Type-annotate new code; use `TYPE_CHECKING` guards to avoid
  circular imports.
- Catch specific exceptions (`OSError`, `csv.Error`, `etree.XMLSyntaxError`,
  `ValueError`, `KeyError`), not bare `Exception`.
- `from __future__ import annotations` goes **below** the module docstring. Above
  it, `__doc__` is `None` and `help()` shows nothing.
- No import-time side effects. Config values that depend on the current date —
  the fiscal-year cutoff, for one — are computed per call, because a long-lived
  worker crosses October 1.
- New column vocabulary goes in `src/config.py`, not inline string literals.
- There is no formatter and no type checker. Ruff runs correctness rules only
  (`F`, `E9`, `B`); match the surrounding style by hand.

### TypeScript / React

- `npm run lint` is `tsc --noEmit` plus `scripts/check-ui-classes.mjs`. There is
  no ESLint.
- Use the primitives in `components/ui/` (`Button`, `Alert`, `StatusBadge`,
  `StepIndicator`). `check-ui-classes.mjs` fails the build when a page hand-rolls
  classes that belong to one.
- Converter labels and descriptions come from `lib/converter-types.ts`. Hardcoding
  them is what made a `training-client` job display as "Training (Form 888)".
- Status and severity must never be conveyed by colour alone — pair them with a
  shape or a label (WCAG 1.4.1). `components/status-icon.tsx` handles this.
- Keep the `aria` discipline of the surrounding code: `role="alert"` on error
  alerts, `aria-live` on counters, proper `progressbar` roles and values.

## Documentation

**A change that alters behaviour changes the docs in the same commit.** That is
the whole reason [`docs/`](./README.md) exists as a structured set rather than a
pile of review files.

- Behaviour change → the relevant guide (`architecture`, `converters`,
  `csv-reference`, `cli`, `api-reference`, `configuration`, `deployment`,
  `operations`, `troubleshooting`, `testing`).
- New or changed env var → [configuration.md](./configuration.md) **and** both
  `.env.example` files.
- New API route or changed status code → [api-reference.md](./api-reference.md).
- **Fixing a tracked finding → flip its marker to `[FIXED]`/`[RESOLVED]` in the
  register under [`reviews/`](./reviews/README.md), in the same commit.** A
  register whose markers are not maintained becomes actively misleading — that is
  exactly how `ARCHITECTURE_REVIEW.md` ended up a historical document with ~20 of
  24 findings already fixed and every line citation stale.
- Counted figures (test totals, coverage, route counts) are stamped with the
  commit they were measured at. Re-stamp them when you re-measure.

Guides use `kebab-case.md`; `CONTRIBUTING.md` and `SECURITY.md` keep their
uppercase names for GitHub; registers under `reviews/` keep their original
`UPPER_SNAKE_CASE.md` names because ~25 source comments reference them by name.

## Tests

- Python: pytest, `tests/test_<module>.py`, `Test*` classes, `test_*` functions.
- Web: vitest, `*.test.ts` beside the file under test.
- Use `fakeredis`, not a live Redis.
- Do not monkeypatch `SCHEMAS_DIR` unless the test is about schema resolution —
  the unpatched CI check is deliberately the only one.
- Adding a converter behaviour? Add a golden in `tests/golden/`. Note that
  `.gitignore` ignores `*.xml` with an explicit `!tests/golden/*.xml` exception —
  without it the goldens vanish on a clean checkout and the tests pass while
  asserting nothing.

Details: [testing.md](./testing.md).

## Branches and commits

Work on a branch off `master`; open a pull request. CI must be green.

Write commit messages that say **why**, not just what. The existing history does
this well — "Give counseling headers one source: CounselingConfig.COLUMN_MAPPING"
beats "refactor config". Code comments in this repo follow the same convention:
several explain the incident that motivated the line. Preserve that when you edit
around them.

## Where to look first

| Working on | Start at |
|---|---|
| Conversion output | `src/converters/`, `src/config.py`, `tests/golden/` |
| Cleaning rules | `src/data_cleaning.py`, `apps/worker/app/services/diff_service.py` |
| Schema errors | `src/xml_validator.py`, `src/xsd_error_mapping.py` |
| Job lifecycle | `apps/web/src/lib/job-*.ts` |
| Worker HTTP | `apps/worker/app/routes/`, `apps/worker/app/main.py` |
| UI flow | `apps/web/src/app/convert/` |
| Known problems | [`reviews/CODEBASE_ANALYSIS.md`](./reviews/CODEBASE_ANALYSIS.md) |

## Good first contributions

Concrete, scoped, and already diagnosed:

- **Sync the audit page's action list with what the code writes** — it offers a
  `conversion_failed` filter nothing writes, and six written actions render as
  "—".
- **Fix `run.py`'s XSD discovery** so the validation prompt finds `schemas/`
  instead of only the launcher's own directory.
- **Replace the 9 hardcoded "50MB" strings** with a value derived from
  `MAX_UPLOAD_BYTES`.
- **Split `convert/[jobId]/results/page.tsx`** (685 lines, a page plus seven
  components, re-declaring two types that already exist in `types/index.ts`).
- **Add a formatter and a type checker** (`ruff format`, mypy) — deliberately
  absent today, and a real gap.

The larger open items — the inverted converter abstraction (§5.1) and routing
counseling's remaining ~70 header literals through `COLUMN_MAPPING` (§5.2) — are
worth scoping deliberately rather than picking up opportunistically.
