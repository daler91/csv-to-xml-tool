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

from src.converters.base_converter import EmptyCSVError
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

    def write_csv(self, rows):
        csv_path = os.path.join(self.dir, "in.csv")
        with open(csv_path, "wb") as f:
            f.write(_csv_bytes(rows))
        return csv_path

    def convert(self, rows):
        self.converter.convert(self.write_csv(rows), self.xml_path)
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


class CodeListTest(_ValidityCase):
    """V.2, V.3 and D3: code lists left with no Code."""

    def test_seeking_detail_without_an_answer_is_filed_as_other(self):
        root = self.convert_row(**{"Currently In Business?": "Yes",
                                   "Nature of the Counseling Seeking?": "",
                                   "Nature of the Counseling Seeking - Other Detail": "Export help"})
        seeking = root.find(".//ClientIntake/CounselingSeeking")
        self.assertEqual([c.text for c in seeking.findall("Code")], ["Other"])
        self.assertEqual(seeking.findtext("Other"), "Export help")

    def test_internet_specify_fills_the_internet_element(self):
        root = self.convert_row(**{"What Prompted you to contact us?": "Internet",
                                   "Internet (specify)": "Google search"})
        intake = root.find(".//ClientIntake")
        self.assertEqual([c.text for c in intake.findall("Media/Code")], ["Internet"])
        self.assertIsNone(intake.find("Media/Other"))
        self.assertEqual(intake.findtext("Internet"), "Google search")
        self.assertEqual(self.issues("Internet"), [])

    def test_internet_specify_without_a_media_answer(self):
        root = self.convert_row(**{"What Prompted you to contact us?": "",
                                   "Internet (specify)": "Google search"})
        intake = root.find(".//ClientIntake")
        self.assertIsNone(intake.find("Media"))
        self.assertEqual(intake.findtext("Internet"), "Google search")

    def test_internet_usage_is_the_fallback(self):
        root = self.convert_row(**{"What Prompted you to contact us?": "Internet",
                                   "Internet (specify)": "", "InternetUsage": "Social media"})
        self.assertEqual(root.findtext(".//ClientIntake/Internet"), "Social media")

    def test_internet_answer_without_a_source_is_still_reported(self):
        self.convert_row(**{"What Prompted you to contact us?": "Internet",
                            "Internet (specify)": "", "InternetUsage": ""})
        self.assertEqual(len(self.issues("Internet", "error")), 1)

    def test_a_separator_only_services_cell_gets_the_default(self):
        root = self.convert_row(**{"Services Provided": " ; "})
        self.assertEqual([c.text for c in root.findall(".//CounselingProvided/Code")],
                         ["Business Start-up/Preplanning"])
        defaulted = self.issues("Services Provided", "warning")
        self.assertEqual(len(defaulted), 1)
        self.assertIn("';' could not be used", defaulted[0]["message"])

    def test_a_separator_only_language_cell_gets_the_default(self):
        root = self.convert_row(**{"Language(s) Used": ";", "Language(s) Used (Other)": "Klingon"})
        language = root.find(".//CounselorRecord/Language")
        self.assertEqual([c.text for c in language.findall("Code")], ["English"])
        self.assertEqual(language.findtext("Other"), "Klingon")


class RepeatLimitTest(_ValidityCase):
    """V.4: more codes than the schema allows."""

    def test_media_keeps_the_first_thirteen_answers(self):
        answers = ["Boots to Business", "Business Owner", "Chamber of Commerce",
                   "Educational Institution", "Lender", "Local Economic Development Official",
                   "Magazine/Newspaper", "SBA District", "SBA Web site", "SBDC", "SCORE",
                   "Television/Radio", "USEAC", "VBOC"]
        root = self.convert_row(**{"What Prompted you to contact us?": "; ".join(answers)})
        self.assertEqual([c.text for c in root.findall(".//ClientIntake/Media/Code")], answers[:13])
        warnings = self.issues("What Prompted you to contact us?", "warning")
        self.assertEqual(len(warnings), 1)
        self.assertIn("left out 'VBOC'", warnings[0]["message"])


class LeftOutRecordTest(_ValidityCase):
    """V.5 and D1: a required value that can't be made valid leaves its row
    out, with an error naming it, and the rest of the file is filed."""

    def assert_left_out(self, field, **overrides):
        root = self.convert([_make_counseling_row(**{"Contact ID": "KEEP"}),
                             _make_counseling_row(**overrides)])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["KEEP"])
        self.assertEqual([source["row"] for source in self.converter.record_sources], [1])
        errors = self.issues(severity="error")
        self.assertEqual([e["field_name"] for e in errors], [field])
        self.assertIn("record was left out of the XML", errors[0]["message"])
        summary = self.validator.get_summary()
        self.assertEqual((summary["total_records"], summary["successful_records"]), (2, 1))

    def test_a_contact_id_over_twenty_characters(self):
        self.assert_left_out("Contact ID", **{"Contact ID": "C" * 21})

    def test_an_activity_id_over_twenty_characters(self):
        self.assert_left_out("Activity ID", **{"Contact ID": "SECOND", "Activity ID": "A" * 21})

    def test_a_location_code_that_is_not_a_number(self):
        self.assert_left_out("LocationCode", **{"Contact ID": "SECOND", "LocationCode": "24900X"})

    def test_a_row_skipped_before_conversion_is_counted(self):
        self.convert([_make_counseling_row(), _make_counseling_row(**{"Contact ID": ""})])
        summary = self.validator.get_summary()
        self.assertEqual((summary["total_records"], summary["successful_records"]), (2, 1))

    def test_nothing_left_to_file_fails_the_conversion(self):
        csv_path = self.write_csv([_make_counseling_row(**{"Contact ID": "C" * 21})])
        with self.assertRaises(EmptyCSVError):
            self.converter.convert(csv_path, self.xml_path)
        self.assertFalse(os.path.exists(self.xml_path))
        self.assertIn("None of the 1 row(s) could be converted",
                      self.issues(severity="error")[-1]["message"])


class TrainingLeftOutTest(_ValidityCase):
    converter_class = TrainingConverter

    def test_an_event_id_over_twenty_characters(self):
        long_id = "E" * 21
        root = self.convert([_make_training_row(**{"Class/Event ID": "EVT-001"}),
                             _make_training_row(**{"Class/Event ID": long_id})])
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in root], ["EVT-001"])
        self.assertEqual(len(self.converter.record_sources), 1)
        errors = self.issues(severity="error")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["record_id"], long_id)
        self.assertIn("record was left out of the XML", errors[0]["message"])
        summary = self.validator.get_summary()
        self.assertEqual((summary["total_records"], summary["successful_records"]), (2, 1))

    def test_nothing_left_to_file_fails_the_conversion(self):
        csv_path = self.write_csv([_make_training_row(**{"Class/Event ID": "E" * 21})])
        with self.assertRaises(EmptyCSVError):
            self.converter.convert(csv_path, self.xml_path)
        self.assertFalse(os.path.exists(self.xml_path))


class TrainingClientRaceTest(_ValidityCase):
    converter_class = TrainingClientConverter

    def test_unlisted_answer_is_self_described(self):
        root = self.convert([_make_training_client_row(Race="Two or More Races")])
        race = root.find(".//ClientIntake/Race")
        self.assertEqual([c.text for c in race.findall("Code")], ["Prefer to Self-Describe"])
        self.assertEqual(race.findtext("SelfDescribedRace"), "Two or More Races")

    def test_a_separator_only_topic_still_gets_a_code(self):
        root = self.convert([_make_training_client_row(**{"Training Topic": ";"})])
        self.assertEqual(len(root.findall(".//CounselingProvided/Code")), 1)

    def test_a_member_id_over_twenty_characters_leaves_the_attendee_out(self):
        root = self.convert([_make_training_client_row(),
                             _make_training_client_row(**{"Contact ID": "003Pe00000Sxsp5",
                                                          "Member ID": "M" * 21})])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["003Pe00000Sxsp4"])
        self.assertIn("record was left out of the XML", self.issues(severity="error")[0]["message"])


if __name__ == "__main__":
    unittest.main()
