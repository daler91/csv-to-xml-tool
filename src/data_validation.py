from __future__ import annotations

"""
Data validation module for CSV to XML conversion.
This module contains functions for validating data before XML conversion.
"""

import re

from datetime import datetime

from typing import TYPE_CHECKING

from .data_cleaning import (
    clean_phone_number, format_date, is_ambiguous_date, is_empty,
    split_multi_value, standardize_country_code, standardize_state_name
)
from .config import (
    COUNSELING_FABRICATION_DEFAULTS,
    ValidationCategory as VC, CounselingConfig, TrainingConfig, TrainingClientConfig,
)

if TYPE_CHECKING:
    from .validation_report import ValidationTracker


def validate_counseling_date(date_str: str) -> bool:
    """
    Validates that the counseling date is not before MIN_COUNSELING_DATE.

    Args:
        date_str: A date string in YYYY-MM-DD format

    Returns:
        Boolean indicating if the date is valid
    """
    if not date_str:
        return True

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        min_date = datetime.strptime(CounselingConfig.MIN_COUNSELING_DATE, "%Y-%m-%d")
        return date_obj >= min_date
    except ValueError:
        return False

# =============================================================================
# COUNSELING-SPECIFIC VALIDATION
# =============================================================================

def validate_counseling_record(row: dict[str, str], row_index: int, validator: ValidationTracker) -> bool:
    """
    Validates a single record for the Counseling converter.
    """
    record_id = row.get(CounselingConfig.REQUIRED_FIELDS[0])
    if not record_id:
        record_id = f"Row_{row_index}"
        validator.add_issue(record_id, "error", VC.MISSING_REQUIRED, CounselingConfig.REQUIRED_FIELDS[0], "Missing required Contact ID.")
        return False # Cannot validate further without an ID

    validator.set_current_record_id(record_id)

    # Example validations (can be expanded)
    if not row.get('Last Name'):
        validator.add_issue(record_id, "warning", VC.MISSING_FIELD, "Last Name", "Missing Last Name.")

    counseling_date = row.get('Date', '')
    if counseling_date:
        formatted_date = format_date(counseling_date)
        if not formatted_date:
            validator.add_issue(record_id, "warning", VC.INVALID_FORMAT, "Date Counseled", f"Invalid date format: {counseling_date}")
        elif not validate_counseling_date(formatted_date):
            validator.add_issue(record_id, "warning", VC.INVALID_DATE, "Date Counseled", f"Date {formatted_date} is before minimum of {CounselingConfig.MIN_COUNSELING_DATE}")

    return True # Return simple True/False, issues are tracked in the validator

# =============================================================================
# TRAINING-SPECIFIC VALIDATION
# =============================================================================

def validate_training_record(row: dict[str, str], row_index: int, validator: ValidationTracker) -> bool:
    """
    Validates a single record for the Training converter.
    For training data, the main validation is ensuring the event ID exists.
    """
    event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
    record_id = row.get(event_id_col)

    # is_empty (not a bare falsiness test): the training CSV is read with
    # dtype=str, so a blank cell arrives as float('nan'), which is *truthy*.
    # A bare `if not record_id` let those rows pass validation and they were
    # then silently dropped by groupby(), which discards NaN keys -- the row
    # vanished from the XML with no issue recorded anywhere.
    if is_empty(record_id):
        record_id = f"Row_{row_index}"
        validator.add_issue(record_id, "error", VC.MISSING_REQUIRED, event_id_col, "Missing required Class/Event ID.")
        return False

    validator.set_current_record_id(record_id)
    return True

# =============================================================================
# ANALYSIS FUNCTIONS (for --analyze-only mode)
# =============================================================================

def analyze_counseling_csv(csv_rows: list[dict[str, str]]) -> dict[str, int]:
    """
    Analyzes CSV data from a counseling report for potential issues.
    """
    analysis = {
        'row_count': len(csv_rows),
        'missing_contact_id': 0,
        'missing_names': 0,
        'invalid_dates': 0,
    }
    for row in csv_rows:
        if not row.get(CounselingConfig.REQUIRED_FIELDS[0]):
            analysis['missing_contact_id'] += 1
        if not row.get('Last Name') or not row.get('First Name'):
            analysis['missing_names'] += 1
        if row.get('Date') and not format_date(row.get('Date')):
            analysis['invalid_dates'] += 1
    return analysis

def analyze_training_csv(csv_rows: list[dict[str, str]]) -> dict[str, int]:
    """
    Analyzes CSV data from a training report for potential issues.
    """
    analysis = {
        'row_count': len(csv_rows),
        'missing_event_id': 0,
    }
    event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
    for row in csv_rows:
        if not row.get(event_id_col):
            analysis['missing_event_id'] += 1
    return analysis

# =============================================================================
# DATA-QUALITY REPORT (feature 2.5, worker /preview "data_quality" payload)
# =============================================================================
# Each check dict follows the web/worker contract:
#   {"key", "label", "count", "severity", "detail", "column"}
# severity "error"  -> the affected rows are skipped or fail conversion;
# severity "warning" -> the rows convert, but degraded (defaulted/flagged).
# Only checks with count > 0 are returned.

_SKIPPED_ROW_DETAIL = (
    "These rows are skipped during conversion and will not appear in the "
    "federal XML."
)


def _quality_check(key: str, label: str, count: int, severity: str, detail: str,
                   column: str | None = None) -> dict:
    return {
        "key": key,
        "label": label,
        "count": count,
        "severity": severity,
        "detail": detail,
        "column": column,
    }


def _column_slug(column: str) -> str:
    """Stable machine key fragment for a CSV column name."""
    return re.sub(r'[^a-z0-9]+', '_', column.lower()).strip('_')


def _counseling_quality_checks(headers: list[str], csv_rows: list[dict[str, str]],
                               fabrication_defaults: dict[str, str],
                               source_columns: dict[str, str] | None = None) -> list[dict]:
    """Counseling-style checks over rows keyed by the counseling column names.

    ``source_columns`` maps the counseling column names this pass reads back to
    the caller's own CSV headers (the training-client form renames its columns
    before analysis); checks report the caller's names so the user recognizes
    them in their file.
    """
    def src(col: str) -> str:
        return source_columns.get(col, col) if source_columns else col

    contact_col = CounselingConfig.REQUIRED_FIELDS[0]
    header_set = set(headers)
    present_fab_cols = [c for c in fabrication_defaults if c in header_set]
    fab_blanks = dict.fromkeys(present_fab_cols, 0)
    missing_contact = missing_last = invalid_dates = ambiguous_dates = 0

    for row in csv_rows:
        if is_empty(row.get(contact_col)):
            # Mirrors validate_counseling_record: the converter skips the whole
            # row, so nothing else in it ships in the XML.
            missing_contact += 1
            continue
        if is_empty(row.get('Last Name')):
            missing_last += 1
        date_raw = row.get('Date', '')
        if not is_empty(date_raw) and not format_date(date_raw):
            invalid_dates += 1
        if is_ambiguous_date(date_raw):
            ambiguous_dates += 1
        for col in present_fab_cols:
            if is_empty(row.get(col)):
                fab_blanks[col] += 1

    checks = []
    if missing_contact:
        checks.append(_quality_check(
            "missing_contact_id", f"Rows missing '{src(contact_col)}'",
            missing_contact, "error", _SKIPPED_ROW_DETAIL, src(contact_col)))
    if missing_last:
        checks.append(_quality_check(
            "missing_last_name", f"Rows missing '{src('Last Name')}'",
            missing_last, "warning",
            "These clients are recorded without a last name in the federal XML.",
            src('Last Name')))
    if invalid_dates:
        # The converter omits DateCounseled (optional in the XSD) when the date
        # cannot be parsed, so the row converts but loses its session date.
        checks.append(_quality_check(
            "invalid_date", f"Rows with an unreadable '{src('Date')}'",
            invalid_dates, "warning",
            "The date could not be read, so the counseling session date is "
            "left out of the federal XML.",
            src('Date')))
    if ambiguous_dates:
        checks.append(_quality_check(
            "ambiguous_date", f"Rows with an ambiguous '{src('Date')}'",
            ambiguous_dates, "warning",
            "These dates read as either MM/DD or DD/MM; they are parsed "
            "month-first in the federal XML.",
            src('Date')))
    for col in present_fab_cols:
        if fab_blanks[col]:
            checks.append(_quality_check(
                f"blank_{_column_slug(src(col))}", f"Blank '{src(col)}' cells",
                fab_blanks[col], "warning",
                f"Blank cells will be recorded as '{fabrication_defaults[col]}' "
                f"in the federal XML.",
                src(col)))
    return checks


def analyze_counseling_quality(headers: list[str], csv_rows: list[dict[str, str]]) -> list[dict]:
    """Data-quality checks for a counseling (Form 641) CSV."""
    return _counseling_quality_checks(headers, csv_rows, COUNSELING_FABRICATION_DEFAULTS)


def analyze_training_quality(headers: list[str], csv_rows: list[dict[str, str]]) -> list[dict]:
    """Data-quality checks for a management training (Form 888) CSV."""
    event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
    date_col = TrainingConfig.COLUMN_MAPPING['start_date']
    missing_event = invalid_dates = 0
    for row in csv_rows:
        if is_empty(row.get(event_id_col)):
            # Mirrors validate_training_record: the row is dropped before the
            # per-event aggregation.
            missing_event += 1
            continue
        date_raw = row.get(date_col, '')
        if not is_empty(date_raw) and not format_date(date_raw):
            invalid_dates += 1

    checks = []
    if missing_event:
        checks.append(_quality_check(
            "missing_event_id", f"Rows missing '{event_id_col}'",
            missing_event, "error", _SKIPPED_ROW_DETAIL, event_id_col))
    if invalid_dates:
        # The training converter falls back to DEFAULT_START_DATE, so the event
        # converts but with a fabricated date.
        checks.append(_quality_check(
            "invalid_start_date", f"Rows with an unreadable '{date_col}'",
            invalid_dates, "warning",
            f"The date could not be read; these events are recorded with the "
            f"default date {TrainingConfig.DEFAULT_START_DATE} in the federal XML.",
            date_col))
    return checks


def analyze_training_client_quality(headers: list[str], csv_rows: list[dict[str, str]]) -> list[dict]:
    """Data-quality checks for a training-client (Form 641) CSV.

    The converter renames the training-client columns to counseling names
    before building the XML, so the same rename is applied here and the
    counseling-style checks run on the mapped rows. Checks still report the
    user's own column names (via the reverse mapping). Fabrication checks only
    cover fabrication-risk columns the training-client form itself collects —
    its injected ``TrainingClientConfig.DEFAULTS`` are intentional.
    """
    mapping = TrainingClientConfig.COLUMN_MAPPING
    reverse_mapping = {counseling: tc for tc, counseling in mapping.items()}
    mapped_headers = [mapping.get(h, h) for h in headers]
    mapped_rows = [{mapping.get(k, k): v for k, v in row.items()} for row in csv_rows]

    event_id_target = mapping['Class/Event ID']  # 'Activity ID' after the rename
    missing_event = sum(1 for row in mapped_rows if is_empty(row.get(event_id_target)))

    checks = []
    if missing_event:
        checks.append(_quality_check(
            "missing_class_event_id", "Rows missing 'Class/Event ID'",
            missing_event, "error",
            "These rows cannot be tied to a training event; the session "
            "identifier is left blank in the federal XML.",
            "Class/Event ID"))

    fabrication_defaults = {
        col: default for col, default in COUNSELING_FABRICATION_DEFAULTS.items()
        if col not in TrainingClientConfig.DEFAULTS
    }
    checks.extend(_counseling_quality_checks(
        mapped_headers, mapped_rows, fabrication_defaults, reverse_mapping))

    # Mirrors TrainingClientConverter._resolve_in_business: an in-business 'Yes'
    # without the conditionally-required business details (which the training
    # form doesn't collect) is recorded as 'No' at conversion. Only the exact
    # string 'Yes' counts — anything else already defaults to 'No'.
    contact_col = CounselingConfig.REQUIRED_FIELDS[0]
    in_business_downgraded = 0
    for row in mapped_rows:
        if is_empty(row.get(contact_col)):
            continue  # row is skipped whole at conversion; never reaches the downgrade
        if (row.get('Currently In Business?') or '').strip() != 'Yes':
            continue
        has_legal_entity = bool(
            split_multi_value(row.get('Legal Entity of Business', ''))
            or (row.get('Other legal entity (specify)') or '').strip())
        has_counseling_seeking = bool(
            split_multi_value(row.get('Nature of the Counseling Seeking?', ''))
            # The converter records the Training Topic as the counseling sought,
            # so a topic satisfies the counseling-seeking requirement too.
            or (row.get('Training Topic') or '').strip())
        if not (has_legal_entity and has_counseling_seeking):
            in_business_downgraded += 1

    if in_business_downgraded:
        in_business_src = reverse_mapping.get('Currently In Business?', 'Currently In Business?')
        checks.append(_quality_check(
            "in_business_downgraded",
            f"Rows with '{in_business_src}' = 'Yes' but no business details",
            in_business_downgraded, "warning",
            "The training form doesn't collect the business details (legal entity, "
            "counseling sought) required for in-business clients, so these clients "
            "are recorded as not in business in the federal XML.",
            in_business_src))
    return checks


def analyze_data_quality(headers: list[str], csv_rows: list[dict[str, str]],
                         converter_type: str) -> dict:
    """Build the /preview ``data_quality`` payload for a parsed CSV.

    Single O(n) pass over the full row set (the preview request carries the
    whole file). Returns ``{"total_rows": <int>, "checks": [...]}`` with only
    the checks whose count is > 0.
    """
    if converter_type == "counseling":
        checks = analyze_counseling_quality(headers, csv_rows)
    elif converter_type == "training":
        checks = analyze_training_quality(headers, csv_rows)
    elif converter_type == "training-client":
        checks = analyze_training_client_quality(headers, csv_rows)
    else:
        checks = []
    return {"total_rows": len(csv_rows), "checks": checks}
