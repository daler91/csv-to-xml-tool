# Technical Debt Register

This document catalogs known technical debt across the CSV-to-XML tool codebase, organized by priority. Each item includes affected files, line references, and a recommended fix.

---

## HIGH Priority

### 1. Weak Type Annotations (Python)

Several core interfaces use `object` instead of proper types, defeating static analysis and IDE support.

| Location | Issue |
|----------|-------|
| `src/converters/base_converter.py:23` | `logger: object` and `validator: object` should be `logging.Logger` and `ValidationTracker` |
| `src/data_validation.py:41` | `validate_counseling_record(... validator: object)` |
| `src/data_validation.py:71` | `validate_training_record(... validator: object)` |
| `src/data_cleaning.py:104` | `map_value(value: object, ..., default_value: object) -> object` |

**Recommended fix:** Replace `object` with the actual types (`logging.Logger`, `ValidationTracker`, `str`, etc.). Add `from __future__ import annotations` where needed to avoid circular imports.

---

### 2. Overly Broad Exception Handling

Generic `except Exception` blocks mask specific errors (I/O failures, XML parse errors, pandas errors), making debugging harder and hiding root causes.

| Location | Context |
|----------|---------|
| `src/xml_validator.py:66` | Catches all errors during XSD validation |
| `src/xml_validator.py:160` | Catches all errors during XML fix |
| `src/converters/counseling_converter.py:35,66,78` | CSV reading and record conversion |
| `src/converters/training_converter.py:42,137` | CSV reading and event processing |
| `src/fix_sba_xml.py:91,159` | XML element reordering |

**Recommended fix:** Replace with specific exception types: `IOError`, `lxml.etree.XMLSyntaxError`, `pd.errors.ParserError`, `ValueError`, etc. Keep a final `except Exception` only at the top-level entry point as a last resort.

---

### 3. Missing Input Validation

| Location | Issue |
|----------|-------|
| `src/converters/counseling_converter.py` (throughout) | No pre-check that expected CSV columns exist before `row.get()` calls |
| `src/converters/training_converter.py` (throughout) | Same issue |
| `src/validation_report.py:139-143,271-272` | File write operations have no exception handling |
| `src/xml_validator.py:147-148` | `.text` accessed on XML element without `None` guard |

**Recommended fix:** After reading the CSV DataFrame, validate that all required columns are present and log/fail early if they are missing. Wrap file I/O in try/except with meaningful error messages. Guard `.text` access with explicit `None` checks.

---

### 4. Hardcoded Credentials in docker-compose.yml

`docker-compose.yml` contains hardcoded secrets that could leak into version control:

| Line | Value |
|------|-------|
| 9 | `NEXTAUTH_SECRET=dev-secret-change-me` |
| 30 | `POSTGRES_USER: user` |
| 31 | `POSTGRES_PASSWORD: pass` |

There is no `.env.example` file documenting required environment variables.

**Recommended fix:** Move all secrets to a `.env` file (git-ignored). Add a `.env.example` with placeholder values. Reference via `env_file:` in docker-compose.yml.

---

### 5. Beta Dependency in Production

`apps/web/package.json:27` depends on `next-auth@5.0.0-beta.30`, a pre-release version. Beta APIs may change without notice, and security patches may lag behind stable releases.

**Recommended fix:** Track the next-auth stable release roadmap. Pin the current version exactly. Document the risk and migration plan for when a stable release is available.

---

## MEDIUM Priority

### 6. Code Duplication

| Pattern | Location | Occurrences |
|---------|----------|-------------|
| `row.get('Field', '').strip()` | `src/converters/counseling_converter.py` | 14+ times |
| Empty/NaN guard: `if not value or str(value).strip() == "" or str(value).lower() == "nan"` | `src/data_cleaning.py` | 9 times |
| CSV reading with try/except and pandas | `src/converters/counseling_converter.py:30-38`, `src/converters/training_converter.py:39-45` | 2 files |
| XML element ordering lists | `src/xml_validator.py:133-143` | Hardcoded instead of in config |

**Recommended fixes:**
- Extract a `get_field(row, name, default='')` helper to replace the `row.get().strip()` pattern.
- Extract an `is_empty(value)` utility in `data_cleaning.py` for the repeated NaN/empty check.
- Move CSV reading logic into `BaseConverter` so both converters inherit it.
- Move element ordering definitions to `src/config.py`.

---

### 7. Magic Numbers and Hardcoded Values

| Location | Value | Meaning |
|----------|-------|---------|
| `src/data_cleaning.py:198-200` | `10`, `11` | Phone number digit count and country code prefix length |
| `src/data_cleaning.py:333` | `0`, `100` | Percentage bounds |
| `src/config.py:16` | `10` | Fiscal year start month (October) |
| `src/config.py:101-103` and `src/data_cleaning.py` | Date format lists | Duplicated between two files |

**Recommended fix:** Define named constants (`PHONE_DIGITS = 10`, `FISCAL_YEAR_START_MONTH = 10`, `PERCENTAGE_MIN = 0`, `PERCENTAGE_MAX = 100`). Consolidate the date format list to a single source of truth in `config.py`.

---

### 8. No Web Application Tests

- No `apps/web/__tests__/` directory exists -- zero frontend test coverage.
- No integration tests for API routes in `apps/web/src/app/api/`.
- No end-to-end tests for the conversion flow through the web UI.
- No test framework (Jest, Vitest, Playwright) is configured in `apps/web/package.json`.

**Recommended fix:** Add Vitest (or Jest) for unit/integration testing of API routes and components. Consider Playwright for E2E tests covering the conversion wizard flow.

---

### 9. Docker Compose Missing Health Checks

No `healthcheck` is defined for any service (web, worker, db, redis). The `depends_on` directive without `condition: service_healthy` means services may start before their dependencies are actually ready.

**Recommended fix:** Add `healthcheck` configurations for each service and use `depends_on` with `condition: service_healthy`.

---

### 10. Large Functions Needing Decomposition

| Location | Function | Lines | Issue |
|----------|----------|-------|-------|
| `src/converters/training_converter.py:166-219` | `_calculate_demographics` | ~53 | Nested helper functions and multiple counting patterns |
| `src/xml_validator.py:25-68` | `validate_against_xsd` | ~43 | Mixes file path validation with XSD validation logic |

**Recommended fix:** Extract sub-functions for demographic counting patterns. Separate file loading/path validation from schema validation logic.

---

## LOW Priority

### 11. Dead and Incomplete Code

| Location | Issue |
|----------|-------|
| `src/config.py:71-75` | `FIELD_MAPPING` dict kept as "reference" but unused by any code |
| `src/config.py:129+` | `TRAINING_TOPIC_MAPPINGS` contains placeholder comments (`# ... (and so on)`) |
| `src/fix_sba_xml.py:137-151` | Contradictory comments about `add_missing` behavior ("set to True" then "should be False") |

**Recommended fix:** Remove unused `FIELD_MAPPING`. Complete or remove the placeholder mappings. Resolve the contradictory comments and finalize the `add_missing` behavior.

---

### 12. Inconsistent Naming Conventions

- `src/data_cleaning.py` mixes underscore-prefixed private functions (`_resolve_state_name`, `_case_insensitive_lookup`) with public functions that serve similar internal roles (`standardize_state_name`).
- Error message formatting varies across modules (some include full context, others are minimal).
- Config access in `src/converters/counseling_converter.py` alternates between `self.config` and `self.general_config` with no clear pattern.

**Recommended fix:** Establish a naming convention: prefix truly internal helpers with `_`, keep public API functions without. Standardize error message format. Use a consistent config access pattern.

---

### 13. Missing Python Linting and Formatting

- No `ruff`, `flake8`, or `black` is configured for the Python codebase.
- No `pyproject.toml` or equivalent configuration file for Python tooling.
- The CI pipeline (`.github/workflows/ci.yml`) runs `pytest` but has no Python linting step.

**Recommended fix:** Add `ruff` as the Python linter/formatter. Create a `pyproject.toml` with ruff configuration. Add a lint step to the CI pipeline.
