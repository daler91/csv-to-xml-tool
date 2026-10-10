"""
Tests for src/schema_rules.py: the XSD facet loader and the per-record guard
that applies those facets before a file is written.

The end-to-end class is the facet test the second-pass review (5.1) asked for:
each input below used to produce a file that failed SBA validation while the
row "converted successfully" with nothing in the report.
"""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.schema_rules import SchemaGuard, load_rules, schema_path, strip_illegal_xml_chars
from src.validation_report import ValidationTracker

from tests.test_integration_xsd import (
    COUNSELING_XSD,
    TRAINING_XSD,
    _make_counseling_row,
    _make_training_row,
    _validate_xml_against_xsd,
    _write_csv,
)

RECORD = ("CounselingInformation", "CounselingRecord")


class TestLoadRules(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules(schema_path("counseling"))

    def test_named_type_facets(self):
        middle = self.rules[RECORD + ("ClientRequest", "ClientNamePart1", "Middle")]
        self.assertTrue(middle.optional)
        self.assertEqual(middle.max_length, 1)
        self.assertEqual(self.rules[RECORD + ("PartnerClientNumber",)].max_length, 20)

    def test_inline_enumeration_under_inline_complex_types(self):
        # Race and Code are both anonymous types nested in ClientIntake's
        # anonymous type -- the case a recursion guard keyed on the type name
        # once cut off below the first level.
        race = self.rules[RECORD + ("ClientIntake", "Race", "Code")]
        self.assertFalse(race.optional)
        self.assertIn("White", race.enumeration)
        self.assertEqual(len(race.enumeration), 9)

    def test_numeric_facets_follow_named_base_types(self):
        employees = self.rules[RECORD + ("CounselorRecord", "TotalNumberOfEmployees")]
        self.assertEqual(employees.base, "integer")
        self.assertEqual(employees.type_name, "PositiveSmallIntegerType")
        self.assertEqual(int(employees.max_inclusive), 32767)
        location = self.rules[RECORD + ("Location", "LocationCode")]
        self.assertEqual((int(location.min_inclusive), int(location.max_inclusive)), (1, 9999999))

    def test_yes_no_type_is_named(self):
        self.assertEqual(self.rules[RECORD + ("ClientRequest", "SurveyAgreement")].type_name, "YesNoType")

    def test_training_schema_loads(self):
        rules = load_rules(schema_path("training"))
        title = rules[("ManagementTrainingReport", "ManagementTrainingRecord", "TrainingTitle")]
        self.assertEqual(title.max_length, 255)

    def test_every_leaf_the_converter_emits_has_a_rule(self):
        """A path the guard can't find is a value it silently doesn't check --
        which is exactly how a loader bug once disabled it below the record."""
        validator = ValidationTracker()
        logger = ConversionLogger("test_schema_rules", log_to_file=False).logger
        csv_path = _write_csv([_make_counseling_row(**{"Currently In Business?": "Yes",
                                                        "Legal Entity of Business": "LLC"})])
        xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
        try:
            CounselingConverter(logger, validator).convert(csv_path, xml_path)
            root = ET.parse(xml_path).getroot()
        finally:
            os.unlink(csv_path)
            os.unlink(xml_path)
        missing = []

        def walk(element, path):
            if len(element) == 0 and path not in self.rules:
                missing.append("/".join(path))
            for child in element:
                walk(child, path + (child.tag,))

        walk(root, (root.tag,))
        self.assertEqual(missing, [])


class TestSchemaGuard(unittest.TestCase):
    """The guard on hand-built records, so each behaviour is pinned exactly."""

    def setUp(self):
        self.validator = ValidationTracker()
        self.guard = SchemaGuard("counseling", self.validator)
        self.record = ET.Element("CounselingRecord")

    def _sub(self, parent, *path_and_text):
        *path, text = path_and_text
        node = parent
        for tag in path:
            found = node.find(tag)
            node = found if found is not None else ET.SubElement(node, tag)
        if text is not None:
            node.text = text
        return node

    def _run(self):
        self.guard.enforce(self.record, "C-1", ("CounselingInformation",))
        return [(i["severity"], i["category"], i["field_name"], i["message"]) for i in self.validator.issues]

    def test_control_characters_become_spaces(self):
        street = self._sub(self.record, "ClientRequest", "AddressPart1", "Street1", "123 Main St\x0bSuite 5")
        issues = self._run()
        self.assertEqual(street.text, "123 Main St Suite 5")
        self.assertEqual(issues[0][1:3], ("standardized_value", "Mailing Street"))

    def test_middle_name_keeps_initial_with_warning(self):
        middle = self._sub(self.record, "ClientRequest", "ClientNamePart1", "Middle", "Marie")
        issues = self._run()
        self.assertEqual(middle.text, "M")
        self.assertEqual(issues, [("warning", "truncated_value", "Middle Name",
                                   "'Marie' is longer than the 1 character SBA allows; kept the initial: 'M'.")])

    def test_identifier_is_never_truncated(self):
        pcn = self._sub(self.record, "PartnerClientNumber", "X" * 21)
        issues = self._run()
        self.assertEqual(pcn.text, "X" * 21)
        self.assertEqual(issues[0][:3], ("error", "invalid_value", "Contact ID"))

    def test_enumeration_is_matched_case_insensitively_without_noise(self):
        code = self._sub(self.record, "CounselorRecord", "Language", "Code", "english")
        self.assertEqual(self._run(), [])
        self.assertEqual(code.text, "English")

    def test_yes_no_synonyms(self):
        survey = self._sub(self.record, "ClientRequest", "SurveyAgreement", "Y")
        online = self._sub(self.record, "ClientIntake", "ConductingBusinessOnline", "false")
        self.assertEqual(self._run(), [])
        self.assertEqual((survey.text, online.text), ("Yes", "No"))

    def test_invalid_optional_element_is_omitted_with_warning(self):
        request = self._sub(self.record, "ClientRequest", None)
        self._sub(request, "Email", "jane@localhost")
        issues = self._run()
        self.assertIsNone(request.find("Email"))
        self.assertEqual(issues[0][:3], ("warning", "invalid_value", "Email"))

    def test_invalid_repeat_is_dropped_when_a_valid_one_remains(self):
        race = self._sub(self.record, "ClientIntake", "Race", None)
        ET.SubElement(race, "Code").text = "White"
        ET.SubElement(race, "Code").text = "Martian"
        issues = self._run()
        self.assertEqual([c.text for c in race.findall("Code")], ["White"])
        self.assertEqual(issues[0][:3], ("warning", "invalid_value", "Race"))

    def test_optional_code_list_is_dropped_whole_when_no_code_is_valid(self):
        media = self._sub(self.record, "ClientIntake", "Media", None)
        ET.SubElement(media, "Code").text = "Facebook"
        issues = self._run()
        self.assertIsNone(self.record.find("ClientIntake/Media"))
        self.assertEqual(issues[0][:3], ("warning", "downgraded_value", "What Prompted you to contact us?"))

    def test_invalid_required_value_is_kept_and_reported_as_error(self):
        race = self._sub(self.record, "ClientIntake", "Race", None)
        ET.SubElement(race, "Code").text = "Martian"
        issues = self._run()
        self.assertEqual(race.find("Code").text, "Martian")
        self.assertEqual(issues[0][:3], ("error", "invalid_value", "Race"))
        self.assertNotIn("_schema_invalid", race.find("Code").attrib)

    def test_required_child_never_drops_a_large_optional_parent(self):
        # ClientIntake is optional, but one bad CurrentlyInBusiness must not
        # take the whole section with it.
        self._sub(self.record, "ClientIntake", "CurrentlyInBusiness", "Maybe")
        self._sub(self.record, "ClientIntake", "CompanyName", "Acme")
        issues = self._run()
        self.assertIsNotNone(self.record.find("ClientIntake/CompanyName"))
        self.assertEqual(issues[0][:3], ("error", "invalid_value", "Currently In Business?"))

    def test_whole_number_is_put_in_integer_form(self):
        employees = self._sub(self.record, "CounselorRecord", "TotalNumberOfEmployees", "12.0")
        self.assertEqual(self._run(), [])
        self.assertEqual(employees.text, "12")

    def test_out_of_range_optional_number_is_omitted(self):
        income = self._sub(self.record, "ClientIntake", "ClientAnnualIncomePart2", None)
        self._sub(income, "GrossRevenues", "-500")
        issues = self._run()
        self.assertIsNone(income.find("GrossRevenues"))
        self.assertIn("must be at least 0", issues[0][3])

    def test_same_cell_in_part1_and_part3_reports_once(self):
        self._sub(self.record, "ClientRequest", "ClientNamePart1", "Middle", "Marie")
        self._sub(self.record, "CounselorRecord", "ClientNamePart3", "Middle", "Marie")
        self.assertEqual(len(self._run()), 1)

    def test_strip_illegal_xml_chars_leaves_tabs_and_newlines(self):
        self.assertEqual(strip_illegal_xml_chars("a\tb\nc\x00d"), "a\tb\nc d")


class TestFacetsEnforcedEndToEnd(unittest.TestCase):
    """Each input converts to schema-valid XML and leaves an issue behind."""

    def setUp(self):
        self.logger = ConversionLogger("test_schema_rules_e2e", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert(self, converter_cls, rows, xsd):
        csv_path = _write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix=".xml", delete=False).name
        try:
            converter_cls(self.logger, self.validator).convert(csv_path, xml_path)
            is_valid, errors = _validate_xml_against_xsd(xml_path, xsd)
            self.assertTrue(is_valid, "XSD validation errors:\n" + "\n".join(errors[:10]))
            return ET.parse(xml_path).getroot()
        finally:
            os.unlink(csv_path)
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def _categories(self):
        return {(i["category"], i["field_name"]) for i in self.validator.issues}

    def test_counseling_over_length_and_off_schema_values(self):
        root = self._convert(CounselingConverter, [_make_counseling_row(**{
            "Middle Name": "Marie",
            "Last Name": "L" * 41,
            "Mailing Street": "S" * 81,
            "Mailing City": "123 Main\x0bSuite 5",
            "Account Name": "A" * 81,
            "Name of Counselor": "N" * 81,
            "Email": "jane@localhost",
            "Mailing State/Province": "Ontario",
            "Agree to Impact Survey": "yes",
            "Type of Business": "Bakery",
            "What Prompted you to contact us?": "Facebook",
            "Language(s) Used": "english",
            "Total Number of Employees": "12.5",
            "Gross Revenues/Sales": "-500",
        })], COUNSELING_XSD)
        record = root.find("CounselingRecord")
        self.assertEqual(record.findtext("ClientRequest/ClientNamePart1/Middle"), "M")
        self.assertEqual(record.findtext("ClientRequest/SurveyAgreement"), "Yes")
        self.assertEqual(record.findtext("CounselorRecord/Language/Code"), "English")
        found = self._categories()
        for expected in [
            ("truncated_value", "Middle Name"),
            ("truncated_value", "Last Name"),
            ("truncated_value", "Mailing Street"),
            ("standardized_value", "Mailing City"),
            ("invalid_value", "Email"),
            ("invalid_value", "Mailing State/Province"),
            ("invalid_value", "Type of Business"),
            ("downgraded_value", "What Prompted you to contact us?"),
            ("invalid_value", "Gross Revenues/Sales"),
        ]:
            self.assertIn(expected, found)

    def test_training_title_over_255_is_truncated(self):
        root = self._convert(TrainingConverter, [_make_training_row(**{
            "Class/Event Name": "T" * 256,
        })], TRAINING_XSD)
        self.assertEqual(len(root.findtext("ManagementTrainingRecord/TrainingTitle")), 255)
        self.assertIn(("truncated_value", "Class/Event Name"), self._categories())


if __name__ == "__main__":
    unittest.main()
