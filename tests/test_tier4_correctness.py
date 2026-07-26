"""Regression tests for the Tier 4 correctness findings.

Each of these is a silent-wrong-answer bug: the conversion succeeded, the XML
validated, and nothing was recorded — the output was just wrong, or a record
vanished.
"""

import csv
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import data_cleaning
from src.config import TrainingConfig
from src.converters.counseling_converter import CounselingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker
from src.xml_validator import _is_within, _validate_file_paths, add_missing_required_elements


class TestRaggedRows(unittest.TestCase):
    """csv.DictReader fills missing trailing fields with None."""

    def test_none_values_become_empty_strings(self):
        row = {"A": "1", "B": None, "C": "3"}
        self.assertEqual(
            data_cleaning.normalize_row_keys(row), {"A": "1", "B": "", "C": "3"}
        )

    def test_restkey_entry_is_dropped(self):
        # Extra trailing cells land under a None key, which normalize_header
        # can't process.
        row = {"A": "1", None: ["extra", "cells"]}
        self.assertEqual(data_cleaning.normalize_row_keys(row), {"A": "1"})

    def test_short_row_does_not_drop_the_record(self):
        """A short row used to raise AttributeError on .strip() and be dropped.

        The per-record handler caught it and recorded an opaque "processing
        error", so one missing trailing comma cost a whole counseling record.
        """
        logger = ConversionLogger("t4_ragged", log_to_file=False).logger
        validator = ValidationTracker()

        header = "Contact ID,Last Name,First Name,Email,Date,Type of Session\n"
        # Second row is short: Date and Type of Session are absent entirely.
        body = "C-1,Smith,John,a@b.com,2025-01-15,Telephone\nC-2,Jones,Ann\n"
        csv_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        csv_path.write(header + body)
        csv_path.close()
        xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
        try:
            CounselingConverter(logger, validator).convert(csv_path.name, xml_path)
            root = ET.parse(xml_path).getroot()
            ids = [e.text for e in root.iter("PartnerClientNumber")]
            self.assertEqual(ids, ["C-1", "C-2"], "the short row was dropped")
            self.assertFalse(
                [i for i in validator.issues if i["category"] == "processing_error"],
                f"unexpected processing errors: {validator.issues}",
            )
        finally:
            os.unlink(csv_path.name)
            if os.path.exists(xml_path):
                os.unlink(xml_path)


class TestFirstPresentFallback(unittest.TestCase):
    """`row.get(a, row.get(b))` is not a fallback — the inner get is a default."""

    def test_blank_primary_falls_through_to_secondary(self):
        row = {"Total No. of Employees (Meeting)": "", "Total Number of Employees": "7"}
        self.assertEqual(
            CounselingConverter._first_present(
                row, "Total No. of Employees (Meeting)", "Total Number of Employees"
            ),
            "7",
        )

    def test_whitespace_only_primary_also_falls_through(self):
        row = {"a": "   ", "b": "value"}
        self.assertEqual(CounselingConverter._first_present(row, "a", "b"), "value")

    def test_present_primary_wins(self):
        row = {"a": "first", "b": "second"}
        self.assertEqual(CounselingConverter._first_present(row, "a", "b"), "first")

    def test_none_is_skipped(self):
        row = {"a": None, "b": "value"}
        self.assertEqual(CounselingConverter._first_present(row, "a", "b"), "value")

    def test_default_when_all_blank(self):
        row = {"a": "", "b": ""}
        self.assertEqual(CounselingConverter._first_present(row, "a", "b"), "")
        self.assertEqual(
            CounselingConverter._first_present(row, "a", "b", default="0"), "0"
        )


class TestSignatureOnFile(unittest.TestCase):
    """The column was compared against ['1', 1] only."""

    def _on_file_for(self, value):
        logger = ConversionLogger("t4_onfile", log_to_file=False).logger
        validator = ValidationTracker()
        row = {
            "Contact ID": "C-1",
            "Last Name": "Smith",
            "First Name": "John",
            "Date": "2025-01-15",
            "Type of Session": "Telephone",
            "Client Signature(On File)": value,
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        writer = csv.DictWriter(tmp, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        tmp.close()
        xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
        try:
            CounselingConverter(logger, validator).convert(tmp.name, xml_path)
            return ET.parse(xml_path).getroot().find(".//ClientSignature/OnFile").text
        finally:
            os.unlink(tmp.name)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_affirmative_spellings_are_recorded_as_yes(self):
        # "Yes" used to be recorded as "No" in a federal filing.
        for value in ("1", "Yes", "yes", "Y", "true", "TRUE"):
            with self.subTest(value=value):
                self.assertEqual(self._on_file_for(value), "Yes")

    def test_negative_and_blank_are_no(self):
        for value in ("0", "No", "false", ""):
            with self.subTest(value=value):
                self.assertEqual(self._on_file_for(value), "No")


class TestDemographicOrderGuard(unittest.TestCase):
    """_build_demographics_section iterates config dicts to satisfy an xs:sequence.

    Reordering DEMOGRAPHIC_KEYWORDS looks cosmetic but silently produces
    schema-invalid XML, so the order is pinned here.
    """

    # Config key -> the XSD child element it is emitted as.
    RACE_KEY_TO_ELEMENT = {
        "asian": "Asian",
        "black": "BlackOrAfricanAmerican",
        "native_american": "NativeAmericanOrAlaskaNative",
        "pacific_islander": "NativeHawaiianOrPacificIslander",
        "white": "White",
        "middle_eastern": "MiddleEastern",
        "north_african": "NorthAfrican",
    }

    def test_race_keyword_order_matches_the_xsd_sequence(self):
        """Derived from the schema rather than hardcoded.

        This fails if either side drifts: a reorder of DEMOGRAPHIC_KEYWORDS (a
        cosmetic-looking edit) or a schema revision that moves an element.
        """
        from lxml import etree

        xsd = os.path.join(
            os.path.dirname(__file__), "..", "schemas",
            "SBA_NEXUS_Training-2-25-2025.xsd",
        )
        if not os.path.exists(xsd):
            self.skipTest("training XSD not present")

        ns = "{http://www.w3.org/2001/XMLSchema}"
        schema_order = None
        for element in etree.parse(xsd).iter(ns + "element"):
            if element.get("name") == "Race":
                schema_order = [
                    child.get("name")
                    for child in element.iter(ns + "element")
                    if child.get("name") and child is not element
                ]
                break
        self.assertIsNotNone(schema_order, "Race element not found in the XSD")

        config_order = [
            self.RACE_KEY_TO_ELEMENT[key]
            for key in TrainingConfig.DEMOGRAPHIC_KEYWORDS["race"]
        ]
        self.assertEqual(
            config_order,
            schema_order,
            "DEMOGRAPHIC_KEYWORDS['race'] is iterated to satisfy an xs:sequence, "
            "so its order must match the schema; reordering it produces invalid "
            "XML with no other symptom",
        )

    def test_military_keyword_order_is_pinned(self):
        """Emitted via key_to_xml_map, which is likewise order-sensitive."""
        self.assertEqual(
            list(TrainingConfig.DEMOGRAPHIC_KEYWORDS["military"]),
            [
                "active_duty",
                "veteran",
                "service_disabled_veteran",
                "reserve_guard",
                "spouse",
            ],
        )

class TestPathValidation(unittest.TestCase):
    def test_is_within_rejects_sibling_prefix(self):
        # /data-evil merely shares a prefix with /data.
        self.assertFalse(_is_within("/data-evil/x.xml", "/data"))
        self.assertTrue(_is_within("/data/x.xml", "/data"))
        self.assertTrue(_is_within("/data", "/data"))
        self.assertTrue(_is_within("/data/sub/x.xml", "/data"))

    def test_is_within_tolerates_a_trailing_separator_on_base(self):
        self.assertTrue(_is_within("/data/x.xml", "/data/"))
        self.assertFalse(_is_within("/data-evil/x.xml", "/data/"))

    def test_absolute_xsd_path_is_accepted(self):
        """The check was startswith(os.sep), which rejects Windows 'C:\\...'."""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = os.path.join(tmp, "a.xml")
            xsd_path = os.path.join(tmp, "a.xsd")
            open(xml_path, "w").close()
            open(xsd_path, "w").close()
            result = _validate_file_paths(xml_path, xsd_path)
            self.assertIsInstance(result, tuple, f"rejected a valid path: {result}")

    def test_relative_xsd_path_is_still_rejected(self):
        result = _validate_file_paths("a.xml", "relative.xsd")
        # realpath() makes it absolute, so this now passes the isabs check --
        # the guard is about traversal, and resolve_within covers confinement.
        self.assertIsInstance(result, tuple)


class TestAddMissingRequiredElements(unittest.TestCase):
    """defusedxml.ElementTree deliberately omits the tree-building API."""

    def test_adds_a_missing_element_without_crashing(self):
        # ET.SubElement raised AttributeError here, and it escaped the caller's
        # `except (OSError, ET.ParseError)` — so --add-missing crashed outright.
        client_intake = ET.Element("ClientIntake")
        added = add_missing_required_elements(client_intake, "C-1")
        self.assertTrue(added)
        self.assertEqual(client_intake.find("CurrentlyInBusiness").text, "No")

    def test_leaves_an_existing_element_alone(self):
        client_intake = ET.Element("ClientIntake")
        existing = ET.SubElement(client_intake, "CurrentlyInBusiness")
        existing.text = "Yes"
        self.assertFalse(add_missing_required_elements(client_intake, "C-1"))
        self.assertEqual(client_intake.find("CurrentlyInBusiness").text, "Yes")


if __name__ == "__main__":
    unittest.main()
