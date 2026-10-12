"""Inputs that used to produce XML failing SBA's XSDs (see
docs/reviews/XSD_VALIDITY_ANALYSIS.md). Every test converts a CSV and checks
the result validates against the schema SBA supplied, plus what was filed and
reported.
"""

import csv
import io
import os
import tempfile
import unittest

from defusedxml import ElementTree as SafeET

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker
from src.xml_validator import validate_against_xsd

from tests.test_integration_xsd import (
    COUNSELING_XSD,
    TRAINING_XSD,
    _make_counseling_row,
    _make_training_client_row,
    _make_training_row,
)

_XSD = {
    CounselingConverter: COUNSELING_XSD,
    TrainingClientConverter: COUNSELING_XSD,
    TrainingConverter: TRAINING_XSD,
}


def _csv_bytes(rows):
    header = list(dict.fromkeys(name for row in rows for name in row))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(name, "") for name in header])
    return buffer.getvalue().encode("utf-8")


class _ValidityCase(unittest.TestCase):
    converter_class = CounselingConverter

    def setUp(self):
        self.validator = ValidationTracker()
        self.converter = self.converter_class(
            ConversionLogger("test_xsd_validity", log_to_file=False).logger, self.validator)
        self.dir = tempfile.mkdtemp()
        self.xml_path = os.path.join(self.dir, "out.xml")

    def convert(self, rows):
        csv_path = os.path.join(self.dir, "in.csv")
        with open(csv_path, "wb") as f:
            f.write(_csv_bytes(rows))
        self.converter.convert(csv_path, self.xml_path)
        result = validate_against_xsd(self.xml_path, _XSD[self.converter_class])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["is_valid"])
        return SafeET.parse(self.xml_path).getroot()

    def convert_row(self, **overrides):
        return self.convert([_make_counseling_row(**overrides)])

    def issues(self, field=None, severity=None):
        return [i for i in self.validator.issues
                if (field is None or i["field_name"] == field)
                and (severity is None or i["severity"] == severity)]


class RaceTest(_ValidityCase):
    """V.1: an answer outside SBA's nine race codes failed the whole file."""

    def race(self, root):
        race = root.find(".//ClientIntake/Race")
        return [c.text for c in race.findall("Code")], race.findtext("SelfDescribedRace")

    def test_unlisted_answers_are_self_described(self):
        for answer in ("Middle Eastern or North African", "Two or More Races", "Other",
                       "Hispanic or Latino", "Martian"):
            with self.subTest(answer=answer):
                self.setUp()
                root = self.convert_row(Race=answer)
                self.assertEqual(self.race(root), (["Prefer to Self-Describe"], answer))
                warnings = self.issues("Race", "warning")
                self.assertEqual(len(warnings), 1)
                self.assertIn("filed as 'Prefer to Self-Describe'", warnings[0]["message"])
                self.assertEqual(self.issues(severity="error"), [])

    def test_listed_answers_are_kept_beside_a_self_description(self):
        root = self.convert_row(Race="White; Two or More Races; Caucasian")
        self.assertEqual(self.race(root), (["White", "Prefer to Self-Describe"], "Two or More Races"))

    def test_declining_is_prefer_not_to_say(self):
        for answer in ("Decline to answer", "Unknown", "Refused", "N/A"):
            with self.subTest(answer=answer):
                self.setUp()
                root = self.convert_row(Race=answer)
                self.assertEqual(self.race(root), (["Prefer not to say"], None))

    def test_an_explicit_self_description_is_kept_without_a_warning(self):
        root = self.convert_row(Race="Prefer to Self-Describe: Arab American")
        self.assertEqual(self.race(root), (["Prefer to Self-Describe"], "Arab American"))
        self.assertEqual(self.issues("Race"), [])

    def test_a_long_self_description_is_cut_to_eighty_characters(self):
        answer = "Descendant of " + "many places " * 10
        root = self.convert_row(Race=answer)
        self.assertEqual(len(self.race(root)[1]), 80)
        self.assertTrue([i for i in self.issues("Race") if "80" in i["message"]])


class TrainingClientRaceTest(_ValidityCase):
    converter_class = TrainingClientConverter

    def test_unlisted_answer_is_self_described(self):
        root = self.convert([_make_training_client_row(Race="Two or More Races")])
        race = root.find(".//ClientIntake/Race")
        self.assertEqual([c.text for c in race.findall("Code")], ["Prefer to Self-Describe"])
        self.assertEqual(race.findtext("SelfDescribedRace"), "Two or More Races")


if __name__ == "__main__":
    unittest.main()
