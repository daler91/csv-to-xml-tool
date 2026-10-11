"""Output-correctness fixes from the third review pass (A.3, A.5, A.6, A.8,
the CLI half of A.9, and D.9).

Each test pins an input that used to convert "successfully" into a wrong
filing, a failed conversion, or an error report pointing at the wrong place.
"""

import csv
import io
import os
import tempfile
import unittest
from datetime import datetime

from defusedxml import ElementTree as SafeET

from src import data_cleaning
from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker
from src.xml_validator import validate_against_xsd
from src.xsd_error_mapping import build_error_details

from tests.test_integration_xsd import (
    COUNSELING_XSD,
    _make_counseling_row,
    _make_training_row,
)


def _csv_bytes(header, rows, encoding="utf-8"):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode(encoding)


def _rows_csv(rows):
    header = list(rows[0])
    return _csv_bytes(header, [[row.get(name, "") for name in header] for row in rows])


class _ConverterCase(unittest.TestCase):
    converter_class = CounselingConverter

    def setUp(self):
        self.validator = ValidationTracker()
        self.converter = self.converter_class(
            ConversionLogger("test_output_correctness", log_to_file=False).logger,
            self.validator)
        self.dir = tempfile.mkdtemp()
        self.xml_path = os.path.join(self.dir, "out.xml")

    def convert(self, data):
        csv_path = os.path.join(self.dir, "in.csv")
        with open(csv_path, "wb") as f:
            f.write(data)
        self.converter.convert(csv_path, self.xml_path)
        return SafeET.parse(self.xml_path).getroot()

    def issues(self, field=None):
        return [issue for issue in self.validator.issues
                if field is None or issue["field_name"] == field]


class DuplicateHeaderTest(_ConverterCase):
    """A.5: the later of two same-named columns silently won."""

    def _with_second_date(self, second_date):
        row = _make_counseling_row()
        header = list(row) + ["Date"]
        return _csv_bytes(header, [[row[name] for name in row] + [second_date]])

    def test_a_blank_duplicate_does_not_erase_the_value(self):
        root = self.convert(self._with_second_date(""))

        self.assertEqual(root.findtext(".//DateCounseled"), "2025-01-15")
        warnings = self.issues("Date")
        self.assertEqual(len(warnings), 1)
        self.assertIn("appears 2 times", warnings[0]["message"])

    def test_when_both_are_filled_the_later_still_wins(self):
        root = self.convert(self._with_second_date("2025-02-01"))
        self.assertEqual(root.findtext(".//DateCounseled"), "2025-02-01")

    def test_reader_matches_dictreader_on_ragged_rows(self):
        reader = data_cleaning.NormalizedDictReader(
            io.StringIO(" A ,B,A\n1,,\n\n2\n3,4,5,extra\n"))
        self.assertEqual(reader.fieldnames, ["A", "B", "A"])
        self.assertEqual(reader.duplicates, {"A": 2})
        self.assertEqual(list(reader), [
            {"A": "1", "B": ""},
            {"A": "2", "B": ""},
            {"A": "5", "B": "4"},
        ])


class EncodingTest(_ConverterCase):
    """A.9: a Windows-1252 export failed the command-line conversion."""

    def test_windows_1252_file_converts_with_a_warning(self):
        root = self.convert(
            _rows_csv([_make_counseling_row(**{"Last Name": "Muñoz–Peña"})]).decode("utf-8")
            .encode("cp1252"))

        self.assertEqual(root.findtext(".//Last"), "Muñoz–Peña")
        self.assertEqual(len([i for i in self.issues("input_file") if "Windows-1252" in i["message"]]), 1)

    def test_decoding_order(self):
        self.assertEqual(data_cleaning.decode_csv_bytes(b"\xef\xbb\xbfA\r\nb"), ("A\nb", "utf-8"))
        self.assertEqual(data_cleaning.decode_csv_bytes("Zoë".encode("utf-16")), ("Zoë", "utf-16"))
        # 0x81 is undefined in cp1252: kept as U+0081, as the web decoder does.
        self.assertEqual(data_cleaning.decode_csv_bytes(b"\x93x\x94\x81"),
                         ("“x”\x81", "windows-1252"))


class GenderTest(unittest.TestCase):
    """A.6: abbreviations listed in config were never consulted."""

    def test_abbreviations_and_words(self):
        cases = {"F": "Female", "f": "Female", "Woman": "Female", "Female": "Female",
                 "M": "Male", "Man": "Male", "male": "Male",
                 "Non-binary": "", "Prefer not to say": "", "": ""}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(data_cleaning.map_gender_to_sex(value), expected)


class TrainingGenderCountTest(_ConverterCase):
    converter_class = TrainingConverter

    def test_abbreviated_answers_are_counted(self):
        root = self.convert(_rows_csv([
            _make_training_row(Gender="F"), _make_training_row(Gender="M"),
            _make_training_row(Gender="Woman")]))
        self.assertEqual(root.findtext(".//NumberTrained/Female"), "2")
        self.assertEqual(root.findtext(".//NumberTrained/Male"), "1")


class TrainingEventIdTest(_ConverterCase):
    """D.9: "EV1 " was filed as a second event beside "EV1"."""

    converter_class = TrainingConverter

    def test_trailing_space_is_the_same_event(self):
        root = self.convert(_rows_csv([
            _make_training_row(**{"Class/Event ID": "EV1"}),
            _make_training_row(**{"Class/Event ID": "EV1 "})]))
        records = root.findall("ManagementTrainingRecord")
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in records], ["EV1"])
        self.assertEqual(records[0].findtext("NumberTrained/Total"), "2")

    def test_records_cite_their_events_first_row(self):
        self.convert(_rows_csv([
            _make_training_row(**{"Class/Event ID": "B"}),
            _make_training_row(**{"Class/Event ID": ""}),
            _make_training_row(**{"Class/Event ID": "A"})]))
        # Sorted by event id; row numbers are 1-based data rows.
        self.assertEqual([s["row"] for s in self.converter.record_sources], [3, 1])
        self.assertEqual([i["record_id"] for i in self.issues("Class/Event ID")], ["Row_2"])


class CounselingValueTest(_ConverterCase):
    """D.9 counseling items and A.8."""

    def convert_row(self, **overrides):
        return self.convert(_rows_csv([_make_counseling_row(**overrides)]))

    def test_whitespace_contact_id_is_missing_not_emitted(self):
        rows = [_make_counseling_row(), _make_counseling_row(**{"Contact ID": "   "})]
        root = self.convert(_rows_csv(rows))
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root.iter("CounselingRecord")],
                         ["C-001"])
        self.assertEqual([i["message"] for i in self.issues("Contact ID")], ["Missing required Contact ID."])

    def test_nine_digit_zip_keeps_its_plus_four(self):
        for value in ("503091234", "50309-1234", "50309 1234"):
            with self.subTest(value=value):
                self.setUp()
                root = self.convert_row(**{"Mailing Zip/Postal Code": value})
                self.assertEqual(root.findtext(".//AddressPart1/ZipCode"), "50309")
                self.assertEqual(root.findtext(".//AddressPart1/Zip4Code"), "1234")
                self.assertEqual(self.issues("Mailing Zip/Postal Code"), [])

    def test_unread_zip_digits_are_reported(self):
        root = self.convert_row(**{"Mailing Zip/Postal Code": "5030912"})
        self.assertEqual(root.findtext(".//AddressPart1/ZipCode"), "50309")
        self.assertIsNone(root.find(".//AddressPart1/Zip4Code"))
        self.assertEqual(len(self.issues("Mailing Zip/Postal Code")), 1)

    def test_fractional_exporting_employees_are_not_truncated(self):
        """12.7 became 12 in both places. Part 2 is an xs:decimal, so it keeps
        12.7; Part 3 is a whole number, so it is left out and reported."""
        root = self.convert_row(**{"Currently In Business?": "Yes",
                                   "Number of Employees in Exporting Business": "12.7"})
        self.assertEqual(root.findtext(".//ClientIntake/NumberOfEmployeesInExportingBusiness"), "12.7")
        self.assertIsNone(root.find(".//CounselorRecord/NumberOfEmployeesInExportingBusiness"))
        self.assertEqual(len(self.issues("Number of Employees in Exporting Business")), 1)

    def test_whole_exporting_employees_still_emit(self):
        root = self.convert_row(**{"Currently In Business?": "Yes",
                                   "Number of Employees in Exporting Business": "12.0"})
        self.assertEqual(
            {e.text for e in root.iter("NumberOfEmployeesInExportingBusiness")}, {"12"})

    def test_bracketed_note_labels_are_kept(self):
        root = self.convert_row(Comments="[Q3]:  revenue   up")
        self.assertEqual(root.findtext(".//CounselorNotes"), "[Q3]: revenue up")

    def test_two_digit_year_is_not_in_the_future(self):
        root = self.convert_row(**{"Client Signature - Date": "01/05/68"})
        self.assertEqual(root.findtext(".//ClientSignature/Date"), "1968-01-05")
        next_year = (datetime.now().year + 1) % 100
        self.assertEqual(data_cleaning.format_date(f"01/05/{next_year:02d}"),
                         f"{datetime.now().year + 1}-01-05")

    def test_mailing_country_case_and_unknown_names(self):
        """A.8: the schema guard (second batch) now canonicalises the case and
        reports a name SBA does not list, instead of an XSD enumeration error."""
        root = self.convert_row(**{"Mailing Country": "germany"})
        self.assertEqual(root.findtext(".//AddressPart1/Country/Code"), "Germany")

        self.setUp()
        root = self.convert_row(**{"Mailing Country": "Deutschland"})
        self.assertIsNone(root.find(".//AddressPart1/Country/Code"))
        self.assertEqual(len(self.issues("Mailing Country")), 1)


@unittest.skipUnless(os.path.exists(COUNSELING_XSD), "counseling XSD not found")
class ErrorLocationTest(_ConverterCase):
    """A.3: XSD errors and guard issues named the wrong row or column."""

    def test_meeting_column_is_blamed_for_its_own_value(self):
        self.convert(_rows_csv([_make_counseling_row(**{
            "Currently In Business?": "Yes",
            "Total No. of Employees (Meeting)": "12.5",
            "Total Number of Employees": "12"})]))
        self.assertEqual(len(self.issues("Total No. of Employees (Meeting)")), 1)
        self.assertEqual(self.issues("Total Number of Employees"), [])

    def test_xsd_errors_cite_the_csv_row(self):
        """Row 2 has no Contact ID and is skipped; the third row's error said
        "Row 2" -- its position in the XML."""
        rows = [_make_counseling_row(**{"Contact ID": "AAA"}),
                _make_counseling_row(**{"Contact ID": ""}),
                _make_counseling_row(**{"Contact ID": "C" * 60})]
        self.convert(_rows_csv(rows))

        errors = validate_against_xsd(self.xml_path, COUNSELING_XSD)["errors"]
        self.assertTrue(errors)
        details = build_error_details(self.xml_path, errors, "counseling",
                                      self.converter.record_sources)
        self.assertEqual({d["row_number"] for d in details}, {3})
        self.assertTrue(details[0]["friendly_message"].startswith("Row 3 (Contact CCC"))

        # Without the sources (standalone /validate-xsd) it is still the
        # record's position.
        positional = build_error_details(self.xml_path, errors, "counseling")
        self.assertEqual({d["row_number"] for d in positional}, {2})


class WorkerMappingKeepsDuplicatesTest(unittest.TestCase):
    """A.5 on the web path: the column-mapping rewrite rebuilt each row as a
    dict, collapsing duplicate headers before the converter could see them."""

    def test_duplicate_survives_the_mapping_step(self):
        from app.services import conversion_service

        row = _make_counseling_row()
        header = list(row) + ["Date"]
        tmp = tempfile.mkdtemp()
        csv_path = os.path.join(tmp, "in.csv")
        with open(csv_path, "wb") as f:
            f.write(_csv_bytes(header, [[row[name] for name in row] + [""]]))

        result = conversion_service.run_conversion(
            csv_path=csv_path, xml_path=os.path.join(tmp, "out.xml"),
            converter_type="counseling", column_mapping={"Last Name": "Last Name"})

        root = SafeET.parse(result["xml_path"]).getroot()
        self.assertEqual(root.findtext(".//DateCounseled"), "2025-01-15")
        self.assertTrue([i for i in result["issues"]
                         if i["field_name"] == "Date" and "appears 2 times" in i["message"]])


if __name__ == "__main__":
    unittest.main()
