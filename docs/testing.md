# Testing

Two suites, both gating CI.

| Suite | Runner | Covers |
|---|---|---|
| `tests/` | pytest | `src/` (conversion core) **and** `apps/worker/app` |
| `apps/web/src/**/*.test.ts` | vitest | The web API routes, queue, runner, reaper, retention, auth, paths |

The Python suite covers the worker as well as the core, so there is no separate
worker suite to run.

## Running everything

```bash
# Python — core + worker
pip install -r requirements.txt -r apps/worker/requirements-dev.txt
python -m pytest tests/ -v \
  --cov=src --cov=apps/worker/app \
  --cov-report=term-missing --cov-fail-under=70

# Web
cd apps/web && npm ci
npm test          # vitest run
npm run lint      # tsc --noEmit + check-ui-classes.mjs
npm run build     # next build

# Python lint
pip install -r requirements-ci.txt && ruff check .
```

The `requirements*.txt` files are hash-locked resolutions compiled from the
human-edited `requirements*.in` files next to them (root, `apps/worker/`, and
`requirements-ci.in` for `ruff` and `pip-audit`). CI and the worker image
install them with `pip install --only-binary :all: --require-hashes`, so a
version or hash that drifts from the lockfile fails the install. To change a
dependency, edit the `.in` file and regenerate with the `uv pip compile`
command in the `.txt` header (`pip install uv` if you don't have it).

`apps/worker/requirements-dev.txt` matters: it carries the worker's runtime
dependencies (`fastapi`, `redis`, …) plus `fakeredis`, an in-memory Redis, so
the registry tests need no live server. Without it the run stops at collection
(see [the caution below](#a-caution-about-missing-dependencies)).

## Current baseline

Measured at commit `7b14f3b` on 2026-10-17 (Python 3.13, Node 22). Re-measure
with the commands above rather than trusting these numbers indefinitely.

| Check | Result |
|---|---|
| pytest | **1027 passed** |
| Coverage (`src/` + worker) | **97.5%** against a 70% gate |
| vitest | **395 passed**, 38 files |
| `tsc --noEmit` | clean |
| `check-ui-classes.mjs` | clean, 108 files |
| `next build` | succeeds, 28 routes |
| `ruff check .` | clean |
| `pip-audit` (both requirement files) | no known vulnerabilities |
| `npm audit --audit-level=high` | 0 vulnerabilities |

The coverage gate is 70% while actual coverage is ~97%, so there is ~27 points of
headroom. Raise the floor when you add coverage; do not lower it.

## CI

`.github/workflows/ci.yml`, three jobs, all on every push and on PRs to `master`.
`GITHUB_TOKEN` is read-only for the whole workflow.

### `python-tests`

1. `pip-audit` on `requirements.txt` and `apps/worker/requirements.txt`. Scoped to
   declared requirements rather than the environment, because an env scan also
   flags the runner's own pip/setuptools. Any known advisory fails the build;
   allowlist a specific one with `--ignore-vuln <ID>`.
2. `ruff check .`
3. **Schemas resolve without `SCHEMAS_DIR`** — imports the default with the
   variable unset and asserts the directory exists. Cheap, and the only thing
   keeping that default honest, since every other test monkeypatches it.
4. pytest with the coverage gate.

### `web-lint`

`npm ci --ignore-scripts` → `npm run generate` → `npm audit --audit-level=high`
→ `npm run lint` → `npm test` → `npm run build`. `--ignore-scripts` keeps every
package's lifecycle scripts off the runner, including the project's own
`postinstall`, so the Prisma client is generated explicitly — the same two steps
`apps/web/Dockerfile` takes. High and critical advisories fail the build;
moderates are reported only.

### `docker-build`

`cp .env.example .env`, then `docker compose build` and `up -d --wait`, dumping
logs on failure and tearing down with `-v` always.

This job exists because three deployment defects shipped while nothing in CI
built an image: an unresolvable build context, a healthcheck calling a binary the
image does not ship, and a failed migration that still started the server.
`build` alone catches only the first — `up --wait` is what exercises the other
two.

## Ruff's scope is deliberate

`pyproject.toml` enables `F`, `E9` and `B` only — correctness rules, not style.

This is not laziness. `F821` is why the linter exists at all: a refactor once
inserted a method into the middle of another, leaving the tail of the outer
method unreachable after a `return`. That silently dropped
`ClientNamePart3`, `Email`, `PhonePart3` and `AddressPart3` from **every**
counseling record. All four are `minOccurs="0"`, so the XML stayed schema-valid
and the entire test suite stayed green. Pyflakes caught it in under a second.

Style rules stay off because there is no formatter in this repo, and turning them
on would bury findings like that one under hundreds of whitespace complaints.

`apps/web` is excluded from ruff. `tests/*` ignores `B011` (bare asserts).

## The tests worth understanding

### `tests/test_integration_xsd.py` — `TestShippedSamplesValidate`

Converts all three sample CSVs and asserts the output validates clean against the
bundled XSDs. **This is the single most important test in the repo.** Two of the
three samples once failed — a first-time user following the README got an invalid
federal filing — and this test is what makes that impossible to reintroduce.

It proves less than its importance suggests: `counseling-sample.csv` carries 16
of the 74 counseling columns in three rows, so it never reaches the address,
Part 3, certification or referral paths. Read it with the next one.

### `tests/test_xsd_validity_fuzz.py` — every column, every converter

The method of [`reviews/XSD_VALIDITY_ANALYSIS.md`](./reviews/XSD_VALIDITY_ANALYSIS.md)
kept as a regression test. A seeded generator fills every column each converter
reads with the schema's own values (exact, lower-cased, cut short, joined into
long multi-selects), near misses and junk. Every file must validate, and the
converters' final XSD check (`BaseConverter._write_valid_xml`) must never have
had to step in: the schema guard and the converters are meant to handle each
case themselves. `test_xsd_validity.py` and `test_xsd_validity_second_pass.py`
pin each finding of that analysis individually.

### `tests/golden/` — characterization goldens

Nine committed XML files that pin converter output byte-for-byte. They were
captured before the pandas removal and are what proved the rewrite produced
identical output.

`.gitignore` blanket-ignores `*.xml`, with an explicit `!tests/golden/*.xml`
exception. Without it the goldens would be absent on a clean checkout and the
tests would regenerate-and-skip: passing while asserting nothing.

### Drift guards

Several tests exist solely to stop two structures disagreeing:

- `test_counseling_column_mapping.py` pins `preview_service.COUNSELING_EXPECTED`,
  `xsd_error_mapping._COUNSELING_ELEMENT_FIELDS`,
  `diff_service.COUNSELING_CLEANING_MAP`, the `column_requirements` tier sets,
  `COUNSELING_FIELD_METADATA` and `COUNSELING_FABRICATION_DEFAULTS` to
  `CounselingConfig.COLUMN_MAPPING`.
- `test_expected_columns.py` parses `counseling_converter.py` with `ast` and
  asserts the expected-column list is exactly the set of headers the converter
  reads — through literals, module constants and the `_mapped` helpers alike.
- `EXPORT_COUNTRY_CODES` is pinned against the schema enumeration
  (`test_integration_xsd.py`).
- `check-ui-classes.mjs` fails the web lint when a page hand-rolls classes that
  belong to a `components/ui/` primitive.

One trap is stated explicitly beside `CounselingConfig.COLUMN_MAPPING` in
`src/config.py`: **counseling's lists are not aliases.** `TrainingConfig`
derives expected columns as `alts[0]`, which
is right there because a list means "several spellings of one column". In
counseling, the Part 3 impact fields *fall back* to their intake counterpart, and
`Total Number of Employees`, `Gross Revenues/Sales` and `Profits/Losses` are each
*also* read on their own. Applying the `alts[0]` rule would drop three real
columns. `expected_columns()` unions instead.

### The conversion invariants

Most conversion failures fixed in October 2026 were one file's formatting or
one spelling of a value, each fixed for the case reported. These state the
property such fixes share, so the next variant fails a test instead of a
filing:

- `test_conversion_invariants.py` — the same data written the ways real
  exports write it (CRLF, every cell quoted, a Salesforce report footer, two
  pasted exports, UTF-16, Windows-1252, stray spaces and zero-width characters
  in headers, padded cells, …) must convert to **byte-identical XML** with no
  new error, through the CLI converter and the worker alike, and a column
  mapping naming every column back must be transparent. A bad row inserted
  anywhere may cost only its own record, and must be filed or reported.
- `test_value_spellings.py` — every spelling of one date, amount, phone,
  Yes/No, gender or state cleans to the same value; near misses are refused,
  not guessed.
- `test_csv_decoding_parity.py` and `csv-decode.test.ts` — the web decodes
  uploads itself, so both decoders are held to one table of bytes and texts,
  `tests/fixtures/csv_decoding_cases.json`. Regenerate it with
  `python tests/test_csv_decoding_parity.py` after changing a case or the
  Python decoder on purpose.
- `test_worker_web_contract.py` — the worker's JSON, from the real app, against
  the TypeScript interfaces the web reads it with, field by field.

When a conversion bug is fixed, add its variant to the first two files rather
than a one-off test: a transformation, a bad row or a spelling.

### `test_converter_characterization.py`

Runs the converters end to end against the goldens; it is what proved the pandas
removal left output byte-identical.

### A caution about missing dependencies

Measured at `7b14f3b`, with only `requirements.txt` installed:

- **The run stops at collection.** `test_conversion_invariants.py` and
  `test_conversion_service_mapping.py` import the worker without a guard, so
  pytest reports `ModuleNotFoundError: No module named 'redis'` and
  `Interrupted: 2 errors during collection`. That is the loud failure, and the
  better one.
- **Eleven more files skip wholesale.** They start with
  `pytest.importorskip("fastapi")` or `("fakeredis")` — the worker route,
  registry, schema-path, column-mapping, diff-service, expected-columns and
  worker-web contract tests, 140 tests in all. Pytest counts each skipped file
  once, so the summary line says `11 skipped`.

Forced past the collection errors (`--continue-on-collection-errors`), the
rest gives 742 passed, 2 failed (two tests elsewhere that drive the worker's
conversion service) and 11 skipped. An environment that has `redis` but not
`fastapi` or `fakeredis` still passes green — `887 passed, 11 skipped` — with
those 140 tests unrun. CI
installs everything, so CI is honest; your laptop may not be. Check the summary
line for skips before trusting a local pass.

This pattern previously guarded two whole files with `importorskip("pandas")`,
which would have turned into silent skips the moment pandas was uninstalled —
exactly the failure mode above. Prefer installing the dependency over adding a
new guard.

## Writing tests

- **Python**: pytest, `tests/test_<module>.py`, classes `Test*`, functions
  `test_*` (`pytest.ini`). `tests/conftest.py` holds shared fixtures.
- **Web**: vitest, `*.test.ts` beside the file under test. `src/test/helpers.ts`
  has the shared mocks.
- Use `fakeredis` rather than a live Redis.
- Do not monkeypatch `SCHEMAS_DIR` unless the test is specifically about schema
  resolution — the CI step above is the only unpatched check, and it is
  deliberately narrow.

### Coverage exclusions

`.coveragerc` omits `tests/*` and `*/__init__.py`. Source directories are passed
on the command line via `--cov` so they are visible in the workflow rather than
hidden in a config file.

## Manual verification

The end-to-end check, when you want to be certain:

```bash
export SBA_OUTPUT_BASE=/tmp/sba-out && mkdir -p "$SBA_OUTPUT_BASE"
for t in counseling training training-client; do
  python -m src.main convert "$t" \
    --input "apps/web/public/samples/$t-sample.csv" \
    --output "$SBA_OUTPUT_BASE/$t.xml" \
    --report-dir "$SBA_OUTPUT_BASE/r" --log-dir "$SBA_OUTPUT_BASE/l"
done

python - <<'EOF'
from lxml import etree
for name, xsd in [("counseling", "SBA_NEXUS_Counseling-2-14"),
                  ("training-client", "SBA_NEXUS_Counseling-2-14"),
                  ("training", "SBA_NEXUS_Training-2-25-2025")]:
    schema = etree.XMLSchema(etree.parse(f"schemas/{xsd}.xsd"))
    ok = schema.validate(etree.parse(f"/tmp/sba-out/{name}.xml"))
    print("PASS" if ok else "FAIL", name, len(list(schema.error_log)), "errors")
EOF
```

All three must print `PASS`. `training-client` is validated against the
**counseling** schema — that is not a typo.
