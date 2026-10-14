"""The second pass over SBA XSD validity (docs/reviews/XSD_VALIDITY_ANALYSIS.md,
"Second pass"). Each test converts a CSV that used to cost a record, hang the
conversion, or change a value without a word, and checks the file validates
against the schema SBA supplied, plus what was filed and reported.
"""

import codecs
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from defusedxml import ElementTree as SafeET

from src import data_cleaning
from src.converters.counseling_converter import CounselingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.converters.training_converter import TrainingConverter
from src.schema_rules import SchemaGuard, _check_value, load_rules, schema_path
from src.xml_validator import validate_against_xsd, validate_xml_content

from tests.test_integration_xsd import _make_counseling_row, _make_training_client_row, _make_training_row
from tests.test_xsd_validity import _XSD, _ValidityCase, _csv_bytes

# What base_converter._write_valid_xml says when the final XSD check had to
# leave a record out: the schema guard should have handled the value itself.
SAFETY_NET = "SBA's schema rejects this"


def _rule(schema_type, *suffix):
    rules = load_rules(schema_path(schema_type))
    return next(rule for path, rule in rules.items() if path[-len(suffix):] == suffix)


class GuardAgreesWithLibxml2Test(_ValidityCase):
    """W.1: the guard judged values with Python's re, Decimal and
    date.fromisoformat, which accept things libxml2 rejects. The final XSD
    check then left the whole record out for an optional value."""

    def assert_dropped_not_left_out(self, field, element, **overrides):
        root = self.convert_row(**overrides)
        self.assertEqual(len(root), 1)
        self.assertIsNone(root.find(f".//{element}"))
        self.assertEqual([i for i in self.validator.issues if SAFETY_NET in i["message"]], [])
        self.assertTrue([i for i in self.issues(field, "warning") if "omitted" in i["message"]])

    def test_fullwidth_digits_in_an_integer(self):
        self.assert_dropped_not_left_out("FIPS_Code", "FIPS_Code", Rural_vs_Urban="Rural",
                                         FIPS_Code="１９１５３")

    def test_digits_libxml2_does_not_count_as_digits(self):
        # Python's \d knows the Tamil digits; the XSD's \d, as libxml2 has it, doesn't.
        self.assert_dropped_not_left_out("Mailing Zip/Postal Code", "AddressPart1/ZipCode",
                                         **{"Mailing Zip/Postal Code": "௫௦௩௦௯"})

    def test_a_huge_whole_number_written_with_a_fraction(self):
        self.assert_dropped_not_left_out("FIPS_Code", "FIPS_Code", Rural_vs_Urban="Rural",
                                         FIPS_Code="1" * 4400 + ".0")

    def test_an_email_that_made_the_pattern_backtrack_forever(self):
        started = time.monotonic()
        self.assert_dropped_not_left_out("Email", "ClientRequest/Email",
                                         Email="a@b" + ".aaaa" * 14 + "!")
        # Python's regex engine took ~47 s for this one and never finished at
        # 90 characters; libxml2 gives up after about 2 s and the result is cached.
        self.assertLess(time.monotonic() - started, 15)

    def test_only_short_values_are_remembered(self):
        # The verdicts are kept for the life of the worker: a 100,000-digit
        # FIPS code in each row of each upload stayed in memory.
        rule = _rule("counseling", "ClientIntake", "FIPS_Code")
        cache = rule.checker._cached_accepts.cache_info
        size = cache().currsize
        rule.checker.accepts(rule.check_tag, "1" * 1000)
        self.assertEqual(cache().currsize, size)
        rule.checker.accepts(rule.check_tag, "98765")
        self.assertEqual(cache().currsize, size + 1)

    def test_line_endings_are_measured_as_the_file_reads_them(self):
        # xml.etree writes CR as it is, and the parser reads CR LF as LF: 20
        # characters with a CR LF were 19 in the file, failing an xs:length of 20.
        rule = _rule("training", "TrainingLocation", "PostalCode")
        self.assertEqual(rule.length, 20)
        self.assertEqual(_check_value("x" * 18 + "\r\n", rule)[1], "must be exactly 20 characters")
        self.assertEqual(_check_value("x" * 19 + "\r\n", rule), ("x" * 19 + "\n", None))
        self.assertEqual(_check_value("x" * 19 + "\r", rule), ("x" * 19 + "\n", None))

    def test_iso_basic_and_week_dates_are_not_xs_date(self):
        rule = _rule("counseling", "CounselorRecord", "DateCounseled")
        for text in ("20250115", "2025-W03-3", "2025-W03", "0000-01-01"):
            with self.subTest(text=text):
                self.assertIsNotNone(_check_value(text, rule)[1])
        self.assertIsNone(_check_value("2025-01-15", rule)[1])

    def test_patterns_are_judged_in_the_xsd_dialect(self):
        # ^ and $ are literal characters in an XSD pattern, and \p{..} is a
        # class Python's re can't compile; a schema update using either used
        # to file invalid values or stop every conversion at start-up.
        xsd = os.path.join(tempfile.mkdtemp(), "patterns.xsd")
        with open(xsd, "w", encoding="utf-8") as f:
            f.write(
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="R">'
                '<xs:complexType><xs:sequence>'
                '<xs:element name="Anchored"><xs:simpleType><xs:restriction base="xs:string">'
                '<xs:pattern value="^[0-9]{10}$"/></xs:restriction></xs:simpleType></xs:element>'
                '<xs:element name="Letters"><xs:simpleType><xs:restriction base="xs:string">'
                '<xs:pattern value="\\p{L}+"/></xs:restriction></xs:simpleType></xs:element>'
                '</xs:sequence></xs:complexType></xs:element></xs:schema>')
        rules = load_rules(xsd)
        self.assertIsNotNone(_check_value("5155551234", rules[("R", "Anchored")])[1])
        self.assertIsNone(_check_value("^5155551234$", rules[("R", "Anchored")])[1])
        self.assertIsNone(_check_value("José", rules[("R", "Letters")])[1])
        self.assertIsNotNone(_check_value("José1", rules[("R", "Letters")])[1])

    def test_one_type_that_does_not_compile_leaves_only_its_values_unchecked(self):
        # CodeType restricts a type from the included file, which the value
        # checks' copy of the schema doesn't have; every pattern went unchecked.
        xsd = os.path.join(tempfile.mkdtemp(), "include.xsd")
        with open(xsd, "w", encoding="utf-8") as f:
            f.write(
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                '<xs:include schemaLocation="types.xsd"/><xs:element name="R"><xs:complexType><xs:sequence>'
                '<xs:element name="Zip" type="ZipType"/><xs:element name="Code" type="CodeType"/>'
                '</xs:sequence></xs:complexType></xs:element>'
                '<xs:simpleType name="ZipType"><xs:restriction base="xs:string"><xs:pattern value="\\d{5}"/>'
                '</xs:restriction></xs:simpleType>'
                '<xs:simpleType name="CodeType"><xs:restriction base="IncludedType"><xs:maxLength value="3"/>'
                '</xs:restriction></xs:simpleType></xs:schema>')
        with self.assertLogs("src.schema_rules", "WARNING") as logs:
            rules = load_rules(xsd)
        self.assertEqual(_check_value("abc", rules[("R", "Zip")])[1], "is not in the format SBA requires")
        self.assertIsNone(rules[("R", "Code")].checker)
        self.assertEqual(_check_value("abcd", rules[("R", "Code")])[1], "is longer than the 3 characters SBA allows")
        warning, = logs.output
        self.assertIn(f"Could not build the value checks of {xsd} for Code: simple type 'CodeType'", warning)


class ExponentTest(_ValidityCase):
    """W.2: clean_numeric wrote out an exponent in full -- '1e5000' raised and
    cost the record, '1E+99999999' never finished."""

    def test_clean_numeric_refuses_absurd_exponents_at_once(self):
        started = time.monotonic()
        for text in ("1e5000", "1E+99999999", "1e-99999999"):
            self.assertEqual(data_cleaning.clean_numeric(text), "")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(data_cleaning.clean_numeric("1.5E+6"), "1500000")

    def test_the_record_is_kept_and_the_value_reported(self):
        root = self.convert_row(**{"Gross Revenues/Sales": "1e5000"})
        self.assertEqual(root.findtext(".//ClientAnnualIncomePart2/GrossRevenues"), "0")
        warning, = self.issues("Gross Revenues/Sales", "warning")
        self.assertIn("'1e5000' could not be used", warning["message"])

    def test_zeros_and_long_numbers_are_read(self):
        # The bound counted a zero's exponent and a long number's digits.
        for text, expected in (("0e5000", "0"), ("0E-5000", "0"), ("0." + "0" * 33, "0"),
                               ("9" * 32, "9" * 32), ("1E+40", "1" + "0" * 40),
                               ("0." + "0" * 30 + "1", "0." + "0" * 30 + "1")):
            with self.subTest(text=text):
                self.assertEqual(data_cleaning.clean_numeric(text), expected)

    def test_an_amount_over_the_maximum_is_omitted_not_filed_as_zero(self):
        # '1E+40' was past the bound and filed as a fabricated 0.
        root = self.convert_row(**{"Gross Revenues/Sales": "1E+40", "Prep Hours": "0e5000"})
        self.assertIsNone(root.find(".//GrossRevenues"))
        self.assertTrue(all("must be at most" in w["message"]
                            for w in self.issues("Gross Revenues/Sales", "warning")))
        self.assertEqual(root.findtext(".//CounselingHours/Prepare"), "0")
        self.assertEqual(self.issues("Prep Hours"), [])


class UnwritableCellTest(_ValidityCase):
    """W.3: a cell of characters XML can't carry was stripped to an empty
    <PartnerClientNumber/> -- valid, but naming nobody."""

    def test_a_contact_id_of_control_characters_is_a_blank_contact_id(self):
        root = self.convert([_make_counseling_row(**{"Contact ID": "KEEP"}),
                             _make_counseling_row(**{"Contact ID": "\x01\x02"})])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["KEEP"])
        self.assertTrue([e for e in self.issues(severity="error")
                         if e["message"] == "Missing required Contact ID."])

    def test_text_around_control_characters_is_kept(self):
        root = self.convert_row(**{"Mailing City": "Des\x0bMoines"})
        self.assertEqual(root.findtext(".//AddressPart1/City"), "Des Moines")


class DateTimeTest(_ValidityCase):
    """W.4: a Salesforce Date/Time export ("1/15/2025 10:30 AM") wasn't read,
    so the session was filed without its date."""

    def test_session_dates_with_a_time(self):
        for text, expected in (("1/15/2025 10:30 AM", "2025-01-15"),
                               ("2025-01-15T14:30:00.000Z", "2025-01-15"),
                               ("2025-01-15 14:30:00", "2025-01-15"),
                               ("Jan 15, 2025", "2025-01-15")):
            with self.subTest(text=text):
                self.setUp()
                root = self.convert_row(Date=text)
                self.assertEqual(root.findtext(".//DateCounseled"), expected)

    def test_an_ambiguous_date_with_a_time_is_still_flagged(self):
        self.assertTrue(data_cleaning.is_ambiguous_date("3/4/2025 9:05 pm"))

    def test_an_unreadable_optional_date_is_reported(self):
        root = self.convert_row(**{"Client Signature - Date": "15/31/2025"})
        self.assertIsNone(root.find(".//ClientSignature/Date"))
        warning, = self.issues("Client Signature - Date", "warning")
        self.assertIn("not a date", warning["message"])


class CounselingReportsWhatItLeavesOutTest(_ValidityCase):
    """W.5: values the converter itself dropped, or filled in, before the
    schema guard could report them."""

    def test_unmapped_demographic_answers(self):
        root = self.convert_row(Gender="Non-binary", Disability="Sometimes")
        self.assertIsNone(root.find(".//ClientIntake/Sex"))
        self.assertIsNone(root.find(".//ClientIntake/Disability"))
        self.assertEqual(len(self.issues("Gender", "warning")), 1)
        self.assertEqual(len(self.issues("Disability", "warning")), 1)

    def test_declining_ethnicity_or_disability_is_prefer_not_to_say(self):
        root = self.convert_row(**{"Ethnicity:": "Decline to answer", "Disability": "Unknown"})
        self.assertEqual(root.findtext(".//ClientIntake/Ethnicity"), "Prefer not to say")
        self.assertEqual(root.findtext(".//ClientIntake/Disability"), "Prefer not to say")

    def test_a_branch_of_prefer_not_to_say_is_filed(self):
        root = self.convert_row(**{"Veteran Status": "Veteran", "Branch Of Service": "Prefer not to say"})
        self.assertEqual(root.findtext(".//ClientIntake/BranchOfService"), "Prefer not to say")
        self.assertEqual(self.issues(severity="error"), [])

    def test_a_branch_without_military_service_is_reported(self):
        root = self.convert_row(**{"Veteran Status": "No", "Branch Of Service": "Army"})
        self.assertIsNone(root.find(".//ClientIntake/BranchOfService"))
        warning, = self.issues("Branch Of Service", "warning")
        self.assertIn("'Army' was left out", warning["message"])

    def test_a_legal_entity_for_a_client_not_in_business_is_reported(self):
        root = self.convert_row(**{"Currently In Business?": "No", "Legal Entity of Business": "LLC"})
        self.assertIsNone(root.find(".//ClientIntake/LegalEntity"))
        self.assertEqual(len(self.issues("Legal Entity of Business", "warning")), 1)

    def test_a_fips_code_without_rural_or_urban_is_reported(self):
        root = self.convert_row(Rural_vs_Urban="Undetermined", FIPS_Code="19153")
        self.assertIsNone(root.find(".//ClientIntake/FIPS_Code"))
        self.assertEqual(len(self.issues("FIPS_Code", "warning")), 1)

    def test_unreadable_numbers_are_reported(self):
        root = self.convert_row(**{"Total Number of Employees": "10-20", "Prep Hours": "1:30"})
        self.assertIsNone(root.find(".//ClientIntake/TotalNumberOfEmployees"))
        self.assertIsNone(root.find(".//CounselingHours/Prepare"))
        self.assertEqual(len(self.issues("Total Number of Employees", "warning")), 1)
        self.assertEqual(len(self.issues("Prep Hours", "warning")), 1)

    def test_a_negative_exporting_headcount_reaches_the_guard(self):
        root = self.convert_row(**{"Are you currently exporting?(old)": "Yes",
                                   "Number of Employees in Exporting Business": "-3"})
        self.assertIsNone(root.find(".//NumberOfEmployeesInExportingBusiness"))
        self.assertTrue(self.issues("Number of Employees in Exporting Business", "warning"))

    def test_an_unrecognised_on_file_answer(self):
        root = self.convert_row(**{"Client Signature(On File)": "Signed"})
        self.assertEqual(root.findtext(".//ClientSignature/OnFile"), "No")
        warning, = self.issues("Client Signature(On File)", "warning")
        self.assertIn("'Signed' is not Yes or No", warning["message"])

    def test_an_unrecognised_employee_owned_answer(self):
        root = self.convert_row(**{"Employee Owned": "Partially"})
        self.assertIsNone(root.find(".//Employee_Owned"))
        self.assertEqual(len(self.issues("Employee Owned", "warning")), 1)

    def test_an_unreadable_female_share(self):
        for text, filed in (("N/A", "0"), ("NaN%", "0")):
            with self.subTest(text=text):
                self.setUp()
                root = self.convert_row(**{"Business Ownership - % Female(old)": text})
                self.assertEqual(root.findtext(".//BusinessOwnership/Female"), filed)
                warning, = self.issues("Business Ownership - % Female(old)", "warning")
                self.assertIn(f"'{text}' could not be used", warning["message"])

    def test_a_code_filed_for_other_text_is_reported(self):
        root = self.convert_row(**{"Other Certifications": "State MBE",
                                   "Other (Referred Client to)": "Local bank"})
        self.assertEqual(root.findtext(".//Certifications/Code"), "Other")
        self.assertEqual(root.findtext(".//ReferredClient/Code"), "Other")
        for column in ("Certifications (SDB, HUBZONE, etc)", "Referred Client to"):
            warning, = self.issues(column, "warning")
            self.assertIn("filed as 'Other'", warning["message"])


class TrainingClientContactHoursTest(_ValidityCase):
    converter_class = TrainingClientConverter

    def test_invented_contact_hours_are_reported_on_the_row(self):
        root = self.convert([_make_training_client_row(**{"Type of Session": "Online"})])
        self.assertEqual(root.findtext(".//CounselingHours/Contact"), "0.5")
        warning, = self.issues("Duration (hours)", "warning")
        self.assertIn("0.5", warning["message"])


class TrainingEventValuesTest(_ValidityCase):
    """W.6: the training form read every event value from its first
    attendee row."""

    converter_class = TrainingConverter

    def test_a_value_only_a_later_row_has_is_filed(self):
        root = self.convert([
            _make_training_row(**{"Start Date": "", "Funding Source": "", "Cosponsor": ""}),
            _make_training_row(**{"Start Date": "2/14/2025", "Funding Source": "2023 Portable Assistance - PA2023",
                                  "Cosponsor": "Iowa Economic Development"}),
        ])
        record = root.find("ManagementTrainingRecord")
        self.assertEqual(record.findtext("DateTrainingStarted"), "2025-02-14")
        self.assertEqual(record.findtext("FundingSource"), "2023 Portable Assistance - PA2023")
        self.assertEqual(record.findtext("CosponsorsName"), "Iowa Economic Development")
        self.assertEqual([i for i in self.validator.issues if i["category"] == "fabricated_default"
                          and i["field_name"] == "Start Date"], [])

    def test_rows_that_disagree_are_reported(self):
        root = self.convert([_make_training_row(**{"Start Date": "2/20/2025"}),
                             _make_training_row(**{"Start Date": "2/13/2025"})])
        self.assertEqual(root.findtext(".//DateTrainingStarted"), "2025-02-20")
        warning, = self.issues("Start Date", "warning")
        self.assertIn("different values", warning["message"])

    def test_a_start_date_equal_to_the_default_is_not_called_unparseable(self):
        self.convert([_make_training_row(**{"Start Date": "12/12/2023"})])
        self.assertEqual(self.issues("Start Date"), [])

    def test_a_placeholder_cosponsor_is_no_cosponsor(self):
        root = self.convert([_make_training_row(Cosponsor="N/A ")])
        self.assertIsNone(root.find(".//CosponsorsName"))

    def test_a_location_code_column_is_honoured(self):
        root = self.convert([_make_training_row(LocationCode="250009")])
        self.assertEqual(root.findtext(".//Location/LocationCode"), "250009")

    def test_a_bad_location_code_leaves_the_event_out(self):
        root = self.convert([_make_training_row(**{"Class/Event ID": "KEEP"}),
                             _make_training_row(**{"Class/Event ID": "BAD", "LocationCode": "24900X"})])
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in root], ["KEEP"])
        error, = self.issues(severity="error")
        self.assertEqual(error["field_name"], "LocationCode")

    def test_zip_plus_four_and_a_zip_that_is_not_one(self):
        root = self.convert([_make_training_row(**{"Zip/Postal Code": "50309-1234"})])
        self.assertEqual(root.findtext(".//TrainingLocation/ZipCode"), "50309")
        self.assertEqual(root.findtext(".//TrainingLocation/Zip4Code"), "1234")
        self.setUp()
        root = self.convert([_make_training_row(**{"Zip/Postal Code": "5155550101"})])
        self.assertNotEqual(root.findtext(".//TrainingLocation/ZipCode"), "51555")
        self.assertTrue(self.issues("Zip/Postal Code", "warning"))

    def test_a_later_complete_address_beats_the_default(self):
        root = self.convert([_make_training_row(City=""), _make_training_row(City="Ames")])
        self.assertEqual(root.findtext(".//TrainingLocation/City"), "Ames")

    def test_demographics_read_the_alias_each_row_fills(self):
        rows = [_make_training_row(Gender="", Sex="Male"), _make_training_row(Gender="Female", Sex="")]
        root = self.convert(rows)
        trained = root.find(".//NumberTrained")
        self.assertEqual((trained.findtext("Female"), trained.findtext("Male")), ("1", "1"))


class SafetyNetWithoutLinesTest(_ValidityCase):
    """W.7: the final XSD check left records out only by the line of each
    error. libxml2 giving up on a value reports no line -- and no other
    error in the file -- so the file stayed invalid and nothing was recorded;
    the command line reported a clean conversion."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(SchemaGuard, "enforce", return_value=[])
        patcher.start()  # a gap in the guard, so the values reach the file
        self.addCleanup(patcher.stop)

    def test_records_are_checked_one_by_one(self):
        root = self.convert([
            _make_counseling_row(**{"Contact ID": "KEEP"}),
            _make_counseling_row(**{"Contact ID": "GAVE-UP", "Email": "a@b" + ".aaaa" * 14 + "!"}),
            _make_counseling_row(**{"Contact ID": "BAD", "Email": "bad@"}),
        ])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["KEEP"])
        left_out = {e["record_id"] for e in self.issues(severity="error")
                    if "left out of the XML" in e["message"]}
        self.assertEqual(left_out, {"GAVE-UP", "BAD"})

    def test_errors_with_no_line_say_what_happened(self):
        # They read "Row 2: SBA's schema validator could not finish checking
        # this (...). SBA's schema rejects this", without the record's ID.
        self.convert([
            _make_counseling_row(**{"Contact ID": "KEEP"}),
            _make_counseling_row(**{"Contact ID": "GAVE-UP", "Email": "a@b" + ".aaaa" * 14 + "!"}),
            _make_counseling_row(**{"Contact ID": "CTRL", "Mailing City": "Des\x01Moines"}),
        ])
        messages = {e["record_id"]: e["message"] for e in self.issues(severity="error")}
        self.assertEqual(messages["GAVE-UP"],
                         "Row 2 (Contact ID GAVE-UP): SBA's schema validator could not check a value in "
                         "this record (it gives up on some malformed values, most often an Email), so the "
                         "record was left out of the XML; correct the value in the CSV and convert again.")
        self.assertEqual(messages["CTRL"],
                         "Row 3 (Contact ID CTRL): the record holds a character XML cannot carry, so the "
                         "record was left out of the XML; correct the value in the CSV and convert again.")

    def test_a_failure_no_record_explains_is_reported(self):
        gave_up = {"is_valid": False, "errors": ["SBA's schema validator could not finish checking this (x)."]}
        with mock.patch("src.converters.base_converter.validate_against_xsd", return_value=gave_up):
            self.converter.convert(self.write_csv([_make_counseling_row()]), self.xml_path)
        error, = self.issues(severity="error")
        self.assertEqual(error["record_id"], "file")
        self.assertIn("no record on its own does", error["message"])

    def test_the_worker_lists_such_a_failure_once(self):
        # Its own XSD check lists the errors (xsd_errors); the converter's
        # file error repeated them on the results page.
        from app.services.conversion_service import run_conversion
        whole_file = {"is_valid": False,
                      "errors": ["Line 1: Element 'CounselingInformation': something only the whole file has."]}
        with mock.patch("src.converters.base_converter.validate_against_xsd", return_value=whole_file), \
                mock.patch("app.services.conversion_service.validate_against_xsd", return_value=whole_file):
            result = run_conversion(self.write_csv([_make_counseling_row()]), self.xml_path, "counseling")
        self.assertEqual(result["xsd_errors"], whole_file["errors"])
        self.assertEqual([i for i in result["issues"] if "no record on its own does" in i["message"]], [])


class SharedSchemaTest(_ValidityCase):
    """The per-record check validates against one compiled schema, shared by
    every conversion the worker runs in its threads. An XMLSchema's error log
    is the object's, so two checks at once read each other's errors -- another
    upload's values -- or none, and an invalid record with no error stopped
    the conversion with an IndexError."""

    def test_concurrent_checks_each_get_their_own_errors(self):
        xsd = schema_path("counseling")
        wrong = []

        def check(marker):
            content = (f"<CounselingInformation><CounselingRecord><PartnerClientNumber>{marker}"
                       f"</PartnerClientNumber><Bogus{marker}/></CounselingRecord>"
                       "</CounselingInformation>").encode()
            for _ in range(500):
                errors = validate_xml_content(content, xsd)["errors"]
                if not errors or any(marker not in error for error in errors):
                    wrong.append((marker, errors))

        threads = [threading.Thread(target=check, args=(marker,)) for marker in ("AAA", "BBB")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(wrong[:1], [])

    def test_a_record_invalid_with_no_error_is_left_out_with_a_reason(self):
        gave_up = {"is_valid": False, "errors": ["SBA's schema validator could not finish checking this (x)."]}
        file_checks = iter([gave_up])

        def check_file(path, xsd):
            return next(file_checks, None) or validate_against_xsd(path, xsd)

        def check_record(content, xsd):
            return {"is_valid": b"BAD" not in content, "errors": []}

        with mock.patch("src.converters.base_converter.validate_against_xsd", side_effect=check_file), \
                mock.patch("src.converters.base_converter.validate_xml_content", side_effect=check_record):
            root = self.convert([_make_counseling_row(**{"Contact ID": "KEEP"}),
                                 _make_counseling_row(**{"Contact ID": "BAD"})])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["KEEP"])
        error, = self.issues(severity="error")
        self.assertEqual(error["record_id"], "BAD")
        self.assertIn("gave no reason", error["message"])


class DamagedUtf16Test(_ValidityCase):
    """A UTF-16 export with a stray byte stopped the command line with a
    UnicodeDecodeError; the web read the same bytes."""

    def convert_utf16(self, rows, damage):
        csv_path = self.write_csv(rows)
        with open(csv_path, "rb") as f:
            text = f.read().decode("utf-8")
        with open(csv_path, "wb") as f:
            f.write(codecs.BOM_UTF16_LE + damage(text))
        self.converter.convert(csv_path, self.xml_path)
        return [r.findtext("PartnerClientNumber") for r in SafeET.parse(self.xml_path).getroot()]

    def test_it_converts_with_a_warning(self):
        # The odd byte at the end was decoded as a last line of '�', read as
        # a row whose Contact ID was '�'.
        filed = self.convert_utf16([_make_counseling_row()], lambda text: text.encode("utf-16-le") + b"\n")
        self.assertEqual(filed, ["C-001"])
        self.assertEqual(self.validator.get_summary()["total_records"], 1)
        warning, = self.issues("input_file", "warning")
        self.assertIn("odd number of bytes", warning["message"])

    def test_a_line_of_bytes_that_are_not_text(self):
        def damage(text):  # half an emoji where the second row's ID was
            header, first, second = text.splitlines(keepends=True)
            return ((header + first).encode("utf-16-le") + "\ud83d".encode("utf-16-le", "surrogatepass")
                    + second.removeprefix("C-2").encode("utf-16-le"))
        filed = self.convert_utf16([_make_counseling_row(**{"Contact ID": "C-1"}),
                                    _make_counseling_row(**{"Contact ID": "C-2"})], damage)
        self.assertEqual(filed, ["C-1"])
        self.assertEqual([e["message"] for e in self.issues("Contact ID", "error")],
                         ["Missing required Contact ID."])
        warning, = self.issues("input_file", "warning")
        self.assertIn("replaced with '�'", warning["message"])


class _TextCase(_ValidityCase):
    """Converts CSV text as written, for shapes _csv_bytes can't produce."""

    def convert_text(self, text):
        csv_path = os.path.join(self.dir, "in.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self.converter.convert(csv_path, self.xml_path)
        result = validate_against_xsd(self.xml_path, _XSD[self.converter_class])
        self.assertEqual(result["errors"], [])
        return SafeET.parse(self.xml_path).getroot()


_TRAINING_HEADER = "Class/Event ID,Class/Event Name,Start Date,City,State,Zip code,Gender,Race,Military Status"
_TRAINING_ROW = "{id},Intro,2025-02-03,Ames,IA,50010,{gender},White,No military service"


class ExcelErrorCellTest(_ValidityCase):
    """X.1: '#N/A' from a failed VLOOKUP was filed as an event called '#N/A'."""

    converter_class = TrainingConverter

    def test_an_excel_error_id_is_a_missing_id(self):
        root = self.convert([_make_training_row(**{"Class/Event ID": "KEEP"}),
                             _make_training_row(**{"Class/Event ID": "#N/A"})])
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in root], ["KEEP"])
        error, = self.issues(severity="error")
        self.assertEqual((error["record_id"], error["message"]), ("Row_2", "Missing required Class/Event ID."))
        warning, = [i for i in self.issues(severity="warning") if "Excel error" in i["message"]]
        self.assertIn("'#N/A' in row 2", warning["message"])

    def test_an_excel_error_amount_is_a_blank_amount(self):
        self.converter = CounselingConverter(self.converter.logger, self.validator)
        self.converter_class = CounselingConverter
        root = self.convert_row(**{"Gross Revenues/Sales": "#REF!"})
        self.assertEqual(root.findtext(".//ClientAnnualIncomePart2/GrossRevenues"), "0")
        self.assertTrue([i for i in self.issues("Gross Revenues/Sales", "warning")
                         if "Blank value defaulted" in i["message"]])


class NonRecordRowTest(_TextCase):
    """X.2: a report's footer lines and a repeated header row were filed as
    training events -- the header as an event called 'Class/Event ID'."""

    converter_class = TrainingConverter

    def skipped(self):
        return {i["record_id"]: i["message"] for i in self.validator.issues if "was skipped" in i["message"]}

    def test_footer_and_repeated_header_rows_are_skipped(self):
        root = self.convert_text("\n".join([
            _TRAINING_HEADER, _TRAINING_ROW.format(id="EVT-1", gender="Female"),
            _TRAINING_HEADER, _TRAINING_ROW.format(id="EVT-2", gender="Male"),
            '""', '"Training Attendance"', '"Generated By:  Jane Doe  2/14/2025 10:41 AM"']) + "\n")
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in root], ["EVT-1", "EVT-2"])
        skipped = self.skipped()
        self.assertEqual(set(skipped), {"Row_2", "Row_4", "Row_5", "Row_6"})
        self.assertIn("repeats the header row", skipped["Row_2"])
        self.assertIn("holds only 'Training Attendance'", skipped["Row_5"])
        self.assertEqual(self.issues(severity="error"), [])

    def test_a_single_value_in_a_narrow_file_is_still_a_record(self):
        root = self.convert_text("Class/Event ID,Gender\nEVT-1,\n")
        self.assertEqual(root.findtext(".//PartnerTrainingNumber"), "EVT-1")
        self.assertEqual(self.skipped(), {})

    def test_counseling_rows_that_are_not_clients(self):
        self.converter_class = CounselingConverter
        self.converter = CounselingConverter(self.converter.logger, self.validator)
        rows = [_make_counseling_row(), {name: name for name in _make_counseling_row()},
                {"Contact ID": "Confidential Information - Do Not Distribute"}]
        root = self.convert(rows)
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["C-001"])
        self.assertEqual(set(self.skipped()), {"Row_2", "Row_3"})
        self.assertEqual(self.issues(severity="error"), [])

    def test_a_training_client_header_row_is_read_before_the_rename(self):
        self.converter_class = TrainingClientConverter
        self.converter = TrainingClientConverter(self.converter.logger, self.validator)
        header = {name: name for name in _make_training_client_row()}
        root = self.convert([_make_training_client_row(), header])
        self.assertEqual(len(root), 1)
        self.assertIn("repeats the header row", self.skipped()["Row_2"])

    def test_the_preview_counts_them_as_the_conversion_does(self):
        from app.services.preview_service import read_csv_preview
        text = "\n".join([_TRAINING_HEADER, _TRAINING_ROW.format(id="EVT-1", gender="Female"),
                          _TRAINING_ROW.format(id="#N/A", gender="Male"), _TRAINING_HEADER,
                          '"Iowa WBC"']) + "\n"
        checks = {c["key"]: c["count"] for c in read_csv_preview(text, "training")["data_quality"]["checks"]}
        self.assertEqual(checks, {"missing_event_id": 1, "not_a_record": 2})


class RowShapeTest(_TextCase):
    """X.3: an unclosed quotation mark swallowed every row after it, and a row
    with an unquoted comma lost its last value; both converted without a word."""

    converter_class = TrainingConverter

    def test_rows_swallowed_by_an_unclosed_quote_are_an_error(self):
        root = self.convert_text("\n".join([
            _TRAINING_HEADER, _TRAINING_ROW.format(id="EVT-1", gender='"Female'),
            _TRAINING_ROW.format(id="EVT-2", gender="Male"),
            _TRAINING_ROW.format(id="EVT-3", gender="Male")]) + "\n")
        self.assertEqual([r.findtext("PartnerTrainingNumber") for r in root], ["EVT-1"])
        error, = self.issues(severity="error")
        self.assertEqual(error["field_name"], "Gender")
        self.assertIn("Row 1's 'Gender' cell runs on over 2 more line(s)", error["message"])

    def test_a_note_over_several_lines_is_not_a_swallowed_row(self):
        self.convert_text(_TRAINING_HEADER + ",Notes\n"
                          + _TRAINING_ROW.format(id="EVT-1", gender="Female") + ',"Met Ann, Bo,\nand Cy, Di"\n')
        self.assertEqual(self.issues(severity="error"), [])

    def test_values_past_the_last_column_are_reported(self):
        self.convert_text("\n".join([
            _TRAINING_HEADER, _TRAINING_ROW.format(id="EVT-1", gender="Female"),
            _TRAINING_ROW.format(id="EVT-1", gender="Doe, LLC")]) + "\n")
        warning, = self.issues("input_file", "warning")
        self.assertIn("Row 2 has more values than the header has columns (9): 'No military service'",
                      warning["message"])

    def test_several_long_rows_are_one_warning(self):
        rows = [_TRAINING_ROW.format(id="EVT-1", gender="Doe, LLC") for _ in range(7)]
        self.convert_text("\n".join([_TRAINING_HEADER, *rows]) + "\n")
        warning, = self.issues("input_file", "warning")
        self.assertIn("7 rows have more values than the header has columns (9): rows 1, 2, 3, 4, 5, ...",
                      warning["message"])

    def test_a_short_row_is_not_reported(self):
        self.convert_text(_TRAINING_HEADER + "\nEVT-1,Intro,2025-02-03,Ames,IA,50010\n")
        self.assertEqual(self.issues("input_file"), [])


class InvisibleCellTest(_ValidityCase):
    """X.4: a cell of zero-width or other invisible characters read as filled:
    a Contact ID of one zero-width space was filed as the client's ID."""

    def test_an_invisible_contact_id_is_a_missing_contact_id(self):
        root = self.convert([_make_counseling_row(**{"Contact ID": "KEEP"}),
                             _make_counseling_row(**{"Contact ID": "​"}),
                             _make_counseling_row(**{"Contact ID": "﻿ ‎"})])
        self.assertEqual([r.findtext("PartnerClientNumber") for r in root], ["KEEP"])
        self.assertEqual(len([e for e in self.issues("Contact ID", "error")
                              if e["message"] == "Missing required Contact ID."]), 2)

    def test_an_invisible_name_is_a_missing_name(self):
        self.convert_row(**{"Last Name": "⁠"})
        self.assertEqual([w["message"] for w in self.issues("Last Name", "warning")], [
            "Row 1's 'Last Name' cell holds only invisible or unreadable characters (U+2060), so it was "
            "read as blank. If a value belongs there, retype it in the spreadsheet.",
            "Missing Last Name."])

    def test_a_cell_read_as_blank_is_reported(self):
        # A LocationCode of control characters was filed as the default code
        # with nothing in the report.
        root = self.convert([_make_counseling_row(**{"Contact ID": "C-1", "LocationCode": "\x01\x02"}),
                             _make_counseling_row(**{"Contact ID": "C-2", "LocationCode": " \x0b"}),
                             _make_counseling_row(**{"Contact ID": "C-3", "LocationCode": "�"})])
        self.assertEqual(len(root), 3)
        warning, = self.issues("LocationCode", "warning")
        self.assertEqual((warning["record_id"], warning["message"]), (
            "file", "3 'LocationCode' cells (rows 1, 2, 3) hold only invisible or unreadable characters "
                    "(U+0001, U+0002, U+000B, U+FFFD), so they were read as blank. If a value belongs there, "
                    "retype it in the spreadsheet."))

    def test_a_duplicate_column_of_control_characters_does_not_erase_the_value(self):
        row = _make_counseling_row(**{"Contact ID": "C-REAL"})
        csv_path = os.path.join(self.dir, "in.csv")
        with open(csv_path, "wb") as f:
            f.write(_csv_bytes([row]).replace(b"\r\n", b",Contact ID\r\n", 1).rstrip(b"\r\n") + b",\x01\r\n")
        self.converter.convert(csv_path, self.xml_path)
        root = SafeET.parse(self.xml_path).getroot()
        self.assertEqual(root.findtext(".//PartnerClientNumber"), "C-REAL")
        self.assertEqual(self.issues(severity="error"), [])

    def test_a_header_with_a_zero_width_space_still_matches(self):
        row = _make_counseling_row()
        row["​Contact ID"] = row.pop("Contact ID")
        root = self.convert([row])
        self.assertEqual(root.findtext(".//PartnerClientNumber"), "C-001")


class IdentifierCharactersTest(_ValidityCase):
    """X.5: an ID's invisible or control characters made a different ID from
    the one shown: a Contact ID with a zero-width space was filed with it, and
    'EVT-001' with a control character became a second event that the guard
    then wrote as 'EVT-001' too."""

    def test_an_invisible_character_is_taken_out_of_a_contact_id(self):
        root = self.convert_row(**{"Contact ID": "003XX000004TMM1AAA​", "Activity ID": "‎A-1"})
        self.assertEqual(root.findtext("CounselingRecord/PartnerClientNumber"), "003XX000004TMM1AAA")
        self.assertEqual(root.findtext(".//PartnerSessionNumber"), "A-1")
        warning, = self.issues("Contact ID", "warning")
        self.assertIn("(U+200B)", warning["message"])
        self.assertIn("filed as '003XX000004TMM1AAA'", warning["message"])
        self.assertEqual(len(self.issues("Activity ID", "warning")), 1)

    def test_event_ids_the_xml_writes_alike_are_one_event(self):
        self.converter_class = TrainingConverter
        self.converter = TrainingConverter(self.converter.logger, self.validator)
        root = self.convert([_make_training_row(), _make_training_row(),
                             _make_training_row(**{"Class/Event ID": "EVT-001\x01"}),
                             _make_training_row(**{"Class/Event ID": "EVT-001\x01"})])
        self.assertEqual([(r.findtext("PartnerTrainingNumber"), r.findtext("NumberTrained/Total"))
                          for r in root], [("EVT-001", "4")])
        warning, = self.issues("Class/Event ID", "warning")
        self.assertIn("(U+0001)", warning["message"])

    def test_a_training_client_member_id(self):
        self.converter_class = TrainingClientConverter
        self.converter = TrainingClientConverter(self.converter.logger, self.validator)
        root = self.convert([_make_training_client_row(**{"Member ID": "00vPe00000Pn89L﻿"})])
        self.assertEqual(root.findtext(".//PartnerSessionNumber"), "00vPe00000Pn89L")
        self.assertEqual(len(self.issues("Member ID", "warning")), 1)


class TrainingDemographicsTest(_ValidityCase):
    """X.6: answers the training counts missed without a word -- a Veteran
    Status checkbox, 'African-American', 'Alaskan Native' -- and accented
    gender answers counted by their stray letters."""

    converter_class = TrainingConverter

    def trained(self, rows):
        root = self.convert([_make_training_row(**row) for row in rows])
        return {e.tag: e.text for e in root.find(".//NumberTrained") if len(e) == 0}

    def test_a_veteran_status_checkbox_counts_veterans(self):
        counts = self.trained([{"Veteran Status": "Yes"}, {"Veteran Status": "true"}, {"Veteran Status": "No"}])
        self.assertEqual(counts.get("Veterans"), "2")
        self.assertEqual(self.issues("Military Status"), [])

    def test_hyphenated_and_alaskan_race_labels_are_counted(self):
        root = self.convert([_make_training_row(Race="African-American"),
                             _make_training_row(Race="Alaskan Native")])
        race = root.find(".//NumberTrained/Race")
        self.assertEqual({e.tag: e.text for e in race},
                         {"BlackOrAfricanAmerican": "1", "NativeAmericanOrAlaskaNative": "1"})
        self.assertEqual(root.findtext(".//NumberUnderservedTrained/Total"), "2")
        self.assertEqual(self.issues("Race"), [])

    def test_race_answers_no_count_takes_are_reported(self):
        root = self.convert([_make_training_row(Race=race) for race in
                             ("Two or More Races", "Multiracial", "Hispanic or Latino", "Decline to answer",
                              "Two or More Races")])
        self.assertIsNone(root.find(".//NumberTrained/Race"))
        warning, = self.issues("Race", "warning")
        self.assertEqual(warning["message"],
                         "'Two or More Races', 'Multiracial', 'Hispanic or Latino' fit none of SBA's race "
                         "counts, so 4 attendee answers were counted under no race category.")

    def test_military_answers_no_count_takes_are_reported(self):
        self.trained([{"Veteran Status": "Retired"}, {"Veteran Status": "Prefer not to say"}])
        warning, = self.issues("Military Status", "warning")
        self.assertIn("'Retired' fits none of SBA's military counts", warning["message"])

    def test_accented_gender_answers_are_not_read_by_their_letters(self):
        counts = self.trained([{"Gender": "Préfère ne pas répondre"}, {"Gender": "Más de uno"},
                               {"Gender": "F"}])
        self.assertEqual((counts.get("Female"), counts.get("Male")), ("1", None))

    def test_counseling_reads_the_hyphenated_label_too(self):
        self.converter = CounselingConverter(self.converter.logger, self.validator)
        self.converter_class = CounselingConverter
        root = self.convert_row(Race="African-American")
        self.assertEqual([c.text for c in root.findall(".//ClientIntake/Race/Code")],
                         ["Black or African American"])
        self.assertEqual(self.issues("Race"), [])


class Part3FallbackTest(_ValidityCase):
    """X.7: a Part 3 "(Meeting)" cell that didn't parse still won over its
    intake column: 'n/a' filed Part 3 revenue as 0 beside a good intake
    figure, and an unreadable Business Start Date hid Date Started (Meeting)."""

    def test_an_unreadable_meeting_amount_falls_back_to_the_intake_amount(self):
        root = self.convert_row(**{"Gross Revenues/Sales": "100000", "Gross Revenues/Sales (Meeting)": "n/a",
                                   "Profits/Losses": "5000", "Profit & Loss (Meeting)": "TBD"})
        self.assertEqual(root.findtext(".//ClientAnnualIncomePart3/GrossRevenues"), "100000")
        self.assertEqual(root.findtext(".//ClientAnnualIncomePart3/ProfitLoss"), "5000")
        warning, = self.issues("Gross Revenues/Sales (Meeting)", "warning")
        self.assertEqual(warning["message"], "'n/a' is not a number, so 'Gross Revenues/Sales' was used instead.")
        self.assertEqual(len(self.issues("Profit & Loss (Meeting)", "warning")), 1)

    def test_an_unreadable_meeting_amount_with_nothing_to_fall_back_on(self):
        root = self.convert_row(**{"Gross Revenues/Sales (Meeting)": "n/a"})
        self.assertEqual(root.findtext(".//ClientAnnualIncomePart3/GrossRevenues"), "0")
        warning, = self.issues("Gross Revenues/Sales (Meeting)", "warning")
        self.assertIn("'n/a' could not be used and was replaced with '0'", warning["message"])

    def test_an_unreadable_date_or_headcount_falls_back(self):
        root = self.convert_row(**{"Business Start Date": "sometime", "Date Started (Meeting)": "2020-05-01",
                                   "Total No. of Employees (Meeting)": "several", "Total Number of Employees": "7"})
        self.assertEqual(root.findtext(".//BusinessStartDatePart3"), "2020-05-01")
        self.assertEqual(root.findtext(".//CounselorRecord/TotalNumberOfEmployees"), "7")
        self.assertIn("so 'Date Started (Meeting)' was used instead",
                      self.issues("Business Start Date", "warning")[0]["message"])
        self.assertEqual(len(self.issues("Total No. of Employees (Meeting)", "warning")), 1)


class TrainingClientBlankColumnTest(_ValidityCase):
    """X.8: training-client renamed its columns to counseling names, and a
    blank cell of a column with the counseling name erased the value: a blank
    'Date' erased the Start Date, a blank 'Type of Session' the 'Training'
    default, which then invented 0.5 contact hours."""

    converter_class = TrainingClientConverter

    def test_a_blank_column_does_not_erase_the_renamed_value(self):
        root = self.convert([_make_training_client_row(**{"Date": "", "Activity ID": "", "Contact: Phone": ""})])
        self.assertEqual(root.findtext(".//TrainingSession/DateTrainingStarted"), "2025-04-08")
        self.assertEqual(root.findtext(".//TrainingSession/PartnerTrainingNumber"), "701Pe00000vtCVy")
        self.assertEqual(root.findtext(".//PhonePart1/Primary"), "5155551234")
        both = {i["field_name"] for i in self.issues(severity="warning") if "both" in i["message"]}
        self.assertEqual(both, {"Start Date", "Class/Event ID", "Phone"})

    def test_a_blank_column_does_not_erase_a_default(self):
        root = self.convert([_make_training_client_row(**{"Type of Session": ""})])
        self.assertEqual(root.findtext(".//SessionType"), "Training")
        self.assertEqual(root.findtext(".//CounselingHours/Contact"), "0")
        self.assertEqual(self.issues("Duration (hours)"), [])
        defaults, = self.issues("configured_defaults")
        self.assertIn("Type of Session (where the CSV's cell is blank)='Training'", defaults["message"])

    def test_the_preview_renames_the_same_way(self):
        from app.services.preview_service import read_csv_preview
        row = _make_training_client_row(**{"Activity ID": ""})
        text = ",".join(row) + "\n" + ",".join(row.values()) + "\n"
        checks = [c["key"] for c in read_csv_preview(text, "training-client")["data_quality"]["checks"]]
        self.assertNotIn("missing_class_event_id", checks)


class DayFirstDateTest(_ValidityCase):
    """X.9: a day-first date with a two-digit year and a day over 12 failed
    month-first and was read year-first: 13/01/25 was filed as 2013-01-25."""

    def test_day_first_dates_read_as_day_first(self):
        for text, expected in (("13/01/25", "2025-01-13"), ("25/12/05", "2005-12-25"),
                               ("15/01/2025", "2025-01-15"), ("03/04/2025", "2025-03-04"),
                               ("99/12/31", "1999-12-31")):
            with self.subTest(text=text):
                self.assertEqual(data_cleaning.format_date(text), expected)
        self.assertTrue(data_cleaning.is_ambiguous_date("03/04/2025"))

    def test_an_optional_date(self):
        root = self.convert_row(**{"Business Start Date": "13/01/25"})
        self.assertEqual(root.findtext(".//BusinessStartDatePart3"), "2025-01-13")
        self.assertEqual(self.issues("Business Start Date"), [])


if __name__ == "__main__":
    unittest.main()
