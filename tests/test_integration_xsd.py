"""
Integration tests that validate generated XML against real XSD schemas.
These tests ensure the converters produce schema-compliant output.
"""

import os
import sys
import csv
import tempfile
import unittest

from lxml import etree

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import EXPORT_COUNTRY_CODES
from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
from src.converters.training_client_converter import TrainingClientConverter
from src.logging_util import ConversionLogger
from src.validation_report import ValidationTracker

SCHEMAS_DIR = os.path.join(os.path.dirname(__file__), '..', 'schemas')
COUNSELING_XSD = os.path.join(SCHEMAS_DIR, 'SBA_NEXUS_Counseling-2-14.xsd')
TRAINING_XSD = os.path.join(SCHEMAS_DIR, 'SBA_NEXUS_Training-2-25-2025.xsd')


def _validate_xml_against_xsd(xml_path, xsd_path):
    """Validate an XML file against an XSD schema. Returns (is_valid, errors)."""
    parser = etree.XMLParser(resolve_entities=False)
    schema_doc = etree.parse(xsd_path, parser=parser)
    schema = etree.XMLSchema(schema_doc)
    xml_doc = etree.parse(xml_path, parser=parser)
    is_valid = schema.validate(xml_doc)
    errors = [str(e) for e in schema.error_log]
    return is_valid, errors


def _make_counseling_row(**overrides):
    """Return a minimal valid counseling row dict."""
    base = {
        'Contact ID': 'C-001',
        'Last Name': 'Smith',
        'First Name': 'John',
        'Middle Name': '',
        'Email': 'john@example.com',
        'Contact: Phone': '(515) 555-1234',
        'Contact: Secondary Phone': '',
        'Mailing Street': '123 Main St',
        'Mailing City': 'Des Moines',
        'Mailing State/Province': 'IA',
        'Mailing Zip/Postal Code': '50309',
        'Mailing Country': 'US',
        'Agree to Impact Survey': 'Yes',
        'Client Signature - Date': '2025-01-15',
        'Client Signature(On File)': '1',
        'Race': 'White',
        'Ethnicity:': 'Non Hispanic or Latino',
        'Gender': 'Male',
        'Disability': '',
        'Veteran Status': '',
        'Branch Of Service': '',
        'What Prompted you to contact us?': '',
        'Internet (specify)': '',
        'InternetUsage': '',
        'Currently In Business?': 'No',
        'Are you currently exporting?(old)': 'No',
        'Account Name': '',
        'Type of Business': '',
        'Business Ownership - % Female(old)': '0',
        'Conduct Business Online?': 'No',
        '8(a) Certified?(old)': 'No',
        'Total Number of Employees': '',
        'Number of Employees in Exporting Business': '',
        'Gross Revenues/Sales': '',
        'Profits/Losses': '',
        'Rural_vs_Urban': 'Undetermined',
        'FIPS_Code': '',
        'Nature of the Counseling Seeking?': '',
        'Nature of the Counseling Seeking - Other Detail': '',
        'Activity ID': 'A-001',
        'Funding Source': '',
        'LocationCode': '249003',
        'Verified To Be In Business': 'No',
        'Reportable Impact': 'No',
        'Reportable Impact Date': '',
        'Business Start Date': '',
        'Date Started (Meeting)': '',
        'Total No. of Employees (Meeting)': '',
        'Gross Revenues/Sales (Meeting)': '',
        'Profit & Loss (Meeting)': '',
        'SBA Loan Amount': '0',
        'Non-SBA Loan Amount': '0',
        'Amount of Equity Capital Received': '0',
        'Certifications (SDB, HUBZONE, etc)': '',
        'Other Certifications': '',
        'SBA Financial Assistance': '',
        'Other SBA Financial Assistance': '',
        'Services Provided': 'Business Start-up/Preplanning',
        'Other Counseling Provided': '',
        'Referred Client to': '',
        'Other (Referred Client to)': '',
        'Type of Session': 'Telephone',
        'Language(s) Used': 'English',
        'Language(s) Used (Other)': '',
        'Date': '2025-01-15',
        'Name of Counselor': 'Jane Doe',
        'Duration (hours)': '1.5',
        'Prep Hours': '0.5',
        'Travel Hours': '0',
        'Comments': 'Initial consultation.',
        'Legal Entity of Business': '',
        'Other legal entity (specify)': '',
    }
    base.update(overrides)
    return base


def _make_training_row(**overrides):
    """Return a minimal valid training row dict."""
    base = {
        'Class/Event ID': 'EVT-001',
        'Class/Event Name': 'Business Workshop',
        'Start Date': '2025-01-15',
        'Funding Source': '',
        'Training Topic': 'Technology',
        'Class/Event Type': 'In-person',
        'City': 'Des Moines',
        'State/Province': 'Iowa',
        'Zip/Postal Code': '50309',
        'Gender': 'Female',
        'Race': 'White',
        'Ethnicity': 'Non-Hispanic',
        'Veteran Status': 'No military service',
        'Currently in Business?': 'Yes',
        'Disabilities': 'No',
    }
    base.update(overrides)
    return base


def _make_training_client_row(**overrides):
    """Return a minimal valid training-client (per-attendee Form 641) row dict."""
    base = {
        'Class/Event ID': '701Pe00000vtCVy',
        'Contact ID': '003Pe00000Sxsp4',
        'Member ID': '00vPe00000Pn89L',
        'First Name': 'Jane',
        'Last Name': 'Doe',
        'Member Type': 'Contact',
        'Member Status': 'Responded',
        'Company': 'Doe Enterprises',
        'Phone': '5155551234',
        'Email': 'jane@example.com',
        'Currently in Business?': 'No',
        'Ethnicity': 'Non Hispanic or Latino',
        'Race': 'White',
        'Disabilities': 'No',
        'Gender': 'Female',
        'Military Status': 'No military service',
        'Training Topic': 'Marketing/Sales',
        'Class/Event Type': 'In-Person',
        'Funding Source': '',
        'Class Teacher': 'Mike Smith',
        # Deliberately NOT supplying 'Client Signature - Date': it isn't on the
        # real training-member export. A blank optional date must omit the
        # element rather than emit an empty <Date/>, which strict XSD validation
        # rejects. This fixture previously supplied a value to work around that
        # bug; leaving it out is what keeps the fix honest.
        'Street': '2210 Grand Ave',
        'city': 'Des Moines',
        'State': 'IA',
        'Zip code': '50312',
        'Start Date': '2025-04-08',
        'Class/Event Name': 'Marketing Basics Workshop',
    }
    base.update(overrides)
    return base


def _write_csv(rows, fieldnames=None):
    """Write rows to a temporary CSV file."""
    if fieldnames is None:
        fieldnames = rows[0].keys() if rows else []
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    tmp.close()
    return tmp.name


@unittest.skipUnless(
    os.path.exists(COUNSELING_XSD),
    f"Counseling XSD not found at {COUNSELING_XSD}"
)
class TestCounselingXSDValidation(unittest.TestCase):
    """Integration tests that validate counseling XML against the real XSD schema."""

    def setUp(self):
        self.logger = ConversionLogger("test_xsd_counseling", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert(self, rows):
        csv_path = _write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = CounselingConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            return xml_path
        finally:
            os.unlink(csv_path)

    def test_single_record_validates_against_xsd(self):
        """A single valid counseling record should produce XSD-compliant XML."""
        xml_path = self._convert([_make_counseling_row()])
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)

    def test_multiple_records_validate_against_xsd(self):
        """Multiple valid counseling records should produce XSD-compliant XML."""
        rows = [
            _make_counseling_row(**{'Contact ID': 'C-001', 'Activity ID': 'A-001'}),
            _make_counseling_row(**{'Contact ID': 'C-002', 'Activity ID': 'A-002', 'First Name': 'Jane', 'Gender': 'Female'}),
        ]
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)

    def test_in_business_record_validates(self):
        """A counseling record with business data should validate."""
        xml_path = self._convert([_make_counseling_row(**{
            'Currently In Business?': 'Yes',
            'Legal Entity of Business': 'LLC',
            'Verified To Be In Business': 'Yes',
            'Nature of the Counseling Seeking?': 'Business Operations/Management',
        })])
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)

    def test_employee_owned_and_export_countries_validate(self):
        """Optional Employee_Owned and ExportCountries are emitted in the correct
        ClientIntake sequence position and validate against the XSD."""
        xml_path = self._convert([_make_counseling_row(**{
            'Employee Owned': 'Yes',
            'Export Countries': 'Belgium; Canada',
        })])
        try:
            parser = etree.XMLParser(resolve_entities=False)
            doc = etree.parse(xml_path, parser=parser)
            self.assertEqual(doc.find('.//ClientIntake/Employee_Owned').text, 'Yes')
            self.assertEqual(
                [c.text for c in doc.findall('.//ClientIntake/ExportCountries/Code')],
                ['Belgium', 'Canada'],
            )
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)


@unittest.skipUnless(
    os.path.exists(COUNSELING_XSD),
    f"Counseling XSD not found at {COUNSELING_XSD}"
)
class TestExportCountryCodesMatchXSD(unittest.TestCase):
    """Drift guard: config.EXPORT_COUNTRY_CODES must mirror the XSD enumeration.

    The converter only emits ExportCountries/Code values from that constant, so
    if SBA ships an updated schema with a changed country list this fails CI
    instead of letting the constant silently drift from the XSD."""

    def test_export_country_codes_match_xsd_enumeration(self):
        parser = etree.XMLParser(resolve_entities=False)
        schema_doc = etree.parse(COUNSELING_XSD, parser=parser)
        ns = {'xs': 'http://www.w3.org/2001/XMLSchema'}
        # The enumeration lives on the anonymous simpleType of the Code element
        # inside the ExportCountryList complexType.
        values = schema_doc.xpath(
            '//xs:complexType[@name="ExportCountryList"]'
            '/xs:sequence/xs:element[@name="Code"]'
            '/xs:simpleType/xs:restriction/xs:enumeration/@value',
            namespaces=ns,
        )
        self.assertTrue(values, "ExportCountryList/Code enumeration not found in XSD")
        self.assertEqual(tuple(values), EXPORT_COUNTRY_CODES)


@unittest.skipUnless(
    os.path.exists(TRAINING_XSD),
    f"Training XSD not found at {TRAINING_XSD}"
)
class TestTrainingXSDValidation(unittest.TestCase):
    """Integration tests that validate training XML against the real XSD schema."""

    def setUp(self):
        self.logger = ConversionLogger("test_xsd_training", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert(self, rows):
        csv_path = _write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = TrainingConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            return xml_path
        finally:
            os.unlink(csv_path)

    def test_single_event_validates_against_xsd(self):
        """A single training event should produce XSD-compliant XML."""
        rows = [
            _make_training_row(),
            _make_training_row(**{'Gender': 'Male'}),  # Need 2+ attendees per XSD minimum
        ]
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, TRAINING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)

    def test_multiple_events_validate_against_xsd(self):
        """Multiple training events should produce XSD-compliant XML."""
        rows = [
            _make_training_row(**{'Class/Event ID': 'EVT-001'}),
            _make_training_row(**{'Class/Event ID': 'EVT-001', 'Gender': 'Male'}),
            _make_training_row(**{'Class/Event ID': 'EVT-002', 'Class/Event Name': 'Marketing 101', 'Training Topic': 'Marketing'}),
            _make_training_row(**{'Class/Event ID': 'EVT-002', 'Gender': 'Male'}),
        ]
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, TRAINING_XSD)
            self.assertTrue(is_valid, f"XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)


@unittest.skipUnless(
    os.path.exists(COUNSELING_XSD),
    f"Counseling XSD not found at {COUNSELING_XSD}"
)
class TestTrainingClientXSDValidation(unittest.TestCase):
    """Training-client output is Form 641 counseling-format XML; these tests pin
    the TrainingSession block's position and child order against the real XSD."""

    def setUp(self):
        self.logger = ConversionLogger("test_xsd_training_client", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert(self, rows):
        csv_path = _write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter = TrainingClientConverter(self.logger, self.validator)
            converter.convert(csv_path, xml_path)
            return xml_path
        finally:
            os.unlink(csv_path)

    def test_attendee_records_validate_against_xsd(self):
        """Per-attendee records with the TrainingSession block are XSD-compliant."""
        rows = [
            _make_training_client_row(),
            _make_training_client_row(**{
                'Contact ID': '003Pe00000Sxsp5',
                'Member ID': '00vPe00000Pn89M',
                'First Name': 'Luis',
                'Gender': 'Male',
            }),
        ]
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, "XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)

    def test_record_without_member_id_or_topic_validates(self):
        """The fallback paths (no Member ID, blank topic) also produce valid XML."""
        rows = [_make_training_client_row(**{'Member ID': '', 'Training Topic': ''})]
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, "XSD validation errors:\n" + "\n".join(errors[:10]))
        finally:
            os.unlink(xml_path)


SAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', 'apps', 'web', 'public', 'samples')

# (sample filename, converter class, XSD) for each converter the app ships a
# sample for. training-client output is Form 641, so it validates against the
# counseling schema.
SHIPPED_SAMPLES = [
    ('counseling-sample.csv', CounselingConverter, COUNSELING_XSD),
    ('training-sample.csv', TrainingConverter, TRAINING_XSD),
    ('training-client-sample.csv', TrainingClientConverter, COUNSELING_XSD),
]


class TestShippedSamplesValidate(unittest.TestCase):
    """The sample CSVs the app ships must convert to schema-valid XML.

    These are the files linked from the landing page and the dashboard empty
    state, so they are the first thing a new user converts. Two of the three
    used to produce invalid XML (13 and 28 errors) while the whole test suite
    stayed green -- every other integration test builds its own fixture, so
    nothing exercised the real samples end to end.

    This is the regression gate for the schema-compliance fixes: unnormalized
    enums, empty facet-constrained elements, short phone numbers, multi-value
    fields exceeding maxOccurs, and non-enumerated funding sources.
    """

    def setUp(self):
        self.logger = ConversionLogger("test_shipped_samples", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert_and_validate(self, sample_name, converter_cls, xsd_path):
        csv_path = os.path.join(SAMPLES_DIR, sample_name)
        self.assertTrue(os.path.exists(csv_path), f"shipped sample missing: {csv_path}")
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            converter_cls(self.logger, self.validator).convert(csv_path, xml_path)
            is_valid, errors = _validate_xml_against_xsd(xml_path, xsd_path)
            self.assertTrue(
                is_valid,
                f"{sample_name} produced XML that fails {os.path.basename(xsd_path)}:\n"
                + "\n".join(errors[:10]),
            )
        finally:
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def test_shipped_samples_produce_valid_xml(self):
        for sample_name, converter_cls, xsd_path in SHIPPED_SAMPLES:
            with self.subTest(sample=sample_name):
                self.setUp()  # fresh tracker per sample
                self._convert_and_validate(sample_name, converter_cls, xsd_path)


@unittest.skipUnless(
    os.path.exists(COUNSELING_XSD),
    f"Counseling XSD not found at {COUNSELING_XSD}"
)
class TestSchemaComplianceRegressions(unittest.TestCase):
    """Targeted regressions for the schema-compliance bug classes."""

    def setUp(self):
        self.logger = ConversionLogger("test_schema_compliance", log_to_file=False).logger
        self.validator = ValidationTracker()

    def _convert(self, rows):
        csv_path = _write_csv(rows)
        xml_path = tempfile.NamedTemporaryFile(suffix='.xml', delete=False).name
        try:
            CounselingConverter(self.logger, self.validator).convert(csv_path, xml_path)
            return xml_path
        finally:
            os.unlink(csv_path)

    def _assert_valid(self, rows):
        xml_path = self._convert(rows)
        try:
            is_valid, errors = _validate_xml_against_xsd(xml_path, COUNSELING_XSD)
            self.assertTrue(is_valid, "XSD validation errors:\n" + "\n".join(errors[:10]))
            return etree.parse(xml_path)
        finally:
            os.unlink(xml_path)

    def test_salesforce_multi_select_fields_validate(self):
        """Semicolon-joined multi-selects must not exceed maxOccurs="1".

        CounselingSeeking/Code and CounselingProvided/Code allow exactly one
        code, but Salesforce joins multi-selects with ';'. Emitting both made
        the entire document invalid.
        """
        tree = self._assert_valid([_make_counseling_row(**{
            'Currently In Business?': 'Yes',
            'Nature of the Counseling Seeking?': 'Business Plan;eCommerce',
            'Services Provided': 'Business Plan;Customer Relations',
            'Legal Entity of Business': 'LLC',
        })])
        self.assertEqual(len(tree.findall('.//CounselingSeeking/Code')), 1)
        self.assertEqual(len(tree.findall('.//CounselingProvided/Code')), 1)
        # The dropped codes must be recorded, not silently discarded.
        self.assertTrue(
            any(i['category'] == 'downgraded_value' for i in self.validator.issues),
            f"expected a downgraded_value issue, got {self.validator.issues}",
        )

    def test_blank_optional_fields_are_omitted_not_emitted_empty(self):
        """Blank cells must omit facet-constrained optional elements.

        ZipCode is \\d{5}, ClientSignature/Date is xs:date, Email is
        pattern-constrained and the counseling hours are xs:decimal -- an empty
        element fails validation where omitting it is valid.
        """
        tree = self._assert_valid([_make_counseling_row(**{
            'Email': '',
            'Mailing Street': '',
            'Mailing City': '',
            'Mailing State/Province': '',
            'Mailing Zip/Postal Code': '',
            'Client Signature - Date': '',
            'Agree to Impact Survey': '',
            'Prep Hours': '',
            'Travel Hours': '',
            'Language(s) Used': '',
        })])
        for path in ('.//ZipCode', './/State', './/ClientSignature/Date', './/Email'):
            self.assertEqual(tree.findall(path), [], f"{path} should be omitted when blank")
        # SurveyAgreement is minOccurs="1" YesNoType, so it must still be present
        # and valid rather than omitted.
        self.assertEqual(tree.find('.//SurveyAgreement').text, 'No')

    def test_salesforce_enum_labels_are_normalized(self):
        """Salesforce exports labels, not schema tokens."""
        tree = self._assert_valid([_make_counseling_row(**{
            'Ethnicity:': 'Not Hispanic or Latino',
            'Veteran Status': 'No',
            'Disability': 'No',
        })])
        self.assertEqual(tree.find('.//Ethnicity').text, 'Non Hispanic or Latino')
        self.assertEqual(tree.find('.//MilitaryStatus').text, 'No military service')
        self.assertEqual(tree.find('.//Disability').text, 'No')

    def test_short_phone_number_is_omitted(self):
        """Phone is [0-9]{10}; a 7-digit number must be dropped, not truncated in."""
        tree = self._assert_valid([_make_counseling_row(**{'Contact: Phone': '555-0101'})])
        self.assertEqual(tree.findall('.//PhonePart1/Primary'), [])

    def test_unrecognized_funding_source_is_omitted(self):
        """A partner funding label is not in the XSD's SBA funding-code enum."""
        tree = self._assert_valid([_make_counseling_row(**{'Funding Source': 'Federal'})])
        self.assertEqual(tree.findall('.//FundingSource'), [])


if __name__ == '__main__':
    unittest.main()
