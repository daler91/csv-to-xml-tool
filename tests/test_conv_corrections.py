"""Tests for the CONV-2..CONV-7 conversion-correctness fixes.

Covers the pure data_cleaning helpers (CONV-2/3/4/5/7) and the empty-CSV failure
(CONV-6) at the converter level. Converter-level *warning* behavior (CONV-3/7) and
header-whitespace tolerance (CONV-2) live in the existing converter test files;
the worker 422 mapping (CONV-6) lives in test_worker_arch4_routes.py.

These import only src/ (no worker deps), so they run in CI under the base
requirements.
"""

import csv
import os
import tempfile
import unittest

from src import data_cleaning as dc
from src.converters.base_converter import EmptyCSVError
from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker


class TestConvDataCleaning(unittest.TestCase):
    # CONV-4 — Decimal precision, no float round-trip / scientific notation.
    def test_clean_numeric_preserves_large_value(self):
        self.assertEqual(dc.clean_numeric("1000000000000000"), "1000000000000000")
        self.assertNotIn("E", dc.clean_numeric("1000000000000000"))

    def test_clean_numeric_decimal_and_integer_forms(self):
        self.assertEqual(dc.clean_numeric("1234.50"), "1234.5")
        self.assertEqual(dc.clean_numeric("$1,000.00"), "1000")
        self.assertEqual(dc.clean_numeric("-1,000.00"), "-1000")
        self.assertEqual(dc.clean_numeric("0.1"), "0.1")

    def test_clean_numeric_rejects_junk_and_nonfinite(self):
        self.assertEqual(dc.clean_numeric("abc"), "")
        self.assertEqual(dc.clean_numeric("nan"), "")
        self.assertEqual(dc.clean_numeric(""), "")

    # CONV-3 — ambiguity detection.
    def test_is_ambiguous_date(self):
        self.assertTrue(dc.is_ambiguous_date("03/04/2025"))   # Mar 4 vs Apr 3
        self.assertFalse(dc.is_ambiguous_date("03/03/2025"))  # same either way
        self.assertFalse(dc.is_ambiguous_date("13/04/2025"))  # only day-first valid
        self.assertFalse(dc.is_ambiguous_date("2025-03-04"))  # unambiguous ISO
        self.assertFalse(dc.is_ambiguous_date(""))

    # CONV-7 — clamp detection.
    def test_percentage_was_clamped(self):
        self.assertTrue(dc.percentage_was_clamped("150"))
        self.assertTrue(dc.percentage_was_clamped("-5"))
        self.assertTrue(dc.percentage_was_clamped("101%"))
        self.assertFalse(dc.percentage_was_clamped("50"))
        self.assertFalse(dc.percentage_was_clamped("100"))
        self.assertFalse(dc.percentage_was_clamped("abc"))

    # CONV-2 — header normalization.
    def test_normalize_header(self):
        self.assertEqual(dc.normalize_header("  Contact   ID "), "Contact ID")
        self.assertEqual(dc.normalize_header("Race "), "Race")
        self.assertEqual(
            dc.normalize_row_keys({" A ": "1", "B": "2"}), {"A": "1", "B": "2"}
        )

    # CONV-5 — configurable delimiter (default from config, override honored).
    def test_split_multi_value_default_and_override(self):
        self.assertEqual(dc.split_multi_value("A;B;C"), ["A", "B", "C"])
        self.assertEqual(dc.split_multi_value("A,B", delimiter=","), ["A", "B"])
        self.assertEqual(dc.split_multi_value(""), [])


def _headers_only_csv(headers):
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
    )
    csv.DictWriter(tmp, fieldnames=headers).writeheader()
    tmp.close()
    return tmp.name


class TestConvEmptyCSV(unittest.TestCase):
    """CONV-6: a headers-only CSV must raise, not silently emit an empty XML."""

    def setUp(self):
        self.logger = ConversionLogger(
            "test_conv", log_level="ERROR", log_to_file=False
        ).logger
        self.validator = ValidationTracker()
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            if os.path.exists(p):
                os.unlink(p)

    def _out_path(self):
        p = os.path.join(tempfile.mkdtemp(), "out.xml")
        self._paths.append(p)
        return p

    def test_counseling_empty_csv_raises(self):
        path = _headers_only_csv(["Contact ID", "Last Name"])
        self._paths.append(path)
        out = self._out_path()
        with self.assertRaises(EmptyCSVError):
            CounselingConverter(self.logger, self.validator).convert(path, out)
        self.assertFalse(os.path.exists(out))  # no partial output written

    def test_training_empty_csv_raises(self):
        path = _headers_only_csv(["Class/Event ID", "Start Date"])
        self._paths.append(path)
        out = self._out_path()
        with self.assertRaises(EmptyCSVError):
            TrainingConverter(self.logger, self.validator).convert(path, out)


if __name__ == "__main__":
    unittest.main()
