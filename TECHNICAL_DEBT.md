# Technical Debt Register

This document catalogs known technical debt across the CSV-to-XML tool codebase, organized by priority. Each item includes affected files, line references, and a recommended fix.

Items marked with **[RESOLVED]** have been addressed.

---

## HIGH Priority

### 1. Weak Type Annotations (Python) **[RESOLVED]**

Replaced `object` with proper types (`logging.Logger`, `ValidationTracker`, `Any`) in `base_converter.py`, `data_validation.py`, and `data_cleaning.py`. Added `TYPE_CHECKING` guards to avoid circular imports.

---

### 2. Overly Broad Exception Handling **[RESOLVED]**

Replaced generic `except Exception` blocks with specific exception types (`OSError`, `csv.Error`, `pd.errors.ParserError`, `etree.XMLSyntaxError`, `ValueError`, `KeyError`, etc.) across all converters, `xml_validator.py`, and `fix_sba_xml.py`. Updated corresponding tests.

---

### 3. Missing Input Validation **[RESOLVED]**

- Added `try/except OSError` around file writes in `validation_report.py` (CSV and HTML report generation).
- Added `None` guard for `.text` access on XML elements in `xml_validator.py`.

**Remaining:** CSV column existence pre-checks in converters could still be added for more robust early failure.

---

### 4. Hardcoded Credentials in docker-compose.yml **[RESOLVED]**

Moved all secrets to an `env_file` reference in `docker-compose.yml`. Created `.env.example` with placeholder values. Added `.env` to `.gitignore`.

---

### 5. Beta Dependency in Production

`apps/web/package.json` depends on `next-auth@5.0.0-beta.30`, a pre-release version. Beta APIs may change without notice, and security patches may lag behind stable releases.

**Status:** Not yet resolved. Requires monitoring for a stable release.

---

### 6. Path Traversal Risk in File Download **[RESOLVED]**

Added `realpath()` validation in `apps/web/src/app/api/jobs/[jobId]/download/route.ts` to ensure the file path stays within `DATA_DIR` before reading.

---

### 7. Unpinned Python Dependencies **[RESOLVED]**

Added version range pins to `requirements.txt` (e.g., `pandas>=2.2.0,<3`).

---

### 8. CI Build Failure Silently Ignored **[RESOLVED]**

Removed `continue-on-error: true` from the web build step in `.github/workflows/ci.yml`.

---

## MEDIUM Priority

### 9. Code Duplication **[RESOLVED]**

- Extracted `is_empty(value)` helper in `data_cleaning.py` to replace 9 repeated empty/NaN guard patterns.
- Moved `client_intake_order` from `xml_validator.py` to `CounselingConfig.CLIENT_INTAKE_ELEMENT_ORDER` in `config.py`.
- Consolidated date format lists to a single `DATE_INPUT_FORMATS` in `config.py`.

**Remaining:** `row.get('Field', '').strip()` pattern in `counseling_converter.py` (14+ occurrences) could still benefit from a helper, but this is lower-impact.

---

### 10. Magic Numbers and Hardcoded Values **[RESOLVED]**

Added named constants in `data_cleaning.py` (`PHONE_NUMBER_DIGITS`, `PHONE_WITH_COUNTRY_CODE_DIGITS`, `PERCENTAGE_MIN`, `PERCENTAGE_MAX`) and `config.py` (`FISCAL_YEAR_START_MONTH`).

---

### 11. No Web Application Tests

- No `apps/web/__tests__/` directory exists -- zero frontend test coverage.
- No integration tests for API routes in `apps/web/src/app/api/`.
- No end-to-end tests for the conversion flow through the web UI.
- No test framework (Jest, Vitest, Playwright) is configured in `apps/web/package.json`.

**Status:** Not yet resolved. Requires adding a test framework and writing tests.

---

### 12. Docker Compose Missing Health Checks **[RESOLVED]**

Added `healthcheck` configurations for db (pg_isready), redis (redis-cli ping), and worker (curl /health). Updated `depends_on` with `condition: service_healthy`.

---

### 13. Large Functions Needing Decomposition **[RESOLVED]**

- Extracted `_resolve_column` and `_count_matches` from nested helpers in `_calculate_demographics` to class methods on `TrainingConverter`.
- Extracted `_validate_file_paths` from `validate_against_xsd` in `xml_validator.py`.

---

### 14. Weak Password Validation **[RESOLVED]**

Added `validatePasswordComplexity()` in `apps/web/src/app/api/auth/signup/route.ts` requiring uppercase, digit, and special character.

---

### 15. Rate Limiting Based on Spoofable Header **[RESOLVED]**

Extracted `getClientIdentifier()` helper that takes only the first IP from `x-forwarded-for` and validates it, instead of blindly trusting the full header.

---

### 16. Memory Risk with Large CSV Files

Both converters load entire files into memory. With a 50MB upload limit, this could consume significant memory.

**Status:** Not yet resolved. Would require significant architectural changes to implement streaming.

---

## LOW Priority

### 17. Dead and Incomplete Code **[RESOLVED]**

- Removed unused `FIELD_MAPPING` from `CounselingConfig`.
- Cleaned up placeholder comments in `TRAINING_TOPIC_MAPPINGS` and `PROGRAM_FORMAT_MAPPINGS`.
- Resolved contradictory comments in `fix_sba_xml.py` about `add_missing` behavior.
- Deleted orphaned `update_validation.py` script.

---

### 18. Inconsistent Naming Conventions

- `src/data_cleaning.py` mixes underscore-prefixed private functions with public functions that serve similar internal roles.
- Error message formatting varies across modules.
- Config access in `src/converters/counseling_converter.py` alternates between `self.config` and `self.general_config`.

**Status:** Partially addressed through code cleanup. Full standardization deferred as low priority.

---

### 19. Missing Python Linting and Formatting

- No `ruff`, `flake8`, or `black` is configured for the Python codebase.
- No `pyproject.toml` or equivalent configuration file for Python tooling.
- The CI pipeline runs `pytest` but has no Python linting step.

**Status:** Not yet resolved. Adding `ruff` deferred to avoid scope creep.
