import unittest
import os
import shutil
import tempfile
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

    def test_generate_html_report_large_issue_set(self):
        # QUAL-4: the issue/category tables are now assembled with "".join()
        # instead of repeated `+=` (which was O(n^2)). Build a large set and
        # assert every row is rendered exactly once, so the join path produces
        # complete, correct output at scale.
        n = 2000
        for i in range(n):
            severity = "error" if i % 2 == 0 else "warning"
            self.tracker.record_processed(success=(severity != "error"))
            self.tracker.add_issue(
                record_id=f"REC-{i:05d}",
                severity=severity,
                category=f"cat_{i % 7}",
                field_name=f"Field {i % 5}",
                message=f"Issue number {i}",
            )

        report_path = self.tracker.generate_html_report(output_dir=self.test_dir)
        with open(report_path, 'r') as f:
            content = f.read()

        # First and last record IDs both present (nothing dropped by the join).
        self.assertIn("REC-00000", content)
        self.assertIn(f"REC-{n - 1:05d}", content)
        # Each issue is rendered exactly once -> n detailed-issue rows total.
        rendered_rows = (
            content.count('<td class="error">ERROR</td>')
            + content.count('<td class="warning">WARNING</td>')
        )
        self.assertEqual(rendered_rows, n)
        # Both category tables are emitted.
        self.assertIn("Errors by Category", content)
        self.assertIn("Warnings by Category", content)

    def test_add_issue_event_id_defaults_to_empty(self):
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg")
        self.assertEqual(self.tracker.issues[0]['event_id'], "")

    def test_add_issue_event_id_explicit_kwarg(self):
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg", event_id="EVT-1")
        self.assertEqual(self.tracker.issues[0]['event_id'], "EVT-1")

    def test_add_issue_event_id_from_context(self):
        self.tracker.set_current_event_id("EVT-2")
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg")
        self.assertEqual(self.tracker.issues[0]['event_id'], "EVT-2")

    def test_add_issue_explicit_event_id_overrides_context(self):
        self.tracker.set_current_event_id("EVT-CTX")
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg", event_id="EVT-EXPLICIT")
        self.assertEqual(self.tracker.issues[0]['event_id'], "EVT-EXPLICIT")

    def test_add_issue_explicit_empty_event_id_suppresses_context(self):
        # Explicit '' means "no event id" and must not fall back to context.
        self.tracker.set_current_event_id("EVT-CTX")
        self.tracker.add_issue("file", "error", "cat", "Field", "msg", event_id="")
        self.assertEqual(self.tracker.issues[0]['event_id'], "")

    def test_set_current_event_id_clears_and_strips(self):
        self.tracker.set_current_event_id("  EVT-3  ")
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg")
        self.assertEqual(self.tracker.issues[0]['event_id'], "EVT-3")

        self.tracker.set_current_event_id(None)
        self.tracker.add_issue("REC-2", "error", "cat", "Field", "msg")
        self.assertEqual(self.tracker.issues[1]['event_id'], "")

        self.tracker.set_current_event_id("EVT-4")
        self.tracker.set_current_event_id("")
        self.tracker.add_issue("REC-3", "error", "cat", "Field", "msg")
        self.assertEqual(self.tracker.issues[2]['event_id'], "")

    def test_save_issues_to_csv_includes_event_id(self):
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg", event_id="EVT-CSV")
        self.tracker.add_issue("REC-2", "warning", "cat", "Field", "msg2")

        import csv as csv_mod
        csv_path = self.tracker.save_issues_to_csv(output_dir=self.test_dir)
        with open(csv_path, newline='') as f:
            reader = csv_mod.DictReader(f)
            self.assertEqual(
                reader.fieldnames,
                ['record_id', 'event_id', 'severity', 'category', 'field_name', 'message', 'timestamp'])
            rows = list(reader)
        self.assertEqual(rows[0]['event_id'], "EVT-CSV")
        self.assertEqual(rows[1]['event_id'], "")

    def test_generate_html_report_includes_event_id(self):
        self.tracker.record_processed(success=True)
        self.tracker.add_issue("REC-1", "error", "cat", "Field", "msg", event_id="EVT-HTML")

        report_path = self.tracker.generate_html_report(output_dir=self.test_dir)
        with open(report_path, 'r') as f:
            content = f.read()

        self.assertIn("<th>Event ID</th>", content)
        self.assertIn("<td>EVT-HTML</td>", content)

if __name__ == '__main__':
    unittest.main()
