import unittest
from unittest.mock import MagicMock
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_validation import (
    validate_counseling_record,
    validate_training_record,
    analyze_counseling_csv,
    analyze_training_csv
)
from src.config import ValidationCategory as VC, CounselingConfig, TrainingConfig

# Use a date within the current fiscal year for valid test cases
_VALID_DATE = CounselingConfig.MIN_COUNSELING_DATE.replace("-01", "-15")

class TestDataValidation(unittest.TestCase):

    def setUp(self):
        self.validator = MagicMock()

    def test_validate_counseling_record_success(self):
        row = {
            CounselingConfig.REQUIRED_FIELDS[0]: "C-123",
            'Last Name': 'Doe',
            'First Name': 'John',
            'Date': _VALID_DATE
        }

        result = validate_counseling_record(row, 1, self.validator)

        self.assertTrue(result)
        self.validator.set_current_record_id.assert_called_once_with("C-123")
        self.validator.add_issue.assert_not_called()

    def test_validate_counseling_record_missing_id(self):
        row = {
            'Last Name': 'Doe',
            'First Name': 'John',
            'Date': _VALID_DATE
        }

        result = validate_counseling_record(row, 2, self.validator)

        self.assertFalse(result)
        self.validator.set_current_record_id.assert_not_called()
        self.validator.add_issue.assert_called_once_with(
            "Row_2", "error", VC.MISSING_REQUIRED, CounselingConfig.REQUIRED_FIELDS[0], "Missing required Contact ID."
        )

    def test_validate_counseling_record_missing_last_name(self):
        row = {
            CounselingConfig.REQUIRED_FIELDS[0]: "C-124",
            'First Name': 'John',
            'Date': _VALID_DATE
        }

        result = validate_counseling_record(row, 3, self.validator)

        self.assertTrue(result)
        self.validator.set_current_record_id.assert_called_once_with("C-124")
        self.validator.add_issue.assert_called_once_with(
            "C-124", "warning", VC.MISSING_FIELD, "Last Name", "Missing Last Name."
        )

    def test_validate_counseling_record_invalid_date_format(self):
        row = {
            CounselingConfig.REQUIRED_FIELDS[0]: "C-125",
            'Last Name': 'Doe',
            'Date': 'invalid-date'
        }

        result = validate_counseling_record(row, 4, self.validator)

        self.assertTrue(result)
        self.validator.set_current_record_id.assert_called_once_with("C-125")
        self.validator.add_issue.assert_called_once_with(
            "C-125", "warning", VC.INVALID_FORMAT, "Date Counseled", "Invalid date format: invalid-date"
        )

    def test_validate_counseling_record_early_date(self):
        row = {
            CounselingConfig.REQUIRED_FIELDS[0]: "C-126",
            'Last Name': 'Doe',
            'Date': '2020-01-01'
        }

        result = validate_counseling_record(row, 5, self.validator)

        self.assertTrue(result)
        self.validator.set_current_record_id.assert_called_once_with("C-126")
        self.validator.add_issue.assert_called_once_with(
            "C-126", "warning", VC.INVALID_DATE, "Date Counseled", f"Date 2020-01-01 is before minimum of {CounselingConfig.MIN_COUNSELING_DATE}"
        )

    def test_validate_training_record_success(self):
        event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
        row = {
            event_id_col: "T-999",
            'Other': 'Data'
        }

        result = validate_training_record(row, 1, self.validator)

        self.assertTrue(result)
        self.validator.set_current_record_id.assert_called_once_with("T-999")
        self.validator.add_issue.assert_not_called()

    def test_validate_training_record_missing_id(self):
        event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
        row = {
            'Other': 'Data'
        }

        result = validate_training_record(row, 2, self.validator)

        self.assertFalse(result)
        self.validator.set_current_record_id.assert_not_called()
        self.validator.add_issue.assert_called_once_with(
            "Row_2", "error", VC.MISSING_REQUIRED, event_id_col, "Missing required Class/Event ID."
        )

    def test_analyze_counseling_csv(self):
        rows = [
            {CounselingConfig.REQUIRED_FIELDS[0]: "C-1", 'Last Name': 'Doe', 'First Name': 'John', 'Date': _VALID_DATE},
            {'Last Name': 'Smith', 'First Name': 'Alice'}, # missing id
            {CounselingConfig.REQUIRED_FIELDS[0]: "C-3", 'First Name': 'Bob'}, # missing last name
            {CounselingConfig.REQUIRED_FIELDS[0]: "C-4", 'Last Name': 'Brown', 'Date': 'invalid'}, # invalid date, missing first name
        ]

        analysis = analyze_counseling_csv(rows)

        self.assertEqual(analysis['row_count'], 4)
        self.assertEqual(analysis['missing_contact_id'], 1)
        self.assertEqual(analysis['missing_names'], 2)
        self.assertEqual(analysis['invalid_dates'], 1)

    def test_analyze_training_csv(self):
        event_id_col = TrainingConfig.COLUMN_MAPPING['event_id']
        rows = [
            {event_id_col: "T-1"},
            {}, # missing event id
            {event_id_col: "T-3"}
        ]

        analysis = analyze_training_csv(rows)

        self.assertEqual(analysis['row_count'], 3)
        self.assertEqual(analysis['missing_event_id'], 1)

if __name__ == '__main__':
    unittest.main()
