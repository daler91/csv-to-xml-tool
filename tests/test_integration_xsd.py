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

from src.converters.counseling_converter import CounselingConverter
from src.converters.training_converter import TrainingConverter
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


if __name__ == '__main__':
    unittest.main()
