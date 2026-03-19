"""
Data validation module for CSV to XML conversion.
This module contains functions for validating data before XML conversion.
"""

from .data_cleaning import (
    format_date, validate_counseling_date,
    clean_percentage, standardize_country_code, standardize_state_name
)
from .config import ValidationCategory as VC, CounselingConfig, TrainingConfig

# =============================================================================
# COUNSELING-SPECIFIC VALIDATION
# =============================================================================

def validate_counseling_record(row, row_index, validator):
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

def validate_training_record(row, row_index, validator):
    """
    Validates a single record for the Training converter.
    For training data, the main validation is ensuring the event ID exists.
    """
    event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
    record_id = row.get(event_id_col)

    if not record_id:
        record_id = f"Row_{row_index}"
        validator.add_issue(record_id, "error", VC.MISSING_REQUIRED, event_id_col, "Missing required Class/Event ID.")
        return False

    validator.set_current_record_id(record_id)
    return True

# =============================================================================
# ANALYSIS FUNCTIONS (for --analyze-only mode)
# =============================================================================

def analyze_counseling_csv(csv_rows):
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

def analyze_training_csv(csv_rows):
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
