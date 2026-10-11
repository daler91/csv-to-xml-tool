"""The results page's before/after cleaning diff (apps/worker diff_service).

The second pass (2.6, 2.8) found it hid every value a cleaner dropped -- an
unreadable phone looked untouched -- and left out the enumeration mappers
entirely, while converters.md promised "every change is recorded".
"""

import csv
import os
import tempfile
import unittest

import pytest

pytest.importorskip("fastapi")

from app.services.diff_service import generate_cleaning_diff  # noqa: E402


def _diff(rows, converter_type="counseling"):
    fieldnames = list(dict.fromkeys(k for row in rows for k in row))
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        path = f.name
    try:
        return {(d["field"], d["original"]): d for d in generate_cleaning_diff(path, converter_type)}
    finally:
        os.unlink(path)


class TestCleaningDiff(unittest.TestCase):

    def test_a_dropped_value_appears_with_an_empty_cleaned_value(self):
        diffs = _diff([{"Contact ID": "C-1", "Contact: Phone": "555-0101", "Gender": "Non-binary"}])
        self.assertEqual(diffs[("Contact: Phone", "555-0101")]["cleaned"], "")
        self.assertEqual(diffs[("Gender", "Non-binary")]["cleaned"], "")

    def test_enumeration_mappers_are_in_the_diff(self):
        diffs = _diff([{
            "Contact ID": "C-1",
            "Ethnicity:": "Not Hispanic or Latino",
            "Veteran Status": "No",
            "Disability": "N",
            "Branch Of Service": "USMC",
            "Race": "Caucasian; Black",
            "Export Countries": "UK; Narnia",
        }])
        self.assertEqual(diffs[("Ethnicity:", "Not Hispanic or Latino")]["cleaned"], "Non Hispanic or Latino")
        self.assertEqual(diffs[("Veteran Status", "No")]["cleaned"], "No military service")
        self.assertEqual(diffs[("Disability", "N")]["cleaned"], "No")
        self.assertEqual(diffs[("Branch Of Service", "USMC")]["cleaned"], "Marine Corps")
        self.assertEqual(diffs[("Race", "Caucasian; Black")]["cleaned"], "White; Black or African American")
        # Narnia is not on SBA's list: dropped from the XML, so from the "after" too.
        self.assertEqual(diffs[("Export Countries", "UK; Narnia")]["cleaned"], "United Kingdom")

    def test_values_the_converter_leaves_alone_are_not_reported(self):
        # A Salesforce trailing ';' on an already-valid multi-select is not a change.
        diffs = _diff([{"Contact ID": "C-1", "Race": "Black or African American; White;",
                        "Ethnicity:": "Hispanic or Latino", "Veteran Status": "Veteran"}])
        self.assertEqual([key for key in diffs if key[0] in ("Race", "Ethnicity:", "Veteran Status")], [])

    def test_counselor_notes_scrubbing_is_shown(self):
        # Whitespace is collapsed; a bracketed label such as "[Q3]:" is the
        # counselor's own text and is kept (third pass D.9).
        diffs = _diff([{"Contact ID": "C-1", "Comments": "[Q3]: Met   with client"}])
        self.assertEqual(diffs[("Comments", "[Q3]: Met   with client")]["cleaned"], "[Q3]: Met with client")

    def test_training_client_columns_use_the_forms_own_names(self):
        diffs = _diff([{"Contact ID": "C-1", "Military Status": "Not Veteran", "Race": "Caucasian"}],
                      "training-client")
        self.assertEqual(diffs[("Military Status", "Not Veteran")]["cleaned"], "No military service")
        self.assertEqual(diffs[("Race", "Caucasian")]["cleaned"], "White")
