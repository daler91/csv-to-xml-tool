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
pip install ruff && ruff check .
```

`apps/worker/requirements-dev.txt` matters: without it the worker route and
registry tests under `tests/` error on a missing `fastapi` or `fakeredis` import.
It pulls in `fakeredis`, an in-memory Redis, so the registry tests need no live
server.

## Current baseline

Measured at commit `d0e71f0` on 2026-09-16. Re-measure with the commands above
rather than trusting these numbers indefinitely.

| Check | Result |
|---|---|
| pytest | **374 passed** |
| Coverage (`src/` + worker) | **88.8%** against a 70% gate |
| vitest | **173 passed**, 23 files |
| `tsc --noEmit` | clean |
| `check-ui-classes.mjs` | clean |
| `next build` | succeeds, 28 routes |
| `ruff check .` | clean |

The coverage gate is 70% while actual coverage is ~89%, so there is ~19 points of
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

`npm ci` → `npm audit --audit-level=high` → `npm run lint` → `npm test` →
`npm run build`. High and critical advisories fail the build; moderates are
reported only.

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

### `tests/golden/` — characterization goldens

Nine committed XML files that pin converter output byte-for-byte. They were
captured before the pandas removal and are what proved the rewrite produced
identical output.

`.gitignore` blanket-ignores `*.xml`, with an explicit `!tests/golden/*.xml`
exception. Without it the goldens would be absent on a clean checkout and the
tests would regenerate-and-skip: passing while asserting nothing.

### Drift guards

Several tests exist solely to stop two structures disagreeing:

- `test_expected_columns.py` pins `preview_service.COUNSELING_EXPECTED`,
  `xsd_error_mapping._COUNSELING_ELEMENT_FIELDS`,
  `diff_service.COUNSELING_CLEANING_MAP`, the `column_requirements` tier sets and
  `COUNSELING_FIELD_METADATA` to `CounselingConfig.COLUMN_MAPPING`.
- `EXPORT_COUNTRY_CODES` is pinned against the schema enumeration.
- `check-ui-classes.mjs` fails the web lint when a page hand-rolls classes that
  belong to a `components/ui/` primitive.

One trap is stated explicitly in `test_expected_columns.py`: **counseling's lists
are not aliases.** `TrainingConfig` derives expected columns as `alts[0]`, which
is right there because a list means "several spellings of one column". In
counseling, the Part 3 impact fields *fall back* to their intake counterpart, and
`Total Number of Employees`, `Gross Revenues/Sales` and `Profits/Losses` are each
*also* read on their own. Applying the `alts[0]` rule would drop three real
columns. `expected_columns()` unions instead.

### `test_converter_characterization.py`

Runs the converters end to end against the goldens; it is what proved the pandas
removal left output byte-identical.

**A caution about `importorskip`.** Six test files start with
`pytest.importorskip("fastapi")` or `("fakeredis")`, so the worker route,
registry, schema-path and column-mapping tests **skip entirely** if you have not
installed `apps/worker/requirements-dev.txt`. A green local run with those
dependencies missing is green because 79 tests did not run. CI installs them, so
CI is honest; your laptop may not be. Check the summary line for skips before
trusting a local pass.

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
