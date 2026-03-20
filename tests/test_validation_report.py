import unittest
import os
import shutil
import tempfile
from datetime import datetime
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.validation_report import ValidationTracker

class TestValidationTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = ValidationTracker()
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_generate_html_report_creates_file_with_content(self):
        # Setup tracker with some data
        self.tracker.record_processed(success=True)
        self.tracker.record_processed(success=False)
        self.tracker.add_issue(
            record_id="REC-001",
            severity="error",
            category="missing_data",
            field_name="Last Name",
            message="Last Name is required"
        )
        self.tracker.add_issue(
            record_id="REC-002",
            severity="warning",
            category="invalid_format",
            field_name="Date",
            message="Invalid date format"
        )

        # Generate report
        report_path = self.tracker.generate_html_report(output_dir=self.test_dir)

        # Assert file exists
        self.assertTrue(os.path.exists(report_path))
        self.assertTrue(report_path.endswith(".html"))

        # Assert content
        with open(report_path, 'r') as f:
            content = f.read()

        # Check for expected elements
        self.assertIn("<title>CSV to XML Conversion Validation Report</title>", content)
        self.assertIn("Total records processed: <strong>2</strong>", content)
        self.assertIn("Successfully processed: <strong class=\"success\">1 (50.0%)</strong>", content)
        self.assertIn("Failed records: <strong class=\"error\">1</strong>", content)

        # Check for issues
        self.assertIn("REC-001", content)
        self.assertIn("Last Name is required", content)
        self.assertIn("REC-002", content)
        self.assertIn("Invalid date format", content)

    def test_generate_html_report_creates_directory(self):
        # Define a nested directory that doesn't exist yet
        nested_dir = os.path.join(self.test_dir, "new", "report", "dir")

        self.assertFalse(os.path.exists(nested_dir))

        # Generate report
        report_path = self.tracker.generate_html_report(output_dir=nested_dir)

        # Assert directory was created and file exists
        self.assertTrue(os.path.exists(nested_dir))
        self.assertTrue(os.path.exists(report_path))

    def test_generate_html_report_empty_tracker(self):
        # Generate report with no issues or records
        report_path = self.tracker.generate_html_report(output_dir=self.test_dir)

        self.assertTrue(os.path.exists(report_path))

        with open(report_path, 'r') as f:
            content = f.read()

        # Should still contain basic structure and 0 counts
        self.assertIn("Total records processed: <strong>0</strong>", content)
        self.assertIn("Successfully processed: <strong class=\"success\">0 (0.0%)</strong>", content)
        self.assertIn("Failed records: <strong class=\"error\">0</strong>", content)

if __name__ == '__main__':
    unittest.main()
